from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, QuoteComparisonEvidence, DerivedEvidence,
    SupplierEvidence, StakeholderView, FieldProvenance,
)
from app.pipeline.decision_integrity import stakeholder_conflict_summary
from app.pipeline.confidence_gate import apply_confidence_ceiling
from app.pipeline.decision_passport import build_decision_passport


def _position(level="high"):
    return CommercialPosition(
        recommendation="Retain Atlas while qualifying EuroMotion.",
        commercial_insights=["EuroMotion offers the strongest direct price opportunity."],
        reasoning="Atlas remains operationally proven; EuroMotion is not yet fully qualified.",
        confidence=Confidence(
            level=level,
            factors=[ConfidenceFactor(factor="evidence", value="mixed", weight="increases confidence")],
            derivation_note="model note",
        ),
        assumptions=["Qualification must complete before production award."],
        disconfirming_condition="If EuroMotion qualification completes with no material supply issue, revisit the award.",
        decision_type="optimization",
    )


def _normalized():
    return NormalizedEvidence(
        content_type="quote_comparison",
        common=CommonEvidence(annual_volume_units=8000),
        case=QuoteComparisonEvidence(
            number_of_suppliers_being_compared="3",
            price_per_supplier="Atlas €52/unit; EuroMotion €43/unit; NordValve €48.50/unit landed",
        ),
        derived=DerivedEvidence(currency_calculation_safe=True),
        provenance={
            "price_per_supplier": FieldProvenance(source="llm_extraction", stage_captured="test"),
            "number_of_suppliers_being_compared": FieldProvenance(source="llm_extraction", stage_captured="test"),
        },
        suppliers=[
            SupplierEvidence(supplier_name="Atlas Marine Systems", currency="EUR", price_display="€52/unit", price_amount=52, is_incumbent=True, qualification_status="complete"),
            SupplierEvidence(supplier_name="EuroMotion Poland", currency="EUR", price_display="€43/unit", price_amount=43, qualification_status="in_progress"),
            SupplierEvidence(supplier_name="NordValve GmbH", currency="EUR", price_display="€48.50/unit", price_amount=48.5, qualification_status="complete"),
        ],
    )


def test_two_supplier_mentions_are_not_automatically_a_stakeholder_conflict():
    n = _normalized()
    n.stakeholder_views = [StakeholderView(
        stakeholder_name="Technical",
        view_type="risk_concern",
        statement="EuroMotion is a safer alternative than NordValve only after qualification is complete.",
    )]
    conflict, details = stakeholder_conflict_summary(n)
    assert conflict is False
    assert details == []


def test_comparative_stakeholder_statement_preserves_direction():
    n = _normalized()
    n.stakeholder_views = [StakeholderView(
        stakeholder_name="Technical",
        view_type="preference",
        statement="NordValve is safer than EuroMotion.",
    )]
    n2 = n.model_copy(update={"stakeholder_views": n.stakeholder_views + [StakeholderView(
        stakeholder_name="Finance", view_type="recommendation", statement="recommends EuroMotion for savings.",
    )]})
    conflict, details = stakeholder_conflict_summary(n2)
    assert conflict is True
    assert "Technical" in details[0] and "Finance" in details[0]


def test_final_confidence_respects_pre_reasoning_stakeholder_cap():
    n = _normalized()
    n.stakeholder_views = [
        StakeholderView(stakeholder_name="Operations", view_type="preference", statement="prefers Atlas Marine Systems."),
        StakeholderView(stakeholder_name="Finance", view_type="recommendation", statement="recommends EuroMotion Poland."),
    ]
    result = apply_confidence_ceiling(_position("high"), n)
    assert result.confidence.level == "medium"
    assert "stakeholder" in result.confidence.derivation_note.lower()


def test_decision_passport_is_answer_first_and_has_direct_quote_economics():
    n = _normalized()
    p = _position("medium")
    passport = build_decision_passport(n, p)
    assert passport["title"] == "VendorEdge Decision Passport"
    assert passport["economics"]["available"] is True
    assert "72,000 EUR/year" in passport["economics"]["headline"]
    assert passport["decision"] == p.recommendation


def test_unquantified_risk_cannot_be_claimed_to_outweigh_price_savings():
    from app.pipeline.claim_integrity import check_unquantified_tradeoff_overstatement
    n = _normalized()
    p = _position("medium")
    p.why_this_wins = "EuroMotion's qualification risk outweighs its €72,000 annual savings."
    findings = check_unquantified_tradeoff_overstatement(p, n)
    assert findings
