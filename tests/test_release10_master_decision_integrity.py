"""Release 10: one deliberately hostile master case across the decision stack.

This suite does not pretend to be a live Anthropic/browser test. It exercises the
real deterministic pipeline layers against one shared NormalizedEvidence object
and one persisted-shape CommercialPosition fixture. The purpose is to prove that
facts, stakeholder views, financials, claim integrity, alternatives, sensitivity,
stress testing, reversal logic and the Control Tower remain coherent when all
of them fire together.
"""
from app.models import CommercialPosition, Confidence, DecisionAudit
from app.pipeline.alternatives import build_alternative_paths
from app.pipeline.claim_integrity import check_all_claim_overstatements
from app.pipeline.control_tower import build_control_tower
from app.pipeline.decision_audit import build_decision_audit
from app.pipeline.decision_integrity import (
    build_stakeholder_decision_protocol,
    compute_pre_reasoning_confidence,
    stakeholder_conflict_summary,
)
from app.pipeline.financial import compute_financial_impact
from app.pipeline.sensitivity import build_sensitivity_analysis
from app.pipeline.stress_test import build_stress_test
from app.pipeline.normalized_evidence import (
    CommonEvidence,
    DerivedEvidence,
    FieldProvenance,
    NormalizedEvidence,
    PriceIncreaseEvidence,
    StakeholderView,
    SupplierEvidence,
)


MASTER_CASE = """
Atlas Bearings requests a 12% price increase from its current $48/unit FCA Hamburg
price. Annual demand is 50,000 units. Atlas has 99.2% OTIF, 0.5% defects and a
6-week lead time. Atlas says steel, energy and labour costs justify the increase,
but no audited or index-linked breakdown has been supplied.

EuroMotion Poland offers $43/unit DDP, reports 97% OTIF and 1.1% defects, has an
8-week lead time and can supply 30% of annual demand immediately. EuroMotion's
production history is unknown and no qualification status is stated.

Finance requires at least 5% savings versus the current baseline. Operations
prefers Atlas because of its stronger reliability history. Finance prefers using
EuroMotion as competitive leverage. Procurement wants a non-exclusive dual-source
option. A plant manager reports that EuroMotion may have capacity constraints
beyond the stated 30%; this is a stakeholder report, not verified supplier data.
""".strip()


def _master_normalized() -> NormalizedEvidence:
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(
            annual_volume_units=50000,
            supplier_currency="USD",
        ),
        case=PriceIncreaseEvidence(
            current_price_or_terms="$48/unit FCA Hamburg",
            requested_increase_percent=12.0,
            suppliers_stated_justification="steel, energy and labour costs",
            annual_spend_usd=2400000.0,
        ),
        derived=DerivedEvidence(
            resolved_annual_spend_usd=2400000.0,
            annual_spend_resolution_method="direct",
            freight_relevant=True,
            currency_calculation_safe=True,
        ),
        provenance={
            "current_price_or_terms": FieldProvenance(source="llm_extraction", stage_captured="master", supplier_name="Atlas Bearings"),
            "requested_increase_percent": FieldProvenance(source="llm_extraction", stage_captured="master"),
            "suppliers_stated_justification": FieldProvenance(source="llm_extraction", stage_captured="master", supplier_name="Atlas Bearings"),
            "annual_spend_usd": FieldProvenance(source="derived_calculation", stage_captured="master"),
        },
        suppliers=[
            SupplierEvidence(
                supplier_name="Atlas Bearings",
                incoterm="FCA",
                currency="USD",
                price_usd=48.0,
                price_display="$48/unit FCA Hamburg",
                lead_time_weeks=6,
                otif_percent=99.2,
                defect_rate_percent=0.5,
                qualification_status="complete",
                production_history_status="established",
                is_incumbent=True,
            ),
            SupplierEvidence(
                supplier_name="EuroMotion Poland",
                incoterm="DDP",
                currency="USD",
                price_usd=43.0,
                price_display="$43/unit DDP",
                lead_time_weeks=8,
                otif_percent=97.0,
                defect_rate_percent=1.1,
                capacity_percent=30.0,
                qualification_status="unknown",
                production_history_status="unknown",
                is_incumbent=False,
            ),
        ],
        stakeholder_views=[
            StakeholderView(
                stakeholder_name="Finance",
                role="Finance",
                view_type="preference",
                statement="Finance prefers EuroMotion as competitive leverage to reach the 5% savings target.",
                basis="5% savings target",
            ),
            StakeholderView(
                stakeholder_name="Operations",
                role="Operations",
                view_type="preference",
                statement="Operations prefers Atlas Bearings because of its stronger reliability history.",
                basis="incumbent performance history",
            ),
            StakeholderView(
                stakeholder_name="Procurement",
                role="Procurement",
                view_type="recommendation",
                statement="Procurement wants a non-exclusive dual-source option.",
                basis="competitive leverage",
            ),
            StakeholderView(
                stakeholder_name="Plant Manager",
                role="Plant Manager",
                view_type="rumor",
                statement="Plant Manager reports EuroMotion may have capacity constraints beyond the stated 30%.",
                basis="unverified operational report",
            ),
        ],
    )


def _position(text: str) -> CommercialPosition:
    return CommercialPosition(
        recommendation=text,
        commercial_insights=[
            "Atlas has stronger stated operating performance.",
            "EuroMotion provides a lower stated delivered price and immediate 30% capacity.",
            "The 12% increase is not supported by an audited cost-driver breakdown.",
        ],
        commercial_hypothesis="Atlas may be using switching friction to test whether an unsupported increase will be accepted.",
        methodology_applied="TCO and BATNA-strengthening negotiation analysis.",
        reasoning=(
            "Reject Atlas's unverified 12% increase and use EuroMotion as a bounded competitive lever. "
            "Atlas has an established production history and stronger stated OTIF/defect performance. "
            "EuroMotion is an alternative supplier with a stated DDP price and 30% immediate capacity, "
            "but its qualification and production history are not established in the evidence."
        ),
        confidence=Confidence(
            level="medium",
            factors=[
                {"factor": "material stakeholder conflict", "value": "Finance and Operations prefer different suppliers", "weight": "decreases confidence"},
                {"factor": "incumbent performance", "value": "99.2% OTIF / 0.5% defects", "weight": "increases confidence"},
            ],
            derivation_note="Medium because the direction is supported but supplier qualification/capacity evidence remains incomplete.",
        ),
        decision_audit=None,
        sensitivity_analysis=None,
        alternative_analysis=None,
        control_tower=None,
        stress_test=None,
        financial_impact=None,
        assumptions=[
            "The stated USD prices are comparable at the stated Incoterms.",
            "EuroMotion's 30% capacity is the currently stated ceiling.",
        ],
        opening_position="No increase until the cost drivers are substantiated.",
        walk_away_threshold="Do not accept the requested increase without verifiable cost evidence.",
        disconfirming_condition="Reconsider if Atlas provides audited index-linked cost evidence supporting the increase or if EuroMotion's stated 30% capacity is withdrawn.",
        decision_type="optimization",
    )


def test_master_case_preserves_supplier_specific_evidence_and_stakeholder_conflict():
    n = _master_normalized()
    assert n.supplier_by_name("Atlas Bearings").price_usd == 48.0
    assert n.supplier_by_name("EuroMotion Poland").price_usd == 43.0
    assert n.supplier_by_name("EuroMotion Poland").qualification_status == "unknown"
    conflict, details = stakeholder_conflict_summary(n)
    assert conflict is True
    assert any("Finance" in d and "Operations" in d for d in details)
    protocol = build_stakeholder_decision_protocol(n)
    assert "MATERIAL STAKEHOLDER CONFLICT DETECTED" in protocol
    assert "Rumors and insider information are NEVER verified facts" in protocol


def test_master_case_financials_are_deterministic():
    n = _master_normalized()
    impact = compute_financial_impact(n)
    assert impact is not None
    assert impact.annual_spend_usd == 2400000.0
    assert impact.requested_change_percent == 12.0
    assert impact.potential_annual_impact_usd == 288000.0


def test_master_case_claim_firewall_rejects_unsupported_supplier_status():
    n = _master_normalized()
    bad = _position("EuroMotion Poland is a qualified supplier and a reliable alternative.")
    bad.reasoning = bad.recommendation
    issues = check_all_claim_overstatements(bad, n, raw_question=MASTER_CASE)
    assert issues, "Unsupported supplier-status/performance claims must not pass silently."
    assert any("EuroMotion Poland" in x for x in issues)


def test_master_case_supported_performance_claim_survives():
    n = _master_normalized()
    good = _position("Atlas Bearings is a reliable incumbent with 99.2% OTIF and 0.5% defects.")
    good.reasoning = good.recommendation
    issues = check_all_claim_overstatements(good, n, raw_question=MASTER_CASE)
    assert not any("Atlas Bearings" in x and "reliable" in x.lower() for x in issues)


def test_master_case_all_decision_layers_remain_coherent():
    n = _master_normalized()
    p = _position("Reject Atlas's unverified 12% increase and use EuroMotion as a bounded competitive lever.")

    pre_level, pre_reasons = compute_pre_reasoning_confidence(n)
    assert pre_level == "medium"
    assert any("stakeholder" in x.lower() for x in pre_reasons)

    audit_data = build_decision_audit(n, p)
    assert audit_data["evidence_integrity_status"] == "UNKNOWN"
    assert audit_data["stakeholder_conflict"]
    assert audit_data["reversal_conditions"]

    p.decision_audit = DecisionAudit(**audit_data)
    p.financial_impact = compute_financial_impact(n)
    p.sensitivity_analysis = build_sensitivity_analysis(n)
    p.alternative_analysis = build_alternative_paths(n)
    p.stress_test = build_stress_test(n, p)
    p.control_tower = build_control_tower(n, p)

    assert p.sensitivity_analysis["available"] is True
    assert p.alternative_analysis["available"] is True
    assert len(p.alternative_analysis["alternatives"]) >= 2
    assert p.stress_test["available"] is True
    assert p.control_tower["readiness"] == "CONDITIONAL"
    assert p.control_tower["stakeholder_conflicts"]
    assert p.control_tower["decision_changers"]
    assert p.control_tower["financial_impact_available"] is True


def test_master_case_never_turns_unverified_capacity_rumor_into_supplier_fact():
    n = _master_normalized()
    euro = n.supplier_by_name("EuroMotion Poland")
    assert euro.capacity_percent == 30.0
    assert not any("beyond" in str(x).lower() for x in build_alternative_paths(n)["alternatives"][0].get("what_you_give_up", []))
    audit = build_decision_audit(n, _position("Use the bounded alternative as leverage."))
    assert any("rumor" in u.lower() for u in audit["uncertainties"])
