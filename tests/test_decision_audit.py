from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.decision_audit import build_decision_audit
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence,
    HistoryContext, SupplierEvidence, FieldProvenance, StakeholderView,
)


def _position(**kw):
    base = dict(
        recommendation="Hold price and negotiate",
        commercial_insights=["Evidence supports negotiation"],
        reasoning="Reasoning",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="evidence", value="good", weight="increases confidence")], derivation_note="evidence"),
        assumptions=["Freight not supplied"],
        disconfirming_condition="Change recommendation if verified cost evidence supports the increase.",
        decision_type="optimization",
    )
    base.update(kw)
    return CommercialPosition(**base)


def _normalized(conflicting=False, stakeholder_views=None):
    n = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Atlas Motion GmbH", unit_price_usd=48),
        case=PriceIncreaseEvidence(current_price_or_terms="€48/unit FCA", requested_increase_percent=12, suppliers_stated_justification="steel and energy inflation", annual_spend_usd=2400000),
        derived=DerivedEvidence(resolved_annual_spend_usd=2400000, annual_spend_resolution_method="direct"),
        history=HistoryContext(),
        suppliers=[
            SupplierEvidence(supplier_name="Atlas Motion GmbH", price_display="€48/unit", is_incumbent=True, qualification_status="complete", otif_percent=99.2),
            SupplierEvidence(supplier_name="EuroMotion Poland", price_display="€43/unit DDP", qualification_status="unknown", otif_percent=97.0),
        ],
        stakeholder_views=stakeholder_views or [],
    )
    n.provenance={
        "current_price_or_terms": FieldProvenance(source="llm_extraction", stage_captured="test"),
        "requested_increase_percent": FieldProvenance(source="llm_extraction", stage_captured="test"),
        "suppliers_stated_justification": FieldProvenance(source="llm_extraction", stage_captured="test", conflicting=conflicting),
        "annual_spend_usd": FieldProvenance(source="llm_extraction", stage_captured="test"),
    }
    return n


def test_audit_exposes_material_evidence_and_unknowns():
    audit = build_decision_audit(_normalized(), _position(commercial_hypothesis="EuroMotion may be a stronger negotiating lever."))
    assert audit["evidence_integrity_status"] == "UNKNOWN"
    assert any(x["label"] == "Requested increase" and x["status"] == "PROVEN" for x in audit["material_evidence"])
    assert any("EuroMotion Poland" in x for x in audit["uncertainties"])
    assert audit["inferred_signals"]
    assert audit["reversal_conditions"]


def test_audit_marks_conflicting_load_bearing_evidence():
    audit = build_decision_audit(_normalized(conflicting=True), _position())
    assert audit["evidence_integrity_status"] == "CONTRADICTED"
    assert any("Conflicting evidence" in x for x in audit["uncertainties"])


def test_stakeholder_views_are_preserved_not_flattened():
    views = [
        StakeholderView(stakeholder_name="Operations", role="Fleet", view_type="preference", statement="We prefer Atlas for reliability."),
        StakeholderView(stakeholder_name="Finance", role="CFO", view_type="recommendation", statement="Finance prefers EuroMotion for savings."),
    ]
    audit = build_decision_audit(_normalized(stakeholder_views=views), _position())
    assert len(audit["stakeholder_tradeoffs"]) == 2
    assert audit["stakeholder_conflict"]


def test_model_accepts_bounded_audit_shape():
    p = _position()
    p.decision_audit = build_decision_audit(_normalized(), p)
    p.decision_audit = __import__("app.models", fromlist=["DecisionAudit"]).DecisionAudit(**p.decision_audit) if isinstance(p.decision_audit, dict) else p.decision_audit
    assert p.decision_audit.evidence_integrity_status == "UNKNOWN"
