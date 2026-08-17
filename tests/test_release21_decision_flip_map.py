from app.models import CommercialPosition, Confidence, ConfidenceFactor, DecisionAudit
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, QuoteComparisonEvidence, DerivedEvidence, FieldProvenance, SupplierEvidence, PriceIncreaseEvidence
from app.pipeline.decision_flip_map import build_decision_flip_map


def _quote(rec="Recommend Atlas"):
    return NormalizedEvidence(
        content_type="quote_comparison",
        common=CommonEvidence(annual_volume_units=8000),
        case=QuoteComparisonEvidence(number_of_suppliers_being_compared="2", price_per_supplier="Atlas €52; EuroMotion €43"),
        derived=DerivedEvidence(currency_calculation_safe=True),
        provenance={
            "price_per_supplier": FieldProvenance(source="llm_extraction", stage_captured="test"),
        },
        suppliers=[
            SupplierEvidence(supplier_name="Atlas", currency="EUR", price_amount=52, price_display="€52", is_incumbent=True),
            SupplierEvidence(supplier_name="EuroMotion", currency="EUR", price_amount=43, price_display="€43"),
        ],
    ), CommercialPosition(
        recommendation=rec,
        commercial_insights=["test"],
        reasoning="test",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="evidence", value="mixed", weight="decreases confidence")], derivation_note="[System-owned confidence level: 'medium'. Deterministic evidence checks: test.]"),
        assumptions=["Qualification must complete."],
        disconfirming_condition="If EuroMotion capacity is not confirmed, revisit the decision.",
        decision_type="optimization",
        decision_audit=DecisionAudit(reversal_conditions=["Supplier capacity is not confirmed"], evidence_integrity_status="PROVEN"),
    )


def test_r21_exact_supplier_price_boundary_is_deterministic():
    n, p = _quote()
    f = build_decision_flip_map(n, p)
    assert f["available"] is True
    threshold = next(x for x in f["flips"] if x["type"] == "price_threshold")
    assert threshold["threshold_value"] == 52.0
    assert threshold["currency"] == "EUR"
    assert threshold["strength"] == "DETERMINISTIC"
    assert "FX" in threshold["basis"]


def test_r21_does_not_invent_fx_for_mixed_currency():
    n, p = _quote()
    n.suppliers[1].currency = "USD"
    f = build_decision_flip_map(n, p)
    assert f["available"] is False
    assert "FX" in f["reason"]
    assert f["flips"] == []


def test_r21_preserves_qualitative_reversal_without_faking_threshold():
    n, p = _quote()
    f = build_decision_flip_map(n, p)
    conditions = [x["condition"] for x in f["evidence_required"]]
    assert "If EuroMotion capacity is not confirmed, revisit the decision." in conditions
    assert all(x["strength"] == "QUALITATIVE" for x in f["evidence_required"])
    assert all("threshold" not in x["effect"].lower() or "no numeric" in x["effect"].lower() for x in f["evidence_required"])


def test_r21_does_not_override_recommendation():
    n, p = _quote("Recommend Atlas")
    f = build_decision_flip_map(n, p)
    assert f["current_recommendation"] == "Recommend Atlas"
    assert f["current_recommendation_supplier"] == "Atlas"


def test_r21_price_increase_is_honest_about_scope():
    n = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(),
        case=PriceIncreaseEvidence(requested_increase_percent=8, annual_spend_usd=100000),
        derived=DerivedEvidence(resolved_annual_spend_usd=100000, currency_calculation_safe=True),
    )
    p = CommercialPosition(
        recommendation="Challenge the increase.", commercial_insights=["test"], reasoning="test",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="evidence", value="mixed", weight="decreases confidence")], derivation_note="[System-owned confidence level: 'medium'. Deterministic evidence checks: test.]"),
        assumptions=["Supplier justification must be validated."], disconfirming_condition="If market evidence supports the increase, revisit.", decision_type="optimization",
    )
    f = build_decision_flip_map(n, p)
    assert f["available"] is True
    assert f["flips"][0]["annual_impact_at_threshold"] == 8000.0
    assert "supplier-switch threshold" in f["warnings"][0]
