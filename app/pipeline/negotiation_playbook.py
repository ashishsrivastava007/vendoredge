"""Release 13: deterministic negotiation playbook.

Builds a meeting-ready negotiation plan from the already validated commercial
position. No LLM call, no new assumptions, and no re-ranking of the decision.
"""
from __future__ import annotations
from typing import Any
from app.models import CommercialPosition


def _moves(position: CommercialPosition) -> list[dict[str, str]]:
    moves: list[dict[str, str]] = []
    for m in (position.negotiation_talk_track or [])[:6]:
        moves.append({"trigger": str(m.trigger), "say": str(m.say), "purpose": str(m.purpose)})
    return moves


def build_negotiation_playbook(position: CommercialPosition) -> dict[str, Any]:
    dims = []
    for d in (position.negotiation_dimensions or [])[:8]:
        dims.append({"dimension": str(d.dimension), "opening": str(d.opening), "target": str(d.target), "walk_away": str(d.walk_away)})
    suppliers = []
    for s in (position.supplier_comparison or [])[:8]:
        suppliers.append({"supplier": str(s.supplier), "price": str(s.price), "quality": str(s.quality), "lead_time": str(s.lead_time)})
    evidence = []
    audit = position.decision_audit
    if audit:
        evidence.extend(str(x) for x in audit.material_evidence[:5])
    questions = []
    for x in (audit.uncertainties[:5] if audit else []):
        questions.append(str(x))
    if position.disconfirming_condition:
        questions.append(position.disconfirming_condition)
    return {
        "available": True,
        "objective": position.recommendation,
        "opening_position": position.opening_position,
        "target": next((d["target"] for d in dims if d["target"]), None),
        "walk_away": position.walk_away_threshold,
        "dimensions": dims,
        "talk_track": _moves(position),
        "supplier_facts": suppliers,
        "evidence_to_lead_with": evidence[:5],
        "questions_to_resolve": questions[:6],
        "red_lines": [d["walk_away"] for d in dims if d["walk_away"]][:5],
        "method": "Deterministic meeting aid assembled only from the validated decision; it does not create supplier facts or alter the recommendation.",
    }
