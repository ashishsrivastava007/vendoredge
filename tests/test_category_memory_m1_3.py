"""
Category Memory M1.3 -- evidence_state storage integrity.

Root cause: memory_items.evidence_state was VARCHAR(20), but the
canonical 9-value evidence-state taxonomy's longest member,
EXTERNAL_MARKET_EVIDENCE, is 24 characters -- PostgreSQL enforces
VARCHAR(n) length at INSERT time (StringDataRightTruncation), which
happens independently of and before the CHECK constraint on allowed
values, so the value never reached the CHECK at all. store_candidates
catches this internally and returns {"error": ...} rather than
raising, so the failure was silent to every caller.

Fix: widened to VARCHAR(30) (derived from the actual taxonomy's
longest member plus headroom, not hardcoded to one value's exact
length), via both the CREATE TABLE definition (fresh databases) and
an explicit ALTER COLUMN ... TYPE statement (existing databases).
"""
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.memory_service import extract_candidates, store_candidates, retrieve_memory

client = TestClient(app)
_CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")

_ALL_CANONICAL_EVIDENCE_STATES = [
    "VERIFIED", "CALCULATED", "SUPPLIER_CLAIM", "STAKEHOLDER_VIEW",
    "EXTERNAL_MARKET_EVIDENCE", "INFERRED", "ASSUMED", "UNKNOWN", "CONTRADICTED",
]


def _make_org(suffix):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"91.100.{suffix}.1"}).json()
    return org, {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}


def _seed_bare_decision(headers):
    classify = {"content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
                "extracted_evidence": {"supplier_currency": "USD"}, "numeric_facts": {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000}, "supplier_specific_evidence": []}
    pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "seed", "mode": "category_strategy"}, headers=headers)
        decision_id = r.json()["id"]
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{decision_id}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return decision_id


# ---------------------------------------------------------------------
# The critical regression: EXTERNAL_MARKET_EVIDENCE (24 chars) --
# previously failed against the old VARCHAR(20) schema with a
# StringDataRightTruncation error, silently swallowed by store_
# candidates' own exception handling, retrieval returning nothing.
# ---------------------------------------------------------------------

def test_external_market_evidence_survives_storage_and_retrieval_unchanged():
    org, headers = _make_org(1)
    decision_id = _seed_bare_decision(headers)
    kernel = {"org_id": org["organisation_id"], "case": {"subject": "M13Supplier"}}
    finding = [{
        "dimension": "external_market_intelligence",
        "finding": "An external market movement in steel has been reported, but no corresponding internal spend or price movement is currently evidenced for this category.",
        "evidence_state": "EXTERNAL_MARKET_EVIDENCE", "decision_impact": "DECISION_CRITICAL_UNKNOWN",
        "source": "kernel:case", "evidence": "x", "implication": "y", "possible_action": "z",
    }]
    candidates = extract_candidates(kernel, finding, source_case_id=decision_id)
    assert candidates[0]["rejected"] is False
    store_result = store_candidates(org["organisation_id"], candidates)
    assert store_result.get("error") is None, f"storage failed: {store_result.get('error')}"
    assert len(store_result["stored"]) == 1
    retrieved = retrieve_memory(org["organisation_id"], category="M13Supplier")
    assert len(retrieved) == 1
    assert retrieved[0]["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE"  # exact value, not truncated


def test_external_market_evidence_reaches_live_category_strategy_answer():
    """The same failure, exercised through the real HTTP path rather
    than the memory service directly -- confirming the write inside
    build_category_strategy_answer's own flow (via a market-driver-
    with-no-internal-movement finding, which always carries this
    exact evidence state) no longer silently fails. A supplier is
    included so the case has a resolvable entity (kernel.case.subject
    is the incumbent supplier's name -- see kernel.py) -- a market-
    driver-only case with no supplier at all has no entity to anchor
    the memory item to and is correctly rejected by the pre-existing,
    unrelated "missing_entity" validation rule, independent of M1.3."""
    org, headers = _make_org(2)
    classify = {"content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
                "extracted_evidence": {"supplier_currency": "USD"},
                "numeric_facts": {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000},
                "supplier_specific_evidence": [{"supplier_name": "M13MarketCo", "is_incumbent": True, "current_annual_spend_usd": 400_000}],
                "market_driver_claims": [{"driver": "steel", "direction": "increased", "attributed_to": "unspecified"}]}
    pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "market driver check", "mode": "category_strategy"}, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}?include_diagnostics=true", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    a = d["commercial_position"]["category_strategy_answer"]
    finding = next(f for f in a["diagnostics"]["findings"] if f["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE")
    assert finding is not None  # the finding itself was always fine -- this confirms the ANSWER isn't broken
    retrieved = retrieve_memory(org["organisation_id"], category="M13MarketCo")
    market_items = [m for m in retrieved if m["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE"]
    assert len(market_items) == 1  # and now the memory WRITE for it succeeded too


# ---------------------------------------------------------------------
# All 9 canonical evidence states -- not just the one that happened to
# fail. Each: candidate -> validate -> store -> retrieve -> exact
# match, no truncation.
# ---------------------------------------------------------------------

def test_all_nine_canonical_evidence_states_survive_end_to_end():
    org, headers = _make_org(3)
    decision_id = _seed_bare_decision(headers)
    for i, state in enumerate(_ALL_CANONICAL_EVIDENCE_STATES):
        supplier = f"M13EvidCo{i}"
        kernel = {"org_id": org["organisation_id"], "case": {"subject": supplier}}
        finding = [{"dimension": "supplier_landscape", "finding": f"{supplier}: challenge.", "evidence_state": state,
                    "decision_impact": "DECISION_CHANGING", "source": "kernel:supplier_strategy", "evidence": "x", "implication": "y", "possible_action": "z"}]
        candidates = extract_candidates(kernel, finding, source_case_id=decision_id)
        store_result = store_candidates(org["organisation_id"], candidates)
        assert store_result.get("error") is None, f"{state} failed to store: {store_result.get('error')}"
        retrieved = retrieve_memory(org["organisation_id"], category=supplier)
        assert len(retrieved) == 1, f"{state} did not retrieve"
        assert retrieved[0]["evidence_state"] == state, f"{state} was altered/truncated to {retrieved[0]['evidence_state']}"


def test_no_silent_truncation_exact_character_count_preserved():
    """Distinct from the exact-match check above: explicitly confirms
    string LENGTH is preserved too, catching a truncation that
    happened to still produce a valid (but wrong, shorter) canonical
    value -- not possible with the current 9 values, but a genuinely
    distinct assertion from "matches expected"."""
    org, headers = _make_org(4)
    decision_id = _seed_bare_decision(headers)
    kernel = {"org_id": org["organisation_id"], "case": {"subject": "M13LengthCo"}}
    finding = [{"dimension": "external_market_intelligence",
                "finding": "An external market movement in copper has been reported, but no corresponding internal spend or price movement is currently evidenced for this category.",
                "evidence_state": "EXTERNAL_MARKET_EVIDENCE", "decision_impact": "DECISION_CRITICAL_UNKNOWN",
                "source": "kernel:case", "evidence": "x", "implication": "y", "possible_action": "z"}]
    candidates = extract_candidates(kernel, finding, source_case_id=decision_id)
    store_candidates(org["organisation_id"], candidates)
    retrieved = retrieve_memory(org["organisation_id"], category="M13LengthCo")
    assert len(retrieved[0]["evidence_state"]) == len("EXTERNAL_MARKET_EVIDENCE") == 24


# ---------------------------------------------------------------------
# Error-handling: the write-failure path is now observable at the one
# call site that previously discarded store_candidates' return value
# entirely (verified by inspection of app/routes/decisions.py; not
# re-testable end-to-end here without reintroducing a real failure,
# since all 9 canonical states now store successfully by construction).
# ---------------------------------------------------------------------

def test_store_candidates_still_reports_errors_in_its_return_value():
    """Confirms the underlying error-reporting contract (an accepted
    but failing write surfaces via result["error"], never raises) is
    unchanged by this fix -- still exercisable via a genuinely invalid
    write (a non-existent source_case_id, violating the foreign key)."""
    org, headers = _make_org(5)
    kernel = {"org_id": org["organisation_id"], "case": {"subject": "M13ErrCo"}}
    finding = [{"dimension": "supplier_landscape", "finding": "M13ErrCo: challenge.", "evidence_state": "CALCULATED",
                "decision_impact": "DECISION_CHANGING", "source": "kernel:supplier_strategy", "evidence": "x", "implication": "y", "possible_action": "z"}]
    candidates = extract_candidates(kernel, finding, source_case_id="00000000-0000-0000-0000-000000000000")  # no such decision
    store_result = store_candidates(org["organisation_id"], candidates)
    assert store_result.get("error") is not None
    assert len(store_result["stored"]) == 0


# ---------------------------------------------------------------------
# RLS / tenant isolation unaffected by the width change
# ---------------------------------------------------------------------

def test_tenant_isolation_unaffected_by_schema_widening():
    org_a, headers_a = _make_org(6)
    org_b, headers_b = _make_org(7)
    decision_id = _seed_bare_decision(headers_a)
    kernel = {"org_id": org_a["organisation_id"], "case": {"subject": "M13IsolCo"}}
    finding = [{"dimension": "external_market_intelligence",
                "finding": "An external market movement in aluminum has been reported, but no corresponding internal spend or price movement is currently evidenced for this category.",
                "evidence_state": "EXTERNAL_MARKET_EVIDENCE", "decision_impact": "DECISION_CRITICAL_UNKNOWN",
                "source": "kernel:case", "evidence": "x", "implication": "y", "possible_action": "z"}]
    candidates = extract_candidates(kernel, finding, source_case_id=decision_id)
    store_candidates(org_a["organisation_id"], candidates)
    retrieved_a = retrieve_memory(org_a["organisation_id"], category="M13IsolCo")
    retrieved_b = retrieve_memory(org_b["organisation_id"], category="M13IsolCo")
    assert len(retrieved_a) == 1
    assert len(retrieved_b) == 0
