"""
Quality Gate Guarantee #3 — No Internal Contradiction Guarantee.

Direct fix for the second confirmed Case 5 audit finding: the response's
headline said "Financial Impact: Not calculable from evidence given"
while its own scenario table, two sections later, used the exact same
inputs to compute a real $4,345,200 figure. The first audit praised this
as good evidence discipline; the deeper, raw-evidence audit showed it was
actually a genuine internal contradiction -- the guaranteed
financial_impact WAS calculable (the code computed it correctly), but the
model's own prose claimed otherwise.

This is deliberately narrow and deterministic, not a vague "check
everything sounds consistent" pass -- it checks specific, real,
previously-confirmed contradiction shapes. Broader reconciliation (of
methodology claims, confidence-vs-evidence) is handled by the separate,
already-existing methodology contracts and the new confidence gate
(Guarantee #5), rather than folded into one enormous, hard-to-test
function.
"""
from app.models import CommercialPosition

_NOT_CALCULABLE_PHRASES = [
    "not calculable", "cannot be calculated", "unable to calculate",
    "financial impact is not available", "no financial impact could be determined",
]


def check_financial_contradiction(position: CommercialPosition) -> list[str]:
    """
    Returns a list of contradiction descriptions (empty if none). The
    exact, confirmed Case 5 pattern: financial_impact is a real,
    guaranteed, code-computed object (never fabricated -- see Hard Rule 1
    and financial.py), so if it's genuinely present, no part of the
    response's own prose should claim the impact "cannot be calculated."
    That claim was true before the guaranteed calculation ran; if it's
    still present in the final text after a real number exists, the
    prose is stale or contradicts the guarantee.
    """
    contradictions = []
    if position.financial_impact is not None:
        text_to_check = " ".join(filter(None, [
            position.reasoning, position.recommendation,
        ])).lower()
        for phrase in _NOT_CALCULABLE_PHRASES:
            if phrase in text_to_check:
                contradictions.append(
                    f"financial_impact is present (a real, guaranteed figure of "
                    f"${position.financial_impact.potential_annual_impact_usd:,.0f} was computed), "
                    f"but the response's own text contains the phrase '{phrase}', directly "
                    f"contradicting the guaranteed calculation."
                )
                break  # one finding is enough to trigger correction; no need to pile on

    return contradictions


def check_scenario_table_contradiction(position: CommercialPosition) -> list[str]:
    """
    A second, related but distinct check: if financial_scenarios contains
    real, populated entries (meaning the model itself successfully
    reasoned through multiple real dollar figures), the same
    "not calculable" language anywhere in the response is contradictory
    for the same reason -- the scenarios prove the underlying data was
    sufficient.
    """
    contradictions = []
    if position.financial_scenarios:
        text_to_check = " ".join(filter(None, [
            position.reasoning, position.recommendation,
        ])).lower()
        for phrase in _NOT_CALCULABLE_PHRASES:
            if phrase in text_to_check:
                contradictions.append(
                    f"financial_scenarios contains {len(position.financial_scenarios)} real, "
                    f"populated entries, but the response's own text contains the phrase "
                    f"'{phrase}' -- if scenarios could be computed, the headline claim that "
                    f"nothing could be calculated is contradictory."
                )
                break

    return contradictions


def check_all_contradictions(position: CommercialPosition) -> list[str]:
    """Runs every registered contradiction check and returns the combined
    list -- the single entry point _run_reasoning actually calls."""
    return check_financial_contradiction(position) + check_scenario_table_contradiction(position)
