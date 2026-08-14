from types import SimpleNamespace
from app.models import CommercialPosition, Confidence
from app.pipeline.control_tower import build_control_tower


def _position(**kwargs):
    base = dict(
        recommendation="Hold current price and negotiate.",
        commercial_insights=["A"],
        reasoning="R",
        confidence=Confidence(level="medium", factors=[{"factor":"gap","value":"x","weight":"decreases confidence"}], derivation_note="test"),
        assumptions=["Known only"], disconfirming_condition="Audited evidence changes the position.", decision_type="optimization",
        decision_audit=SimpleNamespace(evidence_integrity_status="PROVEN", uncertainties=[], reversal_conditions=[], stakeholder_conflict=[]),
        alternative_analysis={"alternatives":[{},{}],"warnings":[]},
        stress_test={"status":"SURVIVES_AVAILABLE_TESTS"},
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _norm():
    return SimpleNamespace(content_type="price_increase", provenance={})


def test_ready_when_no_material_blockers():
    out = build_control_tower(_norm(), _position())
    assert out["readiness"] == "READY"
    assert out["alternative_count"] == 2
    assert out["stress_status"] == "SURVIVES_AVAILABLE_TESTS"


def test_critical_evidence_makes_decision_conditional():
    p = _position(decision_audit=SimpleNamespace(
        evidence_integrity_status="PROVEN",
        uncertainties=["Freight cost is not provided."],
        reversal_conditions=["If freight changes materially, reconsider."],
        stakeholder_conflict=[]), alternative_analysis={"alternatives":[],"warnings":[]})
    out = build_control_tower(_norm(), p)
    assert out["readiness"] == "CONDITIONAL"
    assert any("Freight" in x for x in out["critical_before_action"])


def test_contradicted_evidence_holds_decision():
    p = _position(decision_audit=SimpleNamespace(
        evidence_integrity_status="CONTRADICTED", uncertainties=[], reversal_conditions=[], stakeholder_conflict=[]))
    out = build_control_tower(_norm(), p)
    assert out["readiness"] == "HOLD"


def test_stakeholder_conflict_is_preserved_not_averaged():
    conflict = "Finance prefers savings; Operations prefers incumbent continuity."
    p = _position(decision_audit=SimpleNamespace(
        evidence_integrity_status="PROVEN", uncertainties=[], reversal_conditions=[], stakeholder_conflict=[conflict]))
    out = build_control_tower(_norm(), p)
    assert out["stakeholder_conflicts"] == [conflict]
