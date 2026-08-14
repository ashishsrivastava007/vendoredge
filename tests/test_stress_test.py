from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, QuoteComparisonEvidence, DerivedEvidence, SupplierEvidence
from app.pipeline.stress_test import build_stress_test


def pos(disconfirming="Reassess if verified cost evidence materially changes the price case."):
    return CommercialPosition(
        recommendation="Hold price and dual-source where feasible.",
        commercial_insights=["Use verified evidence."],
        reasoning="The commercial position is based on explicit evidence.",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="Evidence", value="explicit", weight="increases confidence")], derivation_note="test"),
        assumptions=["No missing inputs are assumed."],
        disconfirming_condition=disconfirming,
        decision_type="optimization",
    )


def test_price_increase_stress_test_exposes_requested_and_double_shock():
    n = NormalizedEvidence(content_type="price_increase", common=CommonEvidence(), case=PriceIncreaseEvidence(requested_increase_percent=10), derived=DerivedEvidence(resolved_annual_spend_usd=100000, currency_calculation_safe=True))
    r = build_stress_test(n, pos())
    assert r["available"]
    assert r["status"] == "SURVIVES_AVAILABLE_TESTS"
    assert any(t["name"] == "2× requested increase" and t["annual_impact_usd"] == 20000 for t in r["tests"])


def test_price_stress_test_is_honest_when_currency_unsafe():
    n = NormalizedEvidence(content_type="price_increase", common=CommonEvidence(), case=PriceIncreaseEvidence(requested_increase_percent=10), derived=DerivedEvidence(resolved_annual_spend_usd=100000, currency_calculation_safe=False))
    r = build_stress_test(n, pos())
    assert r["status"] == "NOT_TESTABLE"


def test_allocation_stress_test_surfaces_capacity_warning():
    n = NormalizedEvidence(content_type="quote_comparison", common=CommonEvidence(annual_volume_units=1000), case=QuoteComparisonEvidence(), derived=DerivedEvidence(), suppliers=[SupplierEvidence(supplier_name="A", currency="USD", price_usd=80, capacity_percent=30), SupplierEvidence(supplier_name="B", currency="USD", price_usd=100)])
    r = build_stress_test(n, pos())
    assert r["status"] == "SENSITIVE"
    assert any("30% capacity" in x for x in r["warnings"])


def test_allocation_stress_test_refuses_fx_assumptions():
    n = NormalizedEvidence(content_type="quote_comparison", common=CommonEvidence(annual_volume_units=1000), case=QuoteComparisonEvidence(), derived=DerivedEvidence(), suppliers=[SupplierEvidence(supplier_name="A", currency="EUR", price_usd=80), SupplierEvidence(supplier_name="B", currency="USD", price_usd=100)])
    r = build_stress_test(n, pos())
    assert r["status"] == "NOT_TESTABLE"
