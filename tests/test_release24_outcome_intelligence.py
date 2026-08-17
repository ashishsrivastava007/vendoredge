from app.models import CommercialPosition, Confidence, ConfidenceFactor, FinancialImpact
from app.pipeline.outcome_intelligence import build_outcome_intelligence


def _position(expected=182000.0):
    return CommercialPosition(
        recommendation="Supplier B",
        recommendation_type="award",
        commercial_insights=["Test insight"],
        reasoning="Evidence-backed recommendation.",
        confidence=Confidence(
            level="medium",
            factors=[ConfidenceFactor(factor="Evidence", value="Adequate", weight="increases confidence")],
            derivation_note="Deterministic test position.",
        ),
        disconfirming_condition="Freight materially exceeds the stated basis.",
        decision_type="optimization",
        assumptions=["Recorded commercial assumptions are valid."],
        financial_impact=FinancialImpact(
            annual_spend_usd=3640000,
            requested_change_percent=5,
            potential_annual_impact_usd=expected,
            note="Test financial basis.",
        ),
    )


def test_r24_computes_structured_expected_vs_actual_variance():
    out = build_outcome_intelligence(
        _position(),
        {
            "outcome_description": "Realized 121k annual impact.",
            "validation_verdict": "reasoning_held",
            "decision_alignment": "followed",
            "actual_financial_impact_usd": 121000,
            "actual_measurement_basis": "12-month realized impact",
        },
    )
    assert out["financial_variance_available"] is True
    assert out["financial_variance_usd"] == -61000
    assert out["financial_variance_percent"] == -33.52


def test_r24_never_parses_free_text_as_financial_actual():
    out = build_outcome_intelligence(
        _position(),
        {
            "outcome_description": "We realized $121,000 of savings.",
            "validation_verdict": "reasoning_held",
            "decision_alignment": "followed",
        },
    )
    assert out["actual_financial_impact_usd"] is None
    assert out["financial_variance_available"] is False


def test_r24_attributes_modified_decision_carefully():
    out = build_outcome_intelligence(
        _position(),
        {
            "outcome_description": "Buyer changed the recommendation before award.",
            "validation_verdict": "reasoning_held",
            "decision_alignment": "modified",
            "actual_financial_impact_usd": 150000,
        },
    )
    assert any("modified" in x.lower() for x in out["learning_signals"])
    assert "not attributed wholly" in out["attribution_note"].lower()


def test_r24_does_not_create_historical_accuracy_from_two_cases():
    history = [
        {"expected_financial_impact_usd": 100000, "actual_financial_impact_usd": 90000},
        {"expected_financial_impact_usd": 200000, "actual_financial_impact_usd": 180000},
    ]
    out = build_outcome_intelligence(_position(), None, history)
    assert out["structured_outcome_count"] == 2
    assert "Not enough structured financial outcomes" in out["historical_realization_note"]


def test_r24_allows_historical_realization_summary_at_three_cases():
    history = [
        {"expected_financial_impact_usd": 100000, "actual_financial_impact_usd": 90000},
        {"expected_financial_impact_usd": 200000, "actual_financial_impact_usd": 180000},
        {"expected_financial_impact_usd": 300000, "actual_financial_impact_usd": 330000},
    ]
    out = build_outcome_intelligence(_position(), None, history)
    assert out["structured_outcome_count"] == 3
    assert "mean absolute financial variance" in out["historical_realization_note"]
