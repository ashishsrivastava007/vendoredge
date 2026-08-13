"""
Production Hardening Fix #1 — Mixed-Currency Financial Calculation.

Confirmed red-team finding: a genuine currency mismatch (supplier bills
in a non-USD currency) combined with no real dollar figure anywhere in
the text meant the guaranteed calculation could silently treat a
foreign-currency number as if it were already in USD. Fixed by making
the calculation structurally refuse to run in that specific, narrow
condition -- while explicitly NOT blocking the honest case where a real
"$" figure is genuinely stated alongside foreign-currency context.
"""
from app.pipeline.normalize import normalize_evidence
from app.pipeline.financial import compute_financial_impact


def test_dangerous_mixed_currency_case_refuses_to_calculate():
    """The exact real red-team finding: no dollar sign anywhere, a
    non-USD currency detected -- the calculation must refuse to run."""
    raw = "Supplier price is €1,000,000 annually, 10% increase requested."
    ne, _ = normalize_evidence(
        raw, "price_increase", {"supplier_currency": "EUR"},
        {"annual_spend_usd": 1_000_000.0, "requested_change_percent": 10.0},
    )
    assert ne.derived.currency_calculation_safe is False
    assert compute_financial_impact(ne) is None


def test_honest_case_with_a_real_dollar_figure_is_never_blocked():
    """Critical negative case: the exact scenario from the original
    red-team test -- a real dollar figure genuinely stated alongside
    foreign-currency context. This must NEVER be blocked."""
    raw = "Supplier bills in EUR at €38,000/month but our budget is tracked in USD at $460,000 annually, requesting a 9% increase."
    ne, _ = normalize_evidence(
        raw, "price_increase", {"supplier_currency": "EUR"},
        {"annual_spend_usd": 460_000.0, "requested_change_percent": 9.0},
    )
    assert ne.derived.currency_calculation_safe is True
    result = compute_financial_impact(ne)
    assert result is not None
    assert result.annual_spend_usd == 460_000.0


def test_no_currency_mismatch_at_all_is_always_safe():
    """The common, everyday case -- no foreign currency ever mentioned --
    must never be affected by this fix at all."""
    raw = "Supplier requests a 10% increase, current annual spend is $1,000,000."
    ne, _ = normalize_evidence(
        raw, "price_increase", {}, {"annual_spend_usd": 1_000_000.0, "requested_change_percent": 10.0},
    )
    assert ne.derived.currency_mismatch is False
    assert ne.derived.currency_calculation_safe is True
    assert compute_financial_impact(ne) is not None


def test_deliberate_break_disabling_the_check_lets_the_real_danger_return():
    """
    MANDATORY deliberate-break proof. Directly simulates the pre-fix
    state (currency_calculation_safe manually forced True despite a real
    mismatch) and confirms the dangerous silent calculation returns --
    proving this specific flag is genuinely load-bearing, not decorative.
    """
    raw = "Supplier price is €1,000,000 annually, 10% increase requested."
    ne, _ = normalize_evidence(
        raw, "price_increase", {"supplier_currency": "EUR"},
        {"annual_spend_usd": 1_000_000.0, "requested_change_percent": 10.0},
    )
    assert ne.derived.currency_calculation_safe is False  # the real, correct state

    # Simulate the pre-fix state directly.
    broken = ne.model_copy(update={"derived": ne.derived.model_copy(update={"currency_calculation_safe": True})})
    broken_result = compute_financial_impact(broken)
    assert broken_result is not None, (
        "Without this flag correctly set, the dangerous silent mixed-currency "
        "calculation returns -- confirming the flag is genuinely load-bearing."
    )
