"""Deterministic decision-audit layer.

Release 5 goal: make every recommendation explainable as an auditable chain:
material evidence -> uncertainty/conflict -> stakeholder trade-off -> reversal condition.
This module never invents evidence and never decides whether the recommendation is good.
"""
from __future__ import annotations
import re
from typing import Literal
from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence

AuditStatus = Literal["PROVEN", "INFERRED", "UNKNOWN", "CONTRADICTED"]

# Contradiction/reconciliation fix, confirmed root cause: a supplier's
# own claim (e.g. "no price adjustment for three years") was never
# checked against the case's own documented pricing history, even when
# the case supplied both -- there was no detection at all, so the claim
# simply stood unchallenged in the final answer. Deliberately narrow,
# explicit phrase-based detection rather than fragile date-range
# parsing: this catches the specific, real pattern (a "no change"
# claim contradicted by ANY non-zero stated historical entry) without
# trying to precisely reconcile which years the claim covers -- that
# imprecision is exactly why this is represented as "requires
# reconciliation" rather than a resolved fact either way.
_NO_ADJUSTMENT_CLAIM_PHRASES = (
    "no price adjustment", "no adjustment", "no increase", "no price increase",
    "prices have been stable", "unchanged for", "held flat", "no change in price",
    "no change to price", "flat pricing",
)
_ZERO_CHANGE_MARKERS = ("0%", "+0%", "0.0%", "no change", "flat", "unchanged")
# Precise, not naive substring matching -- "+3.0%" must never match as a
# zero-change entry merely because it ends in the characters "0%".
_ZERO_CHANGE_RE = re.compile(r"(?<![.\d])[+-]?0(?:\.0+)?\s*%")


def _detect_claim_vs_history_contradiction(normalized: NormalizedEvidence) -> list[str]:
    """Returns a list of contradiction descriptions (empty if none). Does
    NOT decide which side is correct -- only detects that a supplier's
    own claim and the case's own documented history disagree, and
    surfaces both, once, so the buyer can resolve it."""
    contradictions: list[str] = []
    claim = getattr(normalized.case, "suppliers_stated_justification", None)
    history = getattr(normalized.case, "stated_price_history", None)
    if not claim or not history:
        return contradictions
    claim_lower = claim.lower()
    if not any(phrase in claim_lower for phrase in _NO_ADJUSTMENT_CLAIM_PHRASES):
        return contradictions
    non_zero_entries = [
        h for h in history
        if not (_ZERO_CHANGE_RE.search(h) or any(m in h.lower() for m in ("no change", "flat", "unchanged")))
    ]
    if non_zero_entries:
        contradictions.append(
            f"CLAIM REQUIRES RECONCILIATION: the supplier states \"{claim.strip()}\", but the case's own "
            f"documented history shows: {'; '.join(non_zero_entries)}. This is not resolved either way -- "
            f"the claim and the documented history disagree, and that disagreement itself is commercially "
            f"material to how much weight the supplier's justification should carry."
        )
    return contradictions


def _detect_unresolved_value_conflicts(normalized: NormalizedEvidence) -> list[str]:
    """Item 1 fix: surfaces genuine, structured value conflicts the
    classifier itself detected in the raw text (see normalized_evidence.
    py's field docstring and the classifier prompt instruction) --
    currency-agnostic by construction, since this never inspects the
    raw text itself or any currency symbol; it only reads the LLM's own
    structured judgment that two numbers for the same fact disagree.
    Does not decide which value is correct -- only surfaces the
    disagreement, once, clearly labelled, so the buyer knows the figure
    is unresolved rather than silently trusting whichever one the
    system happened to keep."""
    conflicts_out: list[str] = []
    for c in getattr(normalized.case, "unresolved_value_conflicts", None) or []:
        field = c.get("field", "an unspecified fact")
        values = c.get("values_found", [])
        note = c.get("note", "")
        values_text = " vs ".join(str(v) for v in values) if values else "conflicting values"
        conflicts_out.append(
            f"UNRESOLVED VALUE CONFLICT on {field}: the case states {values_text}, "
            f"and neither can be treated as authoritative from the evidence supplied."
            + (f" {note}" if note else "")
        )
    return conflicts_out


def _status_for_field(normalized: NormalizedEvidence, field: str) -> AuditStatus:
    prov = normalized.provenance.get(field)
    if prov is None:
        return "UNKNOWN"
    if prov.conflicting:
        return "CONTRADICTED"
    if prov.source in {"llm_extraction", "user_followup", "both_agree", "database_history"}:
        return "PROVEN"
    if prov.source == "derived_calculation":
        return "PROVEN"
    if prov.source == "deterministic_fallback":
        return "INFERRED"
    return "UNKNOWN"


def _value_text(value) -> str:
    if value is None or value == "":
        return "Not provided"
    return str(value)


def build_decision_audit(normalized: NormalizedEvidence, position: CommercialPosition) -> dict:
    """Build the user-facing audit from normalized evidence only.

    The model's recommendation is deliberately not treated as evidence. The
    only model-derived element carried into the audit is the disconfirming
    condition, which is clearly labelled as the model's stated reversal test.
    """
    items: list[dict] = []

    if normalized.content_type == "price_increase":
        fields = [
            ("Current commercial terms", "current_price_or_terms", normalized.case.current_price_or_terms),
            ("Requested increase", "requested_increase_percent", normalized.case.requested_increase_percent),
            ("Supplier justification", "suppliers_stated_justification", normalized.case.suppliers_stated_justification),
            ("Annual spend", "annual_spend_usd", normalized.case.annual_spend_usd),
        ]
    elif normalized.content_type == "problem_solving":
        fields = [
            ("Problem", "problem_statement", normalized.case.problem_statement),
            ("Current condition", "current_condition", normalized.case.current_condition),
            ("Desired condition", "desired_condition", normalized.case.desired_condition),
            ("Stated impact", "stated_impact", normalized.case.stated_impact),
        ]
    else:
        fields = [
            ("Supplier pricing", "price_per_supplier", normalized.case.price_per_supplier),
            ("Suppliers compared", "number_of_suppliers_being_compared", normalized.case.number_of_suppliers_being_compared),
            ("Payment terms", "payment_terms_per_supplier", normalized.case.payment_terms_per_supplier),
            ("Lead times", "lead_time_per_supplier", normalized.case.lead_time_per_supplier),
        ]

    for label, field, value in fields:
        items.append({"label": label, "status": _status_for_field(normalized, field), "evidence": _value_text(value)})

    for supplier in normalized.suppliers[:6]:
        details = []
        for label, value in (("price", supplier.price_display or supplier.price_usd),
                             ("OTIF", supplier.otif_percent),
                             ("defect rate", supplier.defect_rate_percent),
                             ("lead time", supplier.lead_time_weeks),
                             ("capacity", supplier.capacity_percent),
                             ("qualification", supplier.qualification_status),
                             ("qualification timeframe", supplier.qualification_time_estimate)):
            if value is not None:
                details.append(f"{label}: {value}")
        # Evidence-retention fix: capacity_status is a genuinely separate
        # fact from the capacity_percent figure itself (a stated number
        # can be explicitly unvalidated) -- surfaced here, distinctly,
        # not merged into the plain "capacity: X%" line above, so the
        # caveat isn't silently lost inside a figure that reads as fully
        # confirmed. Only surfaced when it's actually informative
        # ("unvalidated" -- the case explicitly said so); "unknown"
        # adds no real information over silence and stays out, matching
        # the same discipline as every other status field in this file.
        if supplier.capacity_status == "unvalidated":
            details.append("capacity status: stated but not yet validated")
        if details:
            items.append({"label": supplier.supplier_name, "status": "PROVEN", "evidence": "; ".join(details)})

    uncertainties: list[str] = []
    for field, prov in normalized.provenance.items():
        if prov.conflicting:
            uncertainties.append(f"Conflicting evidence for {field}")
    # Do not turn every absent supplier attribute into a user-facing blocker.
    # "Not provided" is not automatically decision-relevant, and surfacing
    # qualification/certification/production-history gaps for every supplier
    # creates false urgency and noisy repetition. Only surface qualification
    # when the current decision actually relies on an alternative supplier.
    # A genuinely material, evidence-grounded signal -- not a fragile scan of
    # free text for specific phrasing. If the evidence itself compares more
    # than one supplier, an unresolved qualification status on a non-incumbent
    # is material regardless of how the recommendation happens to be worded;
    # a true single-supplier case has nothing to compare against, so this
    # naturally avoids the noise the original design comment (below) warned
    # about, without depending on keyword matches that can silently miss
    # real cases -- found by an adversarial test using valid phrasing
    # ("negotiating lever") the original keyword list didn't cover.
    alternative_reliance = len(normalized.suppliers) > 1
    for supplier in normalized.suppliers:
        if alternative_reliance and not supplier.is_incumbent:
            if supplier.qualification_status in {"unknown", "not_started", "in_progress"}:
                # Evidence-retention fix, confirmed root cause: this
                # previously said "qualification status was not
                # provided" purely because qualification_status (the
                # categorical enum) wasn't "complete" -- even when the
                # case explicitly stated a real timeframe
                # (qualification_time_estimate, e.g. "4-6 months"),
                # which is a genuinely different fact this condition
                # never checked. That silently turned an explicitly
                # supplied fact into a false claim of no information at
                # all. Surface the real timeframe when one exists;
                # only claim "not provided" when genuinely nothing was
                # stated.
                if supplier.qualification_time_estimate:
                    uncertainties.append(
                        f"{supplier.supplier_name}: qualification stated as {supplier.qualification_time_estimate} "
                        f"(not yet complete)"
                    )
                else:
                    uncertainties.append(
                        f"{supplier.supplier_name}: qualification status was not provided"
                    )
        # Certification and production history are not emitted merely because
        # the fields are absent. They become visible only when an actual
        # decision field explicitly relies on that attribute elsewhere.
    if not normalized.stakeholder_views:
        pass
    else:
        for view in normalized.stakeholder_views:
            if view.view_type in {"risk_concern", "rumor", "experience"}:
                uncertainties.append(f"{view.stakeholder_name}: {view.view_type} — {view.statement}")

    conflict_fields = [f for f, p in normalized.provenance.items() if p.conflicting]
    normalization_warnings = list(normalized.normalization_warnings[:12])
    claim_contradictions = _detect_claim_vs_history_contradiction(normalized)
    value_conflicts = _detect_unresolved_value_conflicts(normalized)
    all_contradictions = claim_contradictions + value_conflicts
    if conflict_fields or all_contradictions:
        status = "CONTRADICTED"
    elif uncertainties or normalization_warnings:
        status = "UNKNOWN"
    else:
        status = "PROVEN"

    conflict, conflict_details = _stakeholder_conflict(normalized)
    stakeholder_tradeoffs = []
    for view in normalized.stakeholder_views[:8]:
        stakeholder_tradeoffs.append({
            "stakeholder": view.stakeholder_name,
            "type": view.view_type,
            "view": view.statement,
            "basis": view.basis,
        })

    reversal_conditions = []
    if position.disconfirming_condition:
        reversal_conditions.append(position.disconfirming_condition)
    for u in uncertainties:
        reversal_conditions.append(f"Reassess if this unresolved point changes materially: {u}")
    # Preserve only distinct reversal conditions; repeating the same unknown
    # in multiple audit sections makes the product look less trustworthy.
    reversal_conditions = list(dict.fromkeys(x.strip() for x in reversal_conditions if x and x.strip()))

    uncertainties = list(dict.fromkeys(x.strip() for x in uncertainties if x and x.strip()))

    inferred = []
    if position.commercial_hypothesis:
        inferred.append(position.commercial_hypothesis)

    counts = {k: 0 for k in ("PROVEN", "INFERRED", "UNKNOWN", "CONTRADICTED")}
    for item in items:
        counts[item["status"]] += 1
    counts["INFERRED"] += len(inferred)
    counts["UNKNOWN"] += len(uncertainties)
    if conflict:
        counts["CONTRADICTED"] += len(conflict_details)

    return {
        "material_evidence": items[:12],
        "inferred_signals": inferred[:3],
        "uncertainties": uncertainties[:10],
        "contradictions": all_contradictions,
        "stakeholder_tradeoffs": stakeholder_tradeoffs,
        "stakeholder_conflict": conflict_details,
        "reversal_conditions": reversal_conditions[:6],
        "normalization_warnings": normalization_warnings,
        "evidence_integrity_status": status,
        "evidence_counts": counts,
    }


def _stakeholder_conflict(normalized: NormalizedEvidence) -> tuple[bool, list[str]]:
    from app.pipeline.decision_integrity import stakeholder_conflict_summary
    return stakeholder_conflict_summary(normalized)
