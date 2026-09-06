"""VendorEdge Release 34 — Outcome Intelligence 2.0.

Closes the decision loop without rewriting history. R34 adds deterministic
calibration, attribution and next-time controls on top of the existing R24
outcome layer.

No LLM call. No free-text financial parsing. No causal claims from sparse data.
"""
from __future__ import annotations
from typing import Any


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(actual: float, expected: float) -> float | None:
    if expected == 0:
        return None
    return round(((actual - expected) / abs(expected)) * 100, 2)


def _attribution(alignment: str, verdict: str) -> tuple[str, str]:
    if alignment == "followed" and verdict == "reasoning_held":
        return "HIGHER_ATTRIBUTION", "The recorded decision was followed and the reasoning was recorded as held; this still does not prove causality."
    if alignment == "modified":
        return "PARTIAL_ATTRIBUTION", "The decision was modified before action, so the realized result cannot be attributed wholly to the original VendorEdge recommendation."
    if alignment == "different_direction":
        return "NO_DIRECT_ATTRIBUTION", "The final action differed from VendorEdge's recommendation; do not score the realized result as a pure VendorEdge outcome."
    if verdict in {"reasoning_wrong_bad_assumption", "reasoning_wrong_bad_execution"}:
        return "DIAGNOSTIC_ONLY", "The recorded verdict identifies a failure mode, but does not establish causal contribution beyond the user's recorded assessment."
    return "UNRESOLVED_ATTRIBUTION", "Insufficient alignment information to attribute the realized result to the original recommendation."


def _controls(verdict: str, alignment: str) -> list[str]:
    controls: list[str] = []
    if verdict == "reasoning_wrong_bad_assumption":
        controls.append("Validate the failed assumption explicitly before reusing the commercial logic.")
    elif verdict == "reasoning_wrong_bad_execution":
        controls.append("Add an execution checkpoint between approval and realized value.")
    elif verdict == "ambiguous_unresolved":
        controls.append("Resolve the outcome before using this case as a learning example.")
    elif verdict == "reasoning_held":
        controls.append("Preserve the evidence and decision conditions that supported the successful reasoning.")
    if alignment == "modified":
        controls.append("Record what changed in the buyer's final decision before comparing realized value with the original expectation.")
    elif alignment == "different_direction":
        controls.append("Keep the final buyer action separate from the original VendorEdge recommendation in future outcome reviews.")
    return controls[:4]


def build_outcome_intelligence(
    position: Any,
    feedback: dict[str, Any] | None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the deterministic closed-loop outcome view."""
    f = feedback or {}
    financial = getattr(position, "financial_impact", None)
    expected = _num(getattr(financial, "potential_annual_impact_usd", None)) if financial else None
    actual = _num(f.get("actual_financial_impact_usd"))
    variance = None
    variance_pct = None
    if expected is not None and actual is not None:
        variance = round(actual - expected, 2)
        variance_pct = _pct(actual, expected)

    verdict = str(f.get("validation_verdict") or "").strip()
    alignment = str(f.get("decision_alignment") or "").strip()
    outcome_recorded = bool(f)

    learning: list[str] = []
    if verdict == "reasoning_wrong_bad_assumption":
        learning.append("Prior reasoning failed because an assumption was wrong. Re-check the assumption before reusing this decision logic.")
    elif verdict == "reasoning_wrong_bad_execution":
        learning.append("The reasoning was judged sound but execution failed. Separate decision quality from implementation discipline next time.")
    elif verdict == "reasoning_held":
        learning.append("The recorded outcome supports the original reasoning. Preserve the evidence that made the decision robust.")
    elif verdict == "ambiguous_unresolved":
        learning.append("Outcome is unresolved. Do not use this case as evidence that the recommendation was right or wrong.")

    if alignment == "modified":
        learning.append("The recommendation was modified before action. Any realized result should not be attributed entirely to the original recommendation.")
    elif alignment == "different_direction":
        learning.append("The final action differed from VendorEdge's recommendation. Do not score the realized outcome as a pure VendorEdge result.")

    if expected is not None and actual is None:
        learning.append("A deterministic financial expectation exists, but no structured actual financial impact was recorded. Financial realization cannot be scored yet.")
    if expected is not None and actual is not None and variance is not None:
        if abs(variance_pct or 0) <= 5:
            learning.append("Realized financial impact was within 5% of the original expectation.")
        elif variance < 0:
            learning.append(f"Realized financial impact was ${abs(variance):,.0f} below the original expectation. Investigate the recorded outcome before treating the miss as a model failure.")
        else:
            learning.append(f"Realized financial impact was ${variance:,.0f} above the original expectation. Investigate the outcome drivers before repeating the approach.")

    hist = history or []
    structured: list[tuple[float, float]] = []
    for row in hist:
        e = _num(row.get("expected_financial_impact_usd"))
        a = _num(row.get("actual_financial_impact_usd"))
        if e is not None and a is not None:
            structured.append((e, a))

    historical_note = "Not enough structured financial outcomes exist to quantify organizational realization accuracy."
    calibration = {
        "available": False,
        "sample_size": len(structured),
        "mean_signed_variance_percent": None,
        "mean_absolute_variance_percent": None,
        "within_10_percent_count": 0,
        "within_10_percent_percent": None,
        "direction": "INSUFFICIENT_HISTORY",
    }
    if len(structured) >= 3:
        abs_errors = [abs(a - e) for e, a in structured]
        abs_pct_errors = [abs(_pct(a, e)) for e, a in structured if _pct(a, e) is not None]
        signed_pct_errors = [_pct(a, e) for e, a in structured if _pct(a, e) is not None]
        mean_abs_error = round(sum(abs_errors) / len(abs_errors), 2)
        mean_abs_pct = round(sum(abs_pct_errors) / len(abs_pct_errors), 2) if abs_pct_errors else None
        mean_signed_pct = round(sum(signed_pct_errors) / len(signed_pct_errors), 2) if signed_pct_errors else None
        within_10 = sum(1 for e, a in structured if (_pct(a, e) is not None and abs(_pct(a, e)) <= 10))
        within_10_pct = round(within_10 / len(structured) * 100, 1)
        direction = "OVER_ESTIMATED" if (mean_signed_pct or 0) < -5 else "UNDER_ESTIMATED" if (mean_signed_pct or 0) > 5 else "GENERALLY_ALIGNED"
        calibration = {
            "available": True,
            "sample_size": len(structured),
            "mean_signed_variance_percent": mean_signed_pct,
            "mean_absolute_variance_percent": mean_abs_pct,
            "within_10_percent_count": within_10,
            "within_10_percent_percent": within_10_pct,
            "direction": direction,
        }
        historical_note = (
            f"Across {len(structured)} structured outcome(s), mean absolute financial variance is "
            f"${mean_abs_error:,.0f}"
            + (f" ({mean_abs_pct:.1f}% of expected impact)." if mean_abs_pct is not None else ".")
        )

    attribution_level, attribution_detail = _attribution(alignment, verdict)
    if expected is None:
        realization_status = "NO_EXPECTATION"
    elif actual is None:
        realization_status = "ACTUAL_NOT_RECORDED"
    elif abs(variance_pct or 0) <= 5:
        realization_status = "CLOSE_TO_EXPECTATION"
    elif (variance_pct or 0) < 0:
        realization_status = "BELOW_EXPECTATION"
    else:
        realization_status = "ABOVE_EXPECTATION"

    if not outcome_recorded:
        learning_status = "AWAITING_OUTCOME"
    elif verdict == "ambiguous_unresolved":
        learning_status = "UNRESOLVED"
    elif expected is not None and actual is not None and attribution_level in {"HIGHER_ATTRIBUTION", "PARTIAL_ATTRIBUTION"}:
        learning_status = "MEASURABLE"
    else:
        learning_status = "RECORDED_BUT_LIMITED"

    return {
        "available": outcome_recorded or expected is not None,
        "version": "R34.1",
        "title": "Outcome Intelligence",
        "outcome_recorded": outcome_recorded,
        "decision_alignment": alignment or None,
        "validation_verdict": verdict or None,
        "expected_financial_impact_usd": expected,
        "actual_financial_impact_usd": actual,
        "financial_variance_usd": variance,
        "financial_variance_percent": variance_pct,
        "financial_variance_available": expected is not None and actual is not None,
        "realization_status": realization_status,
        "learning_status": learning_status,
        "attribution_level": attribution_level,
        "attribution_detail": attribution_detail,
        "actual_measurement_basis": f.get("actual_measurement_basis") or None,
        "outcome_description": f.get("outcome_description") or None,
        "unexpected_insight": f.get("unexpected_insight") or None,
        "learning_signals": learning[:6],
        "next_time_controls": _controls(verdict, alignment),
        "historical_realization_note": historical_note,
        "calibration": calibration,
        "structured_outcome_count": len(structured),
        "attribution_note": (
            "A realized result is not attributed wholly to VendorEdge when the recommendation was modified or rejected. "
            "Financial variance is calculated only from structured values recorded on the same USD annual-impact basis."
        ),
        "honesty_note": "Outcome intelligence measures what happened after the decision. It does not rewrite the original recommendation or prove causality from one case.",
        "method": "Deterministic closed-loop outcome analysis; no LLM call, no free-text financial parsing and no recommendation mutation.",
    }
