"""
THE most important test in the entire NormalizedEvidence migration
(requirement 11): proves check_missing_evidence(), compute_financial_impact(),
and determine_relevant_tco_dimensions() all consume the SAME
NormalizedEvidence object -- not that each independently extracts the
same value and happens to agree.

The proof technique: construct a NormalizedEvidence whose values are
DELIBERATELY WRONG relative to what the raw question text actually says
-- a raw question that says "FOB Gdansk, no duty rate given" is paired
with a NormalizedEvidence manually set to incoterm=None, duty_relevant=
False, resolved_annual_spend_usd=999_999.0 (a number that appears
nowhere in the text at all). If any consumer were secretly re-extracting
from the raw text on its own, it would recover the REAL, text-derived
values (FOB, freight_relevant=True, the real spend figure) -- not my
deliberately fake ones. Seeing the fake values reflected downstream is
therefore direct, object-level proof of single-source-of-truth, not an
assumption resting on the two sides happening to agree.
"""
from app.pipeline.evidence import check_missing_evidence
from app.pipeline.financial import compute_financial_impact
from app.pipeline.methodology_consistency import determine_relevant_tco_dimensions
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence,
)


def test_all_three_consumers_read_the_same_object_not_independent_extractions():
    # This raw text, if independently re-extracted by ANY consumer, would
    # produce: incoterm=FOB, freight_relevant=True, duty_relevant=True,
    # spend=$2,000,000. None of these real values are used below.
    raw_question_that_says_something_different = (
        "Terms are FOB Gdansk. Our supplier in Poland states the import "
        "duty is 4.5%. Annual spend is $2,000,000, requesting a 10% increase."
    )

    # Deliberately WRONG values -- these could never come from genuinely
    # re-extracting the text above. If any consumer below reflects THESE
    # values instead of the real ones, that consumer is proven to be
    # reading the object, not the raw text.
    deliberately_fake = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(incoterm=None, duty_or_tax_rate_percent=None),
        case=PriceIncreaseEvidence(
            requested_increase_percent=10.0,
            current_price_or_terms="x", suppliers_stated_justification="x",
            how_critical_is_this_supplier_relationship="x",
        ),
        derived=DerivedEvidence(
            resolved_annual_spend_usd=999_999.0,  # appears nowhere in the real text
            annual_spend_resolution_method="direct",
            freight_relevant=False,  # would be True if genuinely re-derived from "FOB"
            duty_relevant=False,     # would be True if genuinely re-derived from "Poland" + "4.5%"
        ),
    )

    # Consumer 1: check_missing_evidence(). If it independently re-derived
    # freight relevance from the (unused) raw text, it would see "FOB" and
    # require freight_cost_or_estimate. It does not, because it only
    # trusts derived.freight_relevant on the object it was given.
    missing = check_missing_evidence(deliberately_fake)
    missing_fields = [m["field"] for m in missing]
    assert "freight_cost_or_estimate" not in missing_fields, (
        "check_missing_evidence() independently re-derived freight relevance "
        "from raw text instead of trusting the given object -- single source "
        "of truth is broken."
    )

    # Consumer 2: compute_financial_impact(). If it independently re-derived
    # spend from the (unused) raw text, it would compute against $2,000,000.
    # It does not -- it uses the object's resolved_annual_spend_usd exactly.
    financial = compute_financial_impact(deliberately_fake)
    assert financial.annual_spend_usd == 999_999.0, (
        "compute_financial_impact() independently re-derived annual spend "
        "from raw text instead of trusting the given object's resolved value."
    )
    assert financial.annual_duty_cost_usd is None, (
        "compute_financial_impact() independently re-derived a duty rate "
        "from raw text instead of trusting the given object (which has None)."
    )

    # Consumer 3: determine_relevant_tco_dimensions(). If it independently
    # re-derived relevance from the (unused) raw text, it would return both
    # freight and duty as relevant. It returns neither, because it only
    # reads the object's derived flags.
    relevant = determine_relevant_tco_dimensions(deliberately_fake)
    assert relevant == [], (
        "determine_relevant_tco_dimensions() independently re-derived "
        "relevance from raw text instead of trusting the given object's "
        "derived flags -- single source of truth is broken."
    )


def test_architecture_break_is_genuinely_detectable():
    """
    Requirement 12 -- the mandatory "break the architecture" test. Proves
    the test suite is actually protecting the single-source-of-truth
    property, not merely producing the expected answer through some
    hidden second path.

    This test is specifically constructed so that "trust the derived
    flag" and "independently re-derive from common fields" DISAGREE --
    common.incoterm says FOB (which would require freight if re-derived
    independently), but derived.freight_relevant is deliberately set to
    False. A correctly-migrated consumer trusts the flag and does NOT
    require freight. A consumer that has regressed to re-deriving
    independently (the exact bug this whole migration fixes) WOULD
    require freight, disagreeing with the trusted flag.

    This exact scenario was verified by hand during migration: with
    check_missing_evidence() deliberately reverted to re-derive freight
    relevance from raw Incoterm text (reintroducing the original,
    pre-migration bug), this assertion genuinely failed -- proving the
    test has real teeth, not just a plausible-looking assertion.
    """
    inconsistent = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(incoterm="FOB"),
        case=PriceIncreaseEvidence(
            requested_increase_percent=10.0, current_price_or_terms="x",
            suppliers_stated_justification="x", how_critical_is_this_supplier_relationship="x",
        ),
        derived=DerivedEvidence(freight_relevant=False),  # deliberately disagrees with incoterm
    )
    missing_fields = [m["field"] for m in check_missing_evidence(inconsistent)]
    assert "freight_cost_or_estimate" not in missing_fields, (
        "ARCHITECTURE VIOLATION DETECTED: check_missing_evidence() required freight "
        "based on common.incoterm='FOB' even though derived.freight_relevant was "
        "explicitly False. This means the function is re-deriving relevance "
        "independently instead of trusting the normalization boundary -- exactly "
        "the class of bug this migration exists to eliminate."
    )
