"""
The core loop's actual endpoints. Deliberately just three: create, get, respond —
plus feedback. Everything else from the full API spec (org/user admin, knowledge
items, audit log) is out of scope for this first slice, per the lean roadmap.

Rebuilt clean after a corruption incident. Full tracebacks are now printed to
the server console on any pipeline failure (not hidden behind a generic 503),
per explicit request — this makes real debugging possible instead of guessing.
"""
import json
import traceback
import time
import hashlib
import secrets
from datetime import timedelta
from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException, Header, Request, UploadFile, File, BackgroundTasks, Response

from app.models import (
    CreateDecisionRequest, RespondRequest, FeedbackRequest, ContinueCaseRequest,
    CommercialDecisionResponse, WorkspaceResponse, WorkspaceInfoResponse, PilotLeadRequest, ControlTower,
    GeneralFeedbackRequest, DecisionAudit, PilotExperienceRequest, DecisionFormatRequest, CustomFormatRequest,
    InviteResponse, AcceptInviteRequest,
)
from app.database import get_org_scoped_connection
from app.auth import create_session_token
from app.pipeline.classifier import classify
from app.pipeline.evidence import check_missing_evidence
from app.pipeline.reasoner import generate_commercial_position
from app.pipeline.financial import compute_financial_impact
from app.pipeline.market_verification import verify_market_claim
from app.pipeline.normalize import normalize_evidence
from app.pipeline import attempt_fencing
from app.pipeline import job_queue
from app.pipeline.normalized_evidence import NormalizedEvidence, HistoryContext
from app.pipeline.methodology_consistency import (
    claims_tco_methodology, determine_relevant_tco_dimensions, check_tco_coverage,
    claims_kraljic_methodology, check_kraljic_reasoning_coverage,
)
from app.pipeline.contradiction_check import check_all_contradictions
from app.pipeline.claim_integrity import check_all_claim_overstatements
from app.pipeline.confidence_gate import apply_confidence_ceiling
from app.pipeline.decision_integrity import (
    compute_pre_reasoning_confidence, build_stakeholder_decision_protocol,
)
from app.pipeline.decision_audit import build_decision_audit
from app.pipeline.sensitivity import build_sensitivity_analysis
from app.pipeline.stress_test import build_stress_test
from app.pipeline.alternatives import build_alternative_paths
from app.pipeline.control_tower import build_control_tower
from app.pipeline.decision_passport import build_decision_passport
from app.pipeline.decision_cockpit import build_decision_cockpit
from app.pipeline.trust_certification import build_trust_certification
from app.pipeline.commercial_model import build_commercial_truth_model
from app.pipeline.decision_flip_map import build_decision_flip_map
from app.pipeline.commercial_war_room import build_commercial_war_room
from app.pipeline.procurement_memory import build_procurement_memory
from app.pipeline.outcome_intelligence import build_outcome_intelligence
from app.pipeline.commercial_dna import build_commercial_dna
from app.pipeline.negotiation_playbook import build_negotiation_playbook
from app.pipeline.decision_formats import render_decision
from app.pipeline.customer_actions import build_action_plan
from app.pipeline.commercial_triage import build_generic_commercial_position
from app.pipeline.customer_exports import render_custom, export_csv
from app.pipeline.webhook import dispatch_event
from app.pipeline.pilot_metrics import build_pilot_metrics
from app.pipeline.file_extraction import (
    extract_text_from_xlsx, extract_text_from_pdf, extract_text_from_eml,
    extract_text_from_zip, FileExtractionError,
)

router = APIRouter(prefix="/api/v1")


def _require_identity(request: Request) -> tuple[str, str]:
    """Return the organisation/user from the signed session, never from a browser header.

    Headers remain accepted by some legacy frontend code, but protected endpoints
    use the signed bearer token as the authority. Membership is checked live so a
    removed user cannot keep using an unexpired token.
    """
    from app.auth import require_session, verify_membership
    claims = require_session(request)
    org_id = str(claims["org_id"])
    user_id = str(claims["sub"])
    verify_membership(org_id, user_id)
    return org_id, user_id

# Lightweight, in-memory rate limiting on workspace creation -- deliberately
# simple, matching the lean philosophy held all night: this closes the
# obvious gap (a script looping to spam-create free workspaces with real
# Anthropic API cost behind each one) without building real rate-limiting
# infrastructure (Redis, etc.) that isn't justified before real usage
# volume exists. In-memory means this resets on a server restart, which is
# an accepted, honest tradeoff for a single-instance free-tier deployment,
# not a claim of bulletproof protection against a determined attacker.
_workspace_creation_log: dict[str, list[float]] = defaultdict(list)
_WORKSPACE_RATE_LIMIT_MAX = 20
_WORKSPACE_RATE_LIMIT_WINDOW_SECONDS = 3600
_validation_run_log: dict[str, list[float]] = defaultdict(list)
_VALIDATION_RATE_LIMIT_MAX = 2
_VALIDATION_RATE_LIMIT_WINDOW_SECONDS = 3600
_invite_accept_log: dict[str, list[float]] = defaultdict(list)
_INVITE_ACCEPT_RATE_LIMIT_MAX = 20
_INVITE_ACCEPT_RATE_LIMIT_WINDOW_SECONDS = 3600


def _check_validation_rate_limit(org_id: str):
    now = time.time()
    recent = [t for t in _validation_run_log[org_id] if now - t < _VALIDATION_RATE_LIMIT_WINDOW_SECONDS]
    if len(recent) >= _VALIDATION_RATE_LIMIT_MAX:
        raise HTTPException(429, "Validation can only be run twice per workspace per hour.")
    recent.append(now)
    _validation_run_log[org_id] = recent


def _check_workspace_rate_limit(client_ip: str):
    now = time.time()
    recent = [t for t in _workspace_creation_log[client_ip] if now - t < _WORKSPACE_RATE_LIMIT_WINDOW_SECONDS]
    if len(recent) >= _WORKSPACE_RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail="Too many new workspaces created recently from this connection. "
                   "Please wait a while before creating another, or use your existing "
                   "workspace link if you already have one.",
        )
    recent.append(now)
    _workspace_creation_log[client_ip] = recent


def _check_invite_accept_rate_limit(client_ip: str):
    now = time.time()
    recent = [t for t in _invite_accept_log[client_ip] if now - t < _INVITE_ACCEPT_RATE_LIMIT_WINDOW_SECONDS]
    if len(recent) >= _INVITE_ACCEPT_RATE_LIMIT_MAX:
        raise HTTPException(429, "Too many invitation attempts from this connection. Please try again later.")
    recent.append(now)
    _invite_accept_log[client_ip] = recent


@router.post("/extract-file")
async def extract_file(request: Request, file: UploadFile = File(...)):
    _require_identity(request)
    """
    Real document text extraction -- pure deterministic parsing, no AI call
    involved. The extracted text is returned to the frontend to drop into
    the question box, reusing the exact same, already-tested text
    extraction pipeline rather than building a new one.
    """
    filename = file.filename.lower()
    extractors = {
        ".xlsx": extract_text_from_xlsx,
        ".pdf": extract_text_from_pdf,
        ".eml": extract_text_from_eml,
        ".zip": extract_text_from_zip,
    }
    matched_ext = next((ext for ext in extractors if filename.endswith(ext)), None)
    if not matched_ext:
        raise HTTPException(
            status_code=400,
            detail="Only .xlsx, .pdf, .eml, and .zip files are supported right now. For other "
                   "formats, please copy and paste the relevant details into the question box.",
        )
    file_bytes = await file.read()
    if len(file_bytes) > 5_000_000:
        raise HTTPException(status_code=400, detail="File is too large (max 5MB).")
    try:
        extracted_text = extractors[matched_ext](file_bytes)
    except FileExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if "[... content truncated" in extracted_text or "[... additional rows truncated ...]" in extracted_text:
        raise HTTPException(
            status_code=422,
            detail="This evidence is larger than VendorEdge can safely analyze as one submission. "
                   "Upload a focused extract or paste the relevant commercial pages/rows; no incomplete document is used for a decision.",
        )
    return {"extracted_text": extracted_text}


@router.post("/general-feedback", status_code=201)
def submit_general_feedback(request: Request, body: GeneralFeedbackRequest, x_org_id: str = Header(...)):
    x_org_id, _ = _require_identity(request)
    """
    Always-available, open-ended feedback -- not tied to any specific
    moment or question, unlike the quick-feedback and outcome fields.
    No reply mechanism, since there's no expectation of one for this.
    """
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO general_feedback (organisation_id, message) VALUES (%s, %s)",
                (x_org_id, body.message),
            )
    return {"received": True}


@router.post("/pilot-lead", status_code=201)
def submit_pilot_lead(request: Request, body: PilotLeadRequest, x_org_id: str = Header(...)):
    x_org_id, _ = _require_identity(request)
    """
    Only reached after a real "Notify me" click, which is already logged
    separately (via interest-signal) the moment it happens -- so an
    abandoned form here doesn't lose that signal. This captures the richer,
    optional follow-through: enough to actually reach out to a real
    interested person, nothing more.
    """
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO pilot_leads
                   (organisation_id, email, name, linkedin, next_case_category, comment)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (x_org_id, body.email, body.name, body.linkedin, body.next_case_category, body.comment),
            )
    return {"received": True}


@router.post("/interest-signal", status_code=201)
def log_interest_signal(request: Request, feature: str):
    _require_identity(request)
    """
    Fake-door demand test: logs a click on a not-yet-built feature (e.g. PDF
    upload) without actually building it. Cheap, real signal on whether a
    feature is worth the engineering cost, before committing to it.
    """
    org_id, _ = _require_identity(request)
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO interest_signals (organisation_id, feature) VALUES (%s, %s)",
                (org_id, feature),
            )
    return {"logged": True}


def _reserve_monthly_llm_usage(org_id: str, cur) -> None:
    """Reserve one paid provider use atomically in the caller's transaction."""
    cur.execute(
        """UPDATE organisations
           SET monthly_decisions_used = CASE
                   WHEN monthly_usage_period < date_trunc('month', now())::date THEN 1
                   ELSE monthly_decisions_used + 1 END,
               monthly_usage_period = date_trunc('month', now())::date
           WHERE id = %s
             AND (monthly_usage_period < date_trunc('month', now())::date
                  OR monthly_decisions_used < monthly_decision_limit)
           RETURNING monthly_decision_limit, monthly_decisions_used""",
        (org_id,),
    )
    row = cur.fetchone()
    if not row:
        cur.execute("SELECT monthly_decision_limit FROM organisations WHERE id = %s", (org_id,))
        limit_row = cur.fetchone()
        limit = limit_row["monthly_decision_limit"] if limit_row else 0
        raise HTTPException(
            status_code=429,
            detail=f"This workspace has reached its {limit} decisions this month. It resets at the start of next month.",
        )


def _log_unsupported_category(category: str, organisation_id: str):
    """
    Same real-demand-evidence pattern as log_interest_signal, applied to
    unsupported question types instead of a feature button. Reuses the same
    table (interest_signals) rather than building new infrastructure --
    querying `SELECT feature, count(*) FROM interest_signals GROUP BY
    feature` after the pilot shows real, ranked demand across BOTH unbuilt
    features and unsupported question categories in one place.
    """
    try:
        with get_org_scoped_connection(organisation_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO interest_signals (organisation_id, feature) VALUES (%s, %s)",
                    (organisation_id, f"unsupported:{category}"),
                )
    except Exception as e:
        print(f"Unsupported-category log skipped (non-blocking): {type(e).__name__}: {e}")


@router.post("/workspaces/invite", response_model=InviteResponse)
def invite_teammate(request: Request, x_org_id: str = Header(...)):
    """Create a short-lived bearer invitation, never a live session token.

    The inviter receives only an invitation secret. The invited person must
    redeem that secret through /workspaces/accept-invite, which creates a fresh
    identity and session for them. This prevents the inviter from accidentally
    handing another person a copy of the inviter's authenticated session.
    """
    x_org_id, inviter_user_id = _require_identity(request)
    invite_secret = secrets.token_urlsafe(32)
    invite_token = f"{x_org_id}.{invite_secret}"
    token_hash = hashlib.sha256(invite_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    invite_id = uuid4()
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO workspace_invites
                   (id, organisation_id, invited_by_user_id, token_hash, expires_at)
                   VALUES (%s, %s, %s, %s, %s)""",
                (str(invite_id), x_org_id, str(inviter_user_id), token_hash, expires_at),
            )
    return InviteResponse(organisation_id=UUID(x_org_id), invite_token=invite_token, expires_at=expires_at)


@router.post("/workspaces/accept-invite", response_model=WorkspaceResponse)
def accept_invite(request: Request, body: AcceptInviteRequest):
    """Redeem a single-use invitation into a brand-new user session."""
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host
    _check_invite_accept_rate_limit(client_ip)
    try:
        org_part, secret = body.invite_token.split(".", 1)
        org_id = str(UUID(org_part))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid invitation link.")
    if len(secret) < 32:
        raise HTTPException(status_code=400, detail="Invalid invitation link.")

    token_hash = hashlib.sha256(body.invite_token.encode("utf-8")).hexdigest()
    new_user_id = uuid4()
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, expires_at FROM workspace_invites
                   WHERE token_hash = %s AND accepted_at IS NULL
                     AND expires_at > now()
                   FOR UPDATE""",
                (token_hash,),
            )
            invite = cur.fetchone()
            if not invite:
                raise HTTPException(status_code=400, detail="This invitation is invalid, expired, or already used.")
            cur.execute(
                """INSERT INTO users (id, organisation_id, email, password_hash)
                   VALUES (%s, %s, %s, 'invite-session-no-password')""",
                (str(new_user_id), org_id, f"{new_user_id}@workspace.local"),
            )
            cur.execute(
                "UPDATE workspace_invites SET accepted_at = now(), accepted_by_user_id = %s WHERE id = %s",
                (str(new_user_id), str(invite["id"])),
            )
    return WorkspaceResponse(
        organisation_id=UUID(org_id),
        user_id=new_user_id,
        access_token=create_session_token(org_id, str(new_user_id)),
    )


@router.post("/workspaces", response_model=WorkspaceResponse)
def create_workspace(request: Request):
    """
    Creates a genuinely new, isolated organisation and user -- the fix for
    the critical pre-pilot finding: every visitor previously shared one
    hardcoded demo organisation, meaning real pilot testers would have seen
    each other's data. Each new visitor now gets their own real organisation,
    protected by the same Row-Level Security already verified in
    test_tenant_isolation.py. This is a private-link model, not full
    password-based login -- adequate for a controlled pilot with known,
    invited testers, not yet for open public exposure to strangers.
    """
    # Real IP, accounting for Render's reverse proxy (X-Forwarded-For is set
    # by the proxy; request.client.host would just be the proxy's own IP).
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host
    _check_workspace_rate_limit(client_ip)

    org_id = uuid4()
    user_id = uuid4()
    with get_org_scoped_connection(str(org_id)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organisations (id, name) VALUES (%s, %s)",
                (str(org_id), f"Workspace {str(org_id)[:8]}"),
            )
            cur.execute(
                "INSERT INTO users (id, organisation_id, email, password_hash) "
                "VALUES (%s, %s, %s, 'no-password-yet')",
                (str(user_id), str(org_id), f"{user_id}@workspace.local"),
            )
    return WorkspaceResponse(organisation_id=org_id, user_id=user_id, access_token=create_session_token(str(org_id), str(user_id)))


@router.post("/workspaces/legacy-session", response_model=WorkspaceResponse)
def legacy_workspace_session(x_org_id: str = Header(...), x_user_id: str = Header(...)):
    """Temporary migration bridge for existing private workspace URLs.

    Disabled by default. It only issues a signed session after confirming the
    supplied user actually belongs to the supplied organisation. Remove this
    bridge once existing pilot links have migrated to signed sessions.
    """
    import os
    if os.environ.get("ALLOW_LEGACY_WORKSPACE_LINKS", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Legacy workspace links are no longer enabled.")
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s AND organisation_id = %s", (x_user_id, x_org_id))
            if not cur.fetchone():
                raise HTTPException(status_code=403, detail="Workspace access denied.")
    return WorkspaceResponse(organisation_id=UUID(x_org_id), user_id=UUID(x_user_id), access_token=create_session_token(x_org_id, x_user_id))


@router.post("/validation/run")
def run_two_case_validation(request: Request):
    _require_identity(request)
    """
    Runs the same 2 real cases from benchmark/real_llm_validation.py
    through the exact production reasoning path -- no reasoning logic is
    duplicated here. Uses an in-process TestClient to call the real
    /commercial-decisions and /respond endpoints, precisely the same
    pattern used throughout the whole test suite tonight, so this is
    genuinely the unmodified production path, not a copy of it.

    Runs against a brand-new, dedicated, throwaway workspace, created
    fresh every time this is called -- this can never touch or consume
    quota from any real pilot workspace's monthly limit, since it never
    reuses one.

    Deliberately synchronous and bounded: exactly 2 cases, real cost is
    small and predictable, and the caller (the simple validation page)
    waits for real results rather than polling -- this endpoint itself
    blocks until both cases reach a terminal state.
    """
    import os
    org_id, _ = _require_identity(request)
    _check_validation_rate_limit(org_id)
    if os.environ.get("VALIDATION_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Validation is not enabled on this environment.")

    import uuid as uuid_module
    from fastapi.testclient import TestClient
    from app.main import app
    from benchmark.real_llm_validation import VALIDATION_CASES, _compute_cost
    from app.pipeline.token_tracking import get_usage, reset_usage

    test_client = TestClient(app)

    # A dedicated, isolated workspace for this run only -- never a real
    # pilot workspace, so this can never affect real quota.
    org_id = uuid_module.uuid4()
    user_id = uuid_module.uuid4()
    with get_org_scoped_connection(str(org_id)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organisations (id, name, monthly_decision_limit) VALUES (%s, %s, 10)",
                (str(org_id), f"Validation Run {str(org_id)[:8]}"),
            )
            cur.execute(
                "INSERT INTO users (id, organisation_id, email, password_hash) "
                "VALUES (%s, %s, %s, 'no-password-yet')",
                (str(user_id), str(org_id), f"{user_id}@validation.local"),
            )

    validation_token = create_session_token(str(org_id), str(user_id), ttl_days=1)
    headers = {
        "Authorization": f"Bearer {validation_token}",
        "x-org-id": str(org_id),
        "x-user-id": str(user_id),
    }
    results = []

    for case in VALIDATION_CASES[:2]:
        reset_usage()
        start = time.time()
        r = test_client.post(
            "/api/v1/commercial-decisions", json={"raw_question": case["raw_question"]}, headers=headers,
        )
        decision_id = r.json()["id"]

        heartbeat_readings = []
        deadline = time.time() + 20 * 60
        data = r.json()
        while data.get("status") == "reasoning" and time.time() < deadline:
            heartbeat_readings.append({
                "elapsed": data.get("processing_elapsed_seconds"),
                "is_stale": data.get("processing_is_stale"),
            })
            time.sleep(2)
            data = test_client.get(f"/api/v1/commercial-decisions/{decision_id}", headers=headers).json()

        elapsed = time.time() - start
        position = data.get("commercial_position") or {}
        usage_entries = get_usage()
        cost_info = _compute_cost(usage_entries)

        results.append({
            "case_id": case["id"],
            "status": data.get("status"),
            "elapsed_seconds": round(elapsed, 1),
            "confidence_level": (position.get("confidence") or {}).get("level"),
            "recommendation_preview": (position.get("recommendation") or "")[:200],
            "financial_impact_present": position.get("financial_impact") is not None,
            "real_api_calls": cost_info["real_api_calls"],
            "retry_occurred": any(
                str(u.get("call_type", "")).endswith("_retry")
                or "_retry" in str(u.get("call_type", ""))
                for u in usage_entries
            ),
            "total_input_tokens": cost_info["total_input_tokens"],
            "total_output_tokens": cost_info["total_output_tokens"],
            "estimated_cost_usd": cost_info["estimated_cost_usd"],
            "heartbeat_stayed_healthy": not any(h["is_stale"] for h in heartbeat_readings),
        })

    total_cost = round(sum(r["estimated_cost_usd"] for r in results), 4)
    return {"cases": results, "total_estimated_cost_usd": total_cost}


@router.get("/workspaces/me", response_model=WorkspaceInfoResponse)
def get_workspace_info(request: Request, x_org_id: str = Header(...)):
    x_org_id, _ = _require_identity(request)
    """
    Real fix for the cross-employer data leakage risk, not just a disclosure
    sentence: returns how long this workspace has genuinely been active, so
    the frontend can periodically prompt "is this still your current business
    context?" rather than relying on a one-time warning nobody re-reads.
    A private-link workspace has no way to know if its holder changed roles
    or employers -- this is a real, functioning checkpoint that at least
    creates a recurring moment to notice and act, given that a fully
    automated identity-verification fix would require infrastructure (e.g.
    verified company email domains) not justified before real evidence.
    """
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, created_at FROM organisations WHERE id = %s", (x_org_id,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Workspace not found")
    days_active = (datetime.now(timezone.utc) - row["created_at"]).days
    return WorkspaceInfoResponse(
        organisation_id=row["id"], created_at=row["created_at"], days_active=days_active
    )

# How many past outcomes to feed back into the reasoner. Kept small and
# deliberately hardcoded for the MVP -- this is the entire "organizational
# learning" mechanism: no retrieval infra, just this org's own most recent
# recorded outcomes for the same content_type.
HISTORY_LIMIT = 5


def _log_full_error(context: str, exc: Exception) -> str:
    """Prints the full traceback to the server console (visible in your logs)
    for real debugging, but returns a calm, generic message to the actual
    user -- not the raw exception text. Verified pre-pilot finding: showing
    a real external user "ValueError: Classifier returned non-JSON output:
    '...'" mid-demo is unprofessional; that detail is exactly as available
    to us in the server logs as it always was, just no longer shown to them."""
    full_trace = traceback.format_exc()
    print(f"\n===== VENDOREDGE ERROR: {context} =====\n{full_trace}=====\n")
    return (
        "VendorEdge is having trouble reasoning through this specific question right now. "
        "Please try again in a moment, or rephrase the question slightly."
    )


def _log_fallback_fired(fallback_name: str, content_type: str | None = None, is_conflict: bool = False, organisation_id: str | None = None):
    """
    Real instrumentation for the deterministic extraction fallbacks
    (region, annual spend, requested percent, freight, incoterm, duty,
    currency, volume) -- built after finding the SAME class of bug
    repeatedly (the model's numeric/structured extraction missing
    something its own text extraction clearly saw). Every real firing
    gets logged here, with real columns for fallback type, content type,
    and model version, specifically so they can be cross-tabulated
    cleanly in SQL (see PILOT_DASHBOARD_QUERIES.md).

    is_conflict=True marks a genuine LLM-vs-fallback disagreement (both
    methods independently extracted a value, and they didn't match) --
    a distinct, arguably more interesting signal than a simple miss,
    since it might mean the fallback pattern itself needs refinement for
    that sentence shape, not just that the model missed something.

    Fire-and-forget: a failure here must never block the main request,
    same discipline as every other non-critical logging in this codebase.
    """
    try:
        if not organisation_id:
            return
        from app.model_config import CLASSIFIER_MODEL
        with get_org_scoped_connection(organisation_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO fallback_events (organisation_id, fallback_type, content_type, model_version, is_conflict) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (organisation_id, fallback_name, content_type, CLASSIFIER_MODEL, is_conflict),
                )
    except Exception as e:
        print(f"Fallback-firing log skipped (non-blocking): {type(e).__name__}: {e}")


@router.post("/commercial-decisions", response_model=CommercialDecisionResponse)
def create_decision(body: CreateDecisionRequest, background_tasks: BackgroundTasks, request: Request,
                     x_org_id: str = Header(...), x_user_id: str = Header(...)):
    x_org_id, x_user_id = _require_identity(request)
    decision_id = body.client_decision_id or uuid4()
    existing = False
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO commercial_decisions
                   (id, organisation_id, created_by_user_id, raw_question, status)
                   VALUES (%s, %s, %s, %s, 'classifying')
                   ON CONFLICT (id) DO NOTHING
                   RETURNING id""",
                (str(decision_id), x_org_id, x_user_id, body.raw_question),
            )
            inserted = cur.fetchone()
            if not inserted:
                # A replay must never call the provider or reserve another
                # quota unit. RLS means a UUID owned by another tenant cannot
                # be observed or returned.
                existing = True
            else:
                _reserve_monthly_llm_usage(x_org_id, cur)

    if existing:
        return _fetch_decision(x_org_id, decision_id)

    # Step A — classify
    try:
        classification = classify(body.raw_question)
    except Exception as e:
        detail = _log_full_error("Classification (Step A) failed", e)
        _update_status(x_org_id, decision_id, "provider_unavailable")
        raise HTTPException(status_code=503, detail=detail)

    content_type = classification.get("content_type")
    if content_type == "unsupported":
        # A real procurement question should never hit a dead-end merely because
        # a specialist module does not exist yet. We keep the specialist
        # classifier honest (it still refuses to force-fit the case), but hand
        # the case to the general commercial triage engine. This engine is
        # explicitly capped at medium confidence and cannot claim specialist
        # TCO/market/legal analysis.
        category = classification.get("unsupported_category", "other")
        try:
            _log_unsupported_category(category, x_org_id)
        except Exception:
            pass

        # Store routing metadata privately; it is useful for demand telemetry
        # and never becomes user-facing evidence.
        with get_org_scoped_connection(x_org_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE commercial_decisions SET user_supplied_inputs = %s, numeric_facts = %s WHERE id = %s",
                    (json.dumps({"__decision_category__": category}), json.dumps({"__decision_category__": category}), str(decision_id)),
                )

        attempt_id = attempt_fencing.start_new_attempt(x_org_id, decision_id, from_status="classifying")
        if attempt_id is None:
            return _fetch_decision(x_org_id, decision_id)
        job_queue.enqueue(x_org_id, decision_id, "generic_triage")
        background_tasks.add_task(_run_queued_job, x_org_id, decision_id)
        return _fetch_decision(x_org_id, decision_id)

    decision_type = classification.get("decision_type")
    constraint_signal = classification.get("constraint_satisfaction_signal")
    llm_extracted_evidence = classification.get("extracted_evidence") or {}
    llm_numeric_facts = classification.get("numeric_facts") or {}

    # THE single evidence-normalization boundary. Every fallback (region,
    # incoterm, duty, currency, volume, annual spend, requested percent,
    # freight parsing), every conflict resolution, and every derivation
    # (freight_relevant, duty_relevant, resolved annual spend) happens
    # exactly once, here. No downstream stage may independently re-extract,
    # re-derive, or reinterpret this evidence.
    normalized, conflicts = normalize_evidence(
        body.raw_question, content_type, llm_extracted_evidence, llm_numeric_facts,
        supplier_specific_evidence=classification.get("supplier_specific_evidence"),
        stakeholder_views=classification.get("stakeholder_views"),
    )
    for field in conflicts:
        _log_fallback_fired(field, content_type, is_conflict=True, organisation_id=x_org_id)
    # Real, honest telemetry: every field whose final value came from the
    # deterministic fallback (not the model) is logged here too, same
    # signal as before the migration, just sourced from one place now
    # instead of two duplicated call sites.
    for field, prov in normalized.provenance.items():
        if prov.source == "deterministic_fallback" and not prov.conflicting:
            _log_fallback_fired(field, content_type, organisation_id=x_org_id)

    stored_evidence = normalized.as_flat_evidence_dict()
    # Persist per-supplier data too, under a reserved key -- without this,
    # a follow-up via /respond or continue_case would silently lose the
    # real multi-supplier evidence built in Guarantee #2, since it isn't
    # part of the flat common/case dict this normally stores.
    if normalized.suppliers:
        stored_evidence["__supplier_specific_evidence__"] = [s.model_dump() for s in normalized.suppliers]
    if normalized.stakeholder_views:
        stored_evidence["__stakeholder_views__"] = [v.model_dump() for v in normalized.stakeholder_views]

    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE commercial_decisions
                   SET classified_content_type = %s, classified_decision_type = %s,
                       user_supplied_inputs = %s, numeric_facts = %s, evidence_provenance = %s
                   WHERE id = %s""",
                (content_type, decision_type, json.dumps(stored_evidence),
                 json.dumps(stored_evidence),
                 json.dumps({k: v.model_dump() for k, v in normalized.provenance.items()}),
                 str(decision_id)),
            )

    # Step B — evidence check, deterministic, no LLM call. Reads
    # normalized.derived.freight_relevant directly -- computed once,
    # above -- rather than re-deriving it from raw Incoterm text.
    missing = check_missing_evidence(normalized)
    if missing:
        _set_awaiting_input(x_org_id, decision_id, missing)
        return _fetch_decision(x_org_id, decision_id)

    attempt_id = attempt_fencing.start_new_attempt(x_org_id, decision_id, from_status="classifying")
    if attempt_id is None:
        # Should not be reachable in practice (this row was just created
        # in this same request), but if it somehow isn't in the expected
        # state, fail safe rather than silently proceed without an
        # attempt identity.
        return _fetch_decision(x_org_id, decision_id)
    job_queue.enqueue(x_org_id, decision_id, "specialist")
    background_tasks.add_task(_run_queued_job, x_org_id, decision_id)
    return _fetch_decision(x_org_id, decision_id)


@router.get("/commercial-decisions", response_model=list[CommercialDecisionResponse])
def list_decisions(request: Request, x_org_id: str = Header(...), x_user_id: str = Header(...)):
    x_org_id, x_user_id = _require_identity(request)
    """
    The 'Commercial Cases' list -- every case this org has ever created, most
    recent first, each flagged with whether its outcome has been recorded yet.
    This is what turns the product from one-shot Q&A into something with a
    home base worth coming back to.
    """
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT cd.id, cd.status, cd.raw_question, cd.classified_content_type,
                          cd.classified_decision_type, cd.missing_inputs_requested,
                          cd.commercial_position, cd.created_at, cd.completed_at,
                          EXISTS(
                              SELECT 1 FROM decision_feedback df
                              WHERE df.commercial_decision_id = cd.id
                          ) AS has_outcome_feedback
                   FROM commercial_decisions cd
                   ORDER BY cd.created_at DESC"""
            )
            rows = cur.fetchall()
            return [CommercialDecisionResponse(**row) for row in rows]
def _restart_reasoning_from_stored_evidence(org_id: str, decision_id, attempt_id: str, row: dict, background_tasks: BackgroundTasks) -> CommercialDecisionResponse:
    """
    Shared recovery logic for both the stale-reasoning and
    provider_unavailable paths -- re-normalizes and re-kicks off
    reasoning using the evidence ALREADY stored on the case (the
    original answer is still there; nothing new was submitted for a
    recovery attempt), then returns an immediate acknowledgment exactly
    like the normal path.
    """
    stored_evidence = row["user_supplied_inputs"] or {}
    restored_suppliers = stored_evidence.get("__supplier_specific_evidence__")
    restored_stakeholders = stored_evidence.get("__stakeholder_views__")
    normalize_input_evidence = {k: v for k, v in stored_evidence.items() if k not in {"__supplier_specific_evidence__", "__stakeholder_views__"}}
    normalized, conflicts = normalize_evidence(
        row["raw_question"], row["classified_content_type"], normalize_input_evidence, normalize_input_evidence,
        supplier_specific_evidence=restored_suppliers,
        stakeholder_views=restored_stakeholders,
    )
    for field in conflicts:
        _log_fallback_fired(field, row["classified_content_type"], is_conflict=True, organisation_id=org_id)
    job_queue.requeue(org_id, decision_id)
    background_tasks.add_task(_run_queued_job, org_id, decision_id)
    return _fetch_decision(org_id, decision_id)


def _run_generic_reasoning_safe(org_id, decision_id, attempt_id: str, raw_question: str, category: str):
    """Run the general commercial triage path safely in the background.

    This is deliberately separate from the specialist pipeline: it has no
    normalized specialist evidence contract and no specialist deterministic
    economics. Its only job is to give the buyer a useful, evidence-disciplined
    next action instead of an unsupported-case dead end.
    """
    try:
        with attempt_fencing.HeartbeatTicker(org_id, decision_id, attempt_id, "general_commercial_triage"):
            position = build_generic_commercial_position(raw_question, category)
        write_succeeded = attempt_fencing.write_final_result(
            org_id, decision_id, attempt_id, position.model_dump_json(),
            _merge_final_provenance(org_id, decision_id, {"generic_triage": {"source": "user_supplied", "stage_captured": "generic_integrity_contract"}})
        )
        if not write_succeeded:
            print(f"Generic triage attempt {attempt_id} was superseded; result discarded safely.")
    except Exception as e:
        try:
            _log_full_error("General commercial triage failed", e)
            attempt_fencing.write_provider_unavailable(org_id, decision_id, attempt_id)
        except Exception:
            pass


def _run_queued_job(org_id: str, decision_id) -> None:
    """Execute a database-leased job; a later process can safely retry it."""
    job = job_queue.claim(org_id, decision_id)
    if not job:
        return
    try:
        with get_org_scoped_connection(org_id) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT raw_question, classified_content_type, user_supplied_inputs, current_attempt_id, status FROM commercial_decisions WHERE id = %s", (str(decision_id),))
                row = cur.fetchone()
        if not row or job_queue.is_cancelled(org_id, decision_id):
            return
        attempt_id = row["current_attempt_id"]
        # job_queue's lease (claim() above) and attempt_fencing's
        # current_attempt_id are two separate mechanisms. Every existing
        # *request-triggered* call site (create_decision, /respond's
        # recovery branches, continue_case) already establishes a fresh
        # attempt_id immediately before dispatch, via start_new_attempt or
        # try_reclaim -- so reusing the row's stored attempt_id is correct
        # there. But this function is also reached by the background
        # dispatcher's own crash/restart discovery (job_queue.find_next_due_job),
        # where no HTTP request -- and therefore no prior reclaim call --
        # was ever involved. Without this check, a truly abandoned worker
        # that eventually, belatedly writes would share the SAME
        # attempt_id as this recovery run and could still overwrite it --
        # exactly the corruption attempt fencing exists to prevent.
        # Reclaim here whenever the row is still genuinely stale; this is
        # a no-op read-plus-possible-reclaim for the normal, non-recovery
        # dispatch path, since a row claimed moments ago by its own fresh
        # start_new_attempt is never stale.
        if row["status"] == "reasoning":
            stale, _ = attempt_fencing.is_stale(org_id, decision_id)
            if stale:
                reclaimed = attempt_fencing.try_reclaim(org_id, decision_id)
                if reclaimed is None:
                    return  # someone else already reclaimed it first
                attempt_id = reclaimed
        if job["job_kind"] == "generic_triage":
            category = (row["user_supplied_inputs"] or {}).get("__decision_category__", "other")
            _run_generic_reasoning_safe(org_id, decision_id, attempt_id, row["raw_question"], category)
        else:
            stored = row["user_supplied_inputs"] or {}
            suppliers = stored.get("__supplier_specific_evidence__")
            stakeholders = stored.get("__stakeholder_views__")
            evidence = {k: v for k, v in stored.items() if not (k.startswith("__") and k.endswith("__"))}
            normalized, _ = normalize_evidence(row["raw_question"], row["classified_content_type"], evidence, evidence,
                                               supplier_specific_evidence=suppliers, stakeholder_views=stakeholders)
            _run_reasoning(org_id, decision_id, attempt_id, normalized, row["raw_question"],
                           continuation_context=stored.get("__continuation_context__"))
        job_queue.complete(org_id, decision_id)
    except Exception as exc:
        if job_queue.fail_or_retry(org_id, decision_id, type(exc).__name__, str(exc)) == "failed":
            attempt_fencing.write_provider_unavailable(org_id, decision_id, row["current_attempt_id"] if row else "")


def _run_reasoning_safe(org_id, decision_id, attempt_id: str, normalized, raw_question, constraint_signal=None, continuation_context=None):
    """
    Wraps _run_reasoning with a broad outer safety net -- this is what
    makes background-task execution genuinely safe. Since a background
    task runs after the HTTP response is already sent, an unhandled
    exception here would otherwise vanish silently. This guarantees ANY
    failure, anywhere in the reasoning chain, results in a real,
    recoverable state -- and the fencing on write_provider_unavailable
    means even THIS failure-handling path can never mark a case failed
    out from under a newer attempt that has since taken over.
    """
    try:
        _run_reasoning(org_id, decision_id, attempt_id, normalized, raw_question, constraint_signal, continuation_context)
    except Exception as e:
        try:
            _log_full_error("Background reasoning task failed", e)
            attempt_fencing.write_provider_unavailable(org_id, decision_id, attempt_id)
        except Exception:
            pass  # even failure-handling itself must never raise further, silently or loudly


@router.post("/commercial-decisions/{decision_id}/respond", response_model=CommercialDecisionResponse)
def respond(decision_id: UUID, body: RespondRequest, background_tasks: BackgroundTasks, request: Request,
            x_org_id: str = Header(...), x_user_id: str = Header(...)):
    x_org_id, x_user_id = _require_identity(request)
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, raw_question, classified_content_type, "
                "classified_decision_type, user_supplied_inputs, numeric_facts, "
                "reasoning_started_at "
                "FROM commercial_decisions WHERE id = %s",
                (str(decision_id),),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Decision not found")

    current_status = row["status"]

    # Idempotent, not an error: if this case already completed (perhaps
    # the user's first submission succeeded and this is a duplicate
    # arriving late), just show the real, final result.
    if current_status == "completed":
        return _fetch_decision(x_org_id, decision_id)

    # Genuinely invalid -- never had evidence requested, or some other
    # state that was never meant to receive a response at all.
    if current_status not in ("awaiting_user_input", "reasoning", "provider_unavailable"):
        raise HTTPException(
            status_code=409,
            detail=f"Decision is in status '{current_status}', not awaiting input.",
        )

    if current_status == "reasoning":
        stale, elapsed = attempt_fencing.is_stale(x_org_id, decision_id)
        if not stale:
            # Direct fix for the reported symptom: a genuine, still-live
            # in-flight case is never an error to the caller -- graceful
            # acknowledgment, not a 409. Heartbeat-based, not time-only --
            # a legitimately 15-minute call is never mistaken for dead.
            return _fetch_decision(x_org_id, decision_id)
        # Genuinely stale (heartbeat evidence, not elapsed time alone) --
        # safe to reclaim. try_reclaim atomically replaces
        # current_attempt_id, permanently invalidating any future write
        # the old, presumed-dead attempt might still somehow make.
        attempt_id = attempt_fencing.try_reclaim(x_org_id, decision_id)
        if attempt_id is None:
            return _fetch_decision(x_org_id, decision_id)  # someone else already reclaimed it
        return _restart_reasoning_from_stored_evidence(x_org_id, decision_id, attempt_id, row, background_tasks)

    if current_status == "provider_unavailable":
        # Recovery path: a genuine, recorded failure is always safely
        # retriable, reusing the evidence already stored.
        attempt_id = attempt_fencing.try_reclaim(x_org_id, decision_id)
        if attempt_id is None:
            return _fetch_decision(x_org_id, decision_id)
        return _restart_reasoning_from_stored_evidence(x_org_id, decision_id, attempt_id, row, background_tasks)

    # current_status == "awaiting_user_input" -- the normal path.
    pending_conflicts = (row["user_supplied_inputs"] or {}).get("__continuation_conflicts__")
    if pending_conflicts:
        confirmation = str(body.user_supplied_inputs.get("continuation_evidence_confirmation", "")).strip().lower()
        if confirmation not in {"confirm", "confirmed", "yes"}:
            raise HTTPException(422, detail="Confirm the changed continuation evidence before recalculation.")
    merged_evidence = {**(row["user_supplied_inputs"] or {}), **body.user_supplied_inputs}
    merged_evidence.pop("__continuation_conflicts__", None)
    merged_evidence.pop("continuation_evidence_confirmation", None)
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE commercial_decisions SET user_supplied_inputs = %s "
                "WHERE id = %s AND status = 'awaiting_user_input'",
                (json.dumps(merged_evidence), str(decision_id)),
            )

    # Atomic claim -- the real concurrency lock. If this fails, someone
    # else (a genuine double-click, a racing client retry) already
    # claimed it between our read above and this attempt; graceful, not
    # an error.
    attempt_id = attempt_fencing.start_new_attempt(x_org_id, decision_id, from_status="awaiting_user_input")
    if attempt_id is None:
        return _fetch_decision(x_org_id, decision_id)

    restored_suppliers = merged_evidence.get("__supplier_specific_evidence__")
    restored_stakeholders = merged_evidence.get("__stakeholder_views__")
    normalize_input_evidence = {k: v for k, v in merged_evidence.items() if k not in {"__supplier_specific_evidence__", "__stakeholder_views__"}}
    normalized, conflicts = normalize_evidence(
        row["raw_question"], row["classified_content_type"], normalize_input_evidence, normalize_input_evidence,
        supplier_specific_evidence=restored_suppliers,
        stakeholder_views=restored_stakeholders,
    )
    for field in conflicts:
        _log_fallback_fired(field, row["classified_content_type"], is_conflict=True, organisation_id=x_org_id)

    missing = check_missing_evidence(normalized)
    if missing:
        # Genuinely still incomplete even after this answer -- revert
        # back to awaiting input for the remaining fields.
        _set_awaiting_input(x_org_id, decision_id, missing)
        return _fetch_decision(x_org_id, decision_id)

    job_queue.requeue(x_org_id, decision_id)
    background_tasks.add_task(_run_queued_job, x_org_id, decision_id)
    return _fetch_decision(x_org_id, decision_id)


@router.get("/commercial-decisions/{decision_id}", response_model=CommercialDecisionResponse)
def get_decision(decision_id: UUID, request: Request, x_org_id: str = Header(...), x_user_id: str = Header(...)):
    x_org_id, x_user_id = _require_identity(request)
    return _fetch_decision(x_org_id, decision_id)


@router.post("/commercial-decisions/{decision_id}/cancel", response_model=CommercialDecisionResponse)
def cancel_decision(decision_id: UUID, request: Request):
    """Cancel queued/running provider work without deleting the case evidence."""
    x_org_id, _ = _require_identity(request)
    if not job_queue.cancel(x_org_id, decision_id):
        raise HTTPException(409, detail="This analysis can no longer be cancelled.")
    _update_status(x_org_id, decision_id, "provider_unavailable")
    return _fetch_decision(x_org_id, decision_id)


@router.post("/commercial-decisions/{decision_id}/continue", response_model=CommercialDecisionResponse)
def continue_case(decision_id: UUID, body: ContinueCaseRequest, background_tasks: BackgroundTasks, request: Request,
                   x_org_id: str = Header(...), x_user_id: str = Header(...)):
    x_org_id, x_user_id = _require_identity(request)
    """
    Creates a NEW, linked commercial_decision that continues an existing
    case -- never edits the original. The parent stays exactly as it was,
    protected by the tamper-prevention trigger; this row carries
    parent_decision_id back to it, preserving a real audit trail of how the
    negotiation evolved rather than overwriting history.
    """
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, raw_question, classified_content_type, user_supplied_inputs,
                          numeric_facts, commercial_position, status
                   FROM commercial_decisions WHERE id = %s""",
                (str(decision_id),),
            )
            parent = cur.fetchone()
            if not parent:
                raise HTTPException(status_code=404, detail="Case not found")
            if parent["status"] != "completed":
                raise HTTPException(
                    status_code=409,
                    detail="Only a completed case can be continued -- this one hasn't finished yet.",
                )

    parent_position = parent["commercial_position"] or {}
    if isinstance(parent_position, str):
        parent_position = json.loads(parent_position)

    continuation_context = (
        f"Prior recommendation: \"{parent_position.get('recommendation', '(none on file)')}\"\n"
        f"Prior confidence: {parent_position.get('confidence', {}).get('level', 'unknown')}\n"
        f"Prior key assumption(s): {'; '.join(parent_position.get('assumptions', [])[:2]) or '(none on file)'}\n\n"
        f"WHAT HAPPENED SINCE (from the user):\n{body.what_happened}"
    )

    new_decision_id = body.client_decision_id or uuid4()
    new_attempt_id = attempt_fencing.new_attempt_id()
    existing_continuation = False
    parent_flat_evidence = parent["user_supplied_inputs"] or {}
    # Non-mutating read -- the INSERT below must still store the full
    # data (including this key) so a FURTHER continuation of this new
    # case can also restore supplier evidence. A prior version of this
    # fix used .pop(), which removed the key before the INSERT ran,
    # silently losing supplier data for any second-level continuation --
    # caught and fixed before shipping.
    restored_suppliers = parent_flat_evidence.get("__supplier_specific_evidence__")
    restored_stakeholders = parent_flat_evidence.get("__stakeholder_views__")
    normalize_input_evidence = {k: v for k, v in parent_flat_evidence.items() if k not in {"__supplier_specific_evidence__", "__stakeholder_views__"}}
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO commercial_decisions
                   (id, organisation_id, created_by_user_id, raw_question,
                    classified_content_type, parent_decision_id, status,
                    user_supplied_inputs, numeric_facts, reasoning_started_at,
                   current_attempt_id, last_heartbeat_at, current_stage)
                   VALUES (%s, %s, %s, %s, %s, %s, 'reasoning', %s, %s, now(), %s, now(), 'starting')
                   ON CONFLICT (id) DO NOTHING
                   RETURNING id""",
                (str(new_decision_id), x_org_id, x_user_id, body.what_happened,
                 parent["classified_content_type"], str(decision_id),
                 json.dumps({**parent_flat_evidence, "__continuation_context__": continuation_context}),
                 json.dumps(parent_flat_evidence), new_attempt_id),
            )
            if cur.fetchone():
                _reserve_monthly_llm_usage(x_org_id, cur)
            else:
                existing_continuation = True

    if existing_continuation:
        return _fetch_decision(x_org_id, new_decision_id)

    # A continuation is new evidence, not merely prose appended to an old
    # answer. Extract it through the live classifier contract, then reconcile
    # it with the immutable parent evidence before any deterministic math.
    try:
        update_classification = classify(body.what_happened)
    except Exception as exc:
        _update_status(x_org_id, new_decision_id, "provider_unavailable")
        raise HTTPException(503, detail=_log_full_error("Continuation extraction failed", exc))
    if update_classification.get("content_type") not in (parent["classified_content_type"], "unsupported"):
        _set_awaiting_input(x_org_id, new_decision_id, [{
            "field": "continuation_scope_confirmation",
            "prompt": "This update appears to describe a different decision type. Confirm the original case type is still correct before continuing.",
            "why": "A new decision type must not reuse the previous case's economics or recommendation."
        }])
        return _fetch_decision(x_org_id, new_decision_id)

    update_normalized, update_conflicts = normalize_evidence(
        body.what_happened, parent["classified_content_type"],
        update_classification.get("extracted_evidence") or {}, update_classification.get("numeric_facts") or {},
        supplier_specific_evidence=update_classification.get("supplier_specific_evidence"),
        stakeholder_views=update_classification.get("stakeholder_views"),
    )
    update_flat = update_normalized.as_flat_evidence_dict()
    parent_visible = {k: v for k, v in parent_flat_evidence.items() if not (k.startswith("__") and k.endswith("__"))}
    changed = [k for k, value in update_flat.items() if value is not None and parent_visible.get(k) not in (None, value)]
    merged_evidence = {**parent_flat_evidence, **{k: v for k, v in update_flat.items() if v is not None}}
    if update_normalized.suppliers:
        merged_evidence["__supplier_specific_evidence__"] = [s.model_dump() for s in update_normalized.suppliers]
    if update_normalized.stakeholder_views:
        merged_evidence["__stakeholder_views__"] = [v.model_dump() for v in update_normalized.stakeholder_views]
    if changed or update_conflicts:
        with get_org_scoped_connection(x_org_id) as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE commercial_decisions SET status = 'awaiting_user_input', user_supplied_inputs = %s, missing_inputs_requested = %s WHERE id = %s",
                            (json.dumps({**merged_evidence, "__continuation_conflicts__": changed}),
                             json.dumps([{"field": "continuation_evidence_confirmation", "prompt": "New evidence changes: " + ", ".join(changed or update_conflicts) + ". Confirm these updated values before VendorEdge recalculates the case.", "why": "Conflicting commercial inputs cannot be silently replaced."}]),
                             str(new_decision_id)))
        return _fetch_decision(x_org_id, new_decision_id)

    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE commercial_decisions SET user_supplied_inputs = %s, numeric_facts = %s WHERE id = %s", (json.dumps(merged_evidence), json.dumps(merged_evidence), str(new_decision_id)))

    # Re-normalize the reconciled evidence to ensure financial calculations
    # use the update, rather than the parent snapshot.
    normalized, conflicts = normalize_evidence(
        body.what_happened, parent["classified_content_type"],
        {k: v for k, v in merged_evidence.items() if not (k.startswith("__") and k.endswith("__"))},
        {k: v for k, v in merged_evidence.items() if not (k.startswith("__") and k.endswith("__"))},
        supplier_specific_evidence=merged_evidence.get("__supplier_specific_evidence__"),
        stakeholder_views=merged_evidence.get("__stakeholder_views__"),
    )
    for field in conflicts:
        _log_fallback_fired(field, parent["classified_content_type"], is_conflict=True, organisation_id=x_org_id)

    job_queue.enqueue(x_org_id, new_decision_id, "specialist")
    background_tasks.add_task(_run_queued_job, x_org_id, new_decision_id)
    return _fetch_decision(x_org_id, new_decision_id)


@router.get("/pilot-metrics")
def pilot_metrics(request: Request):
    """Return deterministic pilot-readiness metrics for the current organisation."""
    x_org_id, _ = _require_identity(request)
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ease_of_use, trust_level, time_saved, would_use_again FROM pilot_experience_feedback")
            experience = cur.fetchall()
            cur.execute("SELECT validation_verdict FROM decision_feedback")
            outcomes = cur.fetchall()
    return build_pilot_metrics(experience, outcomes)


@router.post("/commercial-decisions/{decision_id}/pilot-experience", status_code=201)
def submit_pilot_experience(decision_id: UUID, body: PilotExperienceRequest, request: Request, x_org_id: str = Header(...), x_user_id: str = Header(...)):
    """Capture real pilot usability/value evidence without changing the decision.

    This is intentionally separate from decision_feedback: commercial outcomes
    answer whether the decision held up; this table answers whether the product
    was useful and usable. Neither is fed into the current decision's reasoning.
    """
    x_org_id, x_user_id = _require_identity(request)
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM commercial_decisions WHERE id = %s", (str(decision_id),))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Decision not found")
            if row["status"] != "completed":
                raise HTTPException(status_code=409, detail="Pilot experience can be recorded after the decision is completed.")
            cur.execute(
                """INSERT INTO pilot_experience_feedback
                   (commercial_decision_id, submitted_by_user_id, ease_of_use, trust_level,
                    time_saved, would_use_again, most_valuable, missing_or_frustrating)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (commercial_decision_id, submitted_by_user_id)
                   DO UPDATE SET ease_of_use = EXCLUDED.ease_of_use,
                                 trust_level = EXCLUDED.trust_level,
                                 time_saved = EXCLUDED.time_saved,
                                 would_use_again = EXCLUDED.would_use_again,
                                 most_valuable = EXCLUDED.most_valuable,
                                 missing_or_frustrating = EXCLUDED.missing_or_frustrating,
                                 recorded_at = now()
                   RETURNING id, recorded_at""",
                (str(decision_id), x_user_id, body.ease_of_use, body.trust_level,
                 body.time_saved, body.would_use_again, body.most_valuable, body.missing_or_frustrating),
            )
            return cur.fetchone()


@router.post("/commercial-decisions/{decision_id}/custom-format")
def render_custom_customer_format(decision_id: UUID, body: CustomFormatRequest, request: Request):
    """Render a user's own text template from the already validated decision.

    The template is a presentation contract only: it cannot introduce a new
    fact, trigger reasoning, or alter the stored decision.
    """
    x_org_id, _ = _require_identity(request)
    decision = _fetch_decision(x_org_id, decision_id)
    if decision.status != "completed" or decision.commercial_position is None:
        raise HTTPException(status_code=409, detail="A completed decision is required.")
    action_plan = build_action_plan(decision.commercial_position)
    try:
        return render_custom(decision.commercial_position, body.template, action_plan)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/commercial-decisions/{decision_id}/integration/webhook")
def dispatch_decision_webhook(decision_id: UUID, request: Request):
    """Explicitly dispatch a minimal completed-decision event to the configured integration."""
    x_org_id, _ = _require_identity(request)
    decision = _fetch_decision(x_org_id, decision_id)
    if decision.status != "completed" or decision.commercial_position is None:
        raise HTTPException(status_code=409, detail="A completed decision is required.")
    return dispatch_event(str(decision_id), decision.commercial_position)


@router.get("/commercial-decisions/{decision_id}/action-plan")
def get_action_plan(decision_id: UUID, request: Request):
    """Return an approval-gated execution plan without causing external side effects."""
    x_org_id, _ = _require_identity(request)
    decision = _fetch_decision(x_org_id, decision_id)
    if decision.status != "completed" or decision.commercial_position is None:
        raise HTTPException(status_code=409, detail="A completed decision is required.")
    return build_action_plan(decision.commercial_position)


@router.get("/commercial-decisions/{decision_id}/export.csv")
def export_decision_csv(decision_id: UUID, request: Request):
    """Export the decision as a deterministic CSV snapshot for downstream systems."""
    x_org_id, _ = _require_identity(request)
    decision = _fetch_decision(x_org_id, decision_id)
    if decision.status != "completed" or decision.commercial_position is None:
        raise HTTPException(status_code=409, detail="A completed decision is required.")
    return Response(
        content=export_csv(decision.commercial_position),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="vendoredge-{decision_id}.csv"'},
    )


@router.post("/commercial-decisions/{decision_id}/format")
def render_customer_format(decision_id: UUID, body: DecisionFormatRequest, request: Request):
    """Render an existing completed decision in a customer-native format.

    This is a pure presentation transform: no new reasoning, no new evidence,
    and no recalculation.
    """
    x_org_id, _ = _require_identity(request)
    decision = _fetch_decision(x_org_id, decision_id)
    if decision.status != "completed" or decision.commercial_position is None:
        raise HTTPException(status_code=409, detail="A completed decision is required.")
    try:
        return render_decision(decision.commercial_position, body.format_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/commercial-decisions/{decision_id}/feedback", status_code=201)
def submit_feedback(decision_id: UUID, body: FeedbackRequest, request: Request, x_org_id: str = Header(...), x_user_id: str = Header(...)):
    x_org_id, x_user_id = _require_identity(request)
    with get_org_scoped_connection(x_org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO decision_feedback
                   (commercial_decision_id, submitted_by_user_id, decision_alignment,
                    outcome_description, validation_verdict, unexpected_insight,
                    actual_financial_impact_usd, actual_measurement_basis)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, outcome_recorded_at""",
                (str(decision_id), x_user_id, body.decision_alignment,
                 body.outcome_description, body.validation_verdict, body.unexpected_insight,
                 body.actual_financial_impact_usd, body.actual_measurement_basis),
            )
            return cur.fetchone()


# --- internal helpers ---

def _get_org_history(org_id, content_type, exclude_decision_id) -> list[dict]:
    """
    This org's own past recorded outcomes for the same content_type -- the
    entire organizational-learning mechanism for the MVP. RLS on
    commercial_decisions (enforced via the org-scoped connection) means this
    INNER JOIN can only ever return feedback rows whose parent decision
    belongs to this org, even though decision_feedback has no organisation_id
    column of its own.

    Includes unexpected_insight -- without pulling this specific field in,
    it would just be stored in the database and never actually reach future
    reasoning, which would defeat the entire point of capturing it.
    """
    if not content_type:
        return []
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT cd.commercial_position, df.outcome_description,
                          df.validation_verdict, df.unexpected_insight,
                          df.actual_financial_impact_usd, df.actual_measurement_basis
                   FROM decision_feedback df
                   JOIN commercial_decisions cd ON cd.id = df.commercial_decision_id
                   WHERE cd.classified_content_type = %s AND cd.id != %s
                   ORDER BY df.outcome_recorded_at DESC
                   LIMIT %s""",
                (content_type, str(exclude_decision_id), HISTORY_LIMIT),
            )
            return cur.fetchall()


def _get_supplier_specific_history(org_id, supplier_name, exclude_decision_id) -> list[dict]:
    """
    Real, distinct addition alongside _get_org_history above: matches past
    cases involving the SAME NAMED supplier, not just the same content
    type. Only fires when a genuine, specific supplier name was captured
    (never a generic "Supplier A" placeholder -- see classifier.py, which
    deliberately excludes those from extraction, since they'd incorrectly
    link unrelated suppliers across different cases).

    Deliberately returns the RAW facts from matching past cases, not a
    computed statistic (e.g. never "settles at 1/3 of opening ask") --
    with realistically few cases per organisation early on, a computed
    average would be false precision dressed up as insight. The reasoning
    prompt is instructed to speak to a genuine pattern only when the real
    volume of history actually supports one, and to say plainly when it
    doesn't -- same honesty discipline as every other guarantee in this
    codebase, just applied to a new capability.
    """
    if not supplier_name or not supplier_name.strip():
        return []
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT cd.raw_question, cd.commercial_position, cd.created_at,
                          df.outcome_description, df.validation_verdict, df.decision_alignment,
                          df.actual_financial_impact_usd, df.actual_measurement_basis
                   FROM commercial_decisions cd
                   LEFT JOIN decision_feedback df ON df.commercial_decision_id = cd.id
                   WHERE cd.user_supplied_inputs->>'supplier_name' ILIKE %s
                     AND cd.id != %s
                     AND cd.status = 'completed'
                   ORDER BY cd.created_at DESC
                   LIMIT %s""",
                (supplier_name.strip(), str(exclude_decision_id), HISTORY_LIMIT),
            )
            return cur.fetchall()


# Real minimum sample size before ANY calibration statistic is computed or
# shown -- below this, the honest answer is "not enough data yet," not a
# percentage from too few real outcomes. Deliberately small (this is a
# pilot), but never zero -- a stat from 1-2 outcomes is exactly the same
# false-precision risk Phase 2 (supplier memory) was built to avoid.
MIN_OUTCOMES_FOR_CALIBRATION = 3


def _compute_confidence_calibration(org_id) -> str | None:
    """
    Real outcome-based learning (Phase 3): computes, in code -- never left
    to the model's own vague sense of "we've been pretty good so far" --
    how often this organization's past recorded outcomes actually
    confirmed VendorEdge's reasoning (validation_verdict == 'reasoning_held')
    versus didn't. Deliberately organization-wide, not per content-type or
    per confidence-level, since splitting further would shrink an already
    small pilot-stage sample into genuinely meaningless fractions.

    Returns None (no note shown at all) when there isn't yet enough real
    data to support a real number -- same honesty discipline as
    _format_supplier_history in reasoner.py, just applied organization-wide
    instead of per-supplier.
    """
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT validation_verdict FROM decision_feedback df
                   JOIN commercial_decisions cd ON cd.id = df.commercial_decision_id"""
            )
            rows = cur.fetchall()

    total = len(rows)
    if total < MIN_OUTCOMES_FOR_CALIBRATION:
        return None

    held = sum(1 for r in rows if r["validation_verdict"] == "reasoning_held")
    percent = round((held / total) * 100)
    return (
        f"Across this organization's {total} recorded outcomes so far, "
        f"reasoning held up as given in {held} ({percent}%) of them -- "
        f"a real, growing track record, not a claim about any single case."
    )


def _run_reasoning(org_id, decision_id, attempt_id: str, normalized: NormalizedEvidence, raw_question, constraint_signal=None, continuation_context=None):
    content_type = normalized.content_type
    history = _get_org_history(org_id, content_type, decision_id)
    supplier_history = []
    try:
        supplier_name = normalized.common.supplier_name
        if supplier_name:
            supplier_history = _get_supplier_specific_history(org_id, supplier_name, decision_id)
    except Exception as e:
        print(f"Supplier-specific history lookup skipped (non-blocking): {type(e).__name__}: {e}")
        supplier_history = []
    normalized.history = HistoryContext(org_history=history, supplier_history=supplier_history)

    try:
        financial_impact = compute_financial_impact(normalized)
    except Exception as e:
        print(f"Financial calculation skipped (non-blocking): {type(e).__name__}: {e}")
        financial_impact = None

    # Requirement 1, enforced by construction: HeartbeatTicker writes are
    # wrapped by write_heartbeat(), which can never raise. Nothing about
    # wrapping a call in a ticker changes its behavior, timing, retry
    # logic, or output -- it is purely observational, layered around the
    # real work, never inside it.
    market_verification = None
    if content_type == "price_increase":
        stated_justification = normalized.case.suppliers_stated_justification or ""
        supplier_region = normalized.common.supplier_region_or_market
        with attempt_fencing.HeartbeatTicker(org_id, decision_id, attempt_id, "market_verification"):
            market_verification = verify_market_claim(stated_justification, region=supplier_region)

    pre_confidence_level, pre_confidence_reasons = compute_pre_reasoning_confidence(normalized)
    stakeholder_protocol = build_stakeholder_decision_protocol(normalized)

    def _reasoning_call(stage_name, **extra_kwargs):
        with attempt_fencing.HeartbeatTicker(org_id, decision_id, attempt_id, stage_name):
            return generate_commercial_position(
                normalized, raw_question, constraint_signal=constraint_signal,
                computed_financial_impact=financial_impact,
                market_verification=market_verification,
                continuation_context=continuation_context,
                system_confidence_level=pre_confidence_level,
                stakeholder_protocol=stakeholder_protocol,
                **extra_kwargs,
            )

    try:
        position = _reasoning_call("primary_reasoning")
        if market_verification is not None:
            position.market_verification_scope = market_verification.get("scope")
        try:
            position.confidence_calibration_note = _compute_confidence_calibration(org_id)
        except Exception as e:
            print(f"Confidence calibration skipped (non-blocking): {type(e).__name__}: {e}")
    except Exception as e:
        detail = _log_full_error("Reasoning (Step D) failed", e)
        # Attempt-fenced: if this attempt has already been superseded by
        # a reclaim, this write correctly, silently no-ops -- a newer
        # attempt already owns the case, and this old, failing attempt
        # must never be allowed to mark it failed out from under it.
        attempt_fencing.write_provider_unavailable(org_id, decision_id, attempt_id)
        raise HTTPException(status_code=503, detail=detail)

    if financial_impact is not None:
        position.financial_impact = financial_impact
    position.informed_by_case_count = len(history)

    # Release 5: attach a deterministic, evidence-only audit trail before the
    # final confidence ceiling is applied. It never treats the model's recommendation as evidence.
    try:
        position.decision_audit = DecisionAudit(**build_decision_audit(normalized, position))
    except Exception as e:
        print(f"Decision audit skipped (non-blocking): {type(e).__name__}: {e}")

    if claims_tco_methodology(position.methodology_applied):
        relevant_dimensions = determine_relevant_tco_dimensions(normalized)
        uncovered = check_tco_coverage(position, relevant_dimensions)
        if uncovered:
            try:
                correction_text = (
                    f"Your response claimed a TCO/landed-cost methodology, but was genuinely "
                    f"missing coverage of: {', '.join(uncovered)}. Either incorporate real "
                    f"numbers for these into your reasoning/financial discussion, or explicitly "
                    f"name them as a real gap in \"assumptions\"."
                )
                retried_position = _reasoning_call("methodology_check", methodology_correction=correction_text)
                if financial_impact is not None:
                    retried_position.financial_impact = financial_impact
                retried_position.informed_by_case_count = len(history)
                still_uncovered = check_tco_coverage(retried_position, relevant_dimensions)
                _log_fallback_fired("tco_retry_fired", content_type, organisation_id=org_id)
                if len(still_uncovered) < len(uncovered):
                    position = retried_position
            except Exception as e:
                print(f"Methodology-consistency retry skipped (non-blocking): {type(e).__name__}: {e}")

    if claims_kraljic_methodology(position.methodology_applied):
        missing_kraljic = check_kraljic_reasoning_coverage(position)
        if missing_kraljic:
            try:
                readable = {
                    "business_impact": "the business impact/criticality of this component (spend, downtime cost, or operational criticality)",
                    "supply_risk": "the supply risk (number of qualified alternatives, switching difficulty, capacity constraints, or lead time)",
                }
                correction_text = (
                    f"Your response claimed a Kraljic-style approach, but the reasoning never "
                    f"genuinely evaluated: {' and '.join(readable[m] for m in missing_kraljic)}. "
                    f"A real Kraljic assessment requires BOTH dimensions to be explicitly "
                    f"discussed before naming a quadrant or recommending a sourcing strategy -- "
                    f"if the evidence genuinely doesn't support assessing one of these, say so "
                    f"plainly rather than naming a quadrant anyway."
                )
                retried_position = _reasoning_call("methodology_check", methodology_correction=correction_text)
                if financial_impact is not None:
                    retried_position.financial_impact = financial_impact
                retried_position.informed_by_case_count = len(history)
                _log_fallback_fired("kraljic_retry_fired", content_type, organisation_id=org_id)
                still_missing = check_kraljic_reasoning_coverage(retried_position)
                if len(still_missing) < len(missing_kraljic):
                    position = retried_position
            except Exception as e:
                print(f"Kraljic-consistency retry skipped (non-blocking): {type(e).__name__}: {e}")

    contradictions = check_all_contradictions(position, normalized)
    if contradictions:
        try:
            correction_text = (
                f"Your response contains a genuine internal contradiction that must be fixed: "
                f"{' '.join(contradictions)} Regenerate your response so the reasoning and "
                f"recommendation text are consistent with the real, guaranteed financial figures "
                f"-- reference the actual computed number, do not claim it is unavailable."
            )
            retried_position = _reasoning_call("contradiction_check", methodology_correction=correction_text)
            if financial_impact is not None:
                retried_position.financial_impact = financial_impact
            retried_position.informed_by_case_count = len(history)
            _log_fallback_fired("contradiction_retry_fired", content_type, organisation_id=org_id)
            still_contradicting = check_all_contradictions(retried_position, normalized)
            if len(still_contradicting) < len(contradictions):
                position = retried_position
        except Exception as e:
            print(f"Contradiction-check retry skipped (non-blocking): {type(e).__name__}: {e}")

    overstatements = check_all_claim_overstatements(
        position, normalized, raw_question, is_continuation=continuation_context is not None,
    )
    if overstatements:
        try:
            correction_text = (
                f"Your response makes claims stronger than the evidence supports: "
                f"{' '.join(overstatements)} Regenerate using language that matches exactly what "
                f"the evidence shows -- never assert verification, certainty, superiority, "
                f"achievement, or legal status beyond what was genuinely established."
            )
            retried_position = _reasoning_call("claim_integrity_check", methodology_correction=correction_text)
            if financial_impact is not None:
                retried_position.financial_impact = financial_impact
            retried_position.informed_by_case_count = len(history)
            _log_fallback_fired("claim_integrity_retry_fired", content_type, organisation_id=org_id)
            still_overstating = check_all_claim_overstatements(
                retried_position, normalized, raw_question, is_continuation=continuation_context is not None,
            )
            if len(still_overstating) < len(overstatements):
                position = retried_position
        except Exception as e:
            print(f"Claim-integrity retry skipped (non-blocking): {type(e).__name__}: {e}")

    position = apply_confidence_ceiling(position, normalized)
    try:
        position.decision_audit = DecisionAudit(**build_decision_audit(normalized, position))
    except Exception as e:
        print(f"Decision audit refresh skipped (non-blocking): {type(e).__name__}: {e}")
    # Release 6: deterministic what-if analysis. The model does not author these numbers.
    try:
        position.sensitivity_analysis = build_sensitivity_analysis(normalized)
    except Exception as e:
        print(f"Sensitivity analysis skipped (non-blocking): {type(e).__name__}: {e}")
    # Release 7: deterministic adversarial stress test. Never another LLM call.
    try:
        position.stress_test = build_stress_test(normalized, position)
    except Exception as e:
        print(f"Stress test skipped (non-blocking): {type(e).__name__}: {e}")
    try:
        position.alternative_analysis = build_alternative_paths(normalized)
    except Exception as e:
        print(f"Alternative-path analysis skipped (non-blocking): {type(e).__name__}: {e}")
    # Release 9: deterministic executive control tower. Presentation/control
    # only; it never changes the recommendation or confidence.
    try:
        position.control_tower = ControlTower(**build_control_tower(normalized, position))
        from app.models import NegotiationPlaybook
        position.negotiation_playbook = NegotiationPlaybook(**build_negotiation_playbook(position))
    except Exception as e:
        print(f"Control tower skipped (non-blocking): {type(e).__name__}: {e}")

    if pre_confidence_reasons:
        position.confidence.derivation_note += (
            " Pre-reasoning evidence signals considered: " + "; ".join(pre_confidence_reasons) + "."
        )
    # Rebuild once after the final confidence/audit state is settled.
    try:
        position.control_tower = ControlTower(**build_control_tower(normalized, position))
        from app.models import NegotiationPlaybook
        position.negotiation_playbook = NegotiationPlaybook(**build_negotiation_playbook(position))
    except Exception as e:
        print(f"Control tower refresh skipped (non-blocking): {type(e).__name__}: {e}")

    # Release 19: deterministic trust certification. It is deliberately
    # computed before presentation artifacts so the certificate reflects the
    # final validated decision state and can never be changed by rendering.
    try:
        position.trust_certification = build_trust_certification(normalized, position)
    except Exception as e:
        print(f"Trust certification skipped (non-blocking): {type(e).__name__}: {e}")

    # Release 20: deterministic Commercial Truth Model. This is the single
    # structural commercial contract for downstream R21-R25 intelligence.
    # It is built after R19 trust is final and before presentation layers.
    try:
        position.commercial_truth_model = build_commercial_truth_model(normalized, position)
    except Exception as e:
        print(f"Commercial Truth Model skipped (non-blocking): {type(e).__name__}: {e}")

    # Release 21: deterministic Decision Flip Map. It is generated only after
    # the validated position exists, and it can never alter that position.
    try:
        position.decision_flip_map = build_decision_flip_map(normalized, position)
    except Exception as e:
        print(f"Decision flip map skipped (non-blocking): {type(e).__name__}: {e}")

    # Release 22: deterministic Commercial War Room. It assembles buyer, supplier,
    # market and stakeholder positions plus explicitly labelled negotiation
    # scenarios. It never predicts supplier psychology or changes the decision.
    try:
        position.commercial_war_room = build_commercial_war_room(normalized, position)
    except Exception as e:
        print(f"Commercial war room skipped (non-blocking): {type(e).__name__}: {e}")

    # Release 23: deterministic Procurement Memory. It is built from the
    # same persisted history already used to inform reasoning, plus recorded
    # outcomes. It cannot alter the current recommendation.
    try:
        position.procurement_memory = build_procurement_memory(
            normalized, position, normalized.history.org_history, normalized.history.supplier_history
        )
    except Exception as e:
        print(f"Procurement memory skipped (non-blocking): {type(e).__name__}: {e}")

    # Native VendorEdge presentation: deterministic answer-first passport.
    # It is generated only after confidence, audit, alternatives and stress
    # state are final, so the top-line card cannot disagree with the detail below.
    try:
        position.decision_passport = build_decision_passport(normalized, position)
    except Exception as e:
        print(f"Decision passport skipped (non-blocking): {type(e).__name__}: {e}")
    # R26: decision-under-uncertainty is computed before the cockpit so the
    # buyer gets a safe path even when evidence is incomplete.
    try:
        from app.pipeline.decision_under_uncertainty import build_decision_under_uncertainty
        position.decision_under_uncertainty = build_decision_under_uncertainty(normalized, position)
    except Exception as e:
        print(f"Decision-under-uncertainty skipped (non-blocking): {type(e).__name__}: {e}")

    # Release 18: native Commercial Decision Cockpit. It is deliberately
    # generated after all deterministic controls are final so the cockpit
    # cannot disagree with the stored recommendation/confidence.
    try:
        position.decision_cockpit = build_decision_cockpit(normalized, position)
    except Exception as e:
        print(f"Decision cockpit skipped (non-blocking): {type(e).__name__}: {e}")

    attempt_fencing.write_heartbeat(org_id, decision_id, attempt_id, "finalizing")
    write_succeeded = attempt_fencing.write_final_result(
        org_id, decision_id, attempt_id,
        position.model_dump_json(),
        _merge_final_provenance(org_id, decision_id, {k: v.model_dump() for k, v in normalized.provenance.items()}),
    )
    if not write_succeeded:
        # This attempt has been superseded -- a newer attempt already
        # owns this case (or already completed it). This attempt's real,
        # fully-computed result is correctly, deliberately discarded,
        # not an error to surface -- the case's true final state belongs
        # to whichever attempt is still current.
        print(f"Attempt {attempt_id} completed its work but was already superseded -- result discarded, not written.")
        return None
    return _fetch_decision(org_id, decision_id)


def _set_awaiting_input(org_id, decision_id, missing):
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE commercial_decisions
                   SET status = 'awaiting_user_input', missing_inputs_requested = %s
                   WHERE id = %s""",
                (json.dumps(missing), str(decision_id)),
            )


def _update_status(org_id, decision_id, status):
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE commercial_decisions SET status = %s WHERE id = %s", (status, str(decision_id)))


def _merge_final_provenance(org_id: str, decision_id, fresh_provenance: dict) -> str:
    """Builds the provenance JSON for the final completion write, merging
    rather than overwriting -- an existing, already-correct provenance
    entry is never replaced by a later re-derivation.

    Genuine bug, found by a real end-to-end test, not a review: once a
    field's value is resolved (e.g. via deterministic fallback because the
    model didn't extract it), that resolved value gets persisted back into
    the SAME flat evidence dict slot the model's own extraction would have
    occupied (as it must, for /respond and dispatch to have a single
    source of stored evidence to work from). Every later re-normalization
    of that stored evidence -- at /respond, at continue_case, and finally
    at actual reasoning dispatch time -- receives this already-resolved
    value as its "llm" input, since there is no way, once flattened, to
    tell "the model actually claimed this" apart from "this was already
    resolved". If the recomputed fallback also matches (as it always will,
    same source text, same regex), _resolve_field's own correct logic
    concludes "both agree" -- but that agreement is illusory: only one
    mechanism (the fallback) ever actually ran, just counted twice.

    The fix is not to make normalize_evidence itself "smarter" about
    detecting this -- once evidence is flattened into one dict, the
    distinction is genuinely, structurally gone, and no downstream
    heuristic can safely reconstruct it. The fix is to never let a later
    pass's provenance overwrite an earlier pass's provenance for a field
    it already correctly, originally classified. create_decision's first
    normalize_evidence call -- the one genuine point where "llm_value" and
    "fallback_value" are still truly independent -- persists its provenance
    immediately (see create_decision). This function is called at every
    later completion write and only adds provenance for fields that don't
    already have an entry -- new fields genuinely first resolved at this
    stage (e.g. derived TCO fields, a user's /respond answer, per-supplier
    data only available once reasoning actually ran) -- while leaving every
    already-correctly-classified field's original provenance untouched.
    """
    existing = get_evidence_provenance(org_id, decision_id) or {}
    merged = dict(existing)
    for field, prov in fresh_provenance.items():
        if field not in merged:
            merged[field] = prov
    return json.dumps(merged)


def get_evidence_provenance(org_id: str, decision_id, field_name: str | None = None) -> dict | None:
    """
    Quality Gate Guarantee #1 -- the actual, queryable answer to "where
    did this number come from," for ANY completed decision, at any later
    point, not just during the live request that produced it. Reads the
    persisted evidence_provenance column, respecting the same org-scoped
    RLS as everything else. If field_name is given, returns just that
    field's provenance entry; otherwise returns the full provenance dict
    for the case.
    """
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT evidence_provenance FROM commercial_decisions WHERE id = %s",
                (str(decision_id),),
            )
            row = cur.fetchone()
    if not row or not row["evidence_provenance"]:
        return None
    provenance = row["evidence_provenance"]
    if field_name is not None:
        return provenance.get(field_name)
    return provenance


# Requirement 5: internal stage names (market_verification,
# contradiction_check, claim_integrity_check, etc.) are real, useful for
# logs and heartbeat tracking, but must never reach a user directly. This
# is the one, single place internal stages are translated into calm,
# honest, non-technical language.
_CALM_STAGE_MESSAGES = {
    "starting": "VendorEdge is getting started on your case.",
    "market_verification": "VendorEdge is checking market conditions relevant to your case.",
    "primary_reasoning": "VendorEdge is analyzing your case.",
    "methodology_check": "VendorEdge is double-checking its commercial analysis.",
    "contradiction_check": "VendorEdge is verifying its own numbers are consistent.",
    "claim_integrity_check": "VendorEdge is verifying every claim matches the evidence.",
    "finalizing": "VendorEdge is finishing up.",
}


def _elapsed_seconds(started_at) -> float | None:
    """Real elapsed time since a timestamp, or None if there isn't one --
    never a fabricated duration."""
    if started_at is None:
        return None
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return (now - started_at).total_seconds()


def _fetch_decision(org_id, decision_id) -> CommercialDecisionResponse:
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT cd.id, cd.status, cd.raw_question, cd.classified_content_type,
                          cd.classified_decision_type, cd.missing_inputs_requested,
                          cd.commercial_position, cd.created_at, cd.completed_at,
                          cd.user_supplied_inputs, cd.parent_decision_id, cd.reasoning_started_at,
                          cd.last_heartbeat_at, cd.current_stage, cd.current_attempt_id,
                          (df.id IS NOT NULL) AS has_outcome_feedback,
                          df.outcome_description AS recorded_outcome_description,
                          df.validation_verdict AS recorded_outcome_verdict,
                          df.outcome_recorded_at AS recorded_outcome_at,
                          df.decision_alignment AS recorded_decision_alignment,
                          df.unexpected_insight AS recorded_unexpected_insight,
                          df.actual_financial_impact_usd AS recorded_actual_financial_impact_usd,
                          df.actual_measurement_basis AS recorded_actual_measurement_basis
                   FROM commercial_decisions cd
                   LEFT JOIN LATERAL (
                       SELECT id, outcome_description, validation_verdict, outcome_recorded_at,
                              decision_alignment, unexpected_insight, actual_financial_impact_usd,
                              actual_measurement_basis
                       FROM decision_feedback
                       WHERE commercial_decision_id = cd.id
                       ORDER BY outcome_recorded_at DESC
                       LIMIT 1
                   ) df ON true
                   WHERE cd.id = %s""",
                (str(decision_id),),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Decision not found")

            row_dict = dict(row)
            # Fix for the confirmed master-case leak: internal bookkeeping
            # keys (reserved __name__ convention, e.g.
            # __supplier_specific_evidence__) are stored in
            # user_supplied_inputs for real, legitimate reasons -- they
            # let /respond and continue_case restore structured data
            # across a round-trip. But they were never meant to be
            # user-facing evidence, and leaking one to the client renders
            # as "[object Object],[object Object]" (a JS array-of-objects
            # naively stringified). Filtered generically here, by naming
            # convention, not by hardcoding this one key -- a real
            # safeguard against the next internal field someone adds
            # later, not a one-off patch for today's specific symptom.
            # Database storage and the respond()/continue_case()
            # restoration logic read the raw column directly and are
            # completely unaffected by this -- only the outbound API
            # response changes.
            if row_dict.get("user_supplied_inputs"):
                row_dict["user_supplied_inputs"] = {
                    k: v for k, v in row_dict["user_supplied_inputs"].items()
                    if not (k.startswith("__") and k.endswith("__"))
                }

            # Total elapsed time is still real and honest to show --
            # "3m 42s" -- but heartbeat freshness, not total elapsed
            # time, is now the actual staleness determinant.
            total_elapsed = _elapsed_seconds(row_dict.pop("reasoning_started_at", None))
            heartbeat_elapsed = _elapsed_seconds(row_dict.pop("last_heartbeat_at", None))
            current_stage = row_dict.pop("current_stage", None)
            row_dict.pop("current_attempt_id", None)  # never expose attempt identity to the client

            if row_dict["status"] == "reasoning":
                is_stale = heartbeat_elapsed is None or heartbeat_elapsed >= attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS
                row_dict["processing_elapsed_seconds"] = round(total_elapsed, 1) if total_elapsed is not None else None
                row_dict["processing_is_stale"] = is_stale
                row_dict["can_retry"] = is_stale
                if is_stale:
                    row_dict["user_facing_state"] = "safely_resuming"
                    row_dict["processing_message"] = (
                        "This analysis appears to have stopped unexpectedly. Your case and "
                        "information are safe. VendorEdge can safely resume the analysis."
                    )
                else:
                    row_dict["user_facing_state"] = "working"
                    row_dict["processing_message"] = _CALM_STAGE_MESSAGES.get(
                        current_stage, "VendorEdge is still analyzing your case."
                    )
            elif row_dict["status"] == "provider_unavailable":
                row_dict["can_retry"] = True
                row_dict["user_facing_state"] = "unable_to_complete"
                row_dict["processing_message"] = (
                    "VendorEdge couldn't complete this analysis. You can safely try again -- "
                    "your answers are saved."
                )

            # R24: outcome intelligence is deliberately computed at read time
            # from immutable decision data + the latest recorded outcome. It
            # never writes back into commercial_position.
            try:
                position_obj = row_dict.get("commercial_position")
                feedback = None
                if row_dict.get("has_outcome_feedback"):
                    feedback = {
                        "outcome_description": row_dict.get("recorded_outcome_description"),
                        "validation_verdict": row_dict.get("recorded_outcome_verdict"),
                        "decision_alignment": row_dict.get("recorded_decision_alignment"),
                        "unexpected_insight": row_dict.get("recorded_unexpected_insight"),
                        "actual_financial_impact_usd": row_dict.get("recorded_actual_financial_impact_usd"),
                        "actual_measurement_basis": row_dict.get("recorded_actual_measurement_basis"),
                    }
                if position_obj:
                    from app.models import CommercialPosition
                    pos_model = position_obj if isinstance(position_obj, CommercialPosition) else CommercialPosition(**position_obj)
                    history_rows = []
                    if row_dict.get("classified_content_type"):
                        with get_org_scoped_connection(org_id) as hconn:
                            with hconn.cursor() as hcur:
                                hcur.execute(
                                    """SELECT cd.commercial_position, df.actual_financial_impact_usd
                                       FROM decision_feedback df
                                       JOIN commercial_decisions cd ON cd.id = df.commercial_decision_id
                                       WHERE cd.classified_content_type = %s AND cd.id != %s
                                         AND df.actual_financial_impact_usd IS NOT NULL
                                       ORDER BY df.outcome_recorded_at DESC LIMIT 50""",
                                    (row_dict["classified_content_type"], str(decision_id)),
                                )
                                for hr in hcur.fetchall():
                                    hp = hr.get("commercial_position") or {}
                                    hf = (hp.get("financial_impact") or {}) if isinstance(hp, dict) else {}
                                    history_rows.append({
                                        "expected_financial_impact_usd": hf.get("potential_annual_impact_usd"),
                                        "actual_financial_impact_usd": hr.get("actual_financial_impact_usd"),
                                    })
                    row_dict["outcome_intelligence"] = build_outcome_intelligence(pos_model, feedback, history_rows)
            except Exception as e:
                print(f"Outcome intelligence skipped (non-blocking): {type(e).__name__}: {e}")

            # R25: Commercial DNA is deliberately organization-wide and read-time.
            # Unlike R23's case-local memory, it looks across completed decisions
            # in this authenticated organization and only uses explicit persisted
            # outcomes. It never mutates commercial_position or the recommendation.
            try:
                dna_rows = []
                with get_org_scoped_connection(org_id) as dconn:
                    with dconn.cursor() as dcur:
                        dcur.execute(
                            """SELECT cd.id, cd.created_at, cd.classified_content_type,
                                      cd.commercial_position,
                                      df.validation_verdict, df.decision_alignment,
                                      df.actual_financial_impact_usd
                               FROM commercial_decisions cd
                               LEFT JOIN LATERAL (
                                   SELECT validation_verdict, decision_alignment, actual_financial_impact_usd
                                   FROM decision_feedback
                                   WHERE commercial_decision_id = cd.id
                                   ORDER BY outcome_recorded_at DESC
                                   LIMIT 1
                               ) df ON true
                               WHERE cd.status = 'completed' AND cd.id != %s
                               ORDER BY cd.created_at DESC
                               LIMIT 100""",
                            (str(decision_id),),
                        )
                        dna_rows = [dict(r) for r in dcur.fetchall()]
                row_dict["commercial_dna"] = build_commercial_dna(
                    row_dict.get("classified_content_type"), dna_rows
                )
            except Exception as e:
                print(f"Commercial DNA skipped (non-blocking): {type(e).__name__}: {e}")

            return CommercialDecisionResponse(**row_dict)
