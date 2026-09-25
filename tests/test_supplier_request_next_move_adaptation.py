"""
Supplier Request quality-gate audit findings, fixed in this pass:

1. next_move's second and third items were hard-coded strings guarded
   by conditions true for virtually every price_increase case ("a
   supplier exists", "a percent was requested"), making them appear
   identically across 11 materially different audit cases -- including
   nonsensical combinations (telling the buyer to "request supplier-
   specific support before agreeing" on a case that was just
   accepted). Now gated on the actual decision state.

2. The decision-stance classifier had a real precision bug: a plain
   substring check for "accept" matched "before accepting the 8%" and
   would have matched "do not accept" -- both genuinely challenge/
   evidence-gathering language, not acceptance. Fixed by checking
   negated/conditional forms first.
"""
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.commercial_answer import _classify_decision_stance

client = TestClient(app)
_CONF = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def test_classifier_does_not_misread_before_accepting_as_accept():
    """The exact bug found in the audit: 'before accepting' must not
    match the plain 'accept' substring check."""
    assert _classify_decision_stance("Ask for the supplier's cost share before accepting the 8%.") != "accept"
    assert _classify_decision_stance("Do not accept the 11% as stated.") != "accept"


def test_classifier_still_correctly_identifies_genuine_accept():
    assert _classify_decision_stance("Accept the 8% increase -- it matches the cited index.") == "accept"


def _run(recommendation, extra_evidence, suffix):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"10.730.{suffix}.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    classify = {
        "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", "suppliers_stated_justification": "Rising costs.", "how_critical_is_this_supplier_relationship": "sole-source", **extra_evidence},
        "numeric_facts": {"annual_spend_usd": 1_000_000, "requested_change_percent": 8.0},
        "supplier_specific_evidence": [{"supplier_name": "Supplier Y", "is_incumbent": True}],
    }
    pos = CommercialPosition(recommendation=recommendation, commercial_insights=["a"], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "test"}, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return d["commercial_position"]["supplier_request_answer"]["next_move"]


def test_next_move_never_requests_supplier_evidence_for_an_accepted_case():
    nm = _run("Accept -- the increase is contractually permitted and verified against the published index.", {}, 1)
    assert not any("request supplier-specific support" in x.lower() for x in nm)


def test_next_move_never_requests_supplier_evidence_when_investigation_is_first():
    nm = _run("Investigate before forming a position -- not enough evidence exists yet.", {}, 2)
    assert not any("request supplier-specific support" in x.lower() for x in nm)


def test_next_move_does_request_supplier_evidence_for_a_genuine_challenge():
    nm = _run("Challenge the 8% -- no supplier-specific cost evidence has been provided.", {}, 3)
    assert any("request supplier-specific support" in x.lower() for x in nm)


def test_next_move_validates_alternative_supplier_only_when_one_is_genuinely_pending():
    with_pending = _run(
        "Use the qualified alternative as leverage before agreeing.",
        {}, 4,
    )
    # Re-run with an explicit pending-qualification alternative supplier
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "10.730.5.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    classify = {
        "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", "suppliers_stated_justification": "Rising costs.", "how_critical_is_this_supplier_relationship": "alternative available"},
        "numeric_facts": {"annual_spend_usd": 1_000_000, "requested_change_percent": 8.0},
        "supplier_specific_evidence": [{"supplier_name": "Supplier Y", "is_incumbent": True}, {"supplier_name": "Alt Z", "qualification_time_estimate": "3 months"}],
    }
    pos = CommercialPosition(recommendation="Use the qualified alternative as leverage before agreeing.", commercial_insights=["a"], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "test"}, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    with_gap = d["commercial_position"]["supplier_request_answer"]["next_move"]

    assert not any("validate alternative-supplier" in x.lower() for x in with_pending)
    assert any("validate alternative-supplier" in x.lower() for x in with_gap)


def test_next_move_genuinely_differs_across_materially_different_cases():
    """The core regression: next_move must not be byte-identical across
    materially different decision states."""
    accept_nm = _run("Accept -- contractually permitted and verified.", {}, 6)
    challenge_nm = _run("Challenge the 8% -- no evidence has been provided.", {}, 7)
    investigate_nm = _run("Investigate before forming a position -- not enough evidence exists yet.", {}, 8)
    assert accept_nm != challenge_nm
    assert accept_nm != investigate_nm
    assert challenge_nm != investigate_nm
