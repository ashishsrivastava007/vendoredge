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


def _money(v: float, currency: str) -> str:
    return f"{v:,.2f} {currency.upper()}"


def _supplier_from_recommendation(recommendation: str, suppliers: list[str]) -> str | None:
    text = (recommendation or "").lower()
    hits = [s for s in suppliers if s and s.lower() in text]
    if len(hits) == 1:
        return hits[0]
    return None


def _quote_flip_map(normalized: NormalizedEvidence, position: CommercialPosition) -> dict[str, Any]:
    volume = normalized.common.annual_volume_units
    priced = [s for s in normalized.suppliers if s.price_amount is not None]
    if volume is None or len(priced) < 2:
        return {"available": False, "mode": "quote_comparison", "reason": "At least two explicit supplier prices and annual volume are required.", "flips": [], "warnings": []}

    currencies = {(s.currency or "").upper() for s in priced}
    if len(currencies) != 1 or not next(iter(currencies)):
        return {"available": False, "mode": "quote_comparison", "reason": "Supplier prices are not safely comparable because currencies are missing or mixed; no FX assumption is permitted.", "flips": [], "warnings": ["No FX conversion is performed."]}

    currency = next(iter(currencies))
    ordered = sorted(priced, key=lambda s: float(s.price_amount))
    low, high = ordered[0], ordered[1]
    recommendation_supplier = _supplier_from_recommendation(position.recommendation, [s.supplier_name for s in priced])

    flips: list[dict[str, Any]] = []
    warnings: list[str] = []

    # The cleanest deterministic boundary: if the recommended supplier is one
    # of the two explicitly priced suppliers, show the exact price level at
    # which the named alternative becomes cheaper, holding everything else
    # constant. This is an economic boundary, not a complete award decision.
    if recommendation_supplier:
        rec = next((s for s in priced if s.supplier_name == recommendation_supplier), None)
        alternatives = [s for s in priced if s.supplier_name != recommendation_supplier]
        if rec and alternatives:
            alt = min(alternatives, key=lambda s: float(s.price_amount))
            rec_price = float(rec.price_amount)
            alt_price = float(alt.price_amount)
            if rec_price <= alt_price:
                delta = alt_price - rec_price
                flips.append({
                    "type": "price_threshold",
                    "driver": f"{rec.supplier_name} unit price",
                    "trigger": f"{rec.supplier_name} price reaches {_money(alt_price, currency)} or higher",
                    "effect": f"{alt.supplier_name} becomes no more expensive on stated unit price, before non-price factors.",
                    "threshold_value": alt_price,
                    "currency": currency,
                    "annual_impact_at_threshold": round(float(volume) * delta, 2),
                    "basis": "Deterministic same-currency unit-price comparison × stated annual volume; no FX, freight, duty, quality or capacity assumptions.",
                    "strength": "DETERMINISTIC",
                })
            else:
                flips.append({
                    "type": "price_threshold",
                    "driver": f"{alt.supplier_name} unit price",
                    "trigger": f"{alt.supplier_name} price reaches {_money(rec_price, currency)} or higher",
                    "effect": f"{rec.supplier_name} becomes cheaper on stated unit price, before non-price factors.",
                    "threshold_value": rec_price,
                    "currency": currency,
                    "annual_impact_at_threshold": round(float(volume) * (rec_price - alt_price), 2),
                    "basis": "Deterministic same-currency unit-price comparison × stated annual volume; no FX, freight, duty, quality or capacity assumptions.",
                    "strength": "DETERMINISTIC",
                })
    else:
        warnings.append("The recommendation does not uniquely name one of the priced suppliers; no supplier-specific award flip is inferred.")

    # Always expose the current economic ordering as a separate signal. This
    # prevents the UI from implying that lowest price equals final recommendation.
    flips.append({
        "type": "economic_baseline",
        "driver": "stated unit price",
        "trigger": f"{low.supplier_name} remains below {high.supplier_name} at the stated prices",
        "effect": f"{low.supplier_name} has the lower direct unit-price basis; this alone does not establish the overall award decision.",
        "threshold_value": float(high.price_amount),
        "currency": currency,
        "basis": "Observed same-currency supplier prices; non-price factors are not collapsed into price.",
        "strength": "DETERMINISTIC",
    })

    qualitative = list(position.disconfirming_condition and [position.disconfirming_condition] or [])
    audit = position.decision_audit
    qualitative.extend((audit.reversal_conditions if audit else [])[:5])
    # Deduplicate while preserving order; these are not converted into numeric thresholds.
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
        "version": "R21.1",
        "decision_scope": "Deterministic economic flip boundaries plus explicitly stated evidence-required reversal conditions.",
        "current_recommendation": position.recommendation,
        "current_recommendation_supplier": recommendation_supplier,
        "flips": flips,
        "evidence_required": evidence_required[:6],
        "warnings": warnings[:6],
        "fragility": _fragility(len([f for f in flips if f.get("strength") == "DETERMINISTIC"]), len(evidence_required), recommendation_supplier is not None),
        "method": "No LLM call. No new facts. Thresholds are calculated only from explicit same-currency supplier prices and stated annual volume.",
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
