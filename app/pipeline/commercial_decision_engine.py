"""Phase 3 — Commercial Decision Engine.

Deterministic decision contract sitting above the validated VendorEdge layers.
It does not create facts or replace the reasoning model. It converts the final
CommercialPosition into one operational decision spine that a buyer can use:
DECIDE / PROTECT / ASK / REVIEW, economics, evidence posture, alternatives,
blockers, next move and reversal triggers.
"""
from __future__ import annotations
from typing import Any

from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence

VERSION = "R31.1"
MAX = 6


def _dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value if isinstance(value, dict) else {}


def _mode(position: CommercialPosition) -> tuple[str, str]:
    uncertainty = _dict(position.decision_under_uncertainty)
    mode = str(uncertainty.get("mode") or "REVIEW").upper()
    if mode == "DECIDE":
        return "DECIDE", "Evidence supports action within the stated conditions."
    if mode == "PROTECT":
        return "PROTECT", "Act only with explicit guardrails while uncertainty remains."
    if mode == "ASK":
        return "ASK", "Resolve the decision-critical question before an irreversible commitment."
    return "REVIEW", "Review the validated evidence before committing."


def _evidence_status(position: CommercialPosition) -> str:
    trust = _dict(position.trust_engine)
    integrity = str(trust.get("decision_integrity") or "")
    if integrity == "REVIEW_REQUIRED":
        return "CONFLICT"
    counts = trust.get("counts") or {}
    if int(counts.get("UNKNOWN", 0) or 0) > 0:
        return "GAPS"
    if int(counts.get("VERIFIED", 0) or 0) > 0:
        return "GROUNDED"
    return "LIMITED"


def _economics(position: CommercialPosition) -> dict[str, Any]:
    financial = _dict(position.financial_impact)
    cockpit = _dict(position.decision_cockpit)
    econ = cockpit.get("economics") or {}
    if financial:
        return {
            "available": True,
            "annual_spend_usd": financial.get("annual_spend_usd"),
            "potential_annual_impact_usd": financial.get("potential_annual_impact_usd"),
            "net_exposure_usd": financial.get("net_exposure_usd"),
            "headline": econ.get("headline") or financial.get("note"),
            "basis": "Deterministic VendorEdge financial calculation from normalized evidence.",
        }
    if econ.get("available"):
        return {"available": True, "headline": econ.get("headline"), "basis": econ.get("basis")}
    return {"available": False, "headline": "Not safely quantified", "basis": "Required comparable monetary inputs are not available."}


def build_commercial_decision_engine(normalized: NormalizedEvidence, position: CommercialPosition) -> dict[str, Any]:
    """Build the operational decision spine from already validated outputs."""
    mode, mode_reason = _mode(position)
    uncertainty = _dict(position.decision_under_uncertainty)
    tower = _dict(position.control_tower)
    audit = _dict(position.decision_audit)
    alternatives = _dict(position.alternative_analysis)
    playbook = _dict(position.negotiation_playbook)
    passport = _dict(position.decision_passport)

    blockers = list((tower.get("critical_before_action") or [])[:MAX])
    unknowns = list((uncertainty.get("unknowns") or passport.get("unknowns") or [])[:MAX])
    changers = list((uncertainty.get("review_trigger") and [uncertainty["review_trigger"]]) or [])
    changers += list((passport.get("decision_changers") or [])[:MAX])
    # Preserve order while removing duplicate triggers.
    seen = set(); unique_changers = []
    for item in changers:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text); unique_changers.append(text)

    next_move = passport.get("next_move") or playbook.get("opening_position") or position.opening_position
    if not next_move:
        next_move = "Review the validated recommendation and act within the stated conditions."

    actions = list((tower.get("action_items") or [])[:5])
    if not actions:
        actions = [{"action": "Review decision", "owner": "buyer", "timing": "before action"}]

    return {
        "title": "VendorEdge Commercial Decision Engine",
        "version": VERSION,
        "status": "READY" if mode == "DECIDE" and _evidence_status(position) != "CONFLICT" else "CONDITIONAL",
        "decision": {
            "mode": mode,
            "mode_reason": mode_reason,
            "recommendation": position.recommendation,
            "decision_type": position.decision_type,
            "confidence": position.confidence.level,
        },
        "evidence": {
            "status": _evidence_status(position),
            "trust_integrity": str((_dict(position.trust_engine)).get("decision_integrity") or "UNKNOWN"),
            "unknowns": unknowns,
            "blockers": blockers,
        },
        "economics": _economics(position),
        "options": {
            "count": len(alternatives.get("alternatives") or []),
            "available": bool(alternatives.get("available")),
            "summary": alternatives.get("summary"),
            "alternatives": list((alternatives.get("alternatives") or [])[:3]),
        },
        "execution": {
            "next_move": str(next_move),
            "actions": actions,
            "opening_position": position.opening_position,
            "walk_away": position.walk_away_threshold,
        },
        "change_conditions": unique_changers[:MAX],
        "negotiation": {
            "available": bool(playbook),
            "objective": playbook.get("objective"),
            "target": playbook.get("target"),
            "walk_away": playbook.get("walk_away"),
            "questions_to_resolve": list((playbook.get("questions_to_resolve") or [])[:MAX]),
        },
        "method": "Deterministic operational compression of validated VendorEdge outputs. No new facts, calculations, thresholds or LLM inference.",
    }
