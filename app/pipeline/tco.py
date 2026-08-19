"""Canonical commercial comparison engine.

R26.1: every customer-facing commercial number comes from one deterministic
comparison path. Known buyer-borne components are credited independently;
unknown components remain explicit unknowns and never trigger a fallback to
a raw price gap when a defensible partial landed comparison is possible.
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
    m = re.search(
        r"(?:€|\$|£|USD|EUR|GBP)?\s*([0-9][0-9,]*(?:\.\d+)?)\s*(?:/\s*unit|per\s+unit|each)\b",
        text,
        re.I,
    )
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _known_unit_cost(s: SupplierEvidence) -> tuple[float | None, list[str], list[str]]:
    """Return (known cost, missing components, included components).

    This function deliberately performs partial normalization. A known freight
    amount is useful evidence even when another buyer-borne component (such as
    duty/tax) is unknown. No unknown component is estimated or filled in.
    """
    if s.price_amount is None:
        return None, ["quoted unit price"], []
    term = (s.incoterm or "").strip().upper()
    if not term:
        return None, ["Incoterm"], []

    cost = float(s.price_amount)
    included = ["quoted unit price"]
    missing: list[str] = []

    if term in _BUYER_FREIGHT:
        freight = _per_unit_amount(s.freight_cost_or_estimate)
        if freight is None:
            missing.append("buyer-borne freight per unit")
        else:
            cost += freight
            included.append("explicit buyer-borne freight")

    # DDP places import clearance/duty with the seller. For other common
    # terms, duty/tax may be buyer-borne. We do not have a supplier-level
    # explicit duty amount in this model, so keep it unknown rather than
    # manufacturing it from a rate or benchmark.
    if term in _BUYER_DUTY:
        missing.append("buyer-borne import duty/tax")

    if term == "DDP":
        missing = [x for x in missing if x != "buyer-borne import duty/tax"]
        included.append("seller-borne import duty/tax under DDP")

    return round(cost, 8), missing, included


def _decision_boundary(unit_gap: float | None, missing_components: list[str]) -> dict[str, Any] | None:
    if unit_gap is None or unit_gap <= 0 or not missing_components:
        return None
    return {
        "unit_threshold": round(unit_gap, 8),
        "statement": (
            f"The currently missing buyer-borne costs would need to reach "
            f"{unit_gap:,.2f} per unit to eliminate the known commercial advantage."
        ),
        "missing_components": missing_components,
    }


def _direct_price_boundary(rec_price: float, alt_price: float, volume: float, currency: str, rec_name: str, alt_name: str) -> dict[str, Any]:
    """Canonical quote-price boundary for Flip Map consumption.

    This is deliberately a *price-basis* boundary, not a savings claim.
    Flip Map must consume this object rather than recomputing price × volume.
    """
    threshold = max(rec_price, alt_price)
    delta = abs(rec_price - alt_price)
    return {
        "threshold_value": round(threshold, 8),
        "currency": currency,
        "annual_impact_at_threshold": round(delta * float(volume), 2),
        "driver_supplier": rec_name if rec_price >= alt_price else alt_name,
        "alternative_supplier": alt_name if rec_price >= alt_price else rec_name,
        "basis": "Canonical same-currency quoted-unit-price boundary × stated annual volume; no FX conversion, landed-cost or savings claim is made.",
    }


def build_quote_tco(normalized: NormalizedEvidence) -> dict[str, Any]:
    if normalized.content_type != "quote_comparison":
        return {"available": False, "type": "not_applicable", "headline": "Not applicable"}

    suppliers = [s for s in normalized.suppliers if s.price_amount is not None and s.currency]
    volume = normalized.common.annual_volume_units
    currencies = {str(s.currency).strip().upper() for s in suppliers}
    if len(suppliers) < 2 or volume is None or volume <= 0:
        return {
            "available": False,
            "type": "not_quantified",
            "headline": "Commercial comparison not safely quantified",
            "basis": "At least two priced suppliers and a positive annual volume are required.",
        }
    if len(currencies) != 1:
        return {
            "available": False,
            "type": "not_quantified",
            "headline": "Commercial comparison not safely quantified",
            "basis": "Supplier currencies differ or are missing; VendorEdge will not invent FX.",
        }

    currency = next(iter(currencies))
    known_costs: dict[str, float] = {}
    missing: dict[str, list[str]] = {}
    included: dict[str, list[str]] = {}
    supplier_by_name = {s.supplier_name: s for s in suppliers}

    for supplier in suppliers:
        value, gaps, components = _known_unit_cost(supplier)
        if value is not None:
            known_costs[supplier.supplier_name] = value
        if gaps:
            missing[supplier.supplier_name] = gaps
        included[supplier.supplier_name] = components

    incumbent = next((s for s in suppliers if s.is_incumbent), None)
    if incumbent is None:
        return {
            "available": False,
            "type": "not_quantified",
            "headline": "Commercial comparison needs an identified incumbent",
            "basis": "VendorEdge needs a clear baseline supplier before presenting a directional commercial advantage.",
        }

    incumbent_cost = known_costs.get(incumbent.supplier_name)
    incumbent_gaps = missing.get(incumbent.supplier_name, [])
    incumbent_components = included.get(incumbent.supplier_name, [])
    incumbent_basis_defensible = (
        incumbent_cost is not None
        and (not incumbent_gaps or "explicit buyer-borne freight" in incumbent_components)
    )
    if not incumbent_basis_defensible:
        quote_boundary = None
        priced_order = sorted(suppliers, key=lambda s: float(s.price_amount))
        if len(priced_order) >= 2:
            low_quote, high_quote = priced_order[0], priced_order[-1]
            quote_boundary = _direct_price_boundary(
                float(high_quote.price_amount),
                float(low_quote.price_amount),
                float(volume),
                currency,
                high_quote.supplier_name,
                low_quote.supplier_name,
            )
        return {
            "available": False,
            "type": "incomplete_landed_cost",
            "headline": "Commercial comparison incomplete — incumbent cost basis is not fully known",
            "basis": "The incumbent's buyer-borne cost basis is incomplete, so VendorEdge will not manufacture a landed baseline.",
            "currency": currency,
            "limitations": [f"{incumbent.supplier_name}: missing {', '.join(missing.get(incumbent.supplier_name, []))}"],
            "quote_price_boundary": quote_boundary,
        }

    # Compare the incumbent against every alternative for which a defensible
    # known-cost basis exists. This intentionally allows partial landed
    # comparisons while preserving the distinction between known advantage and
    # confirmed savings.
    def _has_defensible_alternative_basis(supplier: SupplierEvidence) -> bool:
        gaps = missing.get(supplier.supplier_name, [])
        if not gaps:
            return True
        # Partial landed comparison is defensible only when at least one
        # buyer-borne component was explicitly quantified. A bare FCA/FOB
        # price with unknown freight is still only a raw quote and must not
        # be promoted into landed economics.
        components = included.get(supplier.supplier_name, [])
        return "explicit buyer-borne freight" in components

    alternatives = [
        s for s in suppliers
        if s.supplier_name != incumbent.supplier_name
        and s.supplier_name in known_costs
        and _has_defensible_alternative_basis(s)
    ]
    if not alternatives:
        # The landed comparison is unavailable, but the canonical engine may
        # still expose a clearly-labelled quoted-price boundary for Flip Map.
        # This is a decision threshold on the stated quote basis, never a
        # savings claim and never a substitute for landed economics.
        priced_order = sorted(suppliers, key=lambda s: float(s.price_amount))
        low_quote, high_quote = priced_order[0], priced_order[-1]
        quote_boundary = _direct_price_boundary(
            float(high_quote.price_amount),
            float(low_quote.price_amount),
            float(volume),
            currency,
            high_quote.supplier_name,
            low_quote.supplier_name,
        )
        return {
            "available": False,
            "type": "incomplete_landed_cost",
            "headline": "Commercial comparison incomplete — no alternative has a defensible landed-cost basis",
            "basis": "Known buyer-borne components are insufficient to compare an alternative without an unsupported assumption.",
            "currency": currency,
            "limitations": [f"{name}: missing {', '.join(gaps)}" for name, gaps in missing.items()],
            "quote_price_boundary": quote_boundary,
        }

    best = min(alternatives, key=lambda s: known_costs[s.supplier_name])
    best_cost = known_costs[best.supplier_name]
    gap = round(incumbent_cost - best_cost, 8)
    annual = round(gap * float(volume), 2)

    if gap <= 0:
        return {
            "available": True,
            "type": "comparable_commercial_cost",
            "headline": "No lower evidenced commercial cost identified",
            "basis": "Known commercial components were compared without adding unsupported values.",
            "comparison_basis": "comparable_landed_price",
            "currency": currency,
            "unit_costs": known_costs,
            "known_components": included,
            "limitations": [f"{name}: missing {', '.join(gaps)}" for name, gaps in missing.items()],
            "decision_boundary": {
                "unit_threshold": round(best_cost, 8),
                "annual_impact_at_threshold": annual,
                "currency": currency,
                "basis": "Canonical comparable commercial-cost boundary from the same deterministic TCO result.",
            },
        }

    unresolved_for_best = missing.get(best.supplier_name, [])
    is_fully_normalized = not unresolved_for_best
    comparison_basis = "comparable_landed_price"
    boundary = _decision_boundary(gap, unresolved_for_best)

    if is_fully_normalized:
        return {
            "available": True,
            "type": "comparable_commercial_cost",
            "headline": f"{annual:,.0f} {currency}/year evidenced commercial opportunity",
            "basis": f"Comparable supplier cost basis after explicitly evidenced buyer-borne costs; {incumbent.supplier_name} vs {best.supplier_name} × {volume:,.0f} units/year.",
            "comparison_basis": comparison_basis,
            "amount": annual,
            "currency": currency,
            "unit_gap": gap,
            "volume": float(volume),
            "from_supplier": incumbent.supplier_name,
            "to_supplier": best.supplier_name,
            "unit_costs": known_costs,
            "known_components": included,
            "limitations": [f"{name}: missing {', '.join(gaps)}" for name, gaps in missing.items()],
            "decision_boundary": _direct_price_boundary(float(incumbent.price_amount), float(best.price_amount), float(volume), currency, incumbent.supplier_name, best.supplier_name),
        }

    return {
        "available": True,
        "type": "partial_landed_cost",
        "headline": f"{annual:,.0f} {currency}/year known landed-cost difference — not confirmed savings",
        "basis": (
            f"Known-cost comparison only: {incumbent.supplier_name} at {incumbent_cost:,.2f} vs "
            f"{best.supplier_name} at {best_cost:,.2f} per unit after explicitly evidenced buyer-borne costs. "
            "Unknown buyer-borne components remain excluded and are not estimated."
        ),
        "comparison_basis": comparison_basis,
        "amount": annual,
        "currency": currency,
        "unit_gap": gap,
        "volume": float(volume),
        "from_supplier": incumbent.supplier_name,
        "to_supplier": best.supplier_name,
        "unit_costs": known_costs,
        "known_components": included,
        "missing_components": unresolved_for_best,
        "limitations": [f"{name}: missing {', '.join(gaps)}" for name, gaps in missing.items()],
        "decision_boundary": {
            **(boundary or {}),
            "canonical_quote_boundary": _direct_price_boundary(float(incumbent.price_amount), float(best.price_amount), float(volume), currency, incumbent.supplier_name, best.supplier_name),
        },
    }
