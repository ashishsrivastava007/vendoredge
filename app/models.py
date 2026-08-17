"""
Pydantic models — the API's actual data contracts.
Kept intentionally narrow to the two MVP content types per the lean roadmap.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from app import caps

ContentType = Literal["price_increase", "quote_comparison"]
DecisionType = Literal["optimization", "constraint_satisfaction"]
Status = Literal[
    "created", "classifying", "awaiting_user_input",
    "reasoning", "completed", "provider_unavailable",
]
ValidationVerdict = Literal[
    "reasoning_held", "reasoning_wrong_bad_assumption",
    "reasoning_wrong_bad_execution", "ambiguous_unresolved",
]
# Sprint 2: captures the "Decision Taken" step -- previously never recorded.
DecisionAlignment = Literal["followed", "modified", "different_direction"]


class WorkspaceResponse(BaseModel):
    organisation_id: UUID
    user_id: UUID
    access_token: str


class InviteResponse(BaseModel):
    organisation_id: UUID
    invite_token: str
    expires_at: datetime


class AcceptInviteRequest(BaseModel):
    invite_token: str = Field(..., min_length=40, max_length=300)


class WorkspaceInfoResponse(BaseModel):
    organisation_id: UUID
    created_at: datetime
    days_active: int


class PilotLeadRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    name: Optional[str] = None
    linkedin: Optional[str] = None
    next_case_category: str
    comment: Optional[str] = None


class GeneralFeedbackRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class CreateDecisionRequest(BaseModel):
    # 20,000 characters -- deliberately generous to genuinely fit several
    # real uploaded documents (each capped at 8,000 chars during
    # extraction), not the previous 4,000, which was silently the real
    # bottleneck even though the reasoning stage was already raised to
    # comfortably handle far more than this.
    raw_question: str = Field(..., min_length=1, max_length=20000)
    # Optional: lets the frontend generate the ID client-side and poll for
    # real progress in parallel with the main request, instead of only
    # finding out the ID once everything is already finished.
    client_decision_id: Optional[UUID] = None


class RespondRequest(BaseModel):
    user_supplied_inputs: dict[str, Any]


class ConfidenceFactor(BaseModel):
    factor: str
    value: str
    weight: Literal["increases confidence", "decreases confidence"]


class CostDriverComparison(BaseModel):
    driver: str
    claimed_percent: float
    market_percent: float


class KeyFigure(BaseModel):
    label: str
    value: str


class SupplierComparison(BaseModel):
    name: str
    price: Optional[str] = None
    otif: Optional[str] = None
    defect_rate: Optional[str] = None
    lead_time: Optional[str] = None


class NegotiationDimension(BaseModel):
    dimension: str
    opening_ask: str
    target_outcome: str
    walk_away: str


class NegotiationMove(BaseModel):
    trigger: str
    line: str


class FinancialScenario(BaseModel):
    scenario: str
    annual_spend: str
    vs_baseline: str


class Confidence(BaseModel):
    level: Literal["high", "medium", "low"]
    factors: list[ConfidenceFactor] = Field(..., min_length=1)
    # Hard Rule 2, enforced structurally: a confidence object cannot exist
    # in this schema without at least one factor and a non-blank derivation note.
    derivation_note: str = Field(..., min_length=1)


class FinancialImpact(BaseModel):
    """
    Computed deterministically in Python (see decisions.py), never trusted
    from the LLM's own arithmetic -- this is the direct fix for a real,
    repeated finding: asking a model to "show its math" in prose is not
    reliable enough on its own, the same lesson already learned once with
    confidence scores. Whenever the underlying numbers are genuinely
    available, this object is calculated by code and attached to the
    response regardless of what the model's own text says, so it can never
    be silently skipped.
    """
    annual_spend_usd: float
    requested_change_percent: float
    potential_annual_impact_usd: float
    switching_cost_usd: Optional[float] = None
    net_exposure_usd: Optional[float] = None
    # Cross-border commercial mechanics addition -- only ever populated
    # when a real duty/tax rate was genuinely given in the evidence, never
    # estimated or assumed, since real rates vary by country and product.
    annual_duty_cost_usd: Optional[float] = None
    # Completes the freight-cost loop -- the number the user typed into
    # the evidence-gate now actually reaches the guaranteed calculation.
    annual_freight_cost_usd: Optional[float] = None
    note: str


class DecisionAlternative(BaseModel):
    name: str
    type: str
    path: str
    supplier: Optional[str] = None
    annual_spend_usd: Optional[float] = None
    financial_basis: str
    unit_price_usd: Optional[float] = None
    unit_price_display: Optional[str] = None
    price_currency: Optional[str] = None
    what_you_gain: list[str] = Field(default_factory=list, max_length=6)
    what_you_give_up: list[str] = Field(default_factory=list, max_length=8)
    stakeholder_impacts: list[str] = Field(default_factory=list, max_length=6)
    evidence_strength: str
    requires_new_evidence: list[str] = Field(default_factory=list, max_length=8)


class AlternativeAnalysis(BaseModel):
    available: bool
    status: str
    summary: str
    alternatives: list[DecisionAlternative] = Field(default_factory=list, max_length=3)
    warnings: list[str] = Field(default_factory=list, max_length=6)
    method: Optional[str] = None


class DecisionAudit(BaseModel):
    material_evidence: list[dict] = Field(default_factory=list, max_length=12)
    inferred_signals: list[str] = Field(default_factory=list, max_length=3)
    uncertainties: list[str] = Field(default_factory=list, max_length=10)
    stakeholder_tradeoffs: list[dict] = Field(default_factory=list, max_length=8)
    stakeholder_conflict: list[str] = Field(default_factory=list, max_length=8)
    reversal_conditions: list[str] = Field(default_factory=list, max_length=6)
    evidence_integrity_status: Literal["PROVEN", "INFERRED", "UNKNOWN", "CONTRADICTED"]
    # LLM extraction quality warnings are user-visible audit signals. They
    # never become evidence and never contain raw untrusted model prose.
    normalization_warnings: list[str] = Field(default_factory=list, max_length=12)
    evidence_counts: dict[str, int] = Field(default_factory=dict)


class ControlTower(BaseModel):
    available: bool
    readiness: Literal["READY", "CONDITIONAL", "HOLD"]
    readiness_reason: str
    recommended_action: str
    confidence: Literal["high", "medium", "low"]
    evidence_integrity: Literal["PROVEN", "INFERRED", "UNKNOWN", "CONTRADICTED"]
    critical_before_action: list[str] = Field(default_factory=list, max_length=5)
    important_not_blocking: list[str] = Field(default_factory=list, max_length=5)
    useful_later: list[str] = Field(default_factory=list, max_length=3)
    decision_changers: list[str] = Field(default_factory=list, max_length=6)
    stakeholder_conflicts: list[str] = Field(default_factory=list, max_length=6)
    alternative_count: int = 0
    stress_status: str
    financial_impact_available: bool
    action_items: list[dict[str, str]] = Field(default_factory=list, max_length=5)
    method: str


class NegotiationPlaybook(BaseModel):
    available: bool = True
    objective: str
    opening_position: Optional[str] = None
    target: Optional[str] = None
    walk_away: Optional[str] = None
    dimensions: list[dict[str, str]] = Field(default_factory=list, max_length=8)
    talk_track: list[dict[str, str]] = Field(default_factory=list, max_length=6)
    supplier_facts: list[dict[str, str]] = Field(default_factory=list, max_length=8)
    evidence_to_lead_with: list[str] = Field(default_factory=list, max_length=5)
    questions_to_resolve: list[str] = Field(default_factory=list, max_length=6)
    red_lines: list[str] = Field(default_factory=list, max_length=5)
    method: str


class CommercialPosition(BaseModel):
    recommendation: str
    commercial_insights: list[str] = Field(
        ..., min_length=caps.MIN_COMMERCIAL_INSIGHTS, max_length=caps.MAX_COMMERCIAL_INSIGHTS
    )
    # Capped string length -- previously unbounded free prose. Forces "name
    # the framework, one reason why" rather than a full paragraph.
    commercial_hypothesis: Optional[str] = Field(default=None, max_length=caps.MAX_HYPOTHESIS_CHARS)
    methodology_applied: Optional[str] = Field(default=None, max_length=caps.MAX_METHODOLOGY_CHARS)
    # All five list fields below were previously UNBOUNDED -- on a dense
    # case (3+ suppliers, 5+ cost drivers, 5+ negotiable dimensions), every
    # optional field firing at once with no ceiling anywhere was the real
    # cause of repeated truncation, not the output token budget itself.
    # These caps are calibrated against tonight's actual proven successful
    # cases -- generous enough to never break something that already
    # worked, tight enough to guarantee a real ceiling going forward.
    # Every number below comes from app/caps.py -- the single source of
    # truth -- not typed here directly, per the consistency audit.
    cost_driver_comparison: Optional[list[CostDriverComparison]] = Field(default=None, max_length=caps.MAX_COST_DRIVERS)
    key_figures: Optional[list[KeyFigure]] = Field(default=None, min_length=caps.MIN_KEY_FIGURES, max_length=caps.MAX_KEY_FIGURES)
    supplier_comparison: Optional[list[SupplierComparison]] = Field(default=None, max_length=caps.MAX_SUPPLIERS)
    why_this_wins: Optional[str] = None
    # Set DETERMINISTICALLY in code (app/routes/decisions.py), right after
    # verify_market_claim() returns -- never left to the model's own prose
    # to report, same "guarantee, don't just ask nicely" pattern as
    # financial_impact and informed_by_case_count. Holds either the real
    # region checked (e.g. "Southeast Asia") or "global" when no region
    # was given, or None when no market verification ran at all.
    market_verification_scope: Optional[str] = None
    negotiation_dimensions: Optional[list[NegotiationDimension]] = Field(default=None, max_length=caps.MAX_NEGOTIATION_DIMENSIONS)
    negotiation_talk_track: Optional[list[NegotiationMove]] = Field(default=None, min_length=caps.MIN_TALK_TRACK_MOVES, max_length=caps.MAX_TALK_TRACK_MOVES)
    financial_scenarios: Optional[list[FinancialScenario]] = Field(default=None, max_length=caps.MAX_FINANCIAL_SCENARIOS)
    # Computed deterministically in code from the real history count, never
    # left to the model to self-report -- same guarantee pattern as
    # financial_impact. Makes organizational memory visible to the user,
    # not just used silently inside the reasoning.
    informed_by_case_count: int = 0
    # Phase 3 of the gap-closing roadmap (outcome-based learning): real,
    # code-computed track record across this organization's own recorded
    # outcomes -- never left to the model's own impression of "we've been
    # pretty good so far." None until there's genuinely enough real data
    # (see MIN_OUTCOMES_FOR_CALIBRATION in decisions.py) to support a real
    # number, same honesty discipline as supplier-specific memory.
    confidence_calibration_note: Optional[str] = None
    reasoning: str
    confidence: Confidence
    # Release 5: deterministic audit of what evidence, uncertainty and reversal conditions surround this decision.
    decision_audit: Optional[DecisionAudit] = None
    # Release 6: deterministic what-if analysis generated from normalized evidence.
    # Never supplied by the LLM and never used as a hidden recommendation.
    sensitivity_analysis: Optional[dict[str, Any]] = None
    # Release 8: deterministic alternative commercial paths.
    alternative_analysis: Optional[AlternativeAnalysis] = None
    # Release 9: deterministic executive control-tower view.
    control_tower: Optional[ControlTower] = None
    # Native VendorEdge presentation: answer-first, proof-on-demand decision card.
    decision_passport: Optional[dict[str, Any]] = None
    # Release 18: deterministic Commercial Decision Cockpit.
    decision_cockpit: Optional[dict[str, Any]] = None
    # Release 19: deterministic Trust Certification. This certifies the
    # integrity of the decision process; it never certifies the commercial
    # outcome itself and cannot alter the recommendation.
    trust_certification: Optional[dict[str, Any]] = None
    # Release 20: deterministic Commercial Truth Model. This is the structured
    # commercial situation consumed by later intelligence layers.
    commercial_truth_model: Optional[dict[str, Any]] = None
    # Release 21: deterministic Decision Flip Map. Shows evidenced numeric
    # boundaries and explicitly stated reversal conditions; it never changes
    # the recommendation or invents a threshold.
    decision_flip_map: Optional[dict[str, Any]] = None
    # Release 22: deterministic Commercial War Room. It is an evidence-backed
    # negotiation theatre and never mutates the recommendation or predicts
    # counterpart psychology as fact.
    commercial_war_room: Optional[dict[str, Any]] = None
    # Release 23: deterministic institutional procurement memory. It records
    # prior cases, supplier-specific history and outcome-backed lessons without
    # turning sparse history into false patterns.
    procurement_memory: Optional[dict[str, Any]] = None
    # Release 24: deterministic expected-vs-actual outcome intelligence.
    # Built at read time from immutable decision data + recorded outcome.
    outcome_intelligence: Optional[dict[str, Any]] = None
    # Release 25: deterministic organization-level Commercial DNA. Built at
    # read time from persisted decisions/outcomes; it never mutates the current
    # recommendation.
    commercial_dna: Optional[dict[str, Any]] = None
    # Release 13: deterministic negotiation meeting aid.
    negotiation_playbook: Optional[NegotiationPlaybook] = None
    # Release 7: deterministic challenge of the recommendation using only
    # stated evidence and explicitly labelled hypothetical shocks.
    stress_test: Optional[dict[str, Any]] = None
    financial_impact: Optional[FinancialImpact] = None
    # Capped, and tightened to short phrases in the prompt itself -- this
    # was the other genuinely unbounded field, sometimes running to 6+ full
    # sentences on dense cases.
    assumptions: list[str] = Field(..., min_length=caps.MIN_ASSUMPTIONS, max_length=caps.MAX_ASSUMPTIONS)
    opening_position: Optional[str] = None
    walk_away_threshold: Optional[str] = None
    disconfirming_condition: str
    decision_type: DecisionType


class DecisionFormatRequest(BaseModel):
    format_name: Literal["decision_cockpit", "cfo_brief", "category_review", "supplier_meeting", "one_page", "executive_60_second"]


class CustomFormatRequest(BaseModel):
    template: str = Field(..., min_length=1, max_length=12000)


class MissingField(BaseModel):
    field: str
    prompt: str
    why: str


class CommercialDecisionResponse(BaseModel):
    id: UUID
    status: Status
    raw_question: str
    parent_decision_id: Optional[UUID] = None
    classified_content_type: Optional[ContentType] = None
    classified_decision_type: Optional[DecisionType] = None
    missing_inputs_requested: Optional[list[MissingField]] = None
    commercial_position: Optional[CommercialPosition] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    # Case-list / outcome-loop support (Phase 2): lets the frontend show a case
    # as "awaiting outcome" without a second round-trip per case.
    has_outcome_feedback: bool = False
    # Sprint 1 (case-summary-as-documentation): the evidence the user supplied,
    # and -- when present -- the most recently recorded outcome, so a case
    # summary can be rendered any time the case is reopened, not only in the
    # same session it was submitted in.
    user_supplied_inputs: Optional[dict[str, Any]] = None
    recorded_outcome_description: Optional[str] = None
    recorded_outcome_verdict: Optional[ValidationVerdict] = None
    recorded_outcome_at: Optional[datetime] = None
    recorded_decision_alignment: Optional[DecisionAlignment] = None
    recorded_unexpected_insight: Optional[str] = None
    recorded_actual_financial_impact_usd: Optional[float] = None
    recorded_actual_measurement_basis: Optional[str] = None
    # Async reasoning hardening: real, honest signals about an in-flight
    # or recoverable case -- never a fabricated progress percentage,
    # only real elapsed time and a real staleness/retry determination.
    processing_elapsed_seconds: Optional[float] = None
    processing_message: Optional[str] = None
    processing_is_stale: bool = False
    can_retry: bool = False
    # Requirement 5: the explicit, calm field the frontend switches on --
    # "working" / "safely_resuming" / "unable_to_complete" -- so it never
    # needs to infer meaning from internal status strings, heartbeat
    # timing, or any other technical detail.
    user_facing_state: Optional[str] = None


class ContinueCaseRequest(BaseModel):
    what_happened: str = Field(..., min_length=1)
    client_decision_id: Optional[UUID] = None


class PilotExperienceRequest(BaseModel):
    """Structured pilot-use signal, kept separate from commercial outcome truth.

    These fields measure whether VendorEdge was useful and usable; they never
    feed into the commercial reasoning engine and never alter a decision.
    """
    ease_of_use: Literal["very_easy", "easy", "okay", "difficult", "very_difficult"]
    trust_level: Literal["high", "medium", "low"]
    time_saved: Literal["significant", "some", "none", "more_time"]
    would_use_again: bool
    most_valuable: str = Field(..., min_length=1, max_length=500)
    missing_or_frustrating: Optional[str] = Field(default=None, max_length=500)


class FeedbackRequest(BaseModel):
    decision_alignment: DecisionAlignment
    outcome_description: str = Field(..., min_length=1)
    validation_verdict: ValidationVerdict
    # Optional, deliberately -- not every outcome has a genuine surprise
    # worth capturing, and forcing one would invite padding with something
    # generic just to fill the field, the same trap avoided everywhere else.
    unexpected_insight: Optional[str] = None
    # R24: optional structured realized financial impact; free text is never parsed.
    actual_financial_impact_usd: Optional[float] = Field(default=None, ge=-1000000000000, le=1000000000000)
    actual_measurement_basis: Optional[str] = Field(default=None, max_length=160)
