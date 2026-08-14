"""Deterministic decision-audit layer.

Release 5 goal: make every recommendation explainable as an auditable chain:
material evidence -> uncertainty/conflict -> stakeholder trade-off -> reversal condition.
This module never invents evidence and never decides whether the recommendation is good.
"""
from __future__ import annotations
from typing import Literal
from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence

AuditStatus = Literal["PROVEN", "INFERRED", "UNKNOWN", "CONTRADICTED"]


def _status_for_field(normalized: NormalizedEvidence, field: str) -> AuditStatus:
    prov = normalized.provenance.get(field)
    if prov is None:
        return "UNKNOWN"
    if prov.conflicting:
        return "CONTRADICTED"
    if prov.source in {"llm_extraction", "user_followup", "both_agree", "database_history"}:
        return "PROVEN"
    if prov.source == "derived_calculation":
        return "PROVEN"
    if prov.source == "deterministic_fallback":
        return "INFERRED"
    return "UNKNOWN"


def _value_text(value) -> str:
    if value is None or value == "":
        return "Not provided"
    return str(value)


def build_decision_audit(normalized: NormalizedEvidence, position: CommercialPosition) -> dict:
    """Build the user-facing audit from normalized evidence only.

    The model's recommendation is deliberately not treated as evidence. The
    only model-derived element carried into the audit is the disconfirming
    condition, which is clearly labelled as the model's stated reversal test.
    """
    items: list[dict] = []

    if normalized.content_type == "price_increase":
        fields = [
            ("Current commercial terms", "current_price_or_terms", normalized.case.current_price_or_terms),
            ("Requested increase", "requested_increase_percent", normalized.case.requested_increase_percent),
            ("Supplier justification", "suppliers_stated_justification", normalized.case.suppliers_stated_justification),
            ("Annual spend", "annual_spend_usd", normalized.case.annual_spend_usd),
        ]
    else:
        fields = [
            ("Supplier pricing", "price_per_supplier", normalized.case.price_per_supplier),
            ("Suppliers compared", "number_of_suppliers_being_compared", normalized.case.number_of_suppliers_being_compared),
            ("Payment terms", "payment_terms_per_supplier", normalized.case.payment_terms_per_supplier),
            ("Lead times", "lead_time_per_supplier", normalized.case.lead_time_per_supplier),
        ]

    for label, field, value in fields:
        items.append({"label": label, "status": _status_for_field(normalized, field), "evidence": _value_text(value)})

    for supplier in normalized.suppliers[:6]:
        details = []
        for label, value in (("price", supplier.price_display or supplier.price_usd),
                             ("OTIF", supplier.otif_percent),
                             ("defect rate", supplier.defect_rate_percent),
                             ("lead time", supplier.lead_time_weeks),
                             ("capacity", supplier.capacity_percent),
                             ("qualification", supplier.qualification_status)):
            if value is not None:
                details.append(f"{label}: {value}")
        if details:
            items.append({"label": supplier.supplier_name, "status": "PROVEN", "evidence": "; ".join(details)})

    uncertainties: list[str] = []
    for field, prov in normalized.provenance.items():
        if prov.conflicting:
            uncertainties.append(f"Conflicting evidence for {field}")
    for supplier in normalized.suppliers:
        if supplier.qualification_status in {"unknown", "not_started", "in_progress"}:
            uncertainties.append(f"{supplier.supplier_name}: qualification status is not complete")
        if supplier.production_history_status == "unknown":
            uncertainties.append(f"{supplier.supplier_name}: production history is unknown")
        if supplier.certification_status == "unknown":
            uncertainties.append(f"{supplier.supplier_name}: certification status is unknown")
    if not normalized.stakeholder_views:
        pass
    else:
        for view in normalized.stakeholder_views:
            if view.view_type in {"risk_concern", "rumor", "experience"}:
                uncertainties.append(f"{view.stakeholder_name}: {view.view_type} — {view.statement}")

    conflict_fields = [f for f, p in normalized.provenance.items() if p.conflicting]
    if conflict_fields:
        status = "CONTRADICTED"
    elif uncertainties:
        status = "UNKNOWN"
    else:
        status = "PROVEN"

    conflict, conflict_details = _stakeholder_conflict(normalized)
    stakeholder_tradeoffs = []
    for view in normalized.stakeholder_views[:8]:
        stakeholder_tradeoffs.append({
            "stakeholder": view.stakeholder_name,
            "type": view.view_type,
            "view": view.statement,
            "basis": view.basis,
        })

    reversal_conditions = []
    if position.disconfirming_condition:
        reversal_conditions.append(position.disconfirming_condition)
    for u in uncertainties[:4]:
        reversal_conditions.append(f"Reassess if this unresolved point changes materially: {u}")

    inferred = []
    if position.commercial_hypothesis:
        inferred.append(position.commercial_hypothesis)

    counts = {k: 0 for k in ("PROVEN", "INFERRED", "UNKNOWN", "CONTRADICTED")}
    for item in items:
        counts[item["status"]] += 1
    counts["INFERRED"] += len(inferred)
    counts["UNKNOWN"] += len(uncertainties)
    if conflict:
        counts["CONTRADICTED"] += len(conflict_details)

    return {
        "material_evidence": items[:12],
        "inferred_signals": inferred[:3],
        "uncertainties": uncertainties[:10],
        "stakeholder_tradeoffs": stakeholder_tradeoffs,
        "stakeholder_conflict": conflict_details,
        "reversal_conditions": reversal_conditions[:6],
        "evidence_integrity_status": status,
        "evidence_counts": counts,
    }


def _stakeholder_conflict(normalized: NormalizedEvidence) -> tuple[bool, list[str]]:
    from app.pipeline.decision_integrity import stakeholder_conflict_summary
    return stakeholder_conflict_summary(normalized)
