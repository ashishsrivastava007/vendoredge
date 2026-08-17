from datetime import datetime, timezone

from app.pipeline.procurement_memory import build_procurement_memory
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence
from app.models import CommercialPosition, Confidence


def _normalized(supplier="Acme"):
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name=supplier),
        case=PriceIncreaseEvidence(),
        derived=DerivedEvidence(),
    )


def _position():
    return CommercialPosition(
        recommendation="Hold current price pending evidence",
        commercial_insights=["Evidence must support the decision."],
        reasoning="reasoning",
        confidence=Confidence(level="medium", factors=[{"factor":"evidence","value":"partial","weight":"decreases confidence"}], derivation_note="test"),
        assumptions=["None"],
        disconfirming_condition="Material new evidence changes the economics.",
        decision_type="optimization",
    )


def _row(**kwargs):
    base={"id":"11111111-1111-1111-1111-111111111111","created_at":datetime(2026,1,1,tzinfo=timezone.utc),"raw_question":"Acme requested 12% increase","outcome_description":None,"validation_verdict":None,"decision_alignment":None,"unexpected_insight":None}
    base.update(kwargs); return base


def test_no_history_does_not_invent_memory():
    m=build_procurement_memory(_normalized(),_position(),[],[])
    assert m["memory_strength"] == "NONE"
    assert m["available"] is False
    assert "Do not infer a pattern" in m["category_pattern"]


def test_one_case_is_context_not_a_pattern():
    m=build_procurement_memory(_normalized(),_position(),[],[_row()])
    assert m["memory_strength"] == "EMERGING"
    assert "not enough to establish a genuine pattern" in m["supplier_pattern"]
    assert m["prior_cases"][0]["outcome_recorded"] is False


def test_three_recorded_supplier_outcomes_can_surface_historical_pattern():
    rows=[
      _row(id="1", outcome_description="Settled at 5%", validation_verdict="reasoning_held"),
      _row(id="2", outcome_description="Settled at 4%", validation_verdict="reasoning_held"),
      _row(id="3", outcome_description="Settled at 3%", validation_verdict="reasoning_held"),
    ]
    m=build_procurement_memory(_normalized(),_position(),[],rows)
    assert m["memory_strength"] == "STRONG"
    assert "consistent positive pattern" in m["supplier_pattern"]


def test_prior_miss_and_unexpected_insight_become_lessons():
    rows=[_row(validation_verdict="reasoning_wrong_bad_assumption", unexpected_insight="Contract length mattered more than price.")]
    m=build_procurement_memory(_normalized(),_position(),[],rows)
    types={x["type"] for x in m["lessons"]}
    assert "prior_miss" in types
    assert "unexpected_insight" in types
    assert m["warnings"]


def test_recommendation_is_not_mutated():
    p=_position(); before=p.recommendation
    build_procurement_memory(_normalized(),p,[],[_row(outcome_description="Changed supplier")])
    assert p.recommendation == before
