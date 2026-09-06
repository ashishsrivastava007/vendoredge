from app.models import CommercialPosition, Confidence, ConfidenceFactor, FinancialImpact
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence, SupplierEvidence
from app.pipeline.supplier_memory import build_supplier_memory


def _position():
    return CommercialPosition(
        recommendation="Hold price increase pending evidence.",
        commercial_insights=["Supplier request is not supported by a detailed cost breakdown."],
        reasoning="Test position.",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="evidence", value="mixed", weight="decreases confidence")], derivation_note="test"),
        assumptions=["Supply continuity remains important."],
        disconfirming_condition="Material new evidence changes economics.",
        decision_type="constraint_satisfaction",
        financial_impact=FinancialImpact(annual_spend_usd=1000000, requested_change_percent=8.5, potential_annual_impact_usd=85000, note="test"),
        opening_position="No unsupported increase.",
        walk_away_threshold="Do not accept unsupported economics.",
    )


def _normalized():
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="ABC Marine Supplies", supplier_currency="USD", incoterm="DAP"),
        case=PriceIncreaseEvidence(current_price_or_terms="$100", requested_increase_percent=8.5),
        derived=DerivedEvidence(resolved_annual_spend_usd=1000000),
        suppliers=[SupplierEvidence(supplier_name="ABC Marine Supplies", currency="USD", incoterm="DAP", payment_terms="Net 60", otif_percent=94, is_incumbent=True)],
    )


def _row(position, outcome_description=None, verdict=None):
    return {
        "id": "prior-1",
        "created_at": "2026-06-01",
        "classified_content_type": "price_increase",
        "user_supplied_inputs": {"supplier_name": "ABC Marine Supplies"},
        "commercial_position": {
            "recommendation": position.recommendation,
            "opening_position": position.opening_position,
            "walk_away_threshold": position.walk_away_threshold,
            "commercial_truth_model": {
                "parties": {"suppliers": [{"name": "ABC Marine Supplies", "role": "incumbent", "currency": "USD", "incoterm": "EXW", "payment_terms": "Net 45"}]}
            },
        },
        "outcome_description": outcome_description,
        "validation_verdict": verdict,
        "decision_alignment": "followed" if verdict else None,
    }


def test_no_supplier_name_is_explicitly_unavailable():
    n = _normalized().model_copy(update={"common": CommonEvidence(), "suppliers": []})
    m = build_supplier_memory(n, _position(), [])
    assert m["available"] is False


def test_first_supplier_capture_creates_baseline_without_pattern_claim():
    m = build_supplier_memory(_normalized(), _position(), [])
    assert m["available"] is True
    assert m["memory_strength"] == "NEW_SUPPLIER"
    assert m["prior_case_count"] == 0
    assert m["current_baseline"]["payment_terms"] == "Net 60"
    assert "prediction" not in m["history_note"].lower()


def test_prior_supplier_case_is_matched_and_outcome_is_counted():
    p = _position()
    m = build_supplier_memory(_normalized(), p, [_row(p, "Increase was rejected", "reasoning_held")])
    assert m["prior_case_count"] == 1
    assert m["recorded_outcome_count"] == 1
    assert m["outcome_summary"]["reasoning_held"] == 1
    assert m["prior_cases"][0]["outcome"] == "Increase was rejected"


def test_supplier_memory_reports_deterministic_term_change_only_when_both_sides_known():
    p = _position()
    m = build_supplier_memory(_normalized(), p, [_row(p)])
    changes = {(x["field"], x["previous"], x["current"]) for x in m["deterministic_changes"]}
    assert ("incoterm", "EXW", "DAP") in changes
    assert ("payment_terms", "Net 45", "Net 60") in changes


def test_sparse_history_never_becomes_established_memory():
    p = _position()
    rows = [_row(p, "done", "reasoning_held"), _row(p, "done", "reasoning_held")]
    m = build_supplier_memory(_normalized(), p, rows)
    assert m["memory_strength"] == "EMERGING"
    assert m["prior_case_count"] == 2
