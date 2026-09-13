"""
Final answer reconciliation.

Runs immediately before a buyer-facing answer is considered complete.
Most of the individual guarantees this checks are already structurally
enforced elsewhere in the pipeline (financial.py can't physically read
category_annual_spend_usd; there is no code path for model output to
write into position.financial_impact; decision_audit.py already detects
contradictions and evidence-retention gaps). This module exists as an
explicit, testable safety net verifying those guarantees actually held
for THIS specific answer -- catching a future code change that breaks
one of them, or a case shape none of the individual fixes anticipated --
not as the only place these things are checked.

Deliberately conservative: this never tries to fix or silently rewrite
the answer. It reports violations; the caller decides what to do with
them (in practice: log, and in the cases that matter most -- entity/
currency/value mismatches -- refuse to serve the wrong number rather
than guess at a correction).
"""
from __future__ import annotations
from typing import Any

from pydantic import BaseModel

from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence
from app.pipeline.financial import compute_financial_impact
from app.pipeline.question_coverage import CoverageRequirement


class ReconciliationViolation(BaseModel):
    check: str
    severity: str  # "blocking" or "advisory"
    detail: str


class ReconciliationResult(BaseModel):
    passed: bool
    violations: list[ReconciliationViolation] = []


def reconcile_answer(
    normalized: NormalizedEvidence,
    position: CommercialPosition,
    coverage_requirements: list[CoverageRequirement] | None = None,
) -> ReconciliationResult:
    violations: list[ReconciliationViolation] = []

    # G. Entity + F. Currency + B. Value, together: recompute the
    # deterministic financial figure fresh, right now, from the same
    # canonical evidence, and confirm the answer's own financial_impact
    # is byte-identical to it. This is the direct, structural proof
    # against the exact confirmed defect (a correct calculation bound to
    # the wrong entity, e.g. category spend instead of supplier spend):
    # if position.financial_impact ever diverges from a fresh
    # recomputation, something downstream altered or replaced it.
    fresh = compute_financial_impact(normalized)
    fi = position.financial_impact
    if fresh is not None and fi is not None:
        if fi.currency != fresh.currency:
            violations.append(ReconciliationViolation(
                check="currency", severity="blocking",
                detail=f"financial_impact.currency ({fi.currency}) does not match the recomputed canonical currency ({fresh.currency})",
            ))
        if fi.potential_annual_impact != fresh.potential_annual_impact:
            violations.append(ReconciliationViolation(
                check="value", severity="blocking",
                detail=f"financial_impact.potential_annual_impact ({fi.potential_annual_impact}) does not match the recomputed canonical value ({fresh.potential_annual_impact}) -- this is exactly the class of defect (a correct number bound to the wrong entity, or a model-supplied number replacing the deterministic one) this check exists to catch",
            ))
    elif fresh is not None and fi is None:
        violations.append(ReconciliationViolation(
            check="value", severity="blocking",
            detail="a deterministic financial calculation is genuinely available from the evidence but position.financial_impact is missing entirely",
        ))

    # C. Question coverage: a requirement whose calculation genuinely
    # exists (CALCULATED) but was never marked as reaching the answer
    # (never promoted to SURFACED) is exactly the "silently disappeared"
    # failure this whole release exists to close.
    if coverage_requirements:
        for req in coverage_requirements:
            if req.status == "CALCULATED":
                violations.append(ReconciliationViolation(
                    check="question_coverage", severity="blocking",
                    detail=f"requirement '{req.requirement_id}' ({req.requested_analysis}) was calculated but never surfaced in the final answer",
                ))

    # D. Contradiction state: if decision_audit detected a claim-vs-
    # history contradiction, evidence_integrity_status must genuinely
    # reflect CONTRADICTED, not be silently downgraded to something
    # calmer by a later step.
    audit = position.decision_audit
    if audit is not None:
        if audit.contradictions and audit.evidence_integrity_status != "CONTRADICTED":
            violations.append(ReconciliationViolation(
                check="contradiction_state", severity="blocking",
                detail=f"decision_audit lists {len(audit.contradictions)} contradiction(s) but evidence_integrity_status is '{audit.evidence_integrity_status}', not CONTRADICTED",
            ))

    # E. Target/walk-away integrity, checked as internal consistency: if
    # negotiation_intelligence marked a dimension NOT_ESTABLISHED, its
    # own buyer_move text must never simultaneously say "hold the stated
    # target" -- that would be exactly the kind of self-contradicting
    # answer (item 4's fix and this check disagreeing) this validator
    # exists to catch, independent of trusting that the upstream fix
    # always fires correctly.
    ni = getattr(position, "negotiation_intelligence", None)
    if ni and isinstance(ni, dict):
        for scenario in ni.get("response_scenarios", []):
            if scenario.get("target_state") == "NOT_ESTABLISHED" and "hold the stated target" in str(scenario.get("buyer_move", "")).lower():
                violations.append(ReconciliationViolation(
                    check="target_integrity", severity="blocking",
                    detail=f"scenario '{scenario.get('trigger')}' is marked NOT_ESTABLISHED but its own buyer_move text still says to hold a target",
                ))

    return ReconciliationResult(passed=not any(v.severity == "blocking" for v in violations), violations=violations)
