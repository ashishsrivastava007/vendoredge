"""
P0 defect fix: the deployed Supplier Request output showed "Draft
response to the supplier — [object Object]". Root cause, traced
precisely: _build_response_draft() returns a structured {subject,
body, status} dict (matching the generic commercial_answer renderer's
own correct handling of this exact field) -- but renderSupplierRequestAnswer
(added in the R46 wiring fix) called esc() on the whole object instead
of extracting .subject/.body, and JavaScript's String() on a plain
object produces literally "[object Object]". Fixed by extracting the
fields, matching the pattern the generic renderer already used
correctly. Not a frontend string workaround -- the object's shape was
always correct; only the rendering was wrong.

Also covers the adjacent, related fix: the draft is no longer forced
into every Supplier Request. It reads the actual decision (accept /
challenge / investigate) from the recommendation text and adapts
accordingly, and is suppressed entirely when the recommendation itself
says more investigation is needed first.
"""
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.commercial_answer import _build_response_draft, _classify_decision_stance
from app.pipeline.normalize import normalize_evidence

INDEX_HTML = Path(__file__).parents[1] / "app" / "static" / "index.html"
client = TestClient(app)
_CONF = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _run(recommendation, extra_evidence, suffix):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"10.710.{suffix}.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    classify = {
        "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", "suppliers_stated_justification": "Rising raw material costs.", "how_critical_is_this_supplier_relationship": "sole-source", **extra_evidence},
        "numeric_facts": {"annual_spend_usd": 1_000_000, "requested_change_percent": 8.0},
        "supplier_specific_evidence": [{"supplier_name": "Supplier X", "is_incumbent": True}],
    }
    pos = CommercialPosition(recommendation=recommendation, commercial_insights=["a"], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        import time
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "test"}, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return d["commercial_position"]


# ---------------------------------------------------------------------
# Frontend markup: structured object must never coerce to a string
# ---------------------------------------------------------------------

def test_draft_response_frontend_extracts_subject_and_body_not_whole_object():
    text = INDEX_HTML.read_text()
    assert "esc(a.draft_response.subject)" in text
    assert "esc(a.draft_response.body)" in text
    # The exact regression: esc() called directly on the whole object,
    # which is what produced [object Object] in the deployed output.
    assert "esc(a.draft_response)}" not in text


def test_object_object_string_never_appears_in_shipped_frontend():
    text = INDEX_HTML.read_text()
    assert "[object Object]" not in text


# ---------------------------------------------------------------------
# Decision-stance classification (deterministic, no model call)
# ---------------------------------------------------------------------

def test_decision_stance_classification():
    assert _classify_decision_stance("Accept the 8% increase.") == "accept"
    assert _classify_decision_stance("Challenge the 8% -- no evidence provided.") == "challenge"
    assert _classify_decision_stance("Investigate the supplier's claims before deciding.") == "investigate"
    assert _classify_decision_stance("") == "unclear"
    assert _classify_decision_stance(None) == "unclear"


# ---------------------------------------------------------------------
# End-to-end: valid draft, no [object Object], no empty section,
# and case-appropriate content
# ---------------------------------------------------------------------

def test_valid_supplier_draft_renders_as_readable_text_not_an_object():
    cp = _run("Challenge the 8% -- no supplier-specific cost evidence has been provided.", {}, 1)
    draft = cp["supplier_request_answer"]["draft_response"]
    assert draft is not None
    assert isinstance(draft["subject"], str) and isinstance(draft["body"], str)
    full = str(draft)
    assert "[object Object]" not in full
    assert "{'label'" not in full  # the earlier raw-dict-repr class of bug, re-checked here too


def test_draft_suppressed_when_investigation_needed_first():
    """Case A from the audit: user needs to investigate first -- no
    draft should be produced, since nothing useful can be sent to the
    supplier before the buyer's own position is established."""
    cp = _run("Investigate the supplier's cost claims before forming a position.", {}, 2)
    assert cp["supplier_request_answer"]["draft_response"] is None


def test_draft_content_differs_between_accept_and_challenge_cases():
    """Case B vs Case C from the audit: accepting and challenging must
    produce genuinely different messages, not the same 'please justify
    this' template regardless of the actual decision."""
    accept_cp = _run("Accept the 8% increase -- it matches the cited cost pressures.", {}, 3)
    challenge_cp = _run("Challenge the 8% -- no supplier-specific cost evidence has been provided.", {}, 4)
    accept_draft = accept_cp["supplier_request_answer"]["draft_response"]
    challenge_draft = challenge_cp["supplier_request_answer"]["draft_response"]
    assert accept_draft["subject"] != challenge_draft["subject"]
    assert accept_draft["body"] != challenge_draft["body"]
    assert "confirm the effective date" in accept_draft["body"].lower()
    assert "please provide the supporting basis" in challenge_draft["body"].lower()
    # The accept draft must not ask the supplier to justify something
    # already being accepted.
    assert "please provide the supporting basis" not in accept_draft["body"].lower()


def test_draft_never_invents_a_number_not_in_the_case():
    """Evidence-safety check specific to the draft: only the requested
    percentage actually stated in the case may appear -- nothing
    invented."""
    cp = _run("Challenge the 8% -- no supplier-specific cost evidence has been provided.", {}, 5)
    draft = cp["supplier_request_answer"]["draft_response"]
    assert "8%" in draft["body"]
    # No other percentage figures should appear anywhere in the body.
    import re
    percentages = re.findall(r"\d+(?:\.\d+)?%", draft["body"])
    assert set(percentages) <= {"8%"}
