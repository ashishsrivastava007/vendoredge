"""
Phase 6 / R41 -- Category archetype detection.

Determines which analytical lenses are relevant to a category, based
ONLY on evidence actually present in the case -- never guessed from a
category name, never defaulted to "industrial" just because that's
the most common shape seen so far. If the evidence doesn't clearly
indicate an archetype, the honest answer is "not established", and the
strategy proceeds without archetype-specific emphasis rather than
forcing a guess.

This is deliberately a SMALL, keyword-based classifier over the two
evidence sources that actually carry archetype signal today:
- market_driver_claims[].driver (e.g. "steel", "labour", "fuel")
- whether qualification/capacity evidence exists at all (an
  industrial/component signal -- these concepts only make sense for a
  physical, qualifiable item)

Five archetypes are supported, matching the phase brief exactly. A
sixth, implicit outcome is "not established" -- this is not a bug, it
is the correct result for the majority of cases, which don't state
enough to classify confidently.
"""
from __future__ import annotations
from typing import Any

_ARCHETYPE_DRIVER_KEYWORDS = {
    "industrial_component": {"steel", "alloy", "aluminum", "aluminium", "resin", "specification", "tooling"},
    "commodity_raw_material": {"commodity", "energy", "electricity", "gas", "fx", "indexation", "cyclical"},
    "labour_intensive_services": {"labour", "labor", "wage", "wages", "attrition", "utilisation", "utilization"},
    "technology_it": {"cloud", "technology cycle", "ai", "ip", "software licensing", "knowledge dependency"},
    "logistics_transport": {"fuel", "freight", "lanes", "equipment", "seasonality", "shipping"},
}


def detect_archetype(kernel: dict[str, Any]) -> dict[str, Any]:
    """Returns {archetype, basis} where archetype is one of the five
    known archetype keys or None, and basis explains, in plain terms,
    what evidence led to that conclusion (or why none was reached) --
    so the classification itself is auditable, not a silent label."""
    claims = kernel.get("case", {}).get("market_driver_claims") or []
    driver_names = {str(c.get("driver", "")).strip().lower() for c in claims}

    scores: dict[str, int] = {}
    for archetype, keywords in _ARCHETYPE_DRIVER_KEYWORDS.items():
        hits = {d for d in driver_names if any(kw in d for kw in keywords)}
        if hits:
            scores[archetype] = len(hits)

    has_qualification_or_capacity_evidence = any(
        s.get("qualification") or s.get("capacity") for s in kernel.get("suppliers", [])
    )

    if scores:
        best = max(scores, key=lambda a: scores[a])
        # A tie between two genuinely different archetypes is exactly
        # the kind of ambiguity that must not be silently resolved --
        # report it as unestablished rather than picking one arbitrarily.
        tied = [a for a, s in scores.items() if s == scores[best]]
        if len(tied) > 1:
            return {"archetype": None, "basis": f"Market-driver evidence points to more than one archetype ({', '.join(sorted(tied))}) with equal support -- not resolved automatically."}
        matched_drivers = [d for d in driver_names if any(kw in d for kw in _ARCHETYPE_DRIVER_KEYWORDS[best])]
        return {"archetype": best, "basis": f"Based on stated market drivers: {', '.join(matched_drivers)}."}

    if has_qualification_or_capacity_evidence:
        return {"archetype": "industrial_component", "basis": "Based on supplier qualification/capacity evidence present in this case -- these concepts are specific to a physical, qualifiable item."}

    return {"archetype": None, "basis": "Not established from available evidence -- no market-driver or qualification/capacity evidence in this case indicates a specific archetype."}


# The lens keywords each archetype should look for when deciding what
# to emphasize -- used only to SELECT which already-real evidence to
# highlight, never to invent evidence that isn't there.
ARCHETYPE_LENS_LABELS = {
    "industrial_component": "material cost, specification, qualification, and capacity",
    "commodity_raw_material": "commodity price movement, energy, FX, and indexation",
    "labour_intensive_services": "labour cost, wages, attrition, and utilisation",
    "technology_it": "technology cycle, licensing, and transition cost",
    "logistics_transport": "fuel, freight, lane capacity, and seasonality",
}
