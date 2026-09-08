"""
Production Hardening Fix #1 — Mixed-Currency Financial Calculation.

UPDATED as part of the currency-scenario-engine fix: the original version
of this file's "dangerous" test case was itself built on the exact
incorrect assumption this later fix corrected -- that ANY explicitly
stated currency (`currency_mismatch = currency is not None`) meant the
calculation should refuse to run, unless a literal "$" also appeared
somewhere in the raw text. That definition wrongly refused to calculate
a case that is entirely, cleanly, consistently denominated in one
non-USD currency -- exactly the shape of the Industrial Valves &
Actuators golden case (all figures genuinely in EUR, no dollar anywhere,
nothing dangerous or ambiguous about it at all).

The real danger this file exists to test is GENUINE currency ambiguity:
the LLM's own extracted currency actually disagreeing with an
independent regex scan of the raw text -- i.e. `"supplier_currency" in
conflicts`, the same conflict-detection machinery every other field in
normalize.py already uses. That is what test_dangerous_mixed_currency_
case_refuses_to_calculate now tests, with a genuinely conflicting case
(LLM says EUR, raw text shows a prominent £ symbol) rather than a clean
single-currency case that was never actually dangerous.
"""
from app.pipeline.normalize import normalize_evidence
from app.pipeline.financial import compute_financial_impact


def test_dangerous_mixed_currency_case_refuses_to_calculate():
    """The real danger case: the LLM's extracted currency genuinely
    disagrees with an independent regex scan of the raw text -- a true
    conflict, not merely 'a currency was mentioned'."""
    raw = "Supplier invoices in £500,000 annually, requesting a 10% increase."
    ne, conflicts = normalize_evidence(
        raw, "price_increase", {"supplier_currency": "EUR"},
        {"annual_spend_usd": 500_000.0, "requested_change_percent": 10.0},
    )
    assert "supplier_currency" in conflicts
    assert ne.derived.currency_mismatch is True
    assert ne.derived.currency_calculation_safe is False
    assert compute_financial_impact(ne) is None


def test_clean_single_currency_eur_case_is_safe_and_correct():
    """The case this whole fix exists for: a clean, single, consistently
    EUR-denominated case -- no ambiguity, no mixing, nothing dangerous.
    Must calculate correctly, natively in EUR, not be refused."""
    raw = "Supplier price is €1,000,000 annually, 10% increase requested."
    ne, conflicts = normalize_evidence(
        raw, "price_increase", {"supplier_currency": "EUR"},
        {"annual_spend_usd": 1_000_000.0, "requested_change_percent": 10.0},
    )
    assert "supplier_currency" not in conflicts
    assert ne.derived.currency_mismatch is False
    assert ne.derived.currency_calculation_safe is True
    assert ne.derived.spend_currency == "EUR"
    result = compute_financial_impact(ne)
    assert result is not None
    assert result.currency == "EUR"
    assert result.potential_annual_impact == 100_000.0
    assert result.annual_spend_usd is None, "a EUR case must never populate the legacy USD-only field"


def test_honest_case_with_a_real_dollar_figure_is_never_blocked():
    """Critical negative case: the exact scenario from the original
    red-team test -- a real dollar figure genuinely stated for the spend
    itself, even though the supplier separately bills in a different
    currency for their own invoicing. This must NEVER be blocked, and
    the spend figure correctly resolves to USD -- the currency it was
    actually, genuinely stated in -- not the supplier's own billing
    currency, which is a separate fact."""
    raw = "Supplier bills in EUR at €38,000/month but our budget is tracked in USD at $460,000 annually, requesting a 9% increase."
    ne, _ = normalize_evidence(
        raw, "price_increase", {"supplier_currency": "EUR"},
        {"annual_spend_usd": 460_000.0, "requested_change_percent": 9.0},
    )
    assert ne.derived.currency_calculation_safe is True
    assert ne.derived.spend_currency == "USD"
    result = compute_financial_impact(ne)
    assert result is not None
    assert result.annual_spend_usd == 460_000.0
    assert result.currency == "USD"


def test_no_currency_mismatch_at_all_is_always_safe():
    """The common, everyday case -- no foreign currency ever mentioned --
    must never be affected by this fix at all."""
    raw = "Supplier requests a 10% increase, current annual spend is $1,000,000."
    ne, _ = normalize_evidence(
        raw, "price_increase", {}, {"annual_spend_usd": 1_000_000.0, "requested_change_percent": 10.0},
    )
    assert ne.derived.currency_mismatch is False
    assert ne.derived.currency_calculation_safe is True
    assert ne.derived.spend_currency == "USD"
    result = compute_financial_impact(ne)
    assert result is not None
    assert result.annual_spend_usd == 1_000_000.0


def test_deliberate_break_disabling_the_check_lets_the_real_danger_return():
    """
    MANDATORY deliberate-break proof. Directly simulates the pre-fix
    state (currency_calculation_safe manually forced True despite a real,
    genuine mismatch) and confirms the dangerous silent calculation
    returns -- proving this specific flag is genuinely load-bearing, not
    decorative.
    """
    raw = "Supplier invoices in £500,000 annually, requesting a 10% increase."
    ne, conflicts = normalize_evidence(
        raw, "price_increase", {"supplier_currency": "EUR"},
        {"annual_spend_usd": 500_000.0, "requested_change_percent": 10.0},
    )
    assert ne.derived.currency_calculation_safe is False  # the real, correct state

    # Simulate the pre-fix state directly.
    broken = ne.model_copy(update={"derived": ne.derived.model_copy(update={"currency_calculation_safe": True})})
    broken_result = compute_financial_impact(broken)
    assert broken_result is not None, (
        "Without this flag correctly set, the dangerous silent mixed-currency "
        "calculation returns -- confirming the flag is genuinely load-bearing."
    )
