"""
Permanent regression tests for the Kraljic Matrix contract. Checks
reasoning PRESENCE (were both required dimensions genuinely evaluated),
not exact wording (no check for the literal word "Strategic" or
"Bottleneck") -- a deliberate design choice for robustness, since checking
exact phrasing would make this fragile to how the model happens to word
things.
"""
from app.pipeline.methodology_consistency import (
    claims_kraljic_methodology, check_kraljic_reasoning_coverage,
)
from app.models import CommercialPosition, Confidence, ConfidenceFactor

_CONF = Confidence(
    level="medium",
    factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
    derivation_note="n",
)


def test_claims_kraljic_detects_real_phrasing():
    assert claims_kraljic_methodology("This is a Kraljic-style approach.")
    assert claims_kraljic_methodology("Kraljic Matrix category management applies here.")
    assert not claims_kraljic_methodology("This is a TCO analysis.")
    assert not claims_kraljic_methodology(None)


def test_real_kowalski_reasoning_correctly_passes():
    """The exact real reasoning text from tonight's actual live response --
    the honest, real-world validation that this check doesn't just reject
    everything."""
    real_reasoning = (
        "The claimed steel, energy, and labour increases each run near double the "
        "independently verified indices, and Kowalski has offered no audited cost "
        "breakdown linking these claims to actual unit cost. Legal's insistence on "
        "independently-published indexation is the right commercial guardrail here. "
        "Operationally, Kowalski's current reliability edge and Meridian's longer lead "
        "time mean an abrupt full switch would be genuinely risky for a safety-critical "
        "component with only a 5-week buffer; a phased ramp matches Engineering's own "
        "recommendation."
    )
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        methodology_applied="This is a TCO/landed-cost analysis combined with Kraljic-style dual-source risk mitigation.",
        reasoning=real_reasoning, confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    assert check_kraljic_reasoning_coverage(position) == []


def test_fully_shallow_claim_is_caught_on_both_dimensions():
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        methodology_applied="This is Kraljic-style category management.",
        reasoning="The price increase seems reasonable given market conditions.",
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    missing = check_kraljic_reasoning_coverage(position)
    assert set(missing) == {"business_impact", "supply_risk"}


def test_partially_shallow_claim_identifies_the_specific_gap():
    """Only business impact discussed -- supply risk genuinely missing."""
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        methodology_applied="Kraljic-style approach applied here.",
        reasoning="This component is safety-critical with significant downtime cost if disrupted.",
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    assert check_kraljic_reasoning_coverage(position) == ["supply_risk"]


def test_no_kraljic_claim_means_no_check_runs():
    """A response that never claims Kraljic shouldn't be held to its
    evidentiary standard at all -- claims_kraljic_methodology gates this."""
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        methodology_applied="This is a simple price comparison.",
        reasoning="Nothing about impact or risk here at all.",
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    assert not claims_kraljic_methodology(position.methodology_applied)
