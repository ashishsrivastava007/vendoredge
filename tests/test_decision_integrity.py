from app.pipeline.decision_integrity import (
    build_stakeholder_decision_protocol,
    compute_pre_reasoning_confidence,
    stakeholder_conflict_summary,
)
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence,
    SupplierEvidence, StakeholderView, FieldProvenance,
)


def _base(views):
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(),
        case=PriceIncreaseEvidence(
            current_price_or_terms="$100/unit",
            requested_increase_percent=10,
            suppliers_stated_justification="cost pressure",
            annual_spend_usd=1_000_000,
        ),
        derived=DerivedEvidence(
            resolved_annual_spend_usd=1_000_000,
            annual_spend_resolution_method="direct",
        ),
        provenance={
            k: FieldProvenance(source="llm_extraction", stage_captured="test")
            for k in ["current_price_or_terms", "requested_increase_percent", "suppliers_stated_justification", "annual_spend_usd"]
        },
        suppliers=[
            SupplierEvidence(supplier_name="Atlas", is_incumbent=True, qualification_status="complete"),
            SupplierEvidence(supplier_name="EuroMotion", qualification_status="complete"),
        ],
        stakeholder_views=views,
    )


def test_conflicting_stakeholders_are_not_averaged():
    ne = _base([
        StakeholderView(stakeholder_name="Operations", view_type="preference", statement="prefers Atlas because reliability matters"),
        StakeholderView(stakeholder_name="Finance", view_type="preference", statement="prefers EuroMotion for savings"),
    ])
    conflict, details = stakeholder_conflict_summary(ne)
    assert conflict is True
    assert len(details) == 1
    protocol = build_stakeholder_decision_protocol(ne)
    assert "MATERIAL STAKEHOLDER CONFLICT DETECTED" in protocol
    assert "do not present one stakeholder's preference" in protocol


def test_rumor_is_never_promoted_to_fact_by_protocol():
    ne = _base([
        StakeholderView(stakeholder_name="Buyer", view_type="rumor", statement="heard EuroMotion may lose capacity", basis="informal supplier call"),
    ])
    protocol = build_stakeholder_decision_protocol(ne)
    assert "Rumors and insider information are NEVER verified facts" in protocol


def test_clean_case_can_reach_system_owned_high_confidence_before_reasoning():
    ne = _base([])
    level, reasons = compute_pre_reasoning_confidence(ne)
    assert level == "high"
    assert reasons == []


def test_incomplete_alternative_does_not_preemptively_cap_before_recommendation_dependency_is_known():
    ne = _base([])
    ne.suppliers[1].qualification_status = "unknown"
    level, reasons = compute_pre_reasoning_confidence(ne)
    assert level == "high"
    assert reasons == []


def test_material_stakeholder_conflict_caps_system_owned_confidence():
    ne = _base([
        StakeholderView(stakeholder_name="Operations", view_type="preference", statement="prefers Atlas"),
        StakeholderView(stakeholder_name="Finance", view_type="recommendation", statement="recommends EuroMotion"),
    ])
    level, reasons = compute_pre_reasoning_confidence(ne)
    assert level == "medium"
    assert any("stakeholder" in r for r in reasons)
