"""
Permanent regression tests for supplier-specific memory (Phase 2 of the
gap-closing roadmap). The critical thing being tested is honesty
calibration: the formatting must never let a pattern be claimed from too
little real data, since that would be false confidence dressed up as
insight -- the same risk this whole codebase has been built to avoid.
"""
from app.pipeline.reasoner import _format_supplier_history


def test_no_supplier_name_produces_no_block_at_all():
    assert _format_supplier_history(None, None) == ""
    assert _format_supplier_history("", []) == ""


def test_zero_prior_cases_explicitly_refuses_any_pattern_claim():
    result = _format_supplier_history("Acme Manufacturing", [])
    assert "first case" in result
    assert "Do not claim a historical pattern" in result


def test_exactly_one_prior_case_references_facts_but_refuses_pattern():
    """The critical boundary case: real data exists, but not enough to
    call it a pattern -- this must be explicit, not implied."""
    one_case = [{
        "raw_question": "Acme wants a 12% increase citing steel costs",
        "outcome_description": "Settled at 5%",
    }]
    result = _format_supplier_history("Acme Manufacturing", one_case)
    assert "not enough to state a genuine pattern" in result
    assert "Acme wants a 12%" in result


def test_multiple_prior_cases_genuinely_allows_pattern_discussion():
    cases = [
        {"raw_question": "Acme wants a 12% increase", "created_at": "2026-01-01",
         "outcome_description": "Settled at 5%", "decision_alignment": "followed"},
        {"raw_question": "Acme wants a 15% increase", "created_at": "2026-03-01",
         "outcome_description": "Settled at 4%", "decision_alignment": "followed"},
        {"raw_question": "Acme wants an 8% increase", "created_at": "2026-06-01",
         "outcome_description": "Settled at 3%", "decision_alignment": "modified"},
    ]
    result = _format_supplier_history("Acme Manufacturing", cases)
    assert "3 prior cases" in result
    assert "enough real history to speak to a genuine pattern" in result
    assert all(f"Settled at {pct}%" in result for pct in ("5", "4", "3"))


def test_case_missing_outcome_data_still_formats_without_crashing():
    """A completed case that was never marked with an outcome (no
    decision_feedback row) must still format safely -- the LEFT JOIN in
    the real query means outcome fields can genuinely be None."""
    cases_without_outcomes = [
        {"raw_question": "Acme wants a 12% increase", "created_at": "2026-01-01",
         "outcome_description": None, "decision_alignment": None},
        {"raw_question": "Acme wants a 15% increase", "created_at": "2026-03-01",
         "outcome_description": None, "decision_alignment": None},
    ]
    result = _format_supplier_history("Acme Manufacturing", cases_without_outcomes)
    assert "2 prior cases" in result
    assert "Acme wants a 12%" in result
