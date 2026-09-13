"""
Phase 2 / R41 -- Commercial Intelligence Kernel.

The single, structured source of commercial truth for a case. This is
deliberately NOT a new computation engine: build_kernel() assembles the
kernel from what earlier phases already computed deterministically
(financial.py's scenario/growth results, decision_audit.py's evidence
classification, question_coverage.py's requirements) -- it never
recalculates, and it never asks the LLM to calculate or reconcile a
deterministic value. Three reasoning profiles (Phase 3) will read this
same kernel; none of them get their own truth object.

Every material value is a CommercialFact: entity + metric + period +
value + currency + evidence_state + provenance. This is what makes
"category spend" and "Supplier A spend" two different, never-
interchangeable facts, and what makes a supplier's claim checkable
against a verified figure rather than silently trusted.
"""
from __future__ import annotations
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.pipeline.normalized_evidence import NormalizedEvidence
from app.pipeline.question_coverage import CoverageRequirement

# The eight evidence states from the spec, kept exactly distinct.
# UNKNOWN and CONTRADICTED are never conflated: UNKNOWN means the case
# never supplied the information; CONTRADICTED means the case supplied
# two things that disagree. A SUPPLIER_CLAIM never silently becomes
# VERIFIED, and an INFERRED value never silently becomes CALCULATED --
# each fact keeps the state its own provenance actually earned.
EvidenceState = Literal[
    "VERIFIED", "CALCULATED", "SUPPLIER_CLAIM", "STAKEHOLDER_VIEW",
    "ASSUMED", "INFERRED", "UNKNOWN", "CONTRADICTED",
]


class CommercialFact(BaseModel):
    entity: str
    metric: str
    period: Optional[str] = None
    value: Any = None
    currency: Optional[str] = None
    evidence_state: EvidenceState
    provenance: str


class CaseIdentity(BaseModel):
    case_id: Optional[str] = None
    case_mode: Optional[str] = None
    case_mode_source: Optional[str] = None
    content_type: Optional[str] = None
    question: Optional[str] = None
    subject: Optional[str] = None
    category: Optional[str] = None
    suppliers: list[str] = Field(default_factory=list)
    objective: Optional[str] = None
    urgency: Optional[str] = None
    decision_horizon: Optional[str] = None
    # Phase 5B / R41: market-driver claims exactly as the case stated
    # them (see normalized_evidence.MarketDriverClaim). Kept as raw
    # claim data here rather than forced into individual CommercialFact
    # entries -- a claim like "steel increased 12% per LME" is
    # genuinely narrative evidence, not a single clean entity/metric/
    # value triple, and market_intelligence.py's own explicit fact/
    # claim/inference/unknown separation is what actually structures
    # it, not the kernel's generic fact list.
    market_driver_claims: list[dict] = Field(default_factory=list)
    # ESG architecture: same rationale as market_driver_claims -- raw
    # claim data, not forced into individual CommercialFact triples,
    # since esg_intelligence.py's own fact/relevance/exposure/
    # implication/action chain is what structures it.
    esg_claims: list[dict] = Field(default_factory=list)
    # Phase 7: raw problem-solving evidence, same rationale as market_
    # driver_claims/esg_claims -- this is narrative/structured evidence
    # problem_solving.py's own reasoning chain (diagnosis, root-cause
    # verdicts, countermeasure verdicts) structures, not something
    # forced into individual CommercialFact triples.
    problem_solving_evidence: Optional[dict] = None


class SupplierProfile(BaseModel):
    supplier_name: str
    is_incumbent: bool = False
    spend: Optional[CommercialFact] = None
    spend_share: Optional[CommercialFact] = None
    performance: list[CommercialFact] = Field(default_factory=list)
    capability: list[CommercialFact] = Field(default_factory=list)
    qualification: Optional[CommercialFact] = None
    capacity: Optional[CommercialFact] = None
    dependencies: list[str] = Field(default_factory=list)
    commercial_position: Optional[str] = None


class StakeholderRecord(BaseModel):
    stakeholder: str
    view: str
    reason: Optional[str] = None
    unresolved_disagreement: bool = False


class DependencyRecord(BaseModel):
    kind: Literal["operational", "engineering", "qualification", "timing", "capacity", "contractual", "data"]
    description: str
    supplier: Optional[str] = None


class UnknownRecord(BaseModel):
    unknown: str
    why_it_matters: str
    resolution_action: str
    could_change: str


class HistoricalFact(BaseModel):
    description: str
    source: Literal["org_history", "supplier_history"]


class CommercialKernel(BaseModel):
    case: CaseIdentity
    facts: list[CommercialFact] = Field(default_factory=list)
    suppliers: list[SupplierProfile] = Field(default_factory=list)
    stakeholders: list[StakeholderRecord] = Field(default_factory=list)
    dependencies: list[DependencyRecord] = Field(default_factory=list)
    unknowns: list[UnknownRecord] = Field(default_factory=list)
    history: list[HistoricalFact] = Field(default_factory=list)


class KernelViolation(BaseModel):
    check: str
    detail: str


# ---------------------------------------------------------------------
# Assembly -- pure, deterministic, no LLM call, no recalculation
# ---------------------------------------------------------------------

def _qualification_fact(entity: str, s) -> Optional[CommercialFact]:
    if s.qualification_time_estimate:
        return CommercialFact(
            entity=entity, metric="qualification_timeline", value=s.qualification_time_estimate,
            evidence_state="VERIFIED", provenance=f"supplier:{entity}:qualification_time_estimate",
        )
    if s.qualification_status != "unknown":
        return CommercialFact(
            entity=entity, metric="qualification_status", value=s.qualification_status,
            evidence_state="VERIFIED", provenance=f"supplier:{entity}:qualification_status",
        )
    return None


def _capacity_fact(entity: str, s) -> Optional[CommercialFact]:
    if s.capacity_percent is None:
        return None
    state: EvidenceState = "VERIFIED" if s.capacity_status == "validated" else ("UNKNOWN" if s.capacity_status == "unvalidated" else "VERIFIED")
    # An unvalidated capacity figure is real evidence the case supplied,
    # not an unknown -- the RIGHT state is VERIFIED (the number was
    # stated) with the caveat carried in the value, never silently
    # dropped and never misrepresented as a confirmed figure either.
    value = f"{s.capacity_percent}% (unvalidated)" if s.capacity_status == "unvalidated" else s.capacity_percent
    return CommercialFact(
        entity=entity, metric="capacity", value=value,
        evidence_state="VERIFIED", provenance=f"supplier:{entity}:capacity_percent",
    )


def build_kernel(
    normalized: Optional[NormalizedEvidence],
    position: Any,
    case_id: Optional[str] = None,
    coverage_requirements: Optional[list[CoverageRequirement]] = None,
) -> CommercialKernel:
    """Assembles the kernel from already-computed sources. Never
    recalculates a deterministic value and never asks the model to
    reconcile one -- every fact here traces back to normalize_evidence(),
    financial.py, decision_audit.py, or question_coverage.py, all of
    which ran before this function is ever called."""
    if normalized is None:
        return CommercialKernel(case=CaseIdentity(case_id=case_id, case_mode=getattr(position, "case_mode", None), case_mode_source=getattr(position, "case_mode_source", None)))

    case = CaseIdentity(
        case_id=case_id,
        case_mode=getattr(position, "case_mode", None),
        case_mode_source=getattr(position, "case_mode_source", None),
        content_type=normalized.content_type,
        # Entity-binding fix, confirmed with a real case: common.
        # supplier_name is only populated when the case-level
        # extraction directly stated a single supplier name; a case
        # whose supplier identity only appears in the per-supplier
        # evidence list (supplier_specific_evidence, e.g. marked
        # is_incumbent) left subject as None, which then made every
        # fact about that supplier show up under the generic entity
        # name "supplier" -- exactly the class of entity-binding
        # failure the rest of this engagement exists to prevent.
        # Falls back to the incumbent supplier's name; only truly
        # ambiguous when there is no incumbent at all.
        subject=normalized.common.supplier_name or next((s.supplier_name for s in normalized.suppliers if s.is_incumbent), None),
        suppliers=[s.supplier_name for s in normalized.suppliers] or ([normalized.common.supplier_name] if normalized.common.supplier_name else []),
        market_driver_claims=[c.model_dump() for c in getattr(normalized.case, "market_driver_claims", None) or []],
        esg_claims=[c.model_dump() for c in getattr(normalized.case, "esg_claims", None) or []],
        problem_solving_evidence=(
            normalized.case.model_dump() if normalized.content_type == "problem_solving" else None
        ),
    )

    facts: list[CommercialFact] = []
    currency = (normalized.derived.spend_currency or "USD") if normalized.derived.currency_calculation_safe else None

    # Economics: spend, volume, price, growth, scenario results --
    # sourced from case/derived evidence and the already-computed
    # financial_impact, never recomputed here.
    case_ev = normalized.case
    if getattr(case_ev, "annual_spend_usd", None) is not None:
        state: EvidenceState = "CONTRADICTED" if any(c.get("field") == "annual_spend_usd" for c in getattr(case_ev, "unresolved_value_conflicts", []) or []) else "VERIFIED"
        facts.append(CommercialFact(entity=case.subject or "supplier", metric="annual_spend", value=case_ev.annual_spend_usd, currency=currency, evidence_state=state, provenance="case.annual_spend_usd"))
    if getattr(case_ev, "category_annual_spend_usd", None) is not None:
        facts.append(CommercialFact(entity="category", metric="annual_spend", value=case_ev.category_annual_spend_usd, currency=currency, evidence_state="VERIFIED", provenance="case.category_annual_spend_usd"))

    fi = getattr(position, "financial_impact", None)
    if fi is not None:
        facts.append(CommercialFact(entity=case.subject or "supplier", metric="requested_change_percent", value=fi.requested_change_percent, evidence_state="VERIFIED", provenance="case.requested_increase_percent"))
        if fi.potential_annual_impact is not None:
            facts.append(CommercialFact(entity=case.subject or "supplier", metric="scenario_annual_impact", value=fi.potential_annual_impact, currency=fi.currency, evidence_state="CALCULATED", provenance="financial.compute_financial_impact"))
        sc = getattr(fi, "scenario_comparison", None)
        if sc is not None:
            facts.append(CommercialFact(entity=case.subject or "supplier", metric="scenario_a_impact", period=sc.scenario_a.name, value=sc.scenario_a.delta.amount, currency=sc.scenario_a.delta.currency, evidence_state="CALCULATED", provenance="scenario_engine.compute_scenario"))
            facts.append(CommercialFact(entity=case.subject or "supplier", metric="scenario_b_impact", period=sc.scenario_b.name, value=sc.scenario_b.delta.amount, currency=sc.scenario_b.delta.currency, evidence_state="CALCULATED", provenance="scenario_engine.compute_scenario"))
            facts.append(CommercialFact(entity=case.subject or "supplier", metric="scenario_difference", value=sc.delta_amount.amount, currency=sc.delta_amount.currency, evidence_state="CALCULATED", provenance="scenario_engine.compare_scenarios"))

    # Growth facts from question_coverage -- CALCULATED, never
    # re-derived here. Metric name is deliberately suffixed
    # "_growth_percent"/"_change_pp" -- a growth RATE and the underlying
    # spend AMOUNT are two different metrics, not the same fact; giving
    # them the same metric name would make the duplicate-conflict
    # validator below (correctly) flag them as if they contradicted
    # each other.
    for req in (coverage_requirements or []):
        if req.status in ("CALCULATED", "SURFACED") and req.result is not None:
            if req.metric == "spend_share_percent":
                metric_name, value = "spend_share_change_pp", req.result.absolute_change
            else:
                metric_name, value = f"{req.metric}_growth_percent", req.result.percent_change
            facts.append(CommercialFact(
                entity=req.entity, metric=metric_name, value=value,
                currency=None, evidence_state="CALCULATED", provenance=f"question_coverage.{req.requirement_id}",
            ))

    # Evidence: verified / supplier claims / stakeholder views / unknowns / contradictions
    audit = getattr(position, "decision_audit", None)
    unknowns: list[UnknownRecord] = []
    if audit is not None:
        for u in (audit.uncertainties or []):
            unknowns.append(UnknownRecord(
                unknown=str(u), why_it_matters="Affects confidence in the recommendation until resolved.",
                resolution_action="Request the missing evidence from the supplier or internal stakeholder.",
                could_change="The strength of the recommendation and any related trade-offs.",
            ))
        for c in (audit.contradictions or []):
            facts.append(CommercialFact(entity=case.subject or "supplier", metric="claim_vs_evidence", value=str(c), evidence_state="CONTRADICTED", provenance="decision_audit.contradictions"))

    justification = getattr(case_ev, "suppliers_stated_justification", None)
    if justification:
        facts.append(CommercialFact(entity=case.subject or "supplier", metric="stated_justification", value=justification, evidence_state="SUPPLIER_CLAIM", provenance="case.suppliers_stated_justification"))

    # Category Strategy fix, confirmed by a real gap: a multi-supplier
    # signal/strategy case (current_annual_spend_usd per supplier, no
    # single case.annual_spend_usd "subject") never produced a raw
    # spend-AMOUNT fact for any supplier -- only the growth PERCENTAGE
    # existed (from question_coverage), because the raw-fact logic
    # above only ever wired to the single "subject supplier" pattern.
    # A category diagnosis genuinely needs "Supplier A spend = X", not
    # only "Supplier A spend grew Y%". Additive: a case with only the
    # single-subject pattern (the overwhelming majority of price_
    # increase cases) already gets its one raw fact from case.
    # annual_spend_usd above and is entirely unaffected here.
    for s in normalized.suppliers:
        if s.current_annual_spend_usd is not None:
            facts.append(CommercialFact(entity=s.supplier_name, metric="annual_spend", value=s.current_annual_spend_usd, currency=currency, evidence_state="VERIFIED", provenance=f"supplier:{s.supplier_name}:current_annual_spend_usd"))
        if s.current_annual_volume_units is not None:
            facts.append(CommercialFact(entity=s.supplier_name, metric="annual_volume", value=s.current_annual_volume_units, evidence_state="VERIFIED", provenance=f"supplier:{s.supplier_name}:current_annual_volume_units"))

    # Suppliers
    suppliers: list[SupplierProfile] = []
    for s in normalized.suppliers:
        profile = SupplierProfile(supplier_name=s.supplier_name, is_incumbent=s.is_incumbent)
        profile.qualification = _qualification_fact(s.supplier_name, s)
        profile.capacity = _capacity_fact(s.supplier_name, s)
        # Phase 5 fix: OTIF, lead time, and defect rate are real,
        # already-extracted evidence (SupplierEvidence.otif_percent
        # etc.) that never reached the kernel at all -- performance
        # stayed permanently empty regardless of what the case actually
        # stated. Populated here, once, at the source, so every
        # consumer (not just category strategy) sees this real
        # evidence, matching the kernel's own "single source of truth"
        # principle rather than each profile re-deriving it from
        # normalized directly.
        if s.otif_percent is not None:
            profile.performance.append(CommercialFact(entity=s.supplier_name, metric="otif_percent", value=s.otif_percent, evidence_state="VERIFIED", provenance=f"supplier:{s.supplier_name}:otif_percent"))
        if s.defect_rate_percent is not None:
            profile.performance.append(CommercialFact(entity=s.supplier_name, metric="defect_rate_percent", value=s.defect_rate_percent, evidence_state="VERIFIED", provenance=f"supplier:{s.supplier_name}:defect_rate_percent"))
        if s.lead_time_weeks is not None:
            profile.performance.append(CommercialFact(entity=s.supplier_name, metric="lead_time_weeks", value=s.lead_time_weeks, evidence_state="VERIFIED", provenance=f"supplier:{s.supplier_name}:lead_time_weeks"))
        _commercial_bits = []
        if s.payment_terms:
            _commercial_bits.append(f"payment terms: {s.payment_terms}")
        if s.incoterm:
            _commercial_bits.append(f"Incoterm: {s.incoterm}")
        if _commercial_bits:
            profile.commercial_position = "; ".join(_commercial_bits)
        suppliers.append(profile)

    # Stakeholders
    stakeholders = [
        StakeholderRecord(stakeholder=v.stakeholder_name, view=v.statement, reason=v.basis, unresolved_disagreement=v.view_type in ("risk_concern", "constraint"))
        for v in (normalized.stakeholder_views or [])
    ]

    # History -- read-only references to what org/supplier history
    # already produced; never recomputed.
    history: list[HistoricalFact] = []
    hist = getattr(normalized, "history", None)
    if hist is not None:
        for h in (getattr(hist, "org_history", None) or [])[:5]:
            history.append(HistoricalFact(description=str(h), source="org_history"))
        for h in (getattr(hist, "supplier_history", None) or [])[:5]:
            history.append(HistoricalFact(description=str(h), source="supplier_history"))

    return CommercialKernel(
        case=case, facts=facts, suppliers=suppliers, stakeholders=stakeholders,
        dependencies=[], unknowns=unknowns, history=history,
    )


# ---------------------------------------------------------------------
# Validation -- deterministic checks on the assembled kernel
# ---------------------------------------------------------------------

def validate_kernel(kernel: CommercialKernel) -> list[KernelViolation]:
    violations: list[KernelViolation] = []
    seen: dict[tuple, CommercialFact] = {}
    for f in kernel.facts:
        if not f.entity:
            violations.append(KernelViolation(check="missing_entity", detail=f"fact for metric '{f.metric}' has no entity"))
        if f.metric in ("annual_spend", "scenario_annual_impact", "scenario_difference") and f.value is not None and f.currency is None and f.evidence_state != "CONTRADICTED":
            violations.append(KernelViolation(check="missing_currency", detail=f"'{f.entity}.{f.metric}' has a monetary value but no currency"))
        key = (f.entity, f.metric, f.period)
        if key in seen:
            prior = seen[key]
            if prior.value == f.value and prior.currency == f.currency:
                violations.append(KernelViolation(check="duplicate_consistent_fact", detail=f"'{f.entity}.{f.metric}' stated more than once with the same value"))
            else:
                violations.append(KernelViolation(check="duplicate_conflicting_fact", detail=f"'{f.entity}.{f.metric}' has conflicting values: {prior.value!r} vs {f.value!r}"))
        else:
            seen[key] = f
    return violations
