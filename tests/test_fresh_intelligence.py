"""
R45 Fresh Decision Intelligence -- first vertical slice. Proves:
1. The gate only fires for the target case shape (real category +
   real supplier spend + real requested change).
2. A found claim flows through the existing market-intelligence
   evidence chain untouched -- never auto-attributed to the case's
   supplier.
3. Nothing found produces the honest, fixed "no material finding"
   message -- never a silently-omitted section, never an invented one.
4. The same case run twice produces the identical answer -- dynamic
   never means random.
"""
from unittest.mock import patch
from app.pipeline.fresh_intelligence import (
    should_research_fresh_intelligence, research_fresh_market_intelligence, build_fresh_intelligence_answer,
)
from app.pipeline.kernel import build_kernel
from app.pipeline.decision_audit import build_decision_audit
from app.pipeline.financial import compute_financial_impact
from app.pipeline.normalize import normalize_evidence
from app.models import CommercialPosition, Confidence, ConfidenceFactor, DecisionAudit

_CONF = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _build_valves_kernel():
    ne, _ = normalize_evidence(
        "Supplier A wants 11%.", "price_increase",
        {"supplier_currency": "EUR", "suppliers_stated_justification": "Rising input costs."},
        {"annual_spend_usd": 5_550_000, "prior_annual_spend_usd": 4_370_000, "requested_change_percent": 11.0},
        supplier_specific_evidence=[{"supplier_name": "Supplier A", "is_incumbent": True, "current_annual_spend_usd": 5_550_000, "prior_annual_spend_usd": 4_370_000}],
    )
    fi = compute_financial_impact(ne)
    pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization", financial_impact=fi)
    pos.decision_audit = DecisionAudit(**build_decision_audit(ne, pos))
    return build_kernel(ne, pos).model_dump()


def test_gate_fires_for_the_target_vertical_shape():
    kernel = _build_valves_kernel()
    assert should_research_fresh_intelligence(kernel) is True


def test_gate_does_not_fire_without_a_real_supplier_or_requested_change():
    ne, _ = normalize_evidence("Just a general question.", "price_increase", {"supplier_currency": "USD"}, {})
    pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    pos.decision_audit = DecisionAudit(**build_decision_audit(ne, pos))
    kernel = build_kernel(ne, pos).model_dump()
    assert should_research_fresh_intelligence(kernel) is False


def test_gate_does_not_fire_for_non_price_increase_content():
    ne, _ = normalize_evidence("Comparing two quotes.", "quote_comparison", {}, {})
    pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    pos.decision_audit = DecisionAudit(**build_decision_audit(ne, pos))
    kernel = build_kernel(ne, pos).model_dump()
    assert should_research_fresh_intelligence(kernel) is False


def test_found_claim_never_auto_attributed_to_the_case_supplier():
    """The core evidence-safety proof: a genuinely relevant, well-formed
    research finding still never becomes "Supplier A's exposure" --
    the exact same discipline market_intelligence.py already enforces
    for claims the case itself stated."""
    kernel = _build_valves_kernel()

    class _FakeTool:
        def search(self, prompt, *, model, max_tokens):
            import json
            return json.dumps([{"driver": "steel", "direction": "increased", "magnitude": "9%", "geography": "Europe",
                "period": "last 3 months", "source": "LME", "publication_or_retrieval_date": "2026-08", "unit_or_currency": "EUR/tonne"}])

    with patch("app.pipeline.fresh_intelligence.get_research_tool", return_value=_FakeTool()):
        claims = research_fresh_market_intelligence(kernel)
    assert len(claims) == 1
    assert claims[0]["attributed_to"] == "external_research"

    kernel["case"]["market_driver_claims"] = claims
    answer = build_fresh_intelligence_answer(kernel)
    assert answer["available"] is True
    assert "steel" in answer["what_changed"][0].lower()
    assert "not been tied" in answer["what_it_means_for_you"][0]
    assert "hasn't been tied" in answer["my_view"]


def test_nothing_found_produces_the_fixed_honest_message():
    kernel = _build_valves_kernel()
    answer = build_fresh_intelligence_answer(kernel)  # no market_driver_claims at all
    assert answer == {"available": False, "message": "No current external development identified that materially changes this decision."}


def test_research_call_failure_fails_safe_never_raises():
    kernel = _build_valves_kernel()

    class _BrokenTool:
        def search(self, *a, **kw):
            raise RuntimeError("network unreachable")

    with patch("app.pipeline.fresh_intelligence.get_research_tool", return_value=_BrokenTool()):
        claims = research_fresh_market_intelligence(kernel)
    assert claims == []


def test_malformed_research_response_produces_no_claims():
    kernel = _build_valves_kernel()

    class _BadTool:
        def search(self, *a, **kw):
            return "not valid json and not an array"

    with patch("app.pipeline.fresh_intelligence.get_research_tool", return_value=_BadTool()):
        claims = research_fresh_market_intelligence(kernel)
    assert claims == []


def test_same_evidence_produces_identical_answer_twice():
    """Dynamic does not mean random -- the exact same claim data run
    through build_fresh_intelligence_answer twice must produce byte-
    identical output both times."""
    kernel = _build_valves_kernel()
    claim = [{"driver": "energy", "direction": "increased", "magnitude": "5%", "geography": "EU", "period": "Q2",
              "source": "Eurostat", "attributed_to": "external_research", "publication_or_retrieval_date": "2026-06", "unit_or_currency": None}]
    kernel["case"]["market_driver_claims"] = claim
    answer_a = build_fresh_intelligence_answer(kernel)
    answer_b = build_fresh_intelligence_answer(kernel)
    assert answer_a == answer_b
