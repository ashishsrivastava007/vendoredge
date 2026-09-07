"""Deterministic safety helpers for LLM-produced CommercialPosition objects."""
from __future__ import annotations

from app import caps

# Every bounded list on CommercialPosition that may be produced by an LLM.
_BOUNDED_LISTS = {
    "commercial_insights": caps.MAX_COMMERCIAL_INSIGHTS,
    "cost_driver_comparison": caps.MAX_COST_DRIVERS,
    "key_figures": caps.MAX_KEY_FIGURES,
    "supplier_comparison": caps.MAX_SUPPLIERS,
    "negotiation_dimensions": caps.MAX_NEGOTIATION_DIMENSIONS,
    "negotiation_talk_track": caps.MAX_TALK_TRACK_MOVES,
    "financial_scenarios": caps.MAX_FINANCIAL_SCENARIOS,
    "assumptions": caps.MAX_ASSUMPTIONS,
}


def normalize_bounded_position_lists(raw: dict) -> dict:
    """Enforce all explicit CommercialPosition list caps before Pydantic validation.

    Prompts are probabilistic; schema limits are deterministic. A model returning
    one extra item must never turn an otherwise useful answer into a user-facing
    500. This function only removes over-cap items and preserves model ordering.
    Fields without an explicit cap are left untouched.
    """
    normalized = dict(raw)
    for field, maximum in _BOUNDED_LISTS.items():
        value = normalized.get(field)
        if isinstance(value, list) and len(value) > maximum:
            normalized[field] = value[:maximum]
    return normalized
