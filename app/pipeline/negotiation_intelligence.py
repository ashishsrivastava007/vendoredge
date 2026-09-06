"""Phase 4 — Negotiation Intelligence.

Builds an evidence-backed negotiation operating brief from the validated
CommercialPosition. No LLM call and no new facts. The module turns existing
negotiation dimensions into give/get rules, response scenarios, escalation
triggers, and a concise preparation checklist.
"""
from __future__ import annotations
from typing import Any
from app.models import CommercialPosition


def _clean(v: Any) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def build_negotiation_intelligence(position: CommercialPosition) -> dict[str, Any]:
    dims = position.negotiation_dimensions or []
    audit = position.decision_audit
    blockers = [str(x).strip() for x in (audit.uncertainties if audit else []) if str(x).strip()][:5]

    give_get = []
    for d in dims[:6]:
        give_get.append({
            "dimension": str(d.dimension),
            "buyer_opening": str(d.opening_ask),
            "buyer_target": str(d.target_outcome),
            "buyer_boundary": str(d.walk_away),
            "rule": "Trade this dimension only for a measurable supplier concession; do not give it away unconditionally.",
        })

    response_scenarios = []
    for d in dims[:5]:
        response_scenarios.append({
            "trigger": f"Supplier resists on {d.dimension}",
            "buyer_move": f"Hold the stated target for {d.dimension}; ask what equivalent commercial value the supplier can provide.",
            "status": "SCENARIO_NOT_PREDICTION",
        })
    if position.opening_position:
        response_scenarios.insert(0, {
            "trigger": "Supplier challenges the opening position",
            "buyer_move": "Ask for the evidence supporting the supplier's counter-position before trading value.",
            "status": "SCENARIO_NOT_PREDICTION",
        })

    escalation = []
    if blockers:
        escalation.extend({"trigger": b, "action": "Resolve or explicitly accept the evidence gap before making a consequential concession."} for b in blockers)
    if position.walk_away_threshold:
        escalation.append({"trigger": f"Negotiation reaches the stated boundary: {position.walk_away_threshold}", "action": "Stop trading beyond the approved boundary and escalate for a new decision."})
    if not escalation:
        escalation.append({"trigger": "Supplier asks for a concession outside the captured position", "action": "Pause and re-run the commercial decision before committing."})

    checklist = [
        "Confirm the evidence supporting the opening position.",
        "Know the target and walk-away boundary before the meeting.",
        "Lead with the strongest evidenced commercial point.",
        "Trade concessions conditionally rather than giving them away.",
        "Capture the supplier response as new evidence after the interaction.",
    ]

    readiness = "READY" if not blockers else "CONDITIONAL"
    if audit and audit.evidence_integrity_status == "CONTRADICTED":
        readiness = "HOLD_FOR_EVIDENCE_CONFLICT"

    return {
        "available": True,
        "version": "R31.4",
        "readiness": readiness,
        "objective": position.recommendation,
        "opening_position": position.opening_position,
        "target": next((d.target_outcome for d in dims if d.target_outcome), None),
        "walk_away": position.walk_away_threshold,
        "give_get_matrix": give_get,
        "response_scenarios": response_scenarios[:6],
        "escalation_triggers": escalation[:6],
        "preparation_checklist": checklist,
        "evidence_to_lead_with": (position.negotiation_playbook.evidence_to_lead_with if position.negotiation_playbook else [])[:5],
        "questions_to_resolve": (position.negotiation_playbook.questions_to_resolve if position.negotiation_playbook else [])[:6],
        "method": "Deterministic negotiation operating brief assembled from the validated position; supplier reactions are scenarios, not predictions.",
    }
