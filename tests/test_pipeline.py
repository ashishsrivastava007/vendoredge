"""
These are literally Test PIPE-01 and PIPE-02 from VE-503A, now as real, runnable code
instead of a described test case. They test the deterministic parts of the pipeline
(evidence checking, schema validation) that don't require a live API call — the two
things that most directly encode the project's two hard rules.
"""
import pytest
from pydantic import ValidationError

from app.pipeline.evidence import check_missing_evidence, EVIDENCE_REQUIREMENTS
from app.pipeline.normalize import normalize_evidence
from app.models import CommercialPosition, Confidence, ConfidenceFactor


def test_pipe01_price_increase_with_no_evidence_is_flagged_missing():
    """Test PIPE-01: an underspecified question must produce a non-empty missing
    list, never silently be treated as answerable."""
    normalized, _ = normalize_evidence("Some vague question with no real details at all.", "price_increase", {}, {})
    missing = check_missing_evidence(normalized)
    assert len(missing) == len(EVIDENCE_REQUIREMENTS["price_increase"])
    assert all(
        isinstance(m, dict) and m["field"] and m["prompt"] and m["why"]
        for m in missing
    )


def test_pipe01_quote_comparison_with_partial_evidence_still_flags_the_rest():
    supplied = {
        "number_of_suppliers_being_compared": "2",
        "price_per_supplier": "A: $100, B: $108",
    }
    normalized, _ = normalize_evidence("Comparing two supplier quotes.", "quote_comparison", supplied, {})
    missing = check_missing_evidence(normalized)
    # 6 required fields, 2 supplied -> 4 should still be missing
    assert len(missing) == 4


def test_pipe01_fully_supplied_evidence_returns_empty():
    supplied_text = {f: "some value" for f in EVIDENCE_REQUIREMENTS["price_increase"] if f != "requested_increase_percent"}
    normalized, _ = normalize_evidence("A fully specified question.", "price_increase", supplied_text, {"requested_change_percent": 12.0})
    missing = check_missing_evidence(normalized)
    assert missing == []


def test_missing_fields_use_real_field_keys_not_positional_labels():
    """Regression test for the exact bug reported: the frontend was submitting
    positional keys (field_0, field_1) that never matched the real field names
    the backend checks against, causing an infinite 'awaiting_user_input' loop.
    This confirms the returned field key is the real, checkable name."""
    normalized, _ = normalize_evidence("Vague question.", "price_increase", {}, {})
    missing = check_missing_evidence(normalized)
    returned_keys = {m["field"] for m in missing}
    assert returned_keys == set(EVIDENCE_REQUIREMENTS["price_increase"])
    # Now confirm supplying evidence keyed by those exact real names actually
    # clears them -- this is the real behavior that was broken before.
    # requested_increase_percent specifically routes through numeric_facts
    # as a real number, not the text evidence dict, per the NormalizedEvidence
    # architecture -- every other field is a plain text answer.
    supplied_text = {m["field"]: "answer" for m in missing if m["field"] != "requested_increase_percent"}
    normalized2, _ = normalize_evidence("Vague question.", "price_increase", supplied_text, {"requested_change_percent": 12.0})
    assert check_missing_evidence(normalized2) == []


def test_pipe02_confidence_without_factors_is_rejected_by_schema():
    """Test PIPE-02: Hard Rule 2 enforced structurally — a confidence object
    with an empty factors list must fail validation, not silently pass through."""
    with pytest.raises(ValidationError):
        Confidence(level="high", factors=[], derivation_note="should not matter, factors is empty")


def test_pipe02_confidence_with_blank_derivation_note_is_rejected():
    with pytest.raises(ValidationError):
        Confidence(
            level="medium",
            factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
            derivation_note="",
        )


def test_pipe02_well_formed_commercial_position_is_accepted():
    position = CommercialPosition(
        recommendation="Stay with Supplier B.",
        commercial_insights=["Test insight for schema validation."],
        reasoning="Three independent signals favor B.",
        confidence=Confidence(
            level="medium",
            factors=[
                ConfidenceFactor(factor="OTIF/defect/lead time all agree", value="favors B", weight="increases confidence"),
                ConfidenceFactor(factor="unit price not provided", value="missing", weight="decreases confidence"),
            ],
            derivation_note="Directional, not a full net-cost calculation, since price data is missing.",
        ),
        assumptions=["Delivery reliability matters more than a small price gap here."],
        disconfirming_condition="If unit price and cost of capital are provided and the math favors A.",
        decision_type="optimization",
    )
    assert position.confidence.level == "medium"
    assert len(position.confidence.factors) == 2


def test_unsupported_content_type_returns_no_requirements():
    # A content type outside the two MVP types should not silently produce
    # an empty (and therefore falsely "complete") requirements list.
    assert EVIDENCE_REQUIREMENTS.get("fraud_concern") is None
