"""VendorEdge Release 21 — deterministic Decision Flip Map.

R21 answers one narrow question without pretending to know more than the evidence:
"What would change this decision?"

This module never asks an LLM for a second opinion, never invents a threshold,
and never changes the recommendation. Numeric boundaries are derived only when
all required inputs are explicitly comparable. Qualitative reversal conditions
remain clearly labelled as evidence-required conditions.
"""
from __future__ import annotations

import re
from typing import Any

from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence
from app.pipeline.tco import build_quote_tco


def _money(v: float, currency: str) -> str:
    return f"{v:,.2f} {currency.upper()}"


def _supplier_from_recommendation(recommendation: str, suppliers: list[str]) -> str | None:
    text = (recommendation or "").lower()
    hits = [s for s in suppliers if s and s.lower() in text]
    if len(hits) == 1:
        return hits[0]
    return None


def _quote_flip_map(normalized: NormalizedEvidence, position: CommercialPosition) -> dict[str, Any]:
    """Build Flip Map from the canonical TCO result.

    R26.1.1: this module is a consumer of commercial economics, never a
    second calculator. Any money/threshold shown here must originate in
    ``build_quote_tco``. Qualitative reversal conditions remain independent
    because they are not monetary calculations.
    """
    tco = build_quote_tco(normalized)
    suppliers = [s for s in normalized.suppliers if s.price_amount is not None]
    if not tco.get("available") and not tco.get("quote_price_boundary"):
        return {
            "available": False,
            "mode": "quote_comparison",
            "reason": tco.get("basis") or tco.get("headline") or "Canonical commercial comparison is not available.",
            "flips": [],
            "warnings": list(tco.get("limitations", []))[:6],
            "commercial_source": "canonical_tco",
        }

    recommendation_supplier = _supplier_from_recommendation(position.recommendation, [s.supplier_name for s in suppliers])
    flips: list[dict[str, Any]] = []
    warnings: list[str] = []
    boundary = tco.get("decision_boundary") or {}
    canonical_boundary = boundary.get("canonical_quote_boundary") if isinstance(boundary, dict) else None
    quote_boundary = tco.get("quote_price_boundary")

    # Prefer the canonical landed/commercial boundary whenever available.
    # A raw quoted-price boundary is only exposed when landed economics are
    # unavailable; it is never mixed into a partial landed-cost result.
    economic_unit_threshold = boundary.get("unit_threshold") if isinstance(boundary, dict) else None
    economic_currency = tco.get("currency")
    economic_annual = boundary.get("annual_impact_at_threshold") if isinstance(boundary, dict) else None
    missing_components = boundary.get("missing_components") if isinstance(boundary, dict) else None

    if recommendation_supplier and economic_unit_threshold is not None:
        flips.append({
            "type": "economic_threshold",
            "driver": "canonical commercial cost advantage",
            "trigger": (
                f"Missing buyer-borne costs reach {_money(float(economic_unit_threshold), str(economic_currency))} per unit"
                if missing_components else
                f"The known commercial cost advantage reaches {_money(float(economic_unit_threshold), str(economic_currency))} per unit"
            ),
            "effect": "The current known commercial advantage is eliminated or the economic ordering changes; non-price factors remain separate.",
            "threshold_value": float(economic_unit_threshold),
            "currency": str(economic_currency),
            "annual_impact_at_threshold": economic_annual,
            "basis": "Consumed from build_quote_tco decision_boundary; no independent price × volume calculation.",
            "strength": "DETERMINISTIC",
            "source": "canonical_tco",
        })
    elif recommendation_supplier and isinstance(quote_boundary, dict):
        # Only when landed economics are unavailable do we expose a quoted-price
        # boundary. It is explicitly a quote-basis threshold, not savings.
        threshold = quote_boundary.get("threshold_value")
        currency = quote_boundary.get("currency") or tco.get("currency")
        annual_impact = quote_boundary.get("annual_impact_at_threshold")
        alt_name = quote_boundary.get("alternative_supplier")
        driver = quote_boundary.get("driver_supplier") or recommendation_supplier
        if threshold is not None and alt_name:
            flips.append({
                "type": "price_threshold",
                "driver": f"{driver} unit price",
                "trigger": f"{driver} price reaches {_money(float(threshold), str(currency))} or higher",
                "effect": f"{alt_name} reaches the same stated quoted-unit-price basis before non-price factors.",
                "threshold_value": float(threshold),
                "currency": str(currency),
                "annual_impact_at_threshold": annual_impact,
                "basis": quote_boundary.get("basis", "Canonical quoted-price boundary from build_quote_tco; not landed savings."),
                "strength": "DETERMINISTIC",
                "source": "canonical_tco",
            })
    elif recommendation_supplier:
        warnings.append("The canonical commercial engine did not produce a supplier-specific numeric boundary; no independent price calculation is performed here.")
    else:
        warnings.append("The recommendation does not uniquely name one priced supplier; no supplier-specific award flip is inferred.")

    # Never create a second economic number here. The canonical TCO headline
    # and result are the sole commercial baseline for customer-facing money.
    flips.append({
        "type": "economic_baseline",
        "driver": "canonical commercial comparison",
        "trigger": tco.get("headline", "Canonical commercial comparison is available"),
        "effect": "The canonical TCO result is the commercial baseline; non-price factors remain separate decision considerations.",
        "threshold_value": economic_unit_threshold if economic_unit_threshold is not None else (quote_boundary.get("threshold_value") if isinstance(quote_boundary, dict) else None),
        "currency": tco.get("currency"),
        "annual_impact_at_threshold": economic_annual if economic_unit_threshold is not None else (quote_boundary.get("annual_impact_at_threshold") if isinstance(quote_boundary, dict) else None),
        "basis": "Consumed directly from build_quote_tco; no independent price × volume calculation is performed.",
        "strength": "DETERMINISTIC",
        "source": "canonical_tco",
    })

    qualitative = list(position.disconfirming_condition and [position.disconfirming_condition] or [])
    audit = position.decision_audit
    qualitative.extend((audit.reversal_conditions if audit else [])[:5])
    seen = set()
    evidence_required = []
    for condition in qualitative:
        key = condition.strip().lower()
        if key and key not in seen:
            seen.add(key)
            evidence_required.append({
                "type": "evidence_required",
                "condition": condition,
                "effect": "Could change the decision only after the stated condition is evidenced; no numeric threshold was invented.",
                "strength": "QUALITATIVE",
            })

    return {
        "available": True,
        "mode": "quote_comparison",
        "version": "R26.1.1",
        "decision_scope": "Canonical commercial boundaries plus explicitly stated evidence-required reversal conditions.",
        "current_recommendation": position.recommendation,
        "current_recommendation_supplier": recommendation_supplier,
        "flips": flips,
        "evidence_required": evidence_required[:6],
        "warnings": warnings[:6],
        "fragility": _fragility(len([f for f in flips if f.get("strength") == "DETERMINISTIC"]), len(evidence_required), recommendation_supplier is not None),
        "commercial_source": "canonical_tco",
        "method": "No LLM call. No independent commercial calculation. Monetary boundaries are consumed from build_quote_tco; qualitative reversal conditions remain evidence-required.",
    }


def _price_increase_flip_map(normalized: NormalizedEvidence, position: CommercialPosition) -> dict[str, Any]:
    spend = normalized.derived.resolved_annual_spend_usd
    requested = normalized.case.requested_increase_percent
    if spend is None or requested is None or not normalized.derived.currency_calculation_safe:
        return {"available": False, "mode": "price_increase", "reason": "Safe annual spend and requested increase are not both available in a calculation-safe currency basis.", "flips": [], "warnings": []}

    flips = [{
        "type": "price_change_threshold",
        "driver": "supplier requested increase",
        "trigger": "Any change away from the stated request changes the deterministic annual cost impact.",
        "effect": "Annual exposure moves by the stated annual spend multiplied by the price-change percentage; this does not by itself establish a different supplier recommendation.",
        "threshold_value": float(requested),
        "currency": "USD",
        "annual_impact_at_threshold": round(float(spend) * float(requested) / 100, 2),
        "basis": "Deterministic annual spend × stated price change.",
        "strength": "DETERMINISTIC",
    }]
    qualitative = []
    if position.disconfirming_condition:
        qualitative.append(position.disconfirming_condition)
    audit = position.decision_audit
    qualitative.extend((audit.reversal_conditions if audit else [])[:5])
    seen = set(); evidence_required = []
    for condition in qualitative:
        key = condition.strip().lower()
        if key and key not in seen:
            seen.add(key)
            evidence_required.append({"type":"evidence_required","condition":condition,"effect":"Decision reversal requires the stated evidence; no unsupported numeric threshold is inferred.","strength":"QUALITATIVE"})
    return {
        "available": True,
        "mode": "price_increase",
        "version": "R21.1",
        "decision_scope": "Deterministic exposure boundary plus explicit evidence-required reversal conditions.",
        "current_recommendation": position.recommendation,
        "current_recommendation_supplier": None,
        "flips": flips,
        "evidence_required": evidence_required[:6],
        "warnings": ["A price-increase case does not contain enough information to invent a supplier-switch threshold."],
        "fragility": _fragility(1, len(evidence_required), False),
        "method": "No LLM call. No new facts. Numeric exposure is annual spend × explicitly stated price change.",
    }


def _fragility(deterministic_count: int, qualitative_count: int, named_recommendation: bool) -> dict[str, Any]:
    if deterministic_count <= 0:
        score = None
        label = "NOT_ASSESSABLE"
    elif qualitative_count == 0 and named_recommendation:
        score = 35
        label = "LOW_SIGNAL"
    elif qualitative_count <= 2 and named_recommendation:
        score = 55
        label = "MODERATE"
    else:
        score = 70
        label = "HIGHER_REVIEW_NEED"
    return {
        "score": score,
        "label": label,
        "interpretation": "R21 fragility is a review signal, not a probability of decision failure. It is intentionally conservative and is never presented as statistical confidence.",
    }


def build_decision_flip_map(normalized: NormalizedEvidence, position: CommercialPosition) -> dict[str, Any]:
    if normalized.content_type == "quote_comparison":
        return _quote_flip_map(normalized, position)
    if normalized.content_type == "price_increase":
        return _price_increase_flip_map(normalized, position)
    return {"available": False, "version": "R21.1", "reason": "Content type is not supported by the deterministic R21 engine.", "flips": [], "warnings": []}
