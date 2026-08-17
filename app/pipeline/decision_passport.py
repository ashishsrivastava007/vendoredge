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
    if position.financial_impact is not None:
        f = position.financial_impact
        return {
            "available": True,
            "type": "price_change",
            "headline": f"{f.potential_annual_impact_usd:,.0f} USD/year potential impact",
            "basis": "Deterministic annual spend × stated price change.",
        }

    if normalized.content_type == "quote_comparison":
        priced = [s for s in normalized.suppliers if s.price_amount is not None or s.price_usd is not None]
        volume = normalized.common.annual_volume_units
        currencies = {(s.currency.upper() if s.currency else "USD") for s in priced}
        if len(priced) >= 2 and volume is not None and len(currencies) == 1:
            lowest = min(priced, key=lambda s: float(s.price_amount if s.price_amount is not None else s.price_usd))
            incumbent = next((s for s in priced if s.is_incumbent), None)
            low_price = float(lowest.price_amount if lowest.price_amount is not None else lowest.price_usd)
            incumbent_price = float(incumbent.price_amount if incumbent and incumbent.price_amount is not None else (incumbent.price_usd if incumbent else 0))
            if incumbent and low_price < incumbent_price:
                savings = round(float(volume) * (incumbent_price - low_price), 2)
                return {
                    "available": True,
                    "type": "quote_comparison",
                    "headline": f"{savings:,.0f} {lowest.currency.upper() if lowest.currency else "USD"}/year direct price opportunity",
                    "basis": f"{incumbent.supplier_name} vs {lowest.supplier_name}; same-currency stated prices × annual volume. No FX, freight or duty assumed.",
                    "from_supplier": incumbent.supplier_name,
                    "to_supplier": lowest.supplier_name,
                    "amount": savings,
                    "currency": lowest.currency.upper() if lowest.currency else "USD",
                }
            spread = round(float(volume) * (max(s.price_amount for s in priced) - min(s.price_amount for s in priced)), 2)
            return {
                "available": True,
                "type": "quote_comparison",
                "headline": f"{spread:,.0f} {next(iter(currencies))}/year price spread",
                "basis": "Same-currency stated supplier prices × annual volume. No FX, freight or duty assumed.",
            }

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
