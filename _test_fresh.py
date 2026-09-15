import sys, json; sys.path.insert(0, ".")
from app.pipeline.normalize import normalize_evidence
from app.pipeline.kernel import build_kernel
from app.pipeline.decision_audit import build_decision_audit
from app.pipeline.financial import compute_financial_impact
from app.pipeline.fresh_intelligence import should_research_fresh_intelligence, research_fresh_market_intelligence
from app.pipeline.market_intelligence import build_market_reasoning, build_market_answer_section
from app.models import CommercialPosition, Confidence, ConfidenceFactor, DecisionAudit
from unittest.mock import patch

conf = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")

ne, _ = normalize_evidence("Supplier A wants 11%.", "price_increase",
    {"supplier_currency": "EUR", "suppliers_stated_justification": "Rising input costs."},
    {"annual_spend_usd": 5_550_000, "prior_annual_spend_usd": 4_370_000, "requested_change_percent": 11.0},
    supplier_specific_evidence=[{"supplier_name": "Supplier A", "is_incumbent": True, "current_annual_spend_usd": 5_550_000, "prior_annual_spend_usd": 4_370_000}])
fi = compute_financial_impact(ne)
pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=conf, assumptions=["a"], disconfirming_condition="...", decision_type="optimization", financial_impact=fi)
pos.decision_audit = DecisionAudit(**build_decision_audit(ne, pos))
kernel = build_kernel(ne, pos).model_dump()

gate = should_research_fresh_intelligence(kernel)
print("should_research_fresh_intelligence:", gate)
assert gate is True

class _FakeTool:
    def search(self, prompt, *, model, max_tokens):
        return json.dumps([{"driver": "steel", "direction": "increased", "magnitude": "9%", "geography": "Europe",
            "period": "last 3 months", "source": "LME", "publication_or_retrieval_date": "2026-08", "unit_or_currency": "EUR/tonne"}])

with patch("app.pipeline.fresh_intelligence.get_research_tool", return_value=_FakeTool()):
    claims = research_fresh_market_intelligence(kernel)
print()
print("claims found:", json.dumps(claims, indent=2))
assert len(claims) == 1
assert claims[0]["attributed_to"] == "external_research"

kernel["case"]["market_driver_claims"] = claims
reasoning = build_market_reasoning(kernel)
print()
print("=== fed into build_market_reasoning ===")
print(json.dumps(reasoning["drivers"][0], indent=2))
assert reasoning["drivers"][0]["applies_to_supplier"] is None
assert "not been tied to any specific" in reasoning["drivers"][0]["decision_implication"]
print()
print("PASS: external research correctly NEVER auto-attributed to Supplier A's exposure")

# Also test the "nothing relevant found" honest path
class _EmptyTool:
    def search(self, prompt, *, model, max_tokens):
        return "[]"
with patch("app.pipeline.fresh_intelligence.get_research_tool", return_value=_EmptyTool()):
    claims_empty = research_fresh_market_intelligence(kernel)
print()
print("Empty research result -> claims:", claims_empty)
assert claims_empty == []
print("PASS: honest 'nothing found' -> empty list, nothing invented")
