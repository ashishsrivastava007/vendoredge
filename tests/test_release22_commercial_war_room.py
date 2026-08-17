from app.models import CommercialPosition, Confidence, ConfidenceFactor, DecisionAudit, NegotiationDimension, NegotiationPlaybook
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, QuoteComparisonEvidence, DerivedEvidence, SupplierEvidence, StakeholderView, FieldProvenance
from app.pipeline.commercial_war_room import build_commercial_war_room


def _position():
    return CommercialPosition(
        recommendation="Recommend Atlas subject to commercial negotiation.",
        commercial_insights=["test"], reasoning="test",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="evidence", value="mixed", weight="decreases confidence")], derivation_note="[System-owned confidence level: 'medium'. Deterministic evidence checks: test.]"),
        assumptions=["Qualification must remain complete."],
        disconfirming_condition="If alternative capacity is not confirmed, revisit.", decision_type="optimization",
        decision_audit=DecisionAudit(evidence_integrity_status="PROVEN", uncertainties=["Alternative capacity needs confirmation"], reversal_conditions=["Alternative capacity is not confirmed"]),
        negotiation_dimensions=[NegotiationDimension(dimension="Payment terms", opening_ask="60 days", target_outcome="45 days", walk_away="30 days")],
        opening_position="We need movement on commercial terms before award.",
        walk_away_threshold="Do not award below 30-day payment terms.",
        negotiation_playbook=NegotiationPlaybook(objective="Recommend Atlas", target="45 days", evidence_to_lead_with=["Current quote comparison"], method="test"),
        market_verification_scope="Europe",
    )


def _evidence():
    return NormalizedEvidence(
        content_type="quote_comparison", common=CommonEvidence(annual_volume_units=8000),
        case=QuoteComparisonEvidence(price_per_supplier="Atlas €52; EuroMotion €43"),
        derived=DerivedEvidence(currency_calculation_safe=True),
        provenance={"price_per_supplier": FieldProvenance(source="llm_extraction", stage_captured="test")},
        suppliers=[
            SupplierEvidence(supplier_name="Atlas", currency="EUR", price_amount=52, price_display="€52", is_incumbent=True, payment_terms="30 days", capacity_percent=90),
            SupplierEvidence(supplier_name="EuroMotion", currency="EUR", price_amount=43, price_display="€43", payment_terms="15 days", lead_time_weeks=6),
        ],
        stakeholder_views=[StakeholderView(stakeholder_name="Operations", role="Fleet", view_type="risk_concern", statement="Continuity matters.", basis="Operational experience")],
    )


def test_r22_separates_buyer_supplier_market_and_stakeholders():
    w = build_commercial_war_room(_evidence(), _position())
    assert w["available"] is True
    assert w["buyer_position"]["leverage"]
    assert len(w["supplier_positions"]) == 2
    assert w["market_position"][0]["signal"] == "Market verification"
    assert w["stakeholder_positions"][0]["stakeholder"] == "Operations"


def test_r22_does_not_predict_supplier_response():
    w = build_commercial_war_room(_evidence(), _position())
    assert all(x["supplier_response"] == "NOT_PREDICTED" for x in w["negotiation_scenarios"])
    assert "not predicted" in w["simulation_disclaimer"].lower()


def test_r22_preserves_recommendation():
    p = _position(); n = _evidence()
    w = build_commercial_war_room(n, p)
    assert w["current_recommendation"] == p.recommendation


def test_r22_no_named_supplier_is_honest():
    n = _evidence(); n.suppliers = []
    w = build_commercial_war_room(n, _position())
    assert w["supplier_positions"] == []
    assert "No named supplier" not in w["method"]


def test_r22_contradicted_evidence_holds_war_room():
    n = _evidence(); n.provenance["price_per_supplier"].conflicting = True
    p = _position(); p.decision_audit.evidence_integrity_status = "CONTRADICTED"
    w = build_commercial_war_room(n, p)
    assert w["readiness"] == "HOLD_FOR_EVIDENCE_CONFLICT"


def test_r22_scenarios_are_grounded_in_negotiation_dimensions():
    w = build_commercial_war_room(_evidence(), _position())
    assert any("Payment terms" in x["scenario"] for x in w["negotiation_scenarios"])
