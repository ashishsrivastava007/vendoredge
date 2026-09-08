"""R39 — Commercial Memory.

A compact, buyer-first memory layer that unifies supplier history,
organizational precedent, and repeated observed patterns. Read-only and
deterministic: history is evidence of what happened, not a prediction.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.pipeline.normalized_evidence import NormalizedEvidence


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _year(value: Any) -> int | None:
    if value is None:
        return None
    if hasattr(value, "year"):
        try:
            return int(value.year)
        except Exception:
            return None
    text = _clean(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).year
    except Exception:
        return None


def _case_summary(row: dict[str, Any]) -> dict[str, Any]:
    position = row.get("commercial_position") or {}
    if not isinstance(position, dict):
        position = {}
    feedback = row.get("feedback") or {}
    if not isinstance(feedback, dict):
        feedback = {}
    inputs = row.get("user_supplied_inputs") or {}
    if not isinstance(inputs, dict):
        inputs = {}
    return {
        "decision_id": str(row.get("id")) if row.get("id") else None,
        "date": row.get("created_at").isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
        "year": _year(row.get("created_at")),
        "content_type": _clean(row.get("classified_content_type")) or None,
        "decision_category": _clean(inputs.get("__decision_category__")) or None,
        "workflow_mode": _clean(inputs.get("__workflow_mode__")) or None,
        "question": _clean(row.get("raw_question"))[:280] or None,
        "supplier_name": _clean(inputs.get("supplier_name")) or None,
        "recommendation": _clean(position.get("recommendation"))[:260] or None,
        "outcome": _clean(feedback.get("outcome_description"))[:320] or None,
        "validation_verdict": _clean(feedback.get("validation_verdict")) or None,
        "decision_alignment": _clean(feedback.get("decision_alignment")) or None,
        "unexpected_insight": _clean(feedback.get("unexpected_insight"))[:320] or None,
        "outcome_recorded": bool(
            feedback.get("outcome_description")
            or feedback.get("validation_verdict")
            or feedback.get("decision_alignment")
            or feedback.get("unexpected_insight")
        ),
    }


def _dedupe(items: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean(item)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
            if len(out) >= limit:
                break
    return out


def build_commercial_memory(
    normalized: NormalizedEvidence,
    supplier_memory: dict[str, Any] | None = None,
    org_history: list[dict[str, Any]] | None = None,
    broader_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    supplier_memory = supplier_memory if isinstance(supplier_memory, dict) else {}
    same_type = [_case_summary(r) for r in (org_history or [])]
    broad = [_case_summary(r) for r in (broader_history or [])]
    supplier_name = _clean(normalized.common.supplier_name)
    current_type = _clean(normalized.content_type)
    current_year = datetime.now(timezone.utc).year

    # Preserve one copy of each supplier precedent; combine the richer R33
    # records with the broader history scan without fabricating matches.
    supplier_cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in supplier_memory.get("prior_cases") or []:
        if isinstance(row, dict):
            item_id = _clean(row.get("decision_id"))
            if item_id and item_id not in seen_ids:
                supplier_cases.append(row)
                seen_ids.add(item_id)
    for row in broad:
        row_supplier = _clean(row.get("supplier_name"))
        row_id = _clean(row.get("decision_id"))
        if supplier_name and row_supplier.casefold() == supplier_name.casefold() and row_id not in seen_ids:
            supplier_cases.append(row)
            if row_id:
                seen_ids.add(row_id)

    year_cases = [r for r in broad if r.get("year") == current_year]
    year_same_type = [r for r in year_cases if r.get("content_type") == current_type]
    activity_keys: list[str] = []
    for r in year_cases:
        if r.get("content_type"):
            activity_keys.append(r["content_type"])
        elif r.get("decision_category"):
            activity_keys.append(f"{r['decision_category']}_general")
    type_counts = Counter(activity_keys)

    repeated_signals: list[dict[str, Any]] = []
    for activity_key, count in type_counts.most_common(5):
        if count >= 2:
            label = activity_key.replace("_general", "").replace("_", " ")
            repeated_signals.append({
                "signal": "REPEATED_ACTIVITY",
                "subject": label,
                "count": count,
                "period": str(current_year),
                "finding": f"{count} completed {label} case(s) were recorded this year.",
                "interpretation": "Observed activity only; this does not predict supplier behavior or category outcomes.",
            })

    outcome_cases = [r for r in supplier_cases if r.get("outcome_recorded")]
    precedent = outcome_cases[0] if outcome_cases else (supplier_cases[0] if supplier_cases else None)

    lessons: list[str] = []
    for row in outcome_cases:
        if row.get("unexpected_insight"):
            lessons.append(str(row["unexpected_insight"]))
        elif row.get("outcome"):
            lessons.append(f"Recorded outcome from prior case: {row['outcome']}")
        if len(lessons) >= 3:
            break

    pattern_level = "OBSERVED" if len(year_same_type) >= 3 else ("EMERGING" if len(year_same_type) >= 2 else "NONE")
    return {
        "available": bool(same_type or supplier_cases or broad),
        "version": "R39.0",
        "title": "Commercial Memory",
        "supplier_name": supplier_name or None,
        "scope": {
            "supplier_cases": len(supplier_cases),
            "same_type_cases": len(same_type),
            "current_year_completed_cases": len(year_cases),
            "current_year_same_type_cases": len(year_same_type),
        },
        "pattern_level": pattern_level,
        "repeated_signals": repeated_signals[:4],
        "strongest_precedent": precedent,
        "lessons": _dedupe(lessons, 3),
        "next_time_note": (
            "Use the strongest precedent as context only; do not copy its recommendation without checking today's evidence."
            if precedent else
            "No outcome-backed precedent is available yet. Record the outcome of this decision to strengthen future memory."
        ),
        "method": "Deterministic commercial memory from tenant-scoped prior decisions and recorded outcomes; no prediction, LLM call, embeddings or recommendation mutation.",
    }
