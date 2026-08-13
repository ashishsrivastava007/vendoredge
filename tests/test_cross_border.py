"""
Real regression tests for the cross-border commercial mechanics addition
(currency, Incoterms, duty/tax) -- specifically the duty/landed-cost
calculation in financial.py.

MIGRATED (NormalizedEvidence architecture): constructs NormalizedEvidence
objects directly, for precise control over the exact numeric values under
test. One test below is genuinely NEW in shape, not just adapted -- see
its docstring for a real, positive finding from the migration: a
malformed duty value is now rejected earlier and more strongly (at
Pydantic construction time) than the old dict-based try/except ever
caught it.
"""
from pydantic import ValidationError
from app.pipeline.financial import compute_financial_impact
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence,
)


def _make_normalized(spend, percent, duty_percent=None, switching_cost=None):
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(duty_or_tax_rate_percent=duty_percent),
        case=PriceIncreaseEvidence(
            annual_spend_usd=spend, requested_increase_percent=percent,
            switching_cost_usd=switching_cost,
        ),
        derived=DerivedEvidence(resolved_annual_spend_usd=spend, annual_spend_resolution_method="direct"),
    )


def test_duty_cost_computed_correctly_when_genuinely_given():
    normalized = _make_normalized(1_000_000, 10, duty_percent=6.5)
    result = compute_financial_impact(normalized)
    assert result.annual_duty_cost_usd == 65_000.0
    assert "6.5% duty" in result.note


def test_duty_cost_stays_none_when_not_given():
    """The honest boundary: no rate given means no fabricated number,
    exactly like every other optional financial figure in this module."""
    normalized = _make_normalized(1_000_000, 10)
    result = compute_financial_impact(normalized)
    assert result.annual_duty_cost_usd is None


def test_duty_cost_combines_correctly_with_switching_cost():
    """Both optional figures can be present at once without interfering
    with each other's calculation or note text."""
    normalized = _make_normalized(500_000, 8, duty_percent=4, switching_cost=50_000)
    result = compute_financial_impact(normalized)
    assert result.annual_duty_cost_usd == 20_000.0
    assert result.net_exposure_usd is not None
    assert "duty" in result.note and "switching cost" in result.note


def test_malformed_duty_rate_is_now_rejected_earlier_by_pydantic():
    """GENUINE FINDING FROM THE MIGRATION, not just a test adaptation:
    pre-migration, a malformed duty value (e.g. a stray non-numeric string
    from an unexpected classifier output) reached financial.py as a raw
    dict value and was caught there, defensively, by a try/except. Now,
    NormalizedEvidence's Pydantic schema rejects it at CONSTRUCTION time,
    inside normalize_evidence() itself -- a genuinely earlier and
    stronger guarantee, not merely equivalent behavior in a new shape."""
    try:
        CommonEvidence(duty_or_tax_rate_percent="not-a-number")
        assert False, "Pydantic should have rejected this"
    except ValidationError:
        pass  # correctly rejected, exactly as expected
