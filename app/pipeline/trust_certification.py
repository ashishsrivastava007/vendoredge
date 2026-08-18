"""VendorEdge Release 19 — deterministic Trust Certification.

R19 turns the existing safety controls into one explicit, user-facing assurance
artifact. It does not decide whether the recommendation is commercially good;
it certifies whether the *decision process* passed a set of structural checks.

No LLM call. No new facts. No new financial calculations.
"""
from __future__ import annotations

from typing import Any

from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence
from app.pipeline.contradiction_check import check_all_contradictions
from app.pipeline.claim_integrity import check_all_claim_overstatements


CRITICAL_CHECKS = {
    "evidence_provenance",
    "internal_consistency",
    "claim_integrity",
    "confidence_enforcement",
    "decision_traceability",
}


def _check(name: str, status: str, summary: str, *, critical: bool = False, details: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "critical": critical,
        "summary": summary,
        "details": (details or [])[:6],
    }


def _evidence_provenance(normalized: NormalizedEvidence) -> tuple[str, str, list[str]]:
    load_bearing = {
        "price_increase": {"current_price_or_terms", "requested_increase_percent", "suppliers_stated_justification", "annual_spend_usd"},
        "quote_comparison": {"price_per_supplier", "number_of_suppliers_being_compared"},
    }.get(normalized.content_type, set())
    if not load_bearing:
        return "PASS", "No content-specific load-bearing provenance rule was required.", []
    missing = sorted(f for f in load_bearing if f not in normalized.provenance)
    conflicting = sorted(f for f in load_bearing if f in normalized.provenance and normalized.provenance[f].conflicting)
    if conflicting:
        return "FAIL", "Load-bearing evidence contains unresolved conflicts.", [f"Conflicting: {x}" for x in conflicting]
    if missing:
        return "WARN", "Some load-bearing evidence has no captured provenance.", [f"Missing provenance: {x}" for x in missing]
    return "PASS", "All load-bearing evidence fields have provenance and no unresolved conflict.", []


def _supplier_attribution(normalized: NormalizedEvidence) -> tuple[str, str, list[str]]:
    if not normalized.suppliers:
        return "PASS", "No multi-supplier attribution check was required.", []
    missing = []
    for supplier in normalized.suppliers:
        for field, value in (("price", supplier.price_amount), ("price display", supplier.price_display), ("freight", supplier.freight_cost_or_estimate)):
            if value is not None:
                prov = next((p for p in normalized.provenance.values() if p.supplier_name == supplier.supplier_name), None)
                if prov is None:
                    missing.append(f"{supplier.supplier_name}: {field} lacks supplier-specific provenance")
                    break
    if missing:
        return "WARN", "Some supplier-specific facts could not be tied to supplier-specific provenance.", missing
    return "PASS", "Supplier-specific evidence is represented without collapsing named suppliers into one case-level source.", []


def _confidence_enforcement(position: CommercialPosition) -> tuple[str, str, list[str]]:
    note = (position.confidence.derivation_note or "").lower()
    if "system-owned confidence level" not in note or "deterministic evidence checks" not in note:
        return "FAIL", "The final confidence does not show the system-owned deterministic ceiling.", []
    return "PASS", f"Final confidence is system-owned: {position.confidence.level}.", []


def _traceability(position: CommercialPosition) -> tuple[str, str, list[str]]:
    audit = position.decision_audit
    if audit is None:
        return "FAIL", "No decision audit is attached to the final position.", []
    if not audit.material_evidence and not audit.evidence_counts:
        return "WARN", "Decision audit exists but contains limited material-evidence detail.", []
    return "PASS", "The recommendation has a deterministic decision audit attached.", []


def _deterministic_controls(position: CommercialPosition, normalized: NormalizedEvidence) -> tuple[str, str, list[str]]:
    details = []
    if position.financial_impact is not None:
        details.append("financial impact is stored as a structured deterministic object")
    if position.sensitivity_analysis:
        details.append("sensitivity analysis is present")
    if position.stress_test:
        details.append("adversarial stress test is present")
    if position.alternative_analysis:
        details.append("alternative-path analysis is present")
    if len(details) >= 2:
        return "PASS", "Multiple system-owned deterministic controls are present.", details
    return "WARN", "The case completed, but some deterministic challenge layers are unavailable.", details


def build_trust_certification(normalized: NormalizedEvidence, position: CommercialPosition) -> dict[str, Any]:
    """Return a deterministic R19 trust certificate for the final position."""
    checks: list[dict[str, Any]] = []

    status, summary, details = _evidence_provenance(normalized)
    checks.append(_check("evidence_provenance", status, summary, critical=True, details=details))

    contradictory = check_all_contradictions(position, normalized)
    checks.append(_check(
        "internal_consistency",
        "FAIL" if contradictory else "PASS",
        "The final recommendation does not contradict the normalized evidence." if not contradictory else "The final recommendation still contains an unresolved contradiction with guaranteed evidence.",
        critical=True,
    ))

    overstatements = check_all_claim_overstatements(position, normalized, "")
    checks.append(_check(
        "claim_integrity",
        "FAIL" if overstatements else "PASS",
        "No unsupported claim-strength escalation was detected." if not overstatements else "The final response contains claims stronger than the evidence supports.",
        critical=True,
        details=overstatements,
    ))

    status, summary, details = _confidence_enforcement(position)
    checks.append(_check("confidence_enforcement", status, summary, critical=True, details=details))

    status, summary, details = _traceability(position)
    checks.append(_check("decision_traceability", status, summary, critical=True, details=details))

    normalization_warnings = list(normalized.normalization_warnings[:12])
    checks.append(_check(
        "normalization_quality",
        "WARN" if normalization_warnings else "PASS",
        (f"{len(normalization_warnings)} evidence extraction warning(s) were downgraded to missing values and surfaced in the decision audit."
         if normalization_warnings else "LLM extraction passed the normalized evidence contract without warnings."),
        details=normalization_warnings[:6],
    ))

    status, summary, details = _supplier_attribution(normalized)
    checks.append(_check("supplier_attribution", status, summary, details=details))

    status, summary, details = _deterministic_controls(position, normalized)
    checks.append(_check("adversarial_and_deterministic_controls", status, summary, details=details))

    audit = position.decision_audit
    stakeholder_conflict = bool(audit and audit.stakeholder_conflict)
    checks.append(_check(
        "stakeholder_attribution",
        "WARN" if stakeholder_conflict else "PASS",
        "Stakeholder conflict is explicitly surfaced and remains attributed." if stakeholder_conflict else "No unresolved material stakeholder conflict is present in the final audit.",
        details=(audit.stakeholder_conflict[:4] if stakeholder_conflict else []),
    ))

    checks.append(_check(
        "model_independence",
        "PASS",
        "Trust certification is computed without another model call and cannot alter the recommendation.",
    ))

    failures = [c for c in checks if c["status"] == "FAIL"]
    critical_failures = [c for c in failures if c["name"] in CRITICAL_CHECKS]
    warnings = [c for c in checks if c["status"] == "WARN"]
    passed = [c for c in checks if c["status"] == "PASS"]

    if critical_failures:
        certificate_status = "NOT_CERTIFIED"
        headline = "Trust certification failed — do not treat this decision as fully certified."
    elif warnings:
        certificate_status = "CONDITIONAL"
        headline = "Trust certification passed with conditions — review the flagged limitations."
    else:
        certificate_status = "CERTIFIED"
        headline = "Trust checks passed — the decision cleared the required integrity checks."

    return {
        "title": "VendorEdge Trust Certification",
        "version": "R19.1",
        "status": certificate_status,
        "headline": headline,
        "checks_passed": len(passed),
        "checks_warned": len(warnings),
        "checks_failed": len(failures),
        "critical_failures": [c["summary"] for c in critical_failures][:5],
        "checks": checks,
        "limitations": [c["summary"] for c in warnings][:5],
        "method": "Deterministic certification of evidence, consistency, claim strength, confidence enforcement, attribution and decision traceability; no new facts, calculations, ranking, or LLM call.",
        "disclaimer": "Certification measures process integrity, not commercial outcome accuracy. A certified decision can still be wrong if the supplied evidence is wrong or future conditions change.",
    }
