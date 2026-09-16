"""
R46 fix -- proves the previously-orphaned supplier_request_answer
object (LEVERAGE, TRADE-OFF, no forced negotiation content) is now
actually reachable by the frontend, matching the same pattern already
proven for category_strategy_answer/problem_solving_answer/
commercial_signal_answer.
"""
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor, NegotiationDimension

INDEX_HTML = Path(__file__).parents[1] / "app" / "static" / "index.html"
client = TestClient(app)
_CONF = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def test_render_supplier_request_answer_is_defined_and_dispatched():
    text = INDEX_HTML.read_text()
    assert "function renderSupplierRequestAnswer(pos)" in text
    assert "!renderSupplierRequestAnswer(pos)" in text


def _run(classify, pos_kwargs, suffix):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"10.520.{suffix}.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    pos = CommercialPosition(**pos_kwargs)
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


def test_supplier_request_answer_reaches_the_position_with_no_diagnostics_leak():
    classify = {"content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", "suppliers_stated_justification": "Rising costs.", "how_critical_is_this_supplier_relationship": "sole-source"},
        "numeric_facts": {"annual_spend_usd": 1_000_000, "requested_change_percent": 8.0},
        "supplier_specific_evidence": [{"supplier_name": "Supplier X", "is_incumbent": True}]}
    pos_kwargs = dict(recommendation="Push back on the 8% increase.", commercial_insights=["a"], reasoning="x",
        confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    cp = _run(classify, pos_kwargs, 1)
    sra = cp.get("supplier_request_answer")
    assert sra is not None
    assert sra["decision"] == "Push back on the 8% increase."
    assert "leverage" in sra and "trade_off" in sra
    full_text = str(sra).lower()
    assert "evidence_state" not in full_text and "pipeline" not in full_text and "archetype" not in full_text


def test_trade_off_only_appears_when_a_real_gap_exists():
    """Case with an unresolved alternative-supplier qualification must
    show a trade-off warning; a clean case with no such gap must not."""
    classify_with_gap = {"content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", "suppliers_stated_justification": "Rising costs.", "how_critical_is_this_supplier_relationship": "alternative available"},
        "numeric_facts": {"annual_spend_usd": 1_000_000, "requested_change_percent": 8.0},
        "supplier_specific_evidence": [{"supplier_name": "Supplier X", "is_incumbent": True}, {"supplier_name": "Alt Supplier", "qualification_time_estimate": "3 months"}]}
    classify_clean = {"content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", "suppliers_stated_justification": "Rising costs.", "how_critical_is_this_supplier_relationship": "sole-source"},
        "numeric_facts": {"annual_spend_usd": 1_000_000, "requested_change_percent": 8.0},
        "supplier_specific_evidence": [{"supplier_name": "Supplier X", "is_incumbent": True}]}
    pos_kwargs = dict(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")

    with_gap = _run(classify_with_gap, dict(pos_kwargs), 2)["supplier_request_answer"]
    clean = _run(classify_clean, dict(pos_kwargs), 3)["supplier_request_answer"]
    assert with_gap["trade_off"] != []
    assert clean["trade_off"] == []


def test_unsupported_negotiation_numbers_never_surface_as_target_or_walkaway():
    """Evidence-safety proof: negotiation_dimensions containing a
    specific percentage with no grounding in the case's own evidence
    must not reach target/walk_away -- the existing sanitization must
    still apply through this new path."""
    classify = {"content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", "suppliers_stated_justification": "Rising costs.", "how_critical_is_this_supplier_relationship": "alternatives available"},
        "numeric_facts": {"annual_spend_usd": 1_000_000, "requested_change_percent": 8.0},
        "supplier_specific_evidence": [{"supplier_name": "Supplier X", "is_incumbent": True}]}
    pos_kwargs = dict(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
        negotiation_dimensions=[NegotiationDimension(dimension="Price", opening_ask="0%", target_outcome="No more than 3%", walk_away="5%")])
    cp = _run(classify, pos_kwargs, 4)
    sra = cp["supplier_request_answer"]
    assert sra["target"] is None
    assert sra["walk_away"] is None
