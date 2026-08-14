"""Deterministic, approval-gated action planning for completed decisions.

This is deliberately an execution *control layer*, not an autonomous actor.
It converts an approved commercial position into explicit next actions while
keeping external side effects behind a human approval boundary.
"""
from __future__ import annotations
from app.models import CommercialPosition


def build_action_plan(position: CommercialPosition) -> dict:
    ct = position.control_tower
    actions: list[dict[str, object]] = []

    actions.append({
        "id": "internal-approval",
        "stage": "DECIDE",
        "title": "Confirm commercial position internally",
        "owner": "procurement",
        "status": "approval_required",
        "approval_required": True,
        "instruction": position.recommendation,
        "evidence": position.decision_audit.evidence_integrity_status if position.decision_audit else "UNKNOWN",
    })

    if position.negotiation_playbook:
        actions.append({
            "id": "supplier-conversation",
            "stage": "NEGOTIATE",
            "title": "Run supplier negotiation",
            "owner": "procurement",
            "status": "approval_required",
            "approval_required": True,
            "instruction": position.negotiation_playbook.objective,
            "opening": position.negotiation_playbook.opening_position,
            "target": position.negotiation_playbook.target,
            "walk_away": position.negotiation_playbook.walk_away,
        })

    if ct and ct.critical_before_action:
        actions.append({
            "id": "resolve-critical-evidence",
            "stage": "VALIDATE",
            "title": "Resolve critical evidence before commitment",
            "owner": "procurement",
            "status": "blocked_until_resolved",
            "approval_required": True,
            "instruction": "Resolve the following before committing: " + "; ".join(ct.critical_before_action),
        })

    actions.append({
        "id": "record-outcome",
        "stage": "LEARN",
        "title": "Record the commercial outcome",
        "owner": "decision-owner",
        "status": "not_started",
        "approval_required": False,
        "instruction": "Record what was agreed, whether the recommendation was followed, what held up, and what surprised you.",
    })

    return {
        "mode": "approval_gated",
        "external_side_effects": False,
        "human_approval_required": True,
        "actions": actions[:5],
        "safety_note": "VendorEdge prepares actions but does not email suppliers, change contracts, create POs, or commit spend without an explicit external approval/integration layer.",
    }
