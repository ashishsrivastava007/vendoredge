"""R26 Decision-under-Uncertainty engine.

The goal is not perfect information. The goal is the safest defensible action
available now, while explicitly separating known evidence, unknowns and the
small number of missing answers that could actually flip the decision.
"""
from __future__ import annotations
from typing import Any

from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence


def _critical_question(normalized: NormalizedEvidence) -> tuple[str, str] | None:
    if normalized.content_type == "price_increase":
        case = normalized.case
        criticality = getattr(case, "how_critical_is_this_supplier_relationship", None)
        if not criticality:
            return ("How critical is this supplier relationship right now?", "The answer can change how much continuity risk should influence the decision.")
        if getattr(case, "requested_increase_percent", None) is not None and getattr(case, "annual_spend_usd", None) is None:
            return ("What is the annual spend or expected annual volume affected by this change?", "It determines the commercial exposure without requiring VendorEdge to invent a number.")
    if normalized.content_type == "quote_comparison":
        if normalized.common.annual_volume_units is None:
            return ("What annual volume is actually at stake?", "It is needed only if you want the supplier price difference translated into annual economics.")
    return None


def build_decision_under_uncertainty(normalized: NormalizedEvidence, position: CommercialPosition) -> dict[str, Any]:
    audit = position.decision_audit
    unknowns = list((audit.uncertainties if audit else [])[:4])
    critical = _critical_question(normalized)
    readiness = (position.control_tower or {}).get("readiness", "CONDITIONAL") if isinstance(position.control_tower, dict) else "CONDITIONAL"
    confidence = position.confidence.level

    if critical:
        question, why = critical
        return {
            "mode": "ASK",
            "label": "ONE QUESTION CAN CHANGE THE DECISION",
            "recommendation": position.recommendation,
            "confidence": confidence,
            "known": list((position.commercial_insights or [])[:3]),
            "unknowns": unknowns,
            "question": question,
            "question_why": why,
            "safe_now": False,
            "reversibility": "Do not make an irreversible long-term commitment until this answer is known.",
            "review_trigger": "Re-run the decision after the answer is provided.",
        }

    # If the existing decision is conditional but no single missing answer is
    # decision-critical, the safest useful action is the validated position
    # with explicit containment rather than refusing to decide.
    return {
        "mode": "DECIDE" if readiness == "READY" else "PROTECT",
        "label": "SAFE DECISION NOW" if readiness != "READY" else "DECISION READY",
        "recommendation": position.recommendation,
        "confidence": confidence,
        "known": list((position.commercial_insights or [])[:3]),
        "unknowns": unknowns,
        "question": None,
        "question_why": None,
        "safe_now": True,
        "reversibility": "Prefer the smallest reversible commitment that satisfies the immediate requirement when uncertainty remains." if readiness != "READY" else "Proceed within the stated commercial conditions.",
        "review_trigger": position.disconfirming_condition or "Reassess if the stated decision conditions change.",
    }
