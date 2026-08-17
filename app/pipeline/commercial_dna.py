"""VendorEdge Release 25 — Commercial DNA.

Deterministic organizational intelligence assembled from the organization's
recorded decisions and measured outcomes. R25 is deliberately conservative:
this module reports repeated, observable decision and realization signals; it
never invents procurement psychology, causal explanations, or a predictive
score from sparse data.

The Commercial DNA layer is read-time intelligence. It never mutates the
current commercial recommendation and makes no LLM call.
"""
from __future__ import annotations
from typing import Any


MIN_OUTCOMES_FOR_SIGNAL = 3
MIN_OUTCOMES_FOR_BEHAVIOR_SIGNAL = 5


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _pct(n: int | float, d: int | float) -> float | None:
    if not d:
        return None
    return round((n / d) * 100, 1)


def _position_financial(row: dict[str, Any]) -> float | None:
    position = row.get("commercial_position") or {}
    if not isinstance(position, dict):
        return None
    financial = position.get("financial_impact") or {}
    if not isinstance(financial, dict):
        return None
    return _num(financial.get("potential_annual_impact_usd"))


def _structured_outcomes(rows: list[dict[str, Any]]) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        expected = _position_financial(row)
        actual = _num(row.get("actual_financial_impact_usd"))
        if expected is not None and actual is not None:
            pairs.append((expected, actual))
    return pairs


def build_commercial_dna(
    current_content_type: str | None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a conservative organizational Commercial DNA view.

    History rows must come from the current authenticated organization. The
    function only uses explicitly persisted fields and never infers causality.
    """
    rows = history or []
    outcomes = [r for r in rows if _clean(r.get("validation_verdict"))]
    pairs = _structured_outcomes(rows)

    held = sum(1 for r in outcomes if r.get("validation_verdict") == "reasoning_held")
    assumption_misses = sum(1 for r in outcomes if r.get("validation_verdict") == "reasoning_wrong_bad_assumption")
    execution_misses = sum(1 for r in outcomes if r.get("validation_verdict") == "reasoning_wrong_bad_execution")
    unresolved = sum(1 for r in outcomes if r.get("validation_verdict") == "ambiguous_unresolved")

    followed = sum(1 for r in outcomes if r.get("decision_alignment") == "followed")
    modified = sum(1 for r in outcomes if r.get("decision_alignment") == "modified")
    different = sum(1 for r in outcomes if r.get("decision_alignment") == "different_direction")

    total_expected = round(sum(e for e, _ in pairs), 2) if pairs else None
    total_actual = round(sum(a for _, a in pairs), 2) if pairs else None
    aggregate_variance = round(total_actual - total_expected, 2) if pairs else None
    realization_pct = round((total_actual / total_expected) * 100, 1) if pairs and total_expected not in (None, 0) else None

    # "Leakage" is intentionally narrow: only the measured shortfall against
    # positive expected value is called leakage. We never claim its cause.
    measured_shortfalls = [max(e - a, 0.0) for e, a in pairs if e > 0]
    realized_shortfall = round(sum(measured_shortfalls), 2) if measured_shortfalls else None

    same_type_outcomes = [
        r for r in outcomes
        if current_content_type and r.get("classified_content_type") == current_content_type
    ]

    signals: list[dict[str, Any]] = []
    if len(pairs) >= MIN_OUTCOMES_FOR_SIGNAL and aggregate_variance is not None and aggregate_variance < 0:
        signals.append({
            "type": "realization_gap",
            "severity": "material" if abs(aggregate_variance) >= 0.1 * abs(total_expected or 1) else "watch",
            "title": "Expected value is not fully being realized",
            "finding": (
                f"Across {len(pairs)} structured outcome(s), actual measured impact trails expected impact "
                f"by ${abs(aggregate_variance):,.0f} ({abs(100 - (realization_pct or 0)):.1f}% of expected)."
            ),
            "evidence_count": len(pairs),
            "causality": "Not established from outcome data alone.",
        })

    if len(outcomes) >= MIN_OUTCOMES_FOR_BEHAVIOR_SIGNAL and assumption_misses >= max(3, round(len(outcomes) * 0.4)):
        signals.append({
            "type": "assumption_risk",
            "severity": "material",
            "title": "Assumption misses recur in recorded outcomes",
            "finding": (
                f"{assumption_misses} of {len(outcomes)} recorded outcomes ({_pct(assumption_misses, len(outcomes)):.1f}%) "
                "were labelled as reasoning misses caused by a bad assumption."
            ),
            "evidence_count": len(outcomes),
            "causality": "This is a repeated recorded failure mode, not proof of the underlying cause beyond the recorded verdict.",
        })

    if len(outcomes) >= MIN_OUTCOMES_FOR_BEHAVIOR_SIGNAL and execution_misses >= max(3, round(len(outcomes) * 0.4)):
        signals.append({
            "type": "execution_risk",
            "severity": "material",
            "title": "Execution misses recur after decisions",
            "finding": (
                f"{execution_misses} of {len(outcomes)} recorded outcomes ({_pct(execution_misses, len(outcomes)):.1f}%) "
                "were labelled as execution misses."
            ),
            "evidence_count": len(outcomes),
            "causality": "The recorded verdict identifies execution as the failure mode; it does not identify every operational root cause.",
        })

    changed = modified + different
    if len(outcomes) >= MIN_OUTCOMES_FOR_BEHAVIOR_SIGNAL and changed >= max(3, round(len(outcomes) * 0.5)):
        signals.append({
            "type": "decision_intervention",
            "severity": "watch",
            "title": "Human intervention frequently changes the recommended direction",
            "finding": (
                f"{changed} of {len(outcomes)} recorded decisions ({_pct(changed, len(outcomes)):.1f}%) "
                "were modified or taken in a different direction."
            ),
            "evidence_count": len(outcomes),
            "causality": "This measures decision alignment, not whether the intervention was good or bad.",
        })

    # Pick one action only when the evidence supports a meaningful repeated signal.
    action = None
    if signals:
        priority = {"realization_gap": 1, "assumption_risk": 2, "execution_risk": 3, "decision_intervention": 4}
        strongest = sorted(signals, key=lambda s: priority.get(s["type"], 99))[0]
        actions = {
            "realization_gap": "Close the expected-to-realized value gap before scaling the same commercial playbook.",
            "assumption_risk": "Add an explicit assumption-validation checkpoint before repeating the decision pattern.",
            "execution_risk": "Add an implementation-control checkpoint between award and realized value.",
            "decision_intervention": "Review why buyers repeatedly change direction before treating the model as the default path.",
        }
        action = actions.get(strongest["type"])

    if len(outcomes) < MIN_OUTCOMES_FOR_SIGNAL:
        maturity = "INSUFFICIENT_HISTORY"
        maturity_note = (
            f"Only {len(outcomes)} recorded outcome(s) are available. Commercial DNA is not yet strong enough "
            "to make an organizational pattern claim."
        )
    elif len(outcomes) < MIN_OUTCOMES_FOR_BEHAVIOR_SIGNAL:
        maturity = "EMERGING"
        maturity_note = (
            f"{len(outcomes)} recorded outcomes are available. Some historical signals can be shown, "
            "but behavioral conclusions remain deliberately limited."
        )
    else:
        maturity = "ESTABLISHED_HISTORY"
        maturity_note = (
            f"{len(outcomes)} recorded outcomes are available. Repeated signals can be surfaced when their "
            "evidence threshold is met; they remain historical evidence, not predictions."
        )

    return {
        "available": bool(rows),
        "version": "R25.1",
        "title": "Commercial DNA",
        "maturity": maturity,
        "maturity_note": maturity_note,
        "organization_decision_count": len(rows),
        "recorded_outcome_count": len(outcomes),
        "structured_financial_outcome_count": len(pairs),
        "current_content_type": current_content_type,
        "current_content_type_outcome_count": len(same_type_outcomes),
        "outcome_mix": {
            "reasoning_held": held,
            "reasoning_wrong_bad_assumption": assumption_misses,
            "reasoning_wrong_bad_execution": execution_misses,
            "ambiguous_unresolved": unresolved,
        },
        "decision_alignment_mix": {
            "followed": followed,
            "modified": modified,
            "different_direction": different,
        },
        "financial_realization": {
            "expected_total_usd": total_expected,
            "actual_total_usd": total_actual,
            "aggregate_variance_usd": aggregate_variance,
            "realization_percent": realization_pct,
            "measured_shortfall_usd": realized_shortfall,
            "available": len(pairs) >= MIN_OUTCOMES_FOR_SIGNAL,
            "basis": "Structured expected and actual annual-impact values only; no free-text parsing.",
        },
        "signals": signals[:4],
        "one_behavior_to_change": action,
        "honesty_note": (
            "Commercial DNA reports repeated recorded behavior and measured realization. "
            "It does not infer supplier psychology, claim causality from sparse outcomes, "
            "or turn historical performance into a forecast."
        ),
    }
