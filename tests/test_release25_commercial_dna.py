from types import SimpleNamespace

from app.pipeline.commercial_dna import build_commercial_dna


def row(expected=None, actual=None, verdict=None, alignment=None, content_type="quote_comparison"):
    return {
        "commercial_position": {"financial_impact": {"potential_annual_impact_usd": expected}} if expected is not None else {},
        "actual_financial_impact_usd": actual,
        "validation_verdict": verdict,
        "decision_alignment": alignment,
        "classified_content_type": content_type,
    }


def test_no_history_does_not_claim_dna():
    out = build_commercial_dna("quote_comparison", [])
    assert out["available"] is False
    assert out["maturity"] == "INSUFFICIENT_HISTORY"
    assert out["signals"] == []


def test_three_structured_outcomes_unlock_financial_realization_only():
    rows = [
        row(100000, 90000, "reasoning_held", "followed"),
        row(200000, 180000, "reasoning_held", "followed"),
        row(300000, 330000, "reasoning_held", "followed"),
    ]
    out = build_commercial_dna("quote_comparison", rows)
    assert out["structured_financial_outcome_count"] == 3
    assert out["financial_realization"]["available"] is True
    assert out["financial_realization"]["expected_total_usd"] == 600000
    assert out["financial_realization"]["actual_total_usd"] == 600000
    assert out["financial_realization"]["aggregate_variance_usd"] == 0


def test_free_text_or_missing_actual_cannot_create_financial_signal():
    rows = [
        row(100000, None, "reasoning_held", "followed"),
        row(200000, None, "reasoning_held", "followed"),
        row(300000, None, "reasoning_held", "followed"),
    ]
    out = build_commercial_dna("quote_comparison", rows)
    assert out["structured_financial_outcome_count"] == 0
    assert out["financial_realization"]["available"] is False
    assert not any(s["type"] == "realization_gap" for s in out["signals"])


def test_material_realization_gap_is_reported_without_causality_claim():
    rows = [
        row(100000, 50000, "reasoning_held", "followed"),
        row(200000, 150000, "reasoning_held", "followed"),
        row(300000, 200000, "reasoning_held", "followed"),
    ]
    out = build_commercial_dna("quote_comparison", rows)
    sig = next(s for s in out["signals"] if s["type"] == "realization_gap")
    assert "trails expected" in sig["finding"]
    assert "Not established" in sig["causality"]
    assert out["one_behavior_to_change"] is not None


def test_behavior_signals_need_five_outcomes():
    rows = [row(100000, 90000, "reasoning_wrong_bad_assumption", "modified") for _ in range(4)]
    out = build_commercial_dna("quote_comparison", rows)
    assert not any(s["type"] == "assumption_risk" for s in out["signals"])
    assert not any(s["type"] == "decision_intervention" for s in out["signals"])


def test_repeated_assumption_and_intervention_signal():
    rows = [
        row(100000, 90000, "reasoning_wrong_bad_assumption", "modified"),
        row(100000, 90000, "reasoning_wrong_bad_assumption", "modified"),
        row(100000, 90000, "reasoning_wrong_bad_assumption", "different_direction"),
        row(100000, 90000, "reasoning_held", "followed"),
        row(100000, 90000, "reasoning_held", "followed"),
    ]
    out = build_commercial_dna("quote_comparison", rows)
    types = {s["type"] for s in out["signals"]}
    assert "assumption_risk" in types
    assert "decision_intervention" in types
    assert out["maturity"] == "ESTABLISHED_HISTORY"
