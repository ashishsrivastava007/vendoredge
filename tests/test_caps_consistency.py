"""
Permanent guard against the exact bug class found and fixed tonight: a cap
number changed in the schema but not in the prompt text (or vice versa),
causing the model to generate something the schema then rejects.

This test doesn't check "is the number 3" -- it checks that the PROMPT
TEXT's stated numbers and the SCHEMA's actual max_length/max_length values
are the same number, by reading both from the same live objects, not by
re-typing expected values here (which would just recreate the same bug in
the test itself).
"""
from app import caps
from app.models import CommercialPosition
from app.pipeline.reasoner import REASONING_SYSTEM_PROMPT


def _get_field_max_length(field_name: str) -> int | None:
    """Reads the REAL, live max_length constraint off the Pydantic model
    field, not a hardcoded expectation."""
    field_info = CommercialPosition.model_fields[field_name]
    for meta in field_info.metadata:
        if hasattr(meta, "max_length") and meta.max_length is not None:
            return meta.max_length
    return None


def test_no_leftover_substitution_tokens():
    """If a new HARD CAP is added to the prompt using a <<TOKEN>> that
    never gets substituted, this catches it immediately -- a leaked token
    would otherwise silently confuse the model in production."""
    import re
    leftover = re.findall(r"<<[A-Z_]+>>", REASONING_SYSTEM_PROMPT)
    assert not leftover, f"Unsubstituted tokens leaked into the live prompt: {leftover}"


def test_commercial_insights_cap_matches_schema():
    assert _get_field_max_length("commercial_insights") == caps.MAX_COMMERCIAL_INSIGHTS
    assert f'produce {caps.MIN_COMMERCIAL_INSIGHTS}-{caps.MAX_COMMERCIAL_INSIGHTS} "Commercial Insights"' in REASONING_SYSTEM_PROMPT


def test_cost_driver_cap_matches_schema():
    assert _get_field_max_length("cost_driver_comparison") == caps.MAX_COST_DRIVERS
    assert f"HARD CAP: at most {caps.MAX_COST_DRIVERS} entries" in REASONING_SYSTEM_PROMPT


def test_key_figures_cap_matches_schema():
    assert _get_field_max_length("key_figures") == caps.MAX_KEY_FIGURES
    assert f"{caps.MIN_KEY_FIGURES} to {caps.MAX_KEY_FIGURES} entries" in REASONING_SYSTEM_PROMPT


def test_supplier_comparison_cap_matches_schema():
    assert _get_field_max_length("supplier_comparison") == caps.MAX_SUPPLIERS
    assert f"HARD CAP: at most {caps.MAX_SUPPLIERS} suppliers" in REASONING_SYSTEM_PROMPT


def test_negotiation_dimensions_cap_matches_schema():
    assert _get_field_max_length("negotiation_dimensions") == caps.MAX_NEGOTIATION_DIMENSIONS
    assert f"HARD CAP: at most {caps.MAX_NEGOTIATION_DIMENSIONS} dimensions" in REASONING_SYSTEM_PROMPT


def test_negotiation_talk_track_cap_matches_schema():
    assert _get_field_max_length("negotiation_talk_track") == caps.MAX_TALK_TRACK_MOVES
    assert f"moves ({caps.MIN_TALK_TRACK_MOVES}-{caps.MAX_TALK_TRACK_MOVES}, not more)" in REASONING_SYSTEM_PROMPT


def test_financial_scenarios_cap_matches_schema():
    assert _get_field_max_length("financial_scenarios") == caps.MAX_FINANCIAL_SCENARIOS
    assert f"HARD CAP: at most {caps.MAX_FINANCIAL_SCENARIOS} scenarios" in REASONING_SYSTEM_PROMPT


def test_assumptions_cap_matches_schema():
    assert _get_field_max_length("assumptions") == caps.MAX_ASSUMPTIONS
    assert f"HARD CAP {caps.MAX_ASSUMPTIONS} items" in REASONING_SYSTEM_PROMPT


def test_methodology_char_cap_matches_schema():
    assert _get_field_max_length("methodology_applied") == caps.MAX_METHODOLOGY_CHARS
    assert f"HARD CAP {caps.MAX_METHODOLOGY_CHARS} characters" in REASONING_SYSTEM_PROMPT


def test_hypothesis_char_cap_matches_schema():
    assert _get_field_max_length("commercial_hypothesis") == caps.MAX_HYPOTHESIS_CHARS
    assert f"HARD CAP {caps.MAX_HYPOTHESIS_CHARS} characters" in REASONING_SYSTEM_PROMPT
