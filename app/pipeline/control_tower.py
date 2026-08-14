"""Release 9: deterministic Commercial Decision Control Tower.

This is a presentation/decision-control layer only. It does not invent facts,
re-rank suppliers, or call an LLM. It assembles already validated outputs into
an executive decision view and prioritises open evidence using deterministic
rules.
"""
from __future__ import annotations
from typing import Any

from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence


def _priority_items(normalized: NormalizedEvidence, position: CommercialPosition) -> tuple[list[str], list[str], list[str]]:
    audit = position.decision_audit
    critical: list[str] = []
    important: list[str] = []
    later: list[str] = []

    if audit:
        for item in audit.uncertainties:
            text = str(item)
            low = text.lower()
            if any(k in low for k in ("freight", "landed", "baseline", "capacity", "qualification", "price", "cost")):
                critical.append(text)
            else:
                important.append(text)

    alt = position.alternative_analysis or {}
    if isinstance(alt, dict):
        for item in alt.get("warnings", [])[:6]:
            if item not in critical:
                critical.append(str(item))
        for path in alt.get("alternatives", [])[:3]:
            for item in path.get("requires_new_evidence", [])[:4]:
                text = str(item)
                if text not in critical and text not in important:
                    important.append(text)

    stress = position.stress_test or {}
    if isinstance(stress, dict):
        for item in stress.get("warnings", [])[:6]:
            text = str(item)
            if text not in critical:
                critical.append(text)

    # Keep the tower useful rather than dumping the entire audit into it.
    critical = list(dict.fromkeys(critical))[:5]
    important = [x for x in dict.fromkeys(important) if x not in critical][:5]
    later = list(dict.fromkeys(later))[:3]
    return critical, important, later


def _action_items(critical: list[str], reversal_conditions: list[str]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for item in critical[:3]:
        actions.append({"priority": "CRITICAL", "action": item})
    for item in reversal_conditions[:2]:
        if item not in [a["action"] for a in actions]:
            actions.append({"priority": "DECISION-CHANGING", "action": item})
    return actions[:5]


def build_control_tower(normalized: NormalizedEvidence, position: CommercialPosition) -> dict[str, Any]:
    audit = position.decision_audit
    critical, important, later = _priority_items(normalized, position)
    reversal = audit.reversal_conditions[:6] if audit else []
    conflicts = audit.stakeholder_conflict[:6] if audit else []

    alternatives = position.alternative_analysis or {}
    alt_count = len(alternatives.get("alternatives", [])) if isinstance(alternatives, dict) else 0
    stress = position.stress_test or {}
    stress_status = stress.get("status") if isinstance(stress, dict) else None

    if audit and audit.evidence_integrity_status == "CONTRADICTED":
        readiness = "HOLD"
        readiness_reason = "Conflicting evidence exists. Resolve it before acting."
    elif critical:
        readiness = "CONDITIONAL"
        readiness_reason = "A decision is possible, but critical evidence gaps remain."
    elif stress_status == "SENSITIVE":
        readiness = "CONDITIONAL"
        readiness_reason = "The recommendation is sensitive to stated commercial constraints."
    else:
        readiness = "READY"
        readiness_reason = "No critical unresolved evidence blocker was identified from the stated evidence."

    return {
        "available": True,
        "readiness": readiness,
        "readiness_reason": readiness_reason,
        "recommended_action": position.recommendation,
        "confidence": position.confidence.level,
        "evidence_integrity": audit.evidence_integrity_status if audit else "UNKNOWN",
        "critical_before_action": critical,
        "important_not_blocking": important,
        "useful_later": later,
        "decision_changers": reversal,
        "stakeholder_conflicts": conflicts,
        "alternative_count": alt_count,
        "stress_status": stress_status or "NOT_TESTED",
        "financial_impact_available": getattr(position, "financial_impact", None) is not None,
        "action_items": _action_items(critical, reversal),
        "method": "Deterministic executive summary assembled only from validated evidence, audit, alternatives, stress test and financial outputs; no new assumptions or LLM judgement introduced.",
    }
