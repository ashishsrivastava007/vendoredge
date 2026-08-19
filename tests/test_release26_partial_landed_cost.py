from app.pipeline.normalized_evidence import CommonEvidence, DerivedEvidence, NormalizedEvidence, QuoteComparisonEvidence, SupplierEvidence
from app.pipeline.tco import build_quote_tco


def _case(freight="EUR 2.20/unit"):
    return NormalizedEvidence(
        content_type="quote_comparison",
        common=CommonEvidence(annual_volume_units=8000),
        case=QuoteComparisonEvidence(number_of_suppliers_being_compared="2", price_per_supplier="Atlas EUR 52/unit; EuroMotion EUR 45.50/unit"),
        derived=DerivedEvidence(currency_calculation_safe=True),
        suppliers=[
            SupplierEvidence(
                supplier_name="Atlas Marine Systems", currency="EUR", price_amount=52,
                incoterm="DDP", is_incumbent=True,
            ),
            SupplierEvidence(
                supplier_name="EuroMotion Poland", currency="EUR", price_amount=45.5,
                incoterm="FCA", freight_cost_or_estimate=freight,
            ),
        ],
    )


def test_partial_landed_cost_credits_known_freight_without_inventing_duty():
    result = build_quote_tco(_case())
    assert result["available"] is True
    assert result["type"] == "partial_landed_cost"
    assert result["amount"] == 34400.0
    assert result["unit_gap"] == 4.3
    assert result["comparison_basis"] == "comparable_landed_price"
    assert "buyer-borne import duty/tax" in result["missing_components"]
    assert result["decision_boundary"]["unit_threshold"] == 4.3
    assert "54,600" not in result["headline"]
    assert "not confirmed savings" in result["headline"]


def test_missing_freight_does_not_promote_raw_fca_price_to_landed_cost():
    result = build_quote_tco(_case(freight=None))
    assert result["available"] is False
    assert result["type"] == "incomplete_landed_cost"
    assert "incomplete" in result["headline"].lower()


def test_partial_landed_cost_does_not_estimate_unknown_components():
    result = build_quote_tco(_case())
    assert result["decision_boundary"]["unit_threshold"] == 4.3
    assert "unknown buyer-borne components remain excluded" in result["basis"].lower()
    assert "benchmark" not in result["basis"].lower()


def test_flip_map_consumes_canonical_partial_landed_boundary_without_raw_annualized_gap():
    from app.models import CommercialPosition, Confidence, ConfidenceFactor, DecisionAudit
    from app.pipeline.decision_flip_map import build_decision_flip_map

    n = _case()
    p = CommercialPosition(
        recommendation="Recommend Atlas Marine Systems",
        commercial_insights=["test"],
        reasoning="test",
        confidence=Confidence(
            level="medium",
            factors=[ConfidenceFactor(factor="evidence", value="mixed", weight="decreases confidence")],
            derivation_note="test",
        ),
        assumptions=["test"],
        disconfirming_condition="If qualification fails, revisit.",
        decision_type="optimization",
        decision_audit=DecisionAudit(reversal_conditions=[], evidence_integrity_status="PROVEN"),
    )
    result = build_decision_flip_map(n, p)
    assert result["available"] is True
    money = [x for x in result["flips"] if x["strength"] == "DETERMINISTIC"]
    assert money
    assert all(x.get("source") == "canonical_tco" for x in money)
    assert any(x.get("threshold_value") == 4.3 for x in money)
    assert all(x.get("annual_impact_at_threshold") != 52000.0 for x in money)
    assert all("canonical commercial cost advantage" in x.get("driver", "").lower() or x.get("type") == "economic_baseline" for x in money)
