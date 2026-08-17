from app.models import CommercialPosition, Confidence, ConfidenceFactor, DecisionAudit, FinancialImpact
from app.pipeline.commercial_model import build_commercial_truth_model
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, QuoteComparisonEvidence, DerivedEvidence, FieldProvenance, SupplierEvidence, StakeholderView


def _position():
    return CommercialPosition(
        recommendation="Choose Supplier B subject to qualification.",
        commercial_insights=["B has the lower same-currency quote."],
        reasoning="Deterministic test position.",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="evidence", value="mixed", weight="decreases confidence")], derivation_note="[System-owned confidence level: 'medium'. Deterministic evidence checks: none.]"),
        assumptions=["Qualification must complete."],
        disconfirming_condition="If freight materially exceeds the stated basis, revisit.",
        decision_type="optimization",
        decision_audit=DecisionAudit(
            material_evidence=[{"label": "quotes", "status": "PROVEN"}],
            evidence_integrity_status="PROVEN",
            evidence_counts={"PROVEN": 3, "UNKNOWN": 1},
            uncertainties=["Supplier B capacity confirmation"],
            reversal_conditions=["If freight exceeds the decision threshold, revisit."],
        ),
        sensitivity_analysis={"available": True},
        stress_test={"status": "PASS"},
        alternative_analysis={"available": True, "status": "EVIDENCE_BACKED_PATHS", "summary": "test", "alternatives": []},
        financial_impact=FinancialImpact(annual_spend_usd=400000, requested_change_percent=0, potential_annual_impact_usd=-72000, note="test"),
        decision_passport={"decision_changers": ["Freight exceeds threshold"], "unknowns": ["Supplier B capacity confirmation"]},
        control_tower={"available": True, "readiness": "CONDITIONAL", "readiness_reason": "test", "recommended_action": "Review", "confidence": "medium", "evidence_integrity": "PROVEN", "stress_status": "PASS", "financial_impact_available": True, "method": "test"},
    )


def _normalized():
    return NormalizedEvidence(
        content_type="quote_comparison",
        common=CommonEvidence(annual_volume_units=8000, supplier_region_or_market="Europe"),
        case=QuoteComparisonEvidence(number_of_suppliers_being_compared="2", price_per_supplier="Atlas €52; Supplier B €43"),
        derived=DerivedEvidence(resolved_annual_spend_usd=416000, annual_spend_resolution_method="derived_from_price_and_volume", currency_calculation_safe=True),
        provenance={
            "price_per_supplier": FieldProvenance(source="llm_extraction", stage_captured="test"),
            "annual_volume_units": FieldProvenance(source="llm_extraction", stage_captured="test"),
        },
        suppliers=[
            SupplierEvidence(supplier_name="Atlas", currency="EUR", price_amount=52, price_display="€52", is_incumbent=True, qualification_status="complete", incoterm="CIF"),
            SupplierEvidence(supplier_name="Supplier B", currency="EUR", price_amount=43, price_display="€43", qualification_status="in_progress", incoterm="FOB"),
        ],
        stakeholder_views=[StakeholderView(stakeholder_name="Fleet", role="Operations", view_type="risk_concern", statement="Avoid transition disruption.")],
    )


def test_r20_builds_single_structural_truth_model():
    m = build_commercial_truth_model(_normalized(), _position())
    assert m["version"] == "R20.1"
    assert m["status"] == "STRUCTURED"
    assert m["parties"]["supplier_count"] == 2
    assert m["economics"]["supplier_quote_comparison"]["lowest_supplier"] == "Supplier B"
    assert m["economics"]["supplier_quote_comparison"]["unit_price_spread"] == 9
    assert m["commercial_dimensions"]
    assert m["evidence"]["provenance_fields"] == 2
    assert m["trace"]["method"].startswith("All values are derived")
    assert m["trace"]["trust_status"] is None


def test_r20_preserves_supplier_specific_incoterms():
    m = build_commercial_truth_model(_normalized(), _position())
    suppliers = {s["name"]: s for s in m["parties"]["suppliers"]}
    assert suppliers["Atlas"]["incoterm"] == "CIF"
    assert suppliers["Supplier B"]["incoterm"] == "FOB"


def test_r20_does_not_introduce_fx_for_mixed_currency_quotes():
    n = _normalized()
    n.suppliers[1].currency = "USD"
    m = build_commercial_truth_model(n, _position())
    comparison = m["economics"]["supplier_quote_comparison"]
    assert comparison["comparable_quote_prices"] is False
    assert comparison["unit_price_spread"] is None
    assert comparison["annualized_price_spread"] is None


def test_r20_preserves_unknowns_and_dependencies():
    m = build_commercial_truth_model(_normalized(), _position())
    assert any(x["type"] == "supplier_qualification" and x["supplier"] == "Supplier B" for x in m["dependencies"])
    assert "Supplier B capacity confirmation" in m["decision"]["unknowns"]
    assert m["stakeholders"][0]["name"] == "Fleet"


def test_r20_model_is_available_to_custom_exports():
    from app.pipeline.customer_exports import render_custom
    p = _position()
    p.commercial_truth_model = {"version": "R20.1", "status": "STRUCTURED"}
    rendered = render_custom(p, "{{commercial_truth_model}}")
    assert '"R20.1"' in rendered["body"]
