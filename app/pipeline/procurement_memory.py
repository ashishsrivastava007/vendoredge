"""VendorEdge Release 23 — Procurement Memory.

Deterministic institutional memory built from persisted completed decisions and
recorded outcomes. Memory is evidence about what happened before; it is not a
new model opinion and it never mutates the current recommendation.

R23 deliberately distinguishes:
- remembered facts from prior cases;
- outcome-backed lessons;
- supplier-specific history;
- genuine patterns (only when sample size is sufficient);
- unresolved history where an outcome was never recorded.
"""
from __future__ import annotations
from typing import Any

from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _uniq(items: list[str], limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean(item)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out[:limit]


def _case_summary(row: dict[str, Any]) -> dict[str, Any]:
    outcome = _clean(row.get("outcome_description"))
    verdict = _clean(row.get("validation_verdict"))
    alignment = _clean(row.get("decision_alignment"))
    unexpected = _clean(row.get("unexpected_insight"))
    return {
        "decision_id": str(row.get("id")) if row.get("id") else None,
        "date": row.get("created_at").isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
        "question": _clean(row.get("raw_question"))[:280],
        "outcome": outcome[:400] if outcome else None,
        "validation_verdict": verdict or None,
        "decision_alignment": alignment or None,
        "unexpected_insight": unexpected[:400] if unexpected else None,
        "outcome_recorded": bool(outcome or verdict or alignment or unexpected),
    }


def _pattern_note(cases: list[dict[str, Any]], subject: str) -> str:
    if not cases:
        return f"No prior recorded {subject} history was found. Do not infer a pattern."
    if len(cases) == 1:
        return f"One prior {subject} case is available. It is useful context, but it is not enough to establish a genuine pattern."
    recorded = [c for c in cases if c.get("outcome_recorded")]
    if len(cases) < 3:
        return f"{len(cases)} prior {subject} cases are available, but the sample is still too small to label a stable pattern."
    if len(recorded) < 3:
        return f"{len(cases)} prior {subject} cases are available, but only {len(recorded)} have recorded outcomes. Do not generalize beyond the recorded evidence."
    held = sum(1 for c in recorded if c.get("validation_verdict") == "reasoning_held")
    wrong = sum(1 for c in recorded if c.get("validation_verdict") in {"reasoning_wrong_bad_assumption", "reasoning_wrong_bad_execution"})
    if held and wrong:
        return f"A mixed outcome pattern exists across {len(recorded)} recorded {subject} outcomes ({held} held, {wrong} did not). Treat the history as a warning signal, not a guarantee."
    if held == len(recorded):
        return f"A consistent positive pattern is visible across {len(recorded)} recorded {subject} outcomes, but it remains historical evidence rather than a prediction."
    return f"A consistent miss pattern is visible across {len(recorded)} recorded {subject} outcomes. Previous failure reasons should be explicitly checked before repeating the approach."


def _lessons(cases: list[dict[str, Any]], limit: int = 6) -> list[dict[str, str]]:
    lessons: list[dict[str, str]] = []
    for c in cases:
        verdict = c.get("validation_verdict")
        if verdict in {"reasoning_wrong_bad_assumption", "reasoning_wrong_bad_execution"}:
            lessons.append({
                "type": "prior_miss",
                "lesson": f"A prior case did not hold ({verdict}). Check the underlying failure before reusing the same approach.",
                "source_date": str(c.get("date") or "unknown"),
            })
        if c.get("unexpected_insight"):
            lessons.append({
                "type": "unexpected_insight",
                "lesson": c["unexpected_insight"],
                "source_date": str(c.get("date") or "unknown"),
            })
    return lessons[:limit]


def build_procurement_memory(
    normalized: NormalizedEvidence,
    position: CommercialPosition,
    org_history: list[dict[str, Any]] | None = None,
    supplier_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    org_cases = [_case_summary(r) for r in (org_history or [])]
    supplier_cases = [_case_summary(r) for r in (supplier_history or [])]
    subject = normalized.content_type.replace("_", " ")

    supplier_names = [s.supplier_name for s in normalized.suppliers if s.supplier_name]
    supplier_names.extend([normalized.common.supplier_name] if normalized.common.supplier_name else [])
    supplier_names = _uniq(supplier_names, 8)

    remembered_facts: list[str] = []
    for case in supplier_cases[:3]:
        if case["outcome"]:
            remembered_facts.append(f"Prior supplier outcome: {case['outcome']}")
        elif case["question"]:
            remembered_facts.append(f"Prior supplier case: {case['question']}")
    for case in org_cases[:3]:
        if case["unexpected_insight"]:
            remembered_facts.append(f"Prior organizational insight: {case['unexpected_insight']}")

    lessons = _lessons(supplier_cases or org_cases)
    warnings: list[str] = []
    for case in supplier_cases:
        if case["validation_verdict"] in {"reasoning_wrong_bad_assumption", "reasoning_wrong_bad_execution"}:
            warnings.append("A prior case involving this supplier was not upheld; inspect the failure reason before repeating the approach.")
        if not case["outcome_recorded"]:
            warnings.append("At least one prior supplier case has no recorded outcome; absence of an outcome is not evidence of success.")

    return {
        "available": bool(org_cases or supplier_cases),
        "version": "R23.1",
        "title": "Procurement Memory",
        "supplier_scope": supplier_names,
        "organization_case_count": len(org_cases),
        "supplier_case_count": len(supplier_cases),
        "memory_strength": "STRONG" if len(supplier_cases) >= 3 and sum(c["outcome_recorded"] for c in supplier_cases) >= 3 else ("EMERGING" if supplier_cases or org_cases else "NONE"),
        "supplier_pattern": _pattern_note(supplier_cases, "supplier") if supplier_cases else "No supplier-specific history is available for the named supplier(s).",
        "category_pattern": _pattern_note(org_cases, subject),
        "remembered_facts": _uniq(remembered_facts, 6),
        "lessons": lessons,
        "prior_cases": supplier_cases[:6],
        "organizational_context": org_cases[:5],
        "warnings": _uniq(warnings, 5),
        "method": "Deterministic memory assembled from persisted completed decisions and recorded feedback. No embeddings, no LLM call, no inferred supplier psychology, no recommendation mutation.",
        "honesty_note": "History is context, not proof of future behavior. Patterns are withheld when the real sample is too small or outcomes are missing.",
    }
