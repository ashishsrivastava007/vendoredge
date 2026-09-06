"""R37 — Commercial Reasoning Loop.

A deterministic reconciliation layer that makes the existing VendorEdge
intelligence layers reason as one decision system. It does not create facts,
calculations, thresholds or recommendations. The model/validator layers own
those; this layer exposes the chain and the strongest counter-case so a buyer
can see why the decision is stable, conditional, or needs review.
"""
from __future__ import annotations
from typing import Any
from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence


def _uniq(items: list[str], limit: int = 6) -> list[str]:
    out: list[str] = []
    seen = set()
    for item in items:
        s = str(item).strip()
        if s and s.lower() not in seen:
            out.append(s)
            seen.add(s.lower())
    return out[:limit]


def build_commercial_reasoning_loop(
    normalized: NormalizedEvidence,
    position: CommercialPosition,
) -> dict[str, Any]:
    audit = position.decision_audit
    cockpit = position.decision_cockpit or {}
    orchestration = position.model_orchestration or {}
    uncertainty = position.decision_under_uncertainty or cockpit.get("decision_under_uncertainty") or {}
    econ = position.financial_impact

    evidence = []
    if audit:
        evidence.extend(
            item.get("evidence", "")
            for item in (audit.material_evidence or [])
            if item.get("status") in {"PROVEN", "CALCULATED"} and item.get("evidence")
        )
    evidence = _uniq(evidence, 4)

    economic_fact = None
    if econ:
        economic_fact = (
            f"{econ.annual_spend_usd:,.0f} annual spend × {econ.requested_change_percent:g}% "
            f"requested change = {econ.potential_annual_impact_usd:,.0f} potential annual impact."
        )

    why = _uniq(list(position.commercial_insights or []), 3)
    changers = _uniq(
        list(cockpit.get("decision_changers") or [])
        + list(uncertainty.get("decision_changers") or [])
        + list((audit.reversal_conditions if audit else []) or []),
        5,
    )

    # The counter-case is deliberately sourced from the independent challenger
    # when present. If unavailable, we do not manufacture a counterargument.
    counter = orchestration.get("alternative_frame") if isinstance(orchestration, dict) else None
    challenge_level = str(orchestration.get("challenge_level", "none")) if isinstance(orchestration, dict) else "none"
    verdict = str(orchestration.get("verdict", "")) if isinstance(orchestration, dict) else ""

    if challenge_level == "critical" or verdict == "requires_human_review":
        stability = "REQUIRES_REVIEW"
        resolution = "The independent challenge found a material issue; keep the primary recommendation separate and resolve the challenge before consequential action."
    elif challenge_level == "material":
        stability = "CONDITIONAL"
        resolution = "The primary recommendation survives only with the material challenge explicitly considered."
    elif challenge_level == "watch" or verdict == "supports_with_caveat":
        stability = "CONDITIONAL"
        resolution = "The primary recommendation remains the best current path, with a documented caveat to monitor."
    else:
        stability = "STABLE_WITH_CURRENT_EVIDENCE"
        resolution = "No material independent challenge is recorded; the recommendation remains tied to the current evidence and stated conditions."

    steps = [
        {"step": 1, "label": "SITUATION", "finding": position.recommendation},
    ]
    if economic_fact:
        steps.append({"step": 2, "label": "ECONOMICS", "finding": economic_fact})
    if evidence:
        steps.append({"step": 3, "label": "EVIDENCE", "finding": "; ".join(evidence[:2])})
    if why:
        steps.append({"step": 4, "label": "TRADE-OFF", "finding": why[0]})
    steps.append({"step": len(steps) + 1, "label": "DECISION", "finding": resolution})

    return {
        "available": True,
        "version": "R37.0",
        "stability": stability,
        "primary_recommendation": position.recommendation,
        "reasoning_trace": steps[:5],
        "strongest_evidence": evidence,
        "commercial_tension": why[:2],
        "strongest_counterargument": counter or "No independent counterargument was generated for this case.",
        "counterargument_source": "independent_challenger" if counter else "none",
        "counterargument_challenge_level": challenge_level,
        "resolution": resolution,
        "decision_changers": changers,
        "unknowns": _uniq(list(uncertainty.get("unknowns") or []) + list((audit.uncertainties if audit else []) or []), 4),
        "method": "Deterministic reconciliation of validated evidence, economics, uncertainty and the independent challenger; it does not create or mutate commercial facts, thresholds or the primary recommendation.",
    }
