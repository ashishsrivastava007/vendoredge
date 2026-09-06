from app.models import CommercialPosition, Confidence, ConfidenceFactor, FinancialImpact
from app.pipeline.outcome_intelligence import build_outcome_intelligence


def _position(expected=182000.0):
    return CommercialPosition(
        recommendation="Supplier B", recommendation_type="award",
        commercial_insights=["Test insight"], reasoning="Evidence-backed recommendation.",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="Evidence", value="Adequate", weight="increases confidence")], derivation_note="Test"),
        disconfirming_condition="Freight materially exceeds the stated basis.", decision_type="optimization",
        assumptions=["Recorded commercial assumptions are valid."],
        financial_impact=FinancialImpact(annual_spend_usd=3640000, requested_change_percent=5, potential_annual_impact_usd=expected, note="Test"),
    )


def test_r34_attribution_is_higher_only_when_followed_and_held():
    out = build_outcome_intelligence(_position(), {"validation_verdict":"reasoning_held", "decision_alignment":"followed", "outcome_description":"held", "actual_financial_impact_usd":180000})
    assert out["attribution_level"] == "HIGHER_ATTRIBUTION"
    assert out["learning_status"] == "MEASURABLE"


def test_r34_modified_decision_is_partial_attribution():
    out = build_outcome_intelligence(_position(), {"validation_verdict":"reasoning_held", "decision_alignment":"modified", "outcome_description":"changed", "actual_financial_impact_usd":150000})
    assert out["attribution_level"] == "PARTIAL_ATTRIBUTION"
    assert any("what changed" in x.lower() for x in out["next_time_controls"])


def test_r34_calibration_requires_three_and_reports_bias_and_hit_rate():
    history = [
        {"expected_financial_impact_usd":100000, "actual_financial_impact_usd":90000},
        {"expected_financial_impact_usd":200000, "actual_financial_impact_usd":176000},
        {"expected_financial_impact_usd":300000, "actual_financial_impact_usd":330000},
    ]
    out = build_outcome_intelligence(_position(), None, history)
    assert out["calibration"]["available"] is True
    assert out["calibration"]["sample_size"] == 3
    assert out["calibration"]["within_10_percent_count"] == 2


def test_r34_bad_assumption_creates_control_without_predicting():
    out = build_outcome_intelligence(_position(), {"validation_verdict":"reasoning_wrong_bad_assumption", "decision_alignment":"followed", "outcome_description":"assumption failed"})
    assert any("assumption" in x.lower() for x in out["next_time_controls"])
    assert "causal" not in out["honesty_note"].lower() or "prove causality" in out["honesty_note"].lower()
