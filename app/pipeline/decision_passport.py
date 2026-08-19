"""VendorEdge native Decision Passport.

A deterministic, executive-first presentation layer: answer first, proof second.
It never creates facts or changes the recommendation. It compresses the already
validated decision into the smallest useful control surface for a procurement
manager, CFO, or category lead.
"""
from __future__ import annotations

from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence


def _direct_economics(normalized: NormalizedEvidence, position: CommercialPosition) -> dict:
    """Single-source commercial economics. Quote comparisons never calculate here."""
    if position.financial_impact is not None:
        f = position.financial_impact
        return {
            "available": True,
            "type": "price_change",
            "headline": f"{f.potential_annual_impact_usd:,.0f} USD/year potential impact",
            "basis": "Deterministic annual spend × stated price change.",
        }
    if normalized.content_type == "quote_comparison":
        from app.pipeline.tco import build_quote_tco
        return build_quote_tco(normalized)
    return {
        "available": False,
        "type": "not_quantified",
        "headline": "Direct economics not safely quantified",
        "basis": "The evidence does not support a deterministic comparable-money calculation without adding an assumption.",
    }


def build_decision_passport(normalized: NormalizedEvidence, position: CommercialPosition) -> dict:
    tower = position.control_tower or {}
    if hasattr(tower, "model_dump"):
        tower = tower.model_dump()
    audit = position.decision_audit
    alternatives = position.alternative_analysis or {}
    stress = position.stress_test or {}

    audit_counts = (audit.evidence_counts if audit else {}) or {}
    unknowns = (audit.uncertainties if audit else [])[:4]
    changers = (audit.reversal_conditions if audit else [])[:3]
    actions = (tower.get("action_items") or [])[:3]

    return {
        "title": "VendorEdge Decision Passport",
        "version": "1.0",
        "decision": position.recommendation,
        "readiness": tower.get("readiness", "CONDITIONAL"),
        "confidence": position.confidence.level,
        "confidence_reason": position.confidence.derivation_note,
        "evidence_integrity": audit.evidence_integrity_status if audit else "UNKNOWN",
        "economics": _direct_economics(normalized, position),
        "why": (position.commercial_insights or [])[:3],
        "critical_before_action": (tower.get("critical_before_action") or [])[:3],
        "next_move": actions[0]["action"] if actions else (position.opening_position or "Review the evidence and act only within the stated decision conditions."),
        "decision_changers": changers,
        "unknowns": unknowns,
        "alternative_count": len(alternatives.get("alternatives", [])) if isinstance(alternatives, dict) else 0,
        "stress_status": stress.get("status", "NOT_TESTED") if isinstance(stress, dict) else "NOT_TESTED",
        "evidence_counts": audit_counts,
        "method": "Deterministic executive compression of the validated decision; no new facts, calculations, ranking, or LLM call.",
    }
