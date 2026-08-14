"""Deterministic commercial alternative paths.

Release 8: present viable commercial paths without asking the LLM to invent
financials, risk scores, capacities, or stakeholder preferences. The module
only uses explicit normalized evidence. It describes trade-offs; it does not
replace the primary recommendation.
"""
from __future__ import annotations

from app.pipeline.normalized_evidence import NormalizedEvidence, SupplierEvidence


def _supplier_constraints(s: SupplierEvidence) -> list[str]:
    out: list[str] = []
    if s.capacity_percent is not None and s.capacity_percent < 100:
        out.append(f"Capacity explicitly stated at {s.capacity_percent:g}%")
    if s.qualification_status != "complete":
        out.append("Qualification is not recorded as complete")
    if s.production_history_status in {"none", "unknown"}:
        out.append("Production history is not established in the supplied evidence")
    if s.incoterm and s.freight_cost_or_estimate is None:
        upper = s.incoterm.upper()
        if upper in {"FCA", "FOB", "EXW", "FAS"}:
            out.append(f"{s.incoterm} freight cost is not quantified")
    return out[:5]


def _stakeholder_impacts(normalized: NormalizedEvidence, supplier_name: str) -> list[str]:
    impacts: list[str] = []
    for v in normalized.stakeholder_views:
        text = v.statement.lower()
        if supplier_name.lower() in text or supplier_name.split()[0].lower() in text:
            impacts.append(f"{v.stakeholder_name}: {v.statement}")
    return impacts[:4]


def _supplier_option(s: SupplierEvidence, label: str, rationale: str) -> dict:
    price = None
    if s.price_usd is not None:
        price = float(s.price_usd)
    return {
        "name": label,
        "type": "supplier_path",
        "path": rationale,
        "supplier": s.supplier_name,
        "annual_spend_usd": None,
        "financial_basis": "Annual volume and an explicitly USD-denominated supplier price are both required to calculate spend." if price is None else None,
        "unit_price_usd": price,
        "what_you_gain": [
            f"Uses the explicitly stated commercial offer from {s.supplier_name}" if price is not None else f"Preserves access to {s.supplier_name} as an explicit option",
        ],
        "what_you_give_up": _supplier_constraints(s),
        "stakeholder_impacts": [],
        "evidence_strength": "supported by stated supplier evidence",
        "requires_new_evidence": _supplier_constraints(s),
    }


def build_alternative_paths(normalized: NormalizedEvidence) -> dict:
    """Build 2–3 transparent commercial paths from stated evidence only."""
    suppliers = [s for s in normalized.suppliers if s.supplier_name]
    paths: list[dict] = []
    warnings: list[str] = []

    if normalized.content_type == "price_increase":
        incumbent = next((s for s in suppliers if s.is_incumbent), None)
        alternatives = [s for s in suppliers if not s.is_incumbent]

        if incumbent:
            current = normalized.derived.resolved_annual_spend_usd
            requested = normalized.case.requested_increase_percent
            accept = {
                "name": "Continuity — accept the requested change",
                "type": "incumbent_continuity",
                "path": f"Retain {incumbent.supplier_name} and accept the supplier's stated price change.",
                "supplier": incumbent.supplier_name,
                "annual_spend_usd": round(float(current) * (1 + float(requested) / 100), 2) if current is not None and requested is not None and normalized.derived.currency_calculation_safe else None,
                "financial_basis": "Deterministic baseline annual spend × stated price change." if current is not None and requested is not None and normalized.derived.currency_calculation_safe else "Safe baseline spend or currency evidence is incomplete.",
                "unit_price_usd": incumbent.price_usd,
                "what_you_gain": ["Continuity with the incumbent relationship"] + ([f"Retains the stated {incumbent.otif_percent:g}% OTIF performance" ] if incumbent.otif_percent is not None else []),
                "what_you_give_up": [f"Accepts the requested {requested:g}% increase" if requested is not None else "Accepts the supplier's requested price movement"],
                "stakeholder_impacts": _stakeholder_impacts(normalized, incumbent.supplier_name),
                "evidence_strength": "supported by the incumbent's stated commercial and performance evidence",
                "requires_new_evidence": [],
            }
            paths.append(accept)

            hold = {
                "name": "Negotiate — protect the current baseline",
                "type": "negotiated_continuity",
                "path": f"Keep {incumbent.supplier_name} as the primary source while negotiating the requested change against the evidence available.",
                "supplier": incumbent.supplier_name,
                "annual_spend_usd": current if normalized.derived.currency_calculation_safe else None,
                "financial_basis": "Current resolved annual spend; no additional supplier concession is assumed.",
                "unit_price_usd": incumbent.price_usd,
                "what_you_gain": ["Avoids automatically accepting the requested increase", "Preserves incumbent continuity"],
                "what_you_give_up": ["Requires successful commercial negotiation"],
                "stakeholder_impacts": _stakeholder_impacts(normalized, incumbent.supplier_name),
                "evidence_strength": "commercially viable path; outcome depends on negotiation and evidence not yet supplied",
                "requires_new_evidence": ["Supplier response to the negotiation position"],
            }
            paths.append(hold)

            if alternatives:
                alt = min(alternatives, key=lambda s: float(s.price_usd) if s.price_usd is not None else float("inf"))
                dual = {
                    "name": "Leverage — develop an alternative source",
                    "type": "dual_source",
                    "path": f"Use {alt.supplier_name} as an alternative source while retaining the incumbent for continuity.",
                    "supplier": alt.supplier_name,
                    "annual_spend_usd": None,
                    "financial_basis": "A safe blended spend is not calculated because no allocation is assumed unless the evidence explicitly states one.",
                    "unit_price_usd": alt.price_usd,
                    "what_you_gain": ["Creates a concrete competitive alternative", "Reduces dependence on a single supplier over time"],
                    "what_you_give_up": _supplier_constraints(alt) + ["Requires qualification/capacity/implementation work where not already evidenced"],
                    "stakeholder_impacts": _stakeholder_impacts(normalized, alt.supplier_name),
                    "evidence_strength": "alternative exists in stated evidence; operational readiness must be verified where incomplete",
                    "requires_new_evidence": _supplier_constraints(alt),
                }
                paths.append(dual)
        else:
            warnings.append("No deterministic incumbent supplier entry was resolved; paths are limited to explicit supplier evidence.")
            paths.extend(_supplier_option(s, f"Supplier path — {s.supplier_name}", f"Use {s.supplier_name} as the named supplier option.") for s in suppliers[:3])
    else:
        priced = [s for s in suppliers if s.price_usd is not None]
        if len(priced) < 2:
            return {"available": False, "status": "NOT_TESTABLE", "summary": "At least two explicitly priced suppliers are required to build alternative paths safely.", "alternatives": [], "warnings": ["Supplier prices are incomplete or not deterministically comparable."]}
        priced.sort(key=lambda s: float(s.price_usd))
        cheapest = priced[0]
        incumbent = next((s for s in priced if s.is_incumbent), None)

        paths.append(_supplier_option(cheapest, f"Cost-led — {cheapest.supplier_name}", f"Use {cheapest.supplier_name} as the primary source based on the lowest explicitly comparable price."))
        paths[-1]["stakeholder_impacts"] = _stakeholder_impacts(normalized, cheapest.supplier_name)

        if incumbent and incumbent.supplier_name != cheapest.supplier_name:
            paths.append(_supplier_option(incumbent, f"Continuity-led — {incumbent.supplier_name}", f"Retain {incumbent.supplier_name} as the primary source despite the cheaper explicit alternative."))
            paths[-1]["stakeholder_impacts"] = _stakeholder_impacts(normalized, incumbent.supplier_name)

        if len(priced) >= 2:
            a, b = priced[0], priced[1]
            paths.append({
                "name": "Balanced — dual-source the two explicit offers",
                "type": "dual_source",
                "path": f"Maintain both {a.supplier_name} and {b.supplier_name} as sources without inventing an allocation percentage.",
                "supplier": f"{a.supplier_name} + {b.supplier_name}",
                "annual_spend_usd": None,
                "financial_basis": "No allocation percentage is assumed; use the allocation sensitivity section for explicit what-if percentages.",
                "unit_price_usd": None,
                "what_you_gain": ["Creates competitive tension", "Reduces single-source dependence"],
                "what_you_give_up": _supplier_constraints(a) + _supplier_constraints(b),
                "stakeholder_impacts": _stakeholder_impacts(normalized, a.supplier_name) + _stakeholder_impacts(normalized, b.supplier_name),
                "evidence_strength": "both suppliers are explicitly evidenced; blended economics depend on an agreed allocation",
                "requires_new_evidence": _supplier_constraints(a) + _supplier_constraints(b),
            })

    paths = paths[:3]
    if not paths:
        return {"available": False, "status": "NOT_TESTABLE", "summary": "No safe commercial alternative path could be constructed from the supplied evidence.", "alternatives": [], "warnings": warnings}

    status = "EVIDENCE_BACKED_PATHS"
    if any(p.get("requires_new_evidence") for p in paths):
        status = "EVIDENCE_BACKED_WITH_OPEN_ITEMS"

    return {
        "available": True,
        "status": status,
        "summary": "These are distinct commercial paths constructed from stated evidence. VendorEdge does not rank them by invented risk scores or assumed stakeholder weights.",
        "alternatives": paths,
        "warnings": warnings[:6],
        "method": "Deterministic path construction from normalized supplier, financial, capacity, qualification, performance and stakeholder evidence. No hidden allocation, risk score, FX, freight or duty assumptions.",
    }
