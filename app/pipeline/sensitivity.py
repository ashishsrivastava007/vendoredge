"""Deterministic commercial sensitivity analysis.

The LLM recommends; this module stress-tests the recommendation using only
numbers already present in NormalizedEvidence. It never invents prices,
volumes, FX rates, freight, savings targets, or supplier capacity.
"""
from __future__ import annotations
from typing import Optional

from app.pipeline.normalized_evidence import NormalizedEvidence


def _money(v: float) -> str:
    return f"${v:,.0f}"


def _pct(v: float) -> str:
    return f"{v:g}%"


def build_sensitivity_analysis(normalized: NormalizedEvidence) -> dict:
    if normalized.content_type == "price_increase":
        spend = normalized.derived.resolved_annual_spend_usd
        requested = normalized.case.requested_increase_percent
        if spend is None or requested is None or not normalized.derived.currency_calculation_safe:
            return {"available": False, "reason": "Insufficient safe numeric evidence for deterministic sensitivity analysis.", "scenarios": []}
        spend = float(spend)
        requested = float(requested)
        points = sorted(set([0.0, 5.0, 10.0, requested, 15.0]))
        scenarios = []
        for pct in points:
            impact = round(spend * pct / 100, 2)
            scenarios.append({
                "scenario": f"Price change of {_pct(pct)}",
                "annual_impact_usd": impact,
                "vs_current_usd": impact,
                "basis": "Deterministic annual spend × price change; no other variables changed.",
            })
        return {
            "available": True,
            "mode": "price_change_sensitivity",
            "baseline_annual_spend_usd": spend,
            "current_requested_change_percent": requested,
            "scenarios": scenarios,
            "decision_boundary": {
                "label": "Requested increase becomes cost-neutral at",
                "value": "0% price change",
                "note": "This is a mathematical boundary, not a recommendation. Other commercial factors remain unchanged."
            },
        }

    volume = normalized.common.annual_volume_units
    suppliers = [s for s in normalized.suppliers if s.price_usd is not None]
    if volume is None or len(suppliers) < 2:
        return {"available": False, "reason": "At least two suppliers with deterministic USD prices and annual volume are required.", "scenarios": []}
    if not all((s.currency or "").upper() in {"USD", "US DOLLAR", "US DOLLARS"} for s in suppliers):
        return {"available": False, "reason": "Supplier currencies are not all explicitly USD; no FX assumptions are permitted.", "scenarios": []}

    # Pairwise allocation sensitivity for the two lowest-price suppliers. We
    # deliberately cap this at two suppliers rather than silently inventing a
    # multi-supplier optimization model.
    suppliers = sorted(suppliers, key=lambda s: float(s.price_usd))[:2]
    a, b = suppliers
    rows = []
    for share_a in (0, 25, 50, 75, 100):
        share_b = 100 - share_a
        spend = float(volume) * (share_a / 100 * float(a.price_usd) + share_b / 100 * float(b.price_usd))
        rows.append({
            "scenario": f"{a.supplier_name} {share_a}% / {b.supplier_name} {share_b}%",
            "annual_spend_usd": round(spend, 2),
            "basis": "Annual volume × weighted supplier prices; freight, duty, FX and capacity are excluded unless explicitly represented in the supplier price evidence.",
        })
    return {
        "available": True,
        "mode": "two_supplier_allocation_sensitivity",
        "annual_volume_units": float(volume),
        "suppliers": [a.supplier_name, b.supplier_name],
        "scenarios": rows,
        "decision_boundary": None,
    }
