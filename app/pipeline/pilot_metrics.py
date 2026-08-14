"""Release 15: deterministic customer-pilot value metrics.

Turns real recorded pilot feedback/outcomes into a small readiness dashboard.
No inferred revenue, no synthetic satisfaction scores, and no LLM calls.
"""
from __future__ import annotations
from collections import Counter
from typing import Any


def build_pilot_metrics(experience_rows: list[dict[str, Any]], outcome_rows: list[dict[str, Any]]) -> dict[str, Any]:
    exp=len(experience_rows); out=len(outcome_rows)
    reuse=sum(bool(r.get("would_use_again")) for r in experience_rows)
    trust=Counter(str(r.get("trust_level")) for r in experience_rows if r.get("trust_level"))
    ease=Counter(str(r.get("ease_of_use")) for r in experience_rows if r.get("ease_of_use"))
    held=sum(1 for r in outcome_rows if r.get("validation_verdict") == "reasoning_held")
    verdict_rate=round(held/out*100) if out else None
    reuse_rate=round(reuse/exp*100) if exp else None
    if exp < 3 or out < 3:
        readiness="INSUFFICIENT_REAL_DATA"
    elif reuse_rate is not None and reuse_rate >= 80 and verdict_rate is not None and verdict_rate >= 70:
        readiness="PROMISING"
    else:
        readiness="LEARN_BEFORE_SCALING"
    return {"experience_responses":exp,"outcome_records":out,"would_use_again_rate":reuse_rate,
            "trust_distribution":dict(trust),"ease_distribution":dict(ease),
            "reasoning_held_rate":verdict_rate,"readiness":readiness,
            "method":"Deterministic counts from recorded customer feedback and commercial outcomes; no model inference and no revenue claim."}
