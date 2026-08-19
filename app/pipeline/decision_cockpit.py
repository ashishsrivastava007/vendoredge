"""VendorEdge Commercial Decision Cockpit.

Deterministic, executive-first presentation assembled only from the validated
CommercialPosition and its evidence-derived companion objects. It never calls
an LLM, creates a new fact, changes a recommendation, or invents economics.
"""
from __future__ import annotations
from typing import Any
from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence
from app.pipeline.decision_under_uncertainty import build_decision_under_uncertainty


def _economics(position: CommercialPosition, passport: dict[str, Any]) -> dict[str, Any]:
    econ = (passport or {}).get("economics") or {}
    if econ.get("available"):
        return econ
    return {"available": False, "headline": "Not safely quantified", "basis": "No deterministic comparable-money calculation is supported."}


def _stakeholder_flags(audit: Any) -> list[str]:
    if not audit:
        return []
    return [str(x) for x in (audit.stakeholder_conflict or [])[:3]]


def build_decision_cockpit(normalized: NormalizedEvidence, position: CommercialPosition) -> dict[str, Any]:
    passport = position.decision_passport or {}
    audit = position.decision_audit
    tower = position.control_tower or {}
    if hasattr(tower, "model_dump"):
        tower = tower.model_dump()
    alternatives = position.alternative_analysis or {}
    stress = position.stress_test or {}

    evidence_counts = (passport.get("evidence_counts") or {}) if isinstance(passport, dict) else {}
    total = sum(int(v or 0) for v in evidence_counts.values())
    proven = int(evidence_counts.get("PROVEN", 0) or 0)
    unknown = int(evidence_counts.get("UNKNOWN", 0) or 0)
    contradicted = int(evidence_counts.get("CONTRADICTED", 0) or 0)

    if contradicted:
        evidence_signal = "CONFLICT"
    elif unknown:
        evidence_signal = "GAPS"
    elif proven:
        evidence_signal = "GROUNDED"
    else:
        evidence_signal = "LIMITED"

    blockers = list((tower.get("critical_before_action") or [])[:3])
    changers = list((passport.get("decision_changers") or [])[:3])
    next_move = passport.get("next_move") or position.opening_position or "Review the validated decision before acting."

    uncertainty = build_decision_under_uncertainty(normalized, position)

    return {
        "title": "VendorEdge Commercial Decision Cockpit",
        "version": "1.0",
        "verdict": position.recommendation,
        "readiness": tower.get("readiness", "CONDITIONAL"),
        "confidence": position.confidence.level,
        "confidence_reason": position.confidence.derivation_note,
        "evidence_signal": evidence_signal,
        "evidence_counts": evidence_counts,
        "evidence_total": total,
        "economics": _economics(position, passport),
        "why": list((position.commercial_insights or [])[:3]),
        "next_move": next_move,
        "blockers": blockers,
        "decision_changers": changers,
        "unknowns": list((passport.get("unknowns") or [])[:4]),
        "stakeholder_flags": _stakeholder_flags(audit),
        "alternative_count": len(alternatives.get("alternatives", [])) if isinstance(alternatives, dict) else 0,
        "stress_status": stress.get("status", "NOT_TESTED") if isinstance(stress, dict) else "NOT_TESTED",
        "decision_under_uncertainty": uncertainty,
        "negotiation": {
            "opening": position.opening_position,
            "target": position.negotiation_playbook.dimensions[0].get("target") if getattr(position, "negotiation_playbook", None) and position.negotiation_playbook.dimensions else None,
            "walk_away": position.walk_away_threshold,
        },
        "method": "Deterministic compression of validated VendorEdge outputs; no new facts, ranking, calculations, or LLM call.",
    }
