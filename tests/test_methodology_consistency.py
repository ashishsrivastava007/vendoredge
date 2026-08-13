"""
Permanent regression tests for the TCO methodology-consistency checker.
Built after a real, live case labeled its own approach "TCO/landed-cost
analysis" while genuinely missing an input (freight cost) that was
relevant and knowable given the stated Incoterm. This is the general,
durable fix: whenever a response claims a TCO-style methodology, verify
every relevant cost dimension is either addressed with real data or
explicitly named as a gap -- never silently dropped.
"""
from app.pipeline.methodology_consistency import (
    claims_tco_methodology, determine_relevant_tco_dimensions, check_tco_coverage,
)
from app.models import CommercialPosition, Confidence, ConfidenceFactor, FinancialImpact
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence

_CONF = Confidence(
    level="medium",
    factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
    derivation_note="n",
)


def test_claims_tco_methodology_detects_real_phrasings():
    assert claims_tco_methodology("This is a TCO/landed-cost analysis.")
    assert claims_tco_methodology("A total cost of ownership approach applies here.")
    assert not claims_tco_methodology("This is Kraljic-style category management.")
    assert not claims_tco_methodology(None)


def _make_normalized(freight_relevant, duty_relevant):
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(), case=PriceIncreaseEvidence(),
        derived=DerivedEvidence(freight_relevant=freight_relevant, duty_relevant=duty_relevant),
    )


def test_relevance_matches_the_exact_real_case():
    """FOB + a named region -- both freight and duty should be relevant,
    matching the real Kowalski/Poland case exactly. Tests
    determine_relevant_tco_dimensions()'s CONSUMPTION of the derived
    flags -- the derivation logic itself is covered separately in
    test_normalize_evidence.py."""
    normalized = _make_normalized(freight_relevant=True, duty_relevant=True)
    relevant = determine_relevant_tco_dimensions(normalized)
    assert "freight" in relevant
    assert "duty" in relevant


def test_ddp_correctly_excludes_freight_but_not_duty():
    normalized = _make_normalized(freight_relevant=False, duty_relevant=True)
    relevant = determine_relevant_tco_dimensions(normalized)
    assert "freight" not in relevant
    assert "duty" in relevant


def test_domestic_case_has_no_relevant_dimensions():
    normalized = _make_normalized(freight_relevant=False, duty_relevant=False)
    assert determine_relevant_tco_dimensions(normalized) == []


def test_coverage_check_reproduces_the_exact_original_bug():
    """Reconstructs the real response almost exactly: duty was covered,
    freight was genuinely missing from both the numbers and the text."""
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        financial_impact=FinancialImpact(
            annual_spend_usd=15361500, requested_change_percent=13,
            potential_annual_impact_usd=1996995, annual_duty_cost_usd=659145,
            note="...",
        ),
        reasoning="This is a TCO analysis considering duty and switching costs.",
        confidence=_CONF,
        assumptions=["No prior supplier history", "Duty applies fully to FOB shipments"],
        disconfirming_condition="...", decision_type="optimization",
    )
    uncovered = check_tco_coverage(position, ["freight", "duty"])
    assert uncovered == ["freight"]


def test_coverage_check_accepts_real_numbers_as_sufficient():
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        financial_impact=FinancialImpact(
            annual_spend_usd=1000000, requested_change_percent=10,
            potential_annual_impact_usd=100000,
            annual_duty_cost_usd=45000, annual_freight_cost_usd=122500,
            note="...",
        ),
        reasoning="...", confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    assert check_tco_coverage(position, ["freight", "duty"]) == []


def test_coverage_check_accepts_an_honest_flag_without_a_hard_number():
    """Honesty satisfies the check just as well as a real number does --
    the point is never silently dropping the dimension, not forcing a
    number that may not be available."""
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        reasoning="...", confidence=_CONF,
        assumptions=["Freight cost not available; landed cost may be understated without it."],
        disconfirming_condition="...", decision_type="optimization",
    )
    assert check_tco_coverage(position, ["freight"]) == []


def test_coverage_check_returns_empty_for_no_relevant_dimensions():
    """A position with no financial data at all is still fine if nothing
    was ever flagged as relevant in the first place."""
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        reasoning="...", confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    assert check_tco_coverage(position, []) == []
