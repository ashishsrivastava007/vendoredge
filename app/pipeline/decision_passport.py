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
    """Return only money that is genuinely comparable on the evidence supplied.

    Quote comparisons are evaluated on a common commercial basis first. A raw
    FCA-vs-DDP price gap is never presented as savings. Where buyer-borne
    freight is explicitly quantified for a supplier, it is added deterministically
    to that supplier's quoted price; otherwise the comparison remains open.
    """
    if position.financial_impact is not None:
        f = position.financial_impact
        return {
            "available": True,
            "type": "price_change",
            "headline": f"{f.potential_annual_impact_usd:,.0f} USD/year potential impact",
            "basis": "Deterministic annual spend × stated price change.",
        }

    if normalized.content_type == "quote_comparison":
        priced = [s for s in normalized.suppliers if s.price_amount is not None and s.currency]
        volume = normalized.common.annual_volume_units
        currencies = {s.currency.upper() for s in priced}
        if len(priced) >= 2 and volume is not None and len(currencies) == 1:
            currency = next(iter(currencies))

            def effective_unit_cost(s):
                base = float(s.price_amount)
                term = (s.incoterm or "").strip().upper()
                if term in {"EXW", "FCA", "FAS", "FOB"}:
                    freight = s.freight_cost_or_estimate
                    if freight is None:
                        return None
                    # Freight text was normalized at the evidence boundary;
                    # accept only a numeric scalar that is already in the same
                    # quote currency. Do not invent FX or benchmark freight.
                    import re
                    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(freight).replace(",", ""))
                    if not m:
                        return None
                    return base + float(m.group(0))
                return base

            effective = {s.supplier_name: effective_unit_cost(s) for s in priced}
            if all(v is not None for v in effective.values()):
                ordered = sorted(priced, key=lambda s: effective[s.supplier_name])
                low, high = ordered[0], ordered[-1]
                low_cost = effective[low.supplier_name]
                high_cost = effective[high.supplier_name]
                spread = round(float(high_cost) - float(low_cost), 2)
                annual = round(float(volume) * spread, 2)
                incumbent = next((s for s in priced if s.is_incumbent), None)
                if incumbent and effective[incumbent.supplier_name] > low_cost:
                    savings = round(float(volume) * (effective[incumbent.supplier_name] - low_cost), 2)
                    return {
                        "available": True,
                        "type": "comparable_landed_quote_comparison",
                        "headline": f"{savings:,.0f} {currency}/year comparable landed-price opportunity",
                        "basis": f"{incumbent.supplier_name} vs {low.supplier_name}; quoted price plus explicitly stated buyer-borne freight where applicable × annual volume. No FX, duty or unprovided logistics cost assumed.",
                        "from_supplier": incumbent.supplier_name,
                        "to_supplier": low.supplier_name,
                        "amount": savings,
                        "currency": currency,
                        "unit_gap": round(float(effective[incumbent.supplier_name]) - float(low_cost), 2),
                        "comparison_basis": "comparable_landed_price",
                    }
                return {
                    "available": True,
                    "type": "comparable_landed_quote_comparison",
                    "headline": f"{annual:,.0f} {currency}/year comparable landed-price spread",
                    "basis": "Comparable supplier price basis after adding only explicitly stated buyer-borne freight. No FX, duty or unprovided logistics cost assumed.",
                    "amount": annual,
                    "currency": currency,
                    "comparison_basis": "comparable_landed_price",
                }

            # Different Incoterms with an unquantified buyer cost are not a
            # safe savings calculation. Surface the gap instead of hiding it.
            incumbent = next((s for s in priced if s.is_incumbent), None)
            lowest = min(priced, key=lambda s: float(s.price_amount))
            raw_spread = round(float((incumbent.price_amount if incumbent else max(s.price_amount for s in priced))) - float(lowest.price_amount), 2)
            return {
                "available": False,
                "type": "quote_comparison_open",
                "headline": "Price gap visible; landed comparison incomplete",
                "basis": "Supplier prices use different cost/risk terms and at least one buyer-borne logistics cost is not quantified. No savings figure is presented.",
                "raw_unit_price_gap": raw_spread,
                "currency": currency,
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
