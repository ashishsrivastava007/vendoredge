"""Phase 9 — Supplier Response Execution, safely bounded.

VendorEdge prepares the work, but consequential external actions remain behind
an explicit human approval boundary. This module is deterministic: it only
uses the validated CommercialPosition and never invents facts or sends anything.
"""
from __future__ import annotations
from typing import Any
from app.models import CommercialPosition


def _text(v: Any) -> str:
    return str(v or "").strip()


def build_agentic_workflow(position: CommercialPosition) -> dict[str, Any]:
    """Build an execution-ready work queue from the existing decision spine."""
    actions: list[dict[str, Any]] = []
    evidence_status = position.decision_audit.evidence_integrity_status if position.decision_audit else "UNKNOWN"
    blocked = bool(position.control_tower and position.control_tower.critical_before_action)

    actions.append({
        "id": "approve-commercial-position",
        "stage": "DECIDE",
        "title": "Approve commercial position",
        "status": "blocked" if blocked else "approval_required",
        "approval_required": True,
        "prepared_output": _text(position.recommendation),
        "evidence_integrity": evidence_status,
        "side_effect": "authorizes downstream preparation only; no supplier contact",
    })

    if position.negotiation_playbook or position.negotiation_intelligence:
        np = position.negotiation_intelligence or {}
        play = position.negotiation_playbook
        objective = _text(np.get("objective")) or _text(getattr(play, "objective", ""))
        opening = _text(np.get("opening_position")) or _text(getattr(play, "opening_position", ""))
        target = _text(np.get("target")) or _text(getattr(play, "target", ""))
        walk = _text(np.get("walk_away")) or _text(getattr(play, "walk_away", ""))
        actions.append({
            "id": "prepare-supplier-negotiation",
            "stage": "NEGOTIATE",
            "title": "Prepare supplier negotiation package",
            "status": "approval_required",
            "approval_required": True,
            "prepared_output": {
                "objective": objective,
                "opening": opening,
                "target": target,
                "walk_away": walk,
            },
            "side_effect": "draft only; no message is sent",
        })

        # The output is explicitly a draft, not a factual transcript.
        actions.append({
            "id": "draft-supplier-message",
            "stage": "EXECUTE",
            "title": "Draft supplier response",
            "status": "approval_required",
            "approval_required": True,
            "prepared_output": _draft_supplier_message(position, objective, opening),
            "side_effect": "draft only; sending requires an external integration and human approval",
        })

    if blocked:
        actions.append({
            "id": "resolve-precommit-blockers",
            "stage": "VALIDATE",
            "title": "Resolve pre-commit blockers",
            "status": "blocked_until_resolved",
            "approval_required": True,
            "prepared_output": list(position.control_tower.critical_before_action),
            "side_effect": "none",
        })

    actions.append({
        "id": "record-outcome",
        "stage": "LEARN",
        "title": "Record commercial outcome",
        "status": "not_started",
        "approval_required": False,
        "prepared_output": "Capture agreed terms, recommendation adherence, realized value and surprises.",
        "side_effect": "none",
    })

    return {
        "available": True,
        "version": "R36.1",
        "mode": "BOUNDED_AGENTIC_WORKFLOW",
        "actions": actions[:6],
        "agent_does": ["organizes work", "prepares negotiation package", "drafts supplier response", "surfaces blockers"],
        "human_approves": ["supplier contact", "commercial commitment", "contract or PO change", "spend commitment"],
        "external_side_effects": False,
        "execution_boundary": "VendorEdge prepares and records approval state; external execution is not performed by this workflow.",
        "trust_note": "Prepared outputs are derived from the validated decision. Draft language is not evidence and must be reviewed before sending.",
    }


def _draft_supplier_message(position: CommercialPosition, objective: str, opening: str) -> str:
    supplier = "the supplier"
    if position.supplier_name:
        supplier = position.supplier_name
    lines = [f"Subject: Commercial discussion — {supplier}", "", "Dear Supplier,", ""]
    if opening:
        lines.append(f"We would like to discuss the requested commercial change. Our current position is: {opening}.")
    else:
        lines.append("We would like to discuss the requested commercial change before confirming acceptance.")
    if objective:
        lines.append(f"Our objective is to reach an outcome consistent with the agreed commercial position: {objective}.")
    lines += ["Please share the supporting commercial detail and any alternative proposal you would like us to consider.", "", "Regards,"]
    return "\n".join(lines)
