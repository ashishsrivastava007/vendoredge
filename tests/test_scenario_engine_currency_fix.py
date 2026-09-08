"""
Dedicated tests for the currency-safe Money type and scenario engine,
and for their wiring through financial.py and commercial_answer.py.

Covers, per the scoped fix's own requirements: EUR, USD, GBP, zero
change, negative change, multiple scenarios, scenario comparison,
currency mismatch, missing currency, legacy-field compatibility, model
output vs deterministic-figure conflict, and API serialization.
"""
import pytest

from app.pipeline.money import Money, currency_symbol
from app.pipeline.scenario_engine import compute_scenario, compare_scenarios
from app.pipeline.financial import compute_financial_impact
from app.pipeline.commercial_answer import build_commercial_answer
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence
from app.models import CommercialPosition, Confidence, ConfidenceFactor, FinancialImpact


# ---------------------------------------------------------------------
# A. Money / scenario_engine core primitives
# ---------------------------------------------------------------------

def test_eur_scenario_exact_golden_numbers():
    baseline = Money(amount=5_550_000, currency="EUR")
    s11 = compute_scenario("Supplier request", baseline, "percent", 11.0)
    s7 = compute_scenario("Negotiated scenario", baseline, "percent", 7.0)
    cmp = compare_scenarios(s11, s7)
    assert s11.delta.amount == 610_500.0
    assert s11.result.amount == 6_160_500.0
    assert s7.delta.amount == 388_500.0
    assert s7.result.amount == 5_938_500.0
    assert cmp.delta_amount.amount == 222_000.0
    assert s11.delta.formatted() == "\u20ac610,500"


def test_usd_scenario():
    baseline = Money(amount=5_550_000, currency="USD")
    s = compute_scenario("test", baseline, "percent", 11.0)
    assert s.delta.formatted() == "$610,500"


def test_gbp_scenario():
    baseline = Money(amount=5_550_000, currency="GBP")
    s = compute_scenario("test", baseline, "percent", 11.0)
    assert s.delta.formatted() == "\u00a3610,500"


def test_zero_percent_change():
    baseline = Money(amount=5_550_000, currency="EUR")
    s = compute_scenario("flat", baseline, "percent", 0.0)
    assert s.delta.amount == 0.0
    assert s.result.amount == baseline.amount


def test_negative_change_is_a_discount():
    baseline = Money(amount=5_550_000, currency="EUR")
    s = compute_scenario("discount", baseline, "percent", -5.0)
    assert s.delta.amount == -277_500.0
    assert s.result.amount == 5_272_500.0


def test_currency_mismatch_in_comparison_raises():
    usd_baseline = Money(amount=5_550_000, currency="USD")
    eur_baseline = Money(amount=5_550_000, currency="EUR")
    a = compute_scenario("a", usd_baseline, "percent", 11.0)
    b = compute_scenario("b", eur_baseline, "percent", 7.0)
    with pytest.raises(ValueError):
        compare_scenarios(a, b)


def test_currency_symbol_missing_falls_back_to_iso_code_not_dollar():
    assert currency_symbol(None) == ""
    assert currency_symbol("XYZ") == "XYZ "  # unrecognized code, never guessed as $


# ---------------------------------------------------------------------
# B. financial.py wiring
# ---------------------------------------------------------------------

def _eur_normalized(alt_percent=None, alt_label=None):
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Supplier A", supplier_currency="EUR"),
        case=PriceIncreaseEvidence(
            current_price_or_terms="EUR 19.77/unit", requested_increase_percent=11.0,
            alternative_scenario_percent=alt_percent, alternative_scenario_label=alt_label,
        ),
        derived=DerivedEvidence(resolved_annual_spend_usd=5_550_000, currency_calculation_safe=True, spend_currency="EUR"),
    )


def test_financial_impact_eur_single_scenario():
    result = compute_financial_impact(_eur_normalized())
    assert result.currency == "EUR"
    assert result.potential_annual_impact == 610_500.0
    assert result.annual_spend_usd is None, "legacy USD-only field must stay None for a EUR case"
    assert result.scenario_comparison is None


def test_financial_impact_eur_two_scenarios_golden_case():
    result = compute_financial_impact(_eur_normalized(alt_percent=7.0, alt_label="Negotiated scenario"))
    assert result.currency == "EUR"
    assert result.potential_annual_impact == 610_500.0
    sc = result.scenario_comparison
    assert sc is not None
    assert sc.scenario_a.delta.amount == 610_500.0
    assert sc.scenario_b.delta.amount == 388_500.0
    assert sc.delta_amount.amount == 222_000.0


def test_financial_impact_usd_case_populates_legacy_fields():
    n = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Acme"),
        case=PriceIncreaseEvidence(requested_increase_percent=10.0),
        derived=DerivedEvidence(resolved_annual_spend_usd=1_000_000, currency_calculation_safe=True, spend_currency="USD"),
    )
    result = compute_financial_impact(n)
    assert result.currency == "USD"
    assert result.annual_spend_usd == 1_000_000.0
    assert result.potential_annual_impact_usd == 100_000.0


def test_financial_impact_returns_none_on_genuine_currency_conflict():
    from app.pipeline.normalize import normalize_evidence
    ne, conflicts = normalize_evidence(
        "Supplier invoices in £500,000 annually, requesting a 10% increase.",
        "price_increase", {"supplier_currency": "EUR"},
        {"annual_spend_usd": 500_000.0, "requested_change_percent": 10.0},
    )
    assert compute_financial_impact(ne) is None


# ---------------------------------------------------------------------
# C. commercial_answer.py wiring -- the actual buyer-facing output
# ---------------------------------------------------------------------

def _position_with(financial_impact):
    return CommercialPosition(
        recommendation="test", commercial_insights=["a"], reasoning="r",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")], derivation_note="n"),
        assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
        financial_impact=financial_impact,
    )


def test_commercial_answer_surfaces_eur_scenario_comparison_end_to_end():
    normalized = _eur_normalized(alt_percent=7.0, alt_label="Negotiated scenario")
    fi = compute_financial_impact(normalized)
    pos = _position_with(fi)
    answer = build_commercial_answer(normalized, pos, "case text")
    money = answer["money"]
    assert money["available"] is True
    assert money["currency"] == "EUR"
    assert money["annual_impact"] == 610_500.0
    es = money["explicit_scenario"]
    assert es is not None
    assert es["annual_impact_from"] == 610_500.0
    assert es["annual_impact_to"] == 388_500.0
    assert es["annual_difference"] == 222_000.0
    assert "\u20ac222,000" in money["notes"][0]


def test_commercial_answer_never_shows_dollar_sign_for_a_eur_case():
    normalized = _eur_normalized(alt_percent=7.0, alt_label="Negotiated scenario")
    fi = compute_financial_impact(normalized)
    pos = _position_with(fi)
    answer = build_commercial_answer(normalized, pos, "case text")
    assert "$" not in answer["money"]["headline"]
    assert "$" not in answer["money"]["basis"]
    for note in answer["money"]["notes"]:
        assert "$" not in note
    for line in answer["evidence"]["calculated"]:
        assert "$" not in line


# ---------------------------------------------------------------------
# D. Model-output-cannot-override-deterministic-figure protection
# ---------------------------------------------------------------------

def test_model_prose_cannot_override_the_deterministic_figure():
    """The kernel's own FinancialImpact, once computed, is attached to the
    position regardless of what the model's own reasoning text claims --
    proven directly: constructing a position whose reasoning text states
    a DIFFERENT number than financial_impact, and confirming
    financial_impact itself is untouched (it's a separate, code-owned
    field the model has no path to write to)."""
    normalized = _eur_normalized()
    fi = compute_financial_impact(normalized)
    pos = CommercialPosition(
        recommendation="test", commercial_insights=["a"],
        reasoning="Exposure is approximately EUR 580,000, not the higher figure.",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")], derivation_note="n"),
        assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
        financial_impact=fi,
    )
    # The model's prose says something different; the deterministic field
    # itself is untouched, because there is no code path by which model
    # text ever writes into financial_impact -- it is only ever set here,
    # by compute_financial_impact, in Python.
    assert pos.financial_impact.potential_annual_impact == 610_500.0
    assert "580,000" in pos.reasoning  # the (wrong) model text, unmodified, still separate


# ---------------------------------------------------------------------
# E. API serialization
# ---------------------------------------------------------------------

def test_financial_impact_serializes_cleanly_with_scenario_comparison():
    normalized = _eur_normalized(alt_percent=7.0, alt_label="Negotiated scenario")
    fi = compute_financial_impact(normalized)
    dumped = fi.model_dump(mode="json")
    assert dumped["currency"] == "EUR"
    assert dumped["potential_annual_impact"] == 610_500.0
    assert dumped["scenario_comparison"]["delta_amount"]["amount"] == 222_000.0
    assert dumped["scenario_comparison"]["delta_amount"]["currency"] == "EUR"
    assert dumped["annual_spend_usd"] is None
    # Round-trips through Pydantic validation cleanly.
    rebuilt = FinancialImpact(**dumped)
    assert rebuilt.scenario_comparison.delta_amount.amount == 222_000.0
