from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.negotiation_intelligence import build_negotiation_intelligence


def _p(**kw):
    base = dict(
        recommendation="Negotiate",
        assumptions=["No unsupported assumptions"],
        disconfirming_condition="Evidence changes",
        decision_type="optimization",
        commercial_insights=["Evidence-backed case"],
        reasoning="Reasoning",
        confidence=Confidence(level="high", factors=[ConfidenceFactor(factor="evidence", value="high", weight="increases confidence", impact="supports", detail="captured")], stress_status="ok", derivation_note="captured", financial_impact_available=False, action_items=[], method="deterministic"),
        negotiation_dimensions=[{"dimension":"Price","opening_ask":"Hold","target_outcome":"3%","walk_away":"6%"}],
        opening_position="Please substantiate the increase before we discuss movement.",
    )
    base.update(kw)
    return CommercialPosition(**base)


def test_give_get_matrix_is_grounded_in_existing_dimensions():
    n = build_negotiation_intelligence(_p())
    assert n["give_get_matrix"][0]["dimension"] == "Price"
    assert n["give_get_matrix"][0]["buyer_target"] == "3%"


def test_supplier_response_is_never_presented_as_prediction():
    n = build_negotiation_intelligence(_p())
    assert all(x["status"] == "SCENARIO_NOT_PREDICTION" for x in n["response_scenarios"])


def test_conflict_holds_negotiation_readiness():
    from app.models import DecisionAudit
    p = _p(decision_audit=DecisionAudit(evidence_integrity_status="CONTRADICTED", material_evidence=[], uncertainties=[], reversal_conditions=[]))
    n = build_negotiation_intelligence(p)
    assert n["readiness"] == "HOLD_FOR_EVIDENCE_CONFLICT"
