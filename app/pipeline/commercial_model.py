"""VendorEdge Release 20 — deterministic Commercial Truth Model.

R20 turns the validated case into a stable, inspectable representation of the
commercial situation. It is deliberately not another LLM summary: every field
is derived from NormalizedEvidence and already-validated VendorEdge outputs.

The model is designed to become the contract consumed by R21 (Decision Flip),
R22 (War Room), R23 (Memory) and R24 (Outcome Loop). Unknown stays unknown;
no missing field is silently promoted into a fact.
"""
from __future__ import annotations

from typing import Any

from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence, SupplierEvidence

R20_VERSION = "R20.1"
MAX_SUPPLIERS = 8
MAX_STAKEHOLDERS = 8
MAX_UNKNOWN_SIGNALS = 8
MAX_DEPENDENCIES = 8
MAX_DECISION_CHANGERS = 6
MAX_EVIDENCE_FACTS = 12


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _supplier_record(s: SupplierEvidence) -> dict[str, Any]:
    return {
        "name": s.supplier_name,
        "role": "incumbent" if s.is_incumbent else "alternative",
        "currency": s.currency,
        "price": s.price_display if s.price_display is not None else s.price_amount,
        "price_amount": s.price_amount,
        "incoterm": s.incoterm,
        "region": s.region,
        "lead_time_weeks": s.lead_time_weeks,
        "otif_percent": s.otif_percent,
        "defect_rate_percent": s.defect_rate_percent,
        "payment_terms": s.payment_terms,
        "capacity_percent": s.capacity_percent,
        "qualification_status": s.qualification_status,
        "qualification_percent": s.qualification_percent,
        "freight": s.freight_cost_or_estimate,
        "production_history_status": s.production_history_status,
        "certification_status": s.certification_status,
        "preferred_supplier_status": s.preferred_supplier_status,
    }


def _evidence_posture(normalized: NormalizedEvidence, position: CommercialPosition) -> dict[str, Any]:
    audit = position.decision_audit
    counts = dict((audit.evidence_counts if audit else {}) or {})
    provenance = normalized.provenance or {}
    conflicts = [name for name, p in provenance.items() if p.conflicting]
    proven = int(counts.get("PROVEN", 0) or 0)
    unknown = int(counts.get("UNKNOWN", 0) or 0)
    contradicted = int(counts.get("CONTRADICTED", 0) or 0)
    inferred = int(counts.get("INFERRED", 0) or 0)
    if contradicted or conflicts:
        standing = "CONTRADICTED"
    elif unknown:
        standing = "UNKNOWN"
    elif inferred and not proven:
        standing = "INFERRED"
    elif proven:
        standing = "PROVEN"
    else:
        standing = "UNKNOWN"
    return {
        "standing": standing,
        "counts": counts,
        "provenance_fields": len(provenance),
        "conflicting_fields": conflicts[:MAX_UNKNOWN_SIGNALS],
        "uncertainties": list((audit.uncertainties if audit else []) or [])[:MAX_UNKNOWN_SIGNALS],
        "method": "Derived from the normalized evidence provenance ledger and final decision audit; no re-extraction.",
    }


def _supplier_economics(normalized: NormalizedEvidence) -> dict[str, Any]:
    suppliers = [s for s in normalized.suppliers if s.price_amount is not None and s.currency]
    same_currency = len({s.currency for s in suppliers}) == 1 and len(suppliers) >= 2
    result: dict[str, Any] = {
        "comparable_quote_prices": same_currency,
        "comparison_currency": suppliers[0].currency if same_currency else None,
        "lowest_supplier": None,
        "highest_supplier": None,
        "unit_price_spread": None,
        "annualized_price_spread": None,
        "basis": "Only same-currency supplier quote prices are compared; no FX is introduced.",
    }
    if not same_currency:
        return result
    ordered = sorted(suppliers, key=lambda s: float(s.price_amount))
    low, high = ordered[0], ordered[-1]
    spread = float(high.price_amount) - float(low.price_amount)
    result.update({
        "lowest_supplier": low.supplier_name,
        "highest_supplier": high.supplier_name,
        "unit_price_spread": spread,
        "annualized_price_spread": spread * float(normalized.common.annual_volume_units) if normalized.common.annual_volume_units is not None else None,
    })
    return result


def _commercial_dimensions(normalized: NormalizedEvidence) -> list[dict[str, Any]]:
    dimensions: list[dict[str, Any]] = []
    supplier_count = len(normalized.suppliers)
    dimensions.append({"name": "price", "status": "available" if normalized.suppliers or normalized.common.unit_price_usd is not None or getattr(normalized.case, "current_price_or_terms", None) else "unknown"})
    dimensions.append({"name": "delivery", "status": "available" if any(s.lead_time_weeks is not None or s.otif_percent is not None for s in normalized.suppliers) else "unknown"})
    dimensions.append({"name": "quality", "status": "available" if any(s.defect_rate_percent is not None for s in normalized.suppliers) or bool(getattr(normalized.case, "quality_or_defect_history_per_supplier", None)) else "unknown"})
    dimensions.append({"name": "payment_terms", "status": "available" if any(s.payment_terms for s in normalized.suppliers) or bool(getattr(normalized.case, "payment_terms_per_supplier", None)) else "unknown"})
    dimensions.append({"name": "capacity", "status": "available" if any(s.capacity_percent is not None for s in normalized.suppliers) else "unknown"})
    dimensions.append({"name": "qualification", "status": "available" if any(s.qualification_status != "unknown" for s in normalized.suppliers) else "unknown"})
    dimensions.append({"name": "logistics", "status": "available" if normalized.derived.freight_relevant or any(s.freight_cost_or_estimate for s in normalized.suppliers) else "unknown"})
    if supplier_count == 0 and normalized.common.supplier_name:
        dimensions.append({"name": "relationship", "status": "incumbent_context_available"})
    return dimensions


def _dependencies(normalized: NormalizedEvidence, position: CommercialPosition) -> list[dict[str, Any]]:
    deps: list[dict[str, Any]] = []
    for s in normalized.suppliers:
        if s.qualification_status in {"not_started", "in_progress", "unknown"}:
            deps.append({"type": "supplier_qualification", "supplier": s.supplier_name, "status": s.qualification_status, "decision_effect": "Award path may depend on qualification completion."})
        if s.capacity_percent is not None and s.capacity_percent < 100:
            deps.append({"type": "supplier_capacity", "supplier": s.supplier_name, "status": "constrained", "decision_effect": "Available capacity may constrain executable award volume."})
    audit = position.decision_audit
    for item in list((audit.reversal_conditions if audit else []) or []):
        deps.append({"type": "decision_reversal_condition", "supplier": None, "status": "open", "decision_effect": str(item)})
    if normalized.common.supplier_name and normalized.case.__class__.__name__ == "PriceIncreaseEvidence":
        if normalized.case.switching_cost_usd is not None:
            deps.append({"type": "switching_cost", "supplier": normalized.common.supplier_name, "status": "quantified", "value_usd": normalized.case.switching_cost_usd, "decision_effect": "Switching economics affect the feasible alternative path."})
    seen = set()
    unique = []
    for d in deps:
        key = (d.get("type"), d.get("supplier"), d.get("decision_effect"))
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique[:MAX_DEPENDENCIES]


def _stakeholders(normalized: NormalizedEvidence) -> list[dict[str, Any]]:
    return [
        {
            "name": s.stakeholder_name,
            "role": s.role,
            "view_type": s.view_type,
            "statement": s.statement,
            "basis": s.basis,
        }
        for s in normalized.stakeholder_views[:MAX_STAKEHOLDERS]
    ]


def _key_facts(normalized: NormalizedEvidence) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for field_name, provenance in list(normalized.provenance.items()):
        if field_name in {"price_per_supplier", "current_price_or_terms", "annual_spend_usd", "requested_increase_percent", "number_of_suppliers_being_compared"}:
            facts.append({
                "field": field_name,
                "source": provenance.source,
                "supplier": provenance.supplier_name,
                "conflicting": provenance.conflicting,
            })
    return facts[:MAX_EVIDENCE_FACTS]


def build_commercial_truth_model(normalized: NormalizedEvidence, position: CommercialPosition) -> dict[str, Any]:
    """Build the R20 structural commercial model without an LLM call."""
    case = normalized.case
    audit = position.decision_audit
    passport = position.decision_passport or {}
    tower = position.control_tower or {}
    if hasattr(tower, "model_dump"):
        tower = tower.model_dump()

    suppliers = [_supplier_record(s) for s in normalized.suppliers[:MAX_SUPPLIERS]]
    if not suppliers and normalized.common.supplier_name:
        suppliers = [{"name": normalized.common.supplier_name, "role": "incumbent", "currency": normalized.common.supplier_currency}]

    annual_volume = normalized.common.annual_volume_units
    annual_spend = normalized.derived.resolved_annual_spend_usd
    if annual_spend is None and position.financial_impact:
        annual_spend = position.financial_impact.annual_spend_usd

    economic_exposure = {
        "annual_volume_units": annual_volume,
        "annual_spend_usd": annual_spend,
        "financial_impact_usd": position.financial_impact.net_exposure_usd if position.financial_impact else None,
        "switching_cost_usd": getattr(case, "switching_cost_usd", None),
        "duty_rate_percent": normalized.common.duty_or_tax_rate_percent,
        "freight_relevant": normalized.derived.freight_relevant,
        "supplier_quote_comparison": _supplier_economics(normalized),
    }

    decision_changers = list((passport.get("decision_changers") or [])[:MAX_DECISION_CHANGERS])
    if not decision_changers and audit:
        decision_changers = list((audit.reversal_conditions or [])[:MAX_DECISION_CHANGERS])

    unknowns = list((passport.get("unknowns") or [])[:MAX_UNKNOWN_SIGNALS])
    if audit:
        for u in audit.uncertainties:
            if u not in unknowns and len(unknowns) < MAX_UNKNOWN_SIGNALS:
                unknowns.append(u)

    model = {
        "title": "VendorEdge Commercial Truth Model",
        "version": R20_VERSION,
        "status": "STRUCTURED",
        "purpose": "A deterministic structural representation of the commercial situation used as the foundation for decision-flip, war-room, memory and outcome layers.",
        "situation": {
            "content_type": normalized.content_type,
            "decision_type": position.decision_type,
            "raw_question_reference": "stored on the decision record; intentionally not duplicated here",
            "readiness": tower.get("readiness", "CONDITIONAL"),
            "recommendation": position.recommendation,
            "confidence": position.confidence.level,
        },
        "parties": {
            "buyer_context": {
                "supplier_region_or_market": normalized.common.supplier_region_or_market,
                "buyer_currency": normalized.common.supplier_currency,
            },
            "suppliers": suppliers,
            "supplier_count": len(suppliers),
        },
        "economics": economic_exposure,
        "commercial_dimensions": _commercial_dimensions(normalized),
        "dependencies": _dependencies(normalized, position),
        "stakeholders": _stakeholders(normalized),
        "decision": {
            "recommendation": position.recommendation,
            "decision_changers": decision_changers,
            "unknowns": unknowns,
            "assumptions": list(position.assumptions[:6]),
            "disconfirming_condition": position.disconfirming_condition,
        },
        "evidence": _evidence_posture(normalized, position),
        "key_evidence_links": _key_facts(normalized),
        "trace": {
            "trust_status": (position.trust_certification or {}).get("status"),
            "audit_integrity": audit.evidence_integrity_status if audit else None,
            "method": "All values are derived from the single NormalizedEvidence object and validated deterministic outputs. No second extraction, no hidden inference, no LLM call.",
        },
    }
    return model
