from datetime import datetime, timezone

from app.pipeline.commercial_memory import build_commercial_memory
from app.pipeline.normalized_evidence import CommonEvidence, DerivedEvidence, NormalizedEvidence, PriceIncreaseEvidence


def _n():
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Nordic"),
        case=PriceIncreaseEvidence(),
        derived=DerivedEvidence(),
    )


def _row(i, content_type="price_increase", outcome=False, insight=None):
    now = datetime.now(timezone.utc)
    return {
        "id": f"case-{i}",
        "created_at": now,
        "classified_content_type": content_type,
        "raw_question": f"Supplier case {i}",
        "user_supplied_inputs": {"supplier_name": "Nordic"},
        "commercial_position": {"recommendation": "Negotiate"},
        "feedback": {
            "outcome_description": "Held" if outcome else None,
            "validation_verdict": "reasoning_held" if outcome else None,
            "decision_alignment": "same" if outcome else None,
            "unexpected_insight": insight,
        },
    }


def test_r39_exposes_current_year_observed_activity_without_prediction():
    rows = [_row(i) for i in range(3)] + [_row(10, content_type="quote_comparison")]
    m = build_commercial_memory(_n(), {"available": True, "prior_cases": []}, rows, rows)
    assert m["scope"]["current_year_completed_cases"] == 4
    assert m["scope"]["current_year_same_type_cases"] == 3
    assert m["pattern_level"] == "OBSERVED"
    assert "prediction" not in str(m["repeated_signals"]).lower()


def test_r39_prefers_recorded_supplier_precedent():
    rows = [_row(1, outcome=False), _row(2, outcome=True, insight="Use evidence before conceding term.")]
    m = build_commercial_memory(_n(), {"available": True, "prior_cases": []}, rows, rows)
    assert m["strongest_precedent"] is not None
    assert m["strongest_precedent"]["outcome"] == "Held"
    assert "Use evidence" in m["lessons"][0]


def test_r39_does_not_claim_pattern_from_one_case():
    rows = [_row(1, outcome=True)]
    m = build_commercial_memory(_n(), {"available": True, "prior_cases": []}, rows, rows)
    assert m["pattern_level"] == "NONE"
    assert "No outcome-backed precedent" not in m["next_time_note"]
