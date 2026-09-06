"""VendorEdge Release 33 — Supplier Memory 2.0.

A deterministic, supplier-centric commercial profile assembled at read/reasoning
 time from the organization's completed decision history. This is deliberately
not supplier prediction: it remembers captured commercial baselines, prior
VendorEdge positions, and recorded outcomes, and highlights only deterministic
changes between comparable snapshots.

No LLM call. No embeddings. No supplier-psychology inference. No recommendation
mutation.
"""
from __future__ import annotations

from typing import Any

from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence


PROFILE_FIELDS = (
    "incoterm",
    "currency",
    "payment_terms",
    "lead_time_weeks",
    "otif_percent",
    "defect_rate_percent",
    "capacity_percent",
    "qualification_status",
    "certification_status",
    "preferred_supplier_status",
)


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _supplier_name_matches(value: Any, target: str) -> bool:
    return _clean(value).casefold() == _clean(target).casefold()


def _current_supplier_snapshot(normalized: NormalizedEvidence, supplier_name: str) -> dict[str, Any]:
    match = next((s for s in normalized.suppliers if _supplier_name_matches(s.supplier_name, supplier_name)), None)
    if match is not None:
        return {
            "supplier_name": match.supplier_name,
            "incoterm": match.incoterm,
            "currency": match.currency,
            "payment_terms": match.payment_terms,
            "lead_time_weeks": match.lead_time_weeks,
            "otif_percent": match.otif_percent,
            "defect_rate_percent": match.defect_rate_percent,
            "capacity_percent": match.capacity_percent,
            "qualification_status": match.qualification_status,
            "certification_status": match.certification_status,
            "preferred_supplier_status": match.preferred_supplier_status,
            "price_display": match.price_display,
            "price_amount": match.price_amount,
            "freight_cost_or_estimate": match.freight_cost_or_estimate,
            "role": "incumbent" if match.is_incumbent else "alternative",
        }
    if _supplier_name_matches(normalized.common.supplier_name, supplier_name):
        return {
            "supplier_name": normalized.common.supplier_name,
            "incoterm": normalized.common.incoterm,
            "currency": normalized.common.supplier_currency,
            "payment_terms": getattr(normalized.case, "payment_terms", None),
            "lead_time_weeks": None,
            "otif_percent": None,
            "defect_rate_percent": None,
            "capacity_percent": None,
            "qualification_status": "unknown",
            "certification_status": "unknown",
            "preferred_supplier_status": "unknown",
            "price_display": None,
            "price_amount": None,
            "freight_cost_or_estimate": getattr(normalized.case, "freight_cost_or_estimate", None),
            "role": "incumbent",
        }
    return {"supplier_name": supplier_name}


def _historical_suppliers(position: Any) -> list[dict[str, Any]]:
    if not isinstance(position, dict):
        try:
            position = position.model_dump()
        except Exception:
            return []
    truth = position.get("commercial_truth_model") or {}
    parties = truth.get("parties") or {}
    suppliers = parties.get("suppliers") or []
    return [s for s in suppliers if isinstance(s, dict) and _clean(s.get("name"))]


def _snapshot_from_history(position: Any, supplier_name: str) -> dict[str, Any] | None:
    for s in _historical_suppliers(position):
        if _supplier_name_matches(s.get("name"), supplier_name):
            # R20's structural model intentionally contains only fields it can
            # safely carry. Preserve those fields without inventing missing ones.
            return {
                "supplier_name": s.get("name"),
                "incoterm": s.get("incoterm"),
                "currency": s.get("currency"),
                "payment_terms": s.get("payment_terms"),
                "lead_time_weeks": s.get("lead_time_weeks"),
                "otif_percent": s.get("otif_percent"),
                "defect_rate_percent": s.get("defect_rate_percent"),
                "capacity_percent": s.get("capacity_percent"),
                "qualification_status": s.get("qualification_status"),
                "certification_status": s.get("certification_status"),
                "preferred_supplier_status": s.get("preferred_supplier_status"),
                "price_display": s.get("price"),
                "price_amount": None,
                "freight_cost_or_estimate": s.get("freight"),
                "role": s.get("role"),
            }
    return None


def _prior_case(row: dict[str, Any], supplier_name: str) -> dict[str, Any] | None:
    position = row.get("commercial_position") or {}
    snapshot = _snapshot_from_history(position, supplier_name)
    # Single-supplier price-increase cases may have only the supplier name in
    # the common truth-model fallback, so use that name as a valid match.
    if snapshot is None:
        truth = position.get("commercial_truth_model") if isinstance(position, dict) else None
        common_name = ((truth or {}).get("parties") or {}).get("suppliers")
        if not common_name and _supplier_name_matches((row.get("user_supplied_inputs") or {}).get("supplier_name"), supplier_name):
            snapshot = {"supplier_name": supplier_name}
    if snapshot is None:
        return None

    feedback = row.get("feedback") or {
        "outcome_description": row.get("outcome_description"),
        "validation_verdict": row.get("validation_verdict"),
        "decision_alignment": row.get("decision_alignment"),
    }
    return {
        "decision_id": str(row.get("id")) if row.get("id") else None,
        "date": row.get("created_at").isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
        "content_type": row.get("classified_content_type"),
        "snapshot": snapshot,
        "recommendation": _clean(position.get("recommendation"))[:320] or None,
        "opening_position": _clean(position.get("opening_position"))[:240] or None,
        "walk_away": _clean(position.get("walk_away_threshold"))[:240] or None,
        "outcome": _clean(feedback.get("outcome_description"))[:360] or None,
        "validation_verdict": _clean(feedback.get("validation_verdict")) or None,
        "decision_alignment": _clean(feedback.get("decision_alignment")) or None,
        "outcome_recorded": bool(feedback),
    }


def _compare(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, Any]]:
    if not previous:
        return []
    changes: list[dict[str, Any]] = []
    for field in PROFILE_FIELDS:
        before = previous.get(field)
        after = current.get(field)
        if before in (None, "", "unknown") or after in (None, "", "unknown"):
            continue
        if str(before).casefold() != str(after).casefold():
            changes.append({"field": field, "previous": before, "current": after})
    return changes[:10]


def build_supplier_memory(
    normalized: NormalizedEvidence,
    position: CommercialPosition,
    history_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    supplier_name = normalized.common.supplier_name
    if not supplier_name and normalized.suppliers:
        supplier_name = normalized.suppliers[0].supplier_name
    if not supplier_name:
        return {
            "available": False,
            "version": "R33.1",
            "title": "Supplier Memory",
            "reason": "No specific supplier name is available, so VendorEdge will not create a supplier profile.",
            "method": "Deterministic supplier memory; no LLM call, embeddings, prediction or recommendation mutation.",
        }

    current = _current_supplier_snapshot(normalized, supplier_name)
    matched: list[dict[str, Any]] = []
    for row in history_rows or []:
        item = _prior_case(row, supplier_name)
        if item:
            matched.append(item)
    matched.sort(key=lambda x: str(x.get("date") or ""), reverse=True)

    outcomes = [x for x in matched if x.get("outcome_recorded")]
    held = sum(1 for x in outcomes if x.get("validation_verdict") == "reasoning_held")
    misses = sum(1 for x in outcomes if x.get("validation_verdict") in {"reasoning_wrong_bad_assumption", "reasoning_wrong_bad_execution"})
    latest = matched[0] if matched else None
    changes = _compare((latest or {}).get("snapshot"), current)

    known = {k: v for k, v in current.items() if k in PROFILE_FIELDS and v not in (None, "", "unknown")}
    unknown = [k for k in PROFILE_FIELDS if k not in known]

    if len(matched) >= 3 and len(outcomes) >= 3:
        strength = "ESTABLISHED"
    elif matched:
        strength = "EMERGING"
    else:
        strength = "NEW_SUPPLIER"

    return {
        "available": True,
        "version": "R33.1",
        "title": "Supplier Memory",
        "supplier_name": supplier_name,
        "memory_strength": strength,
        "prior_case_count": len(matched),
        "recorded_outcome_count": len(outcomes),
        "outcome_summary": {"reasoning_held": held, "recorded_misses": misses},
        "current_baseline": current,
        "previous_baseline": (latest or {}).get("snapshot"),
        "deterministic_changes": changes,
        "known_fields": sorted(known),
        "current_unknown_fields": unknown,
        "prior_cases": matched[:6],
        "history_note": (
            "No supplier-specific history exists yet; this is a first captured baseline."
            if not matched else
            "Prior cases are historical context. A prior VendorEdge position is not a fact about supplier behavior."
        ),
        "method": "Deterministic supplier profile assembled from captured commercial evidence, prior decision records and recorded outcomes. No LLM call, embeddings, supplier psychology or recommendation mutation.",
    }
