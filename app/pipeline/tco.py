"""Canonical commercial comparison engine.

R26: every customer-facing commercial number comes from one deterministic
comparison path. Raw quote price differences are never labelled savings.
Unknown buyer-borne costs remain unknown; no FX or market assumption is
invented here.
"""
from __future__ import annotations

import re
from typing import Any

from app.pipeline.normalized_evidence import NormalizedEvidence, SupplierEvidence

_BUYER_FREIGHT = {"EXW", "FCA", "FAS", "FOB"}
_BUYER_DUTY = {"EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU"}


def _per_unit_amount(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value)
    m = re.search(r"(?:€|\$|£|USD|EUR|GBP)?\s*([0-9][0-9,]*(?:\.\d+)?)\s*(?:/\s*unit|per\s+unit|each)\b", text, re.I)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _unit_cost(s: SupplierEvidence) -> tuple[float | None, list[str]]:
    if s.price_amount is None:
        return None, ["quoted unit price"]
    term = (s.incoterm or "").strip().upper()
    if not term:
        return None, ["Incoterm"]
    cost = float(s.price_amount)
    missing: list[str] = []
    if term in _BUYER_FREIGHT:
        freight = _per_unit_amount(s.freight_cost_or_estimate)
        if freight is None:
            missing.append("buyer-borne freight per unit")
        else:
            cost += freight
    # DDP places import clearance/duty with the seller. For other common
    # terms in this set, a duty amount is buyer-borne but is not represented
    # as a supplier-level normalized field, so we deliberately refuse to
    # manufacture it from a percentage or benchmark.
    if term in _BUYER_DUTY:
        missing.append("buyer-borne import duty/tax")
    if term == "DDP":
        missing = [x for x in missing if x != "buyer-borne import duty/tax"]
    return (round(cost, 8), []) if not missing else (None, missing)


def build_quote_tco(normalized: NormalizedEvidence) -> dict[str, Any]:
    if normalized.content_type != "quote_comparison":
        return {"available": False, "type": "not_applicable", "headline": "Not applicable"}

    suppliers = [s for s in normalized.suppliers if s.price_amount is not None and s.currency]
    volume = normalized.common.annual_volume_units
    currencies = {str(s.currency).strip().upper() for s in suppliers}
    if len(suppliers) < 2 or volume is None or volume <= 0:
        return {"available": False, "type": "not_quantified", "headline": "Commercial comparison not safely quantified", "basis": "At least two priced suppliers and a positive annual volume are required."}
    if len(currencies) != 1:
        return {"available": False, "type": "not_quantified", "headline": "Commercial comparison not safely quantified", "basis": "Supplier currencies differ or are missing; VendorEdge will not invent FX."}

    currency = next(iter(currencies))
    costs: dict[str, float] = {}
    missing: dict[str, list[str]] = {}
    for s in suppliers:
        value, gaps = _unit_cost(s)
        if value is None:
            missing[s.supplier_name] = gaps
        else:
            costs[s.supplier_name] = value

    incumbent = next((s for s in suppliers if s.is_incumbent), None)
    lowest = min(suppliers, key=lambda s: float(s.price_amount))

    if incumbent and not missing and incumbent.supplier_name in costs:
        best_name = min(costs, key=costs.get)
        if best_name != incumbent.supplier_name and costs[best_name] < costs[incumbent.supplier_name]:
            gap = round(costs[incumbent.supplier_name] - costs[best_name], 8)
            annual = round(gap * float(volume), 2)
            return {
                "available": True,
                "type": "comparable_commercial_cost",
                "headline": f"{annual:,.0f} {currency}/year evidenced commercial opportunity",
                "basis": f"Comparable supplier cost basis after explicitly evidenced buyer-borne freight; {incumbent.supplier_name} vs {best_name} × {volume:,.0f} units/year. No FX, duty or other unprovided cost assumed.",
                "amount": annual, "currency": currency, "unit_gap": gap, "volume": float(volume),
                "from_supplier": incumbent.supplier_name, "to_supplier": best_name,
                "unit_costs": costs,
            }
        return {
            "available": True, "type": "comparable_commercial_cost",
            "headline": "No lower evidenced commercial cost identified",
            "basis": "All required components represented by the evidence were included; no unsupported cost was added.",
            "currency": currency, "unit_costs": costs,
        }

    # Useful but deliberately non-savings output when full normalization is
    # impossible. This is the key R26 truth-preserving distinction.
    incumbent_price = float(incumbent.price_amount) if incumbent else None
    raw_gap = round(incumbent_price - float(lowest.price_amount), 8) if incumbent and float(lowest.price_amount) < incumbent_price else None
    return {
        "available": False,
        "type": "direct_price_only",
        "headline": (f"{raw_gap * float(volume):,.0f} {currency}/year direct price gap — not confirmed savings" if raw_gap is not None else "Direct price comparison available; full commercial cost not confirmed"),
        "basis": "Quoted unit prices are comparable only on their stated price basis. Landed/TCO savings are withheld because one or more buyer-borne components remain unverified.",
        "amount": round(raw_gap * float(volume), 2) if raw_gap is not None else None,
        "currency": currency,
        "limitations": [f"{name}: missing {', '.join(gaps)}" for name, gaps in missing.items()],
    }
