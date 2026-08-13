"""
Methodology-consistency checking. Built after a real, live finding: a
response labeled its own approach "TCO/landed-cost analysis" while
quietly omitting an input (freight cost) that was genuinely relevant and
genuinely knowable. The freight-specific gap is now fixed directly (see
evidence.py and financial.py) -- this module is the general, durable
fix: whenever a response claims a TCO-style methodology, check that every
cost dimension the EVIDENCE actually makes relevant is either addressed
with real data or explicitly named as a gap, not silently dropped.

Deliberately narrow for now: only checks TCO-style claims. Other named
methodologies (Kraljic, BATNA-strengthening) are real candidates for the
same pattern later, once this one is proven, not built speculatively now.
"""
from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence

# Real, distinct signal words for whether a response is claiming a
# TCO-style approach -- checked against methodology_applied, case
# insensitive. Kept narrow and specific rather than a loose keyword match,
# since a false trigger here would create friction on cases that never
# claimed this discipline in the first place.
_TCO_SIGNAL_PHRASES = ["total cost of ownership", "tco", "landed cost", "landed-cost"]

# Each relevant dimension maps to: the evidence condition that makes it
# genuinely relevant, and the words that count as "addressed" if they
# appear in reasoning or assumptions even without a hard number attached.
_DIMENSION_KEYWORDS = {
    "freight": ["freight", "transport cost", "shipping cost"],
    "duty": ["duty", "import tax", "tariff", "customs"],
}


def claims_tco_methodology(methodology_applied: str | None) -> bool:
    if not methodology_applied:
        return False
    lowered = methodology_applied.lower()
    return any(phrase in lowered for phrase in _TCO_SIGNAL_PHRASES)


def determine_relevant_tco_dimensions(normalized: NormalizedEvidence) -> list[str]:
    """
    Reads normalized.derived.freight_relevant and .duty_relevant directly
    -- both computed exactly once, upstream, in normalize_evidence(). This
    function no longer independently re-derives relevance from raw
    Incoterm/region/currency text. This is the structural fix ensuring
    the prose (Hard Rule 18) and the guaranteed calculation are provably
    looking at the same normalized facts, not two separate reads of a
    similar-but-not-identical dict.

    Deliberately scoped to freight and duty only, matching the original
    design decision to exclude switching cost (no equally reliable
    deterministic relevance signal exists for it yet).
    """
    relevant = []
    if normalized.derived.freight_relevant:
        relevant.append("freight")
    if normalized.derived.duty_relevant:
        relevant.append("duty")
    return relevant


def check_tco_coverage(position: CommercialPosition, relevant_dimensions: list[str]) -> list[str]:
    """
    Returns the list of relevant dimensions that are genuinely uncovered --
    neither reflected in the guaranteed financial_impact numbers nor named
    explicitly in assumptions. Empty list means full, honest coverage.
    """
    if not relevant_dimensions:
        return []

    financial = position.financial_impact
    assumptions_text = " ".join(position.assumptions or []).lower()
    reasoning_text = (position.reasoning or "").lower()

    uncovered = []
    for dimension in relevant_dimensions:
        keywords = _DIMENSION_KEYWORDS[dimension]

        has_real_number = False
        if financial is not None:
            if dimension == "freight" and financial.annual_freight_cost_usd is not None:
                has_real_number = True
            if dimension == "duty" and financial.annual_duty_cost_usd is not None:
                has_real_number = True

        explicitly_named = any(
            kw in assumptions_text or kw in reasoning_text for kw in keywords
        )

        if not has_real_number and not explicitly_named:
            uncovered.append(dimension)

    return uncovered


# ---------------------------------------------------------------------------
# Kraljic Matrix contract
#
# Deliberately different in kind from the TCO check above: TCO's coverage
# check can lean on real, structured numbers (financial_impact fields) as
# strong evidence. Kraljic has no equivalent structured field -- "was
# business impact assessed" is inherently a question about whether the
# REASONING TEXT actually did the work, not a number to check. This is a
# genuinely softer, keyword-presence check, and that limit is honest, not
# hidden: it can tell whether the topic was addressed, not whether the
# assessment was good. Quality of the explanation is left to the prompt's
# own instruction (Hard Rule text), not a separate deterministic check --
# verifying explanation QUALITY would need another AI judgment call, which
# isn't genuinely deterministic, the same reasoning that kept
# switching-cost detection out of the TCO check above.
#
# Deliberately does NOT check for an exact quadrant word (Strategic,
# Leverage, Bottleneck, Non-critical) -- checking that the two required
# assessments were genuinely done is more robust than checking exact
# wording, which would make the check fragile to how the model happens to
# phrase things.
# ---------------------------------------------------------------------------

_KRALJIC_SIGNAL_PHRASES = ["kraljic"]

_BUSINESS_IMPACT_KEYWORDS = [
    "annual spend", "critical", "criticality", "downtime", "disruption",
    "business impact", "safety-critical", "safety critical",
]

_SUPPLY_RISK_KEYWORDS = [
    "supply risk", "sole source", "sole-source", "single source", "single-source",
    "alternative supplier", "switching", "qualification", "capacity constraint",
    "scarce", "scarcity", "lead time", "dependency", "dependent on",
]


def claims_kraljic_methodology(methodology_applied: str | None) -> bool:
    if not methodology_applied:
        return False
    lowered = methodology_applied.lower()
    return any(phrase in lowered for phrase in _KRALJIC_SIGNAL_PHRASES)


def check_kraljic_reasoning_coverage(position: CommercialPosition) -> list[str]:
    """
    Returns which of the two required Kraljic assessments are genuinely
    missing from the reasoning text -- 'business_impact', 'supply_risk',
    or both. Checked against "reasoning" (the full prose), not
    "methodology_applied" (a one-sentence, character-capped label too
    short to contain a real assessment).
    """
    reasoning_text = (position.reasoning or "").lower()

    missing = []
    if not any(kw in reasoning_text for kw in _BUSINESS_IMPACT_KEYWORDS):
        missing.append("business_impact")
    if not any(kw in reasoning_text for kw in _SUPPLY_RISK_KEYWORDS):
        missing.append("supply_risk")

    return missing
