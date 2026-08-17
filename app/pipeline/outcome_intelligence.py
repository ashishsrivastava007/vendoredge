"""VendorEdge Release 24 — Outcome Intelligence.

Deterministic comparison of what VendorEdge expected with what the user later
recorded as the actual outcome. R24 deliberately separates:
- decision outcome (did the reasoning hold?);
- execution outcome (was the decision followed?);
- measurable financial realization (only when the user records a structured
  value on the same USD annual-impact basis);
- learning signals (what should be checked next time).

No LLM call. No mutation of the immutable commercial position. No parsing of
free-text outcomes into numbers: structured actual values are required for
financial variance.
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


def build_outcome_intelligence(
    position: Any,
    feedback: dict[str, Any] | None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the R24 view without changing the stored commercial position."""
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
    structured = []
    for row in hist:
        e = _num(row.get("expected_financial_impact_usd"))
        a = _num(row.get("actual_financial_impact_usd"))
        if e is not None and a is not None:
            structured.append((e, a))

    historical_note = "Not enough structured financial outcomes exist to quantify organizational realization accuracy."
    if len(structured) >= 3:
        abs_errors = [abs(a - e) for e, a in structured]
        abs_pct_errors = [abs(_pct(a, e)) for e, a in structured if _pct(a, e) is not None]
        mean_abs_error = round(sum(abs_errors) / len(abs_errors), 2)
        mean_abs_pct = round(sum(abs_pct_errors) / len(abs_pct_errors), 2) if abs_pct_errors else None
        historical_note = (
            f"Across {len(structured)} structured outcome(s), mean absolute financial variance is "
            f"${mean_abs_error:,.0f}"
            + (f" ({mean_abs_pct:.1f}% of expected impact)." if mean_abs_pct is not None else ".")
        )

    return {
        "available": outcome_recorded or expected is not None,
        "version": "R24.1",
        "title": "Outcome Intelligence",
        "outcome_recorded": outcome_recorded,
        "decision_alignment": alignment or None,
        "validation_verdict": verdict or None,
        "expected_financial_impact_usd": expected,
        "actual_financial_impact_usd": actual,
        "financial_variance_usd": variance,
        "financial_variance_percent": variance_pct,
        "financial_variance_available": expected is not None and actual is not None,
        "actual_measurement_basis": f.get("actual_measurement_basis") or None,
        "outcome_description": f.get("outcome_description") or None,
        "unexpected_insight": f.get("unexpected_insight") or None,
        "learning_signals": learning[:6],
        "historical_realization_note": historical_note,
        "structured_outcome_count": len(structured),
        "attribution_note": (
            "A realized result is not attributed wholly to VendorEdge when the recommendation was modified or rejected. "
            "Financial variance is calculated only from structured values recorded on the same USD annual-impact basis."
        ),
        "honesty_note": "Outcome intelligence measures what happened after the decision. It does not rewrite the original recommendation or prove causality from one case.",
    }
