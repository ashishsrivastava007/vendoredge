"""
Pydantic models — the API's actual data contracts.
Kept intentionally narrow to the two MVP content types per the lean roadmap.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app import caps
from app.pipeline.scenario_engine import ScenarioComparison

ContentType = Literal["price_increase", "quote_comparison", "problem_solving"]
DecisionType = Literal["optimization", "constraint_satisfaction"]
# Phase 1 / R41 foundation: a genuinely independent dimension from
# ContentType. ContentType answers "what kind of commercial analysis is
# this"; CaseMode answers "which reasoning lens did the buyer select".
# Nothing in this phase changes reasoning based on mode -- this exists
# purely to make mode real, persistent, first-class data, proven to
# survive the full request lifecycle, before any mode-specific
# reasoning is built on top of it.
CaseMode = Literal["supplier_request", "commercial_signal", "category_strategy"]
CaseModeSource = Literal["explicit", "inferred"]
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
    # Phase 1 / R41 foundation: the mode the buyer explicitly selected
    # on the landing page (Supplier Request / Something I Noticed /
    # Category Strategy), sent as real structured data, not inferred
    # from prose. Optional and backward-compatible -- an older client
    # or a direct API caller that sends no mode is not rejected; the
    # backend falls back to inference and marks it accordingly (see
    # create_decision's mode-resolution logic), never silently
    # pretending an inferred mode was explicitly chosen.
    mode: Optional[CaseMode] = None
    ingestion_artifact_ids: list[UUID] = Field(default_factory=list, max_length=10)


class RespondRequest(BaseModel):
    user_supplied_inputs: dict[str, Any]


class SupplierResponseDraftRequest(BaseModel):
    recipient: str = Field(..., min_length=3, max_length=320)
    subject: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1, max_length=20000)
    expected_version: Optional[int] = Field(default=None, ge=1)


class SupplierResponseHandoffRequest(BaseModel):
    expected_version: int = Field(..., ge=1)


class SupplierReplyRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=30000)


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

    Currency redesign: the fields ending in "_usd" below are legacy and
    are ONLY ever populated when `currency` is genuinely "USD" -- they are
    never repurposed to silently hold a EUR or GBP amount under a name
    that promises USD. The canonical, currency-correct amounts are the
    fields without a "_usd" suffix, always populated in whatever currency
    `currency` states, using the Money/scenario_engine machinery. This
    exists because the previous design refused to calculate at all for a
    consistently non-USD case (see normalize.py's currency_calculation_safe
    fix) -- once that gate was corrected, a EUR case needed somewhere
    honest to put a EUR number, rather than either crashing a "_usd" field
    open or leaving buyers with nothing.
    """
    currency: str = "USD"
    annual_spend: Optional[float] = None
    potential_annual_impact: Optional[float] = None
    switching_cost: Optional[float] = None
    net_exposure: Optional[float] = None
    annual_duty_cost: Optional[float] = None
    annual_freight_cost: Optional[float] = None
    # Populated only when the evidence genuinely contained a second,
    # comparable scenario (e.g. a supplier's conditional offer) -- the
    # scenario engine's own structured comparison, carried through
    # end-to-end rather than left for prose to reconstruct.
    scenario_comparison: Optional["ScenarioComparison"] = None
    requested_change_percent: float
    # --- legacy USD-only fields, kept for backward compatibility only ---
    # None whenever currency != "USD"; never a EUR/GBP value under a USD name.
    annual_spend_usd: Optional[float] = None
    potential_annual_impact_usd: Optional[float] = None
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
    # Contradiction/reconciliation fix: a supplier claim contradicted by
    # the case's own documented history (e.g. "no price adjustment for
    # three years" vs a stated non-zero historical change) -- distinct
    # from uncertainties (an absence of information) and distinct from
    # stakeholder_conflict (disagreeing people, not disagreeing facts).
    # Deliberately not resolved either way; both sides are preserved.
    contradictions: list[str] = Field(default_factory=list, max_length=6)
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
    # model_orchestration below is a real, deliberately-named field (which
    # model handled which stage of reasoning), not an accidental collision.
    # This only silences Pydantic's protected-namespace warning for names
    # starting with "model_" -- it changes no behavior and renames nothing.
    model_config = ConfigDict(protected_namespaces=())

    # Phase 1 / R41 foundation: carried through from case creation,
    # never set or changed by reasoning itself in this phase. See
    # models.py's CaseMode/CaseModeSource for what these mean.
    case_mode: Optional[CaseMode] = None
    case_mode_source: Optional[CaseModeSource] = None
    # Phase 2 / R41 foundation: the single, structured source of
    # commercial truth for this case -- assembled from everything else
    # on this position (financial_impact, decision_audit, etc.), never
    # a second computation path. dict, not the Pydantic CommercialKernel
    # type, to avoid a circular import between models.py and
    # pipeline/kernel.py; kernel.py's CommercialKernel model is the
    # authoritative schema this dict conforms to.
    kernel: Optional[dict] = None
    # Phase 3 / R41: the supplier_request-specific answer contract
    # (DECISION/WHY/MONEY/LEVERAGE/TRADE-OFF/NEXT MOVE/WHAT COULD
    # CHANGE THIS/DRAFT RESPONSE), built only when case_mode is
    # supplier_request. Other modes leave this None -- they are not
    # built yet.
    supplier_request_answer: Optional[dict] = None
    # Phase 4 / R41: the commercial_signal-specific answer contract
    # (SIGNAL/WHAT THE DATA SAYS/WHAT MAY EXPLAIN IT/WHAT WE CANNOT
    # PROVE/COMMERCIAL RISK/WHAT TO CHECK NEXT/ACTION PLAN), built only
    # when case_mode is commercial_signal.
    commercial_signal_answer: Optional[dict] = None
    # Phase 5 / R41: the category_strategy-specific answer contract.
    # See app/pipeline/category_strategy_profile.py's module docstring
    # for this pass's explicitly scoped coverage (category diagnosis +
    # evidence-based supplier strategy) versus what's deliberately not
    # built yet (market intelligence, full 3-year roadmap, contract/
    # supply-chain detail).
    category_strategy_answer: Optional[dict] = None
    # Phase 7: the problem-solving-specific answer contract (Problem/
    # What we know/What is likely/What still needs checking/
    # Recommendation/Next action). Only populated when the case's
    # content_type is genuinely "problem_solving".
    problem_solving_answer: Optional[dict] = None

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
    # External market context is preserved separately from supplier evidence.
    # It can inform questions, but never becomes proof of the supplier's own cost base.
    market_verification: Optional[dict[str, Any]] = None
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
    # R26: deterministic decision-under-uncertainty view. It does not replace
    # the recommendation; it tells the buyer whether to decide, protect, or
    # answer one decision-critical question before committing.
    decision_under_uncertainty: Optional[dict[str, Any]] = None
    # Release 19: deterministic Trust Certification. This certifies the
    # integrity of the decision process; it never certifies the commercial
    # outcome itself and cannot alter the recommendation.
    trust_certification: Optional[dict[str, Any]] = None
    # Release 29: buyer-readable deterministic trust ledger. It classifies
    # evidence and decision outputs as VERIFIED/CALCULATED/ASSUMED/INFERRED/UNKNOWN.
    trust_engine: Optional[dict[str, Any]] = None
    # Release 31: deterministic Commercial Decision Engine. One operational
    # decision spine for daily buyer use; it compresses validated layers and
    # never creates new facts, thresholds or model inference.
    commercial_decision_engine: Optional[dict[str, Any]] = None
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
    negotiation_intelligence: Optional[dict[str, Any]] = None
    # Release 33: supplier-centric deterministic memory. Read-time context only;
    # it never mutates the recommendation or turns sparse history into prediction.
    supplier_memory: Optional[dict[str, Any]] = None
    # Release 34.1: adaptive second-opinion model orchestration; advisory only.
    model_orchestration: Optional[dict[str, Any]] = None
    # R37: deterministic commercial reasoning loop. Reconciles the validated
    # decision layers and exposes the strongest independent counter-case.
    reasoning_loop: Optional[dict[str, Any]] = None
    # R38: deterministic buyer-facing answer packet. Compresses validated decision layers
    # into one actionable answer; it cannot create new facts, calculations, thresholds or
    # supplier economics.
    commercial_answer: Optional[dict[str, Any]] = None
    # Final-answer-reconciliation safety net: verifies the assembled
    # commercial_answer against a fresh recomputation of the canonical
    # evidence/calculations immediately before the response is
    # returned -- see app/pipeline/final_answer_reconciliation.py.
    final_answer_reconciliation: Optional[dict[str, Any]] = None
    # R39: unified buyer-first commercial memory across supplier history, organizational precedent and observed activity.
    commercial_memory: Optional[dict[str, Any]] = None
    # Release 35.1: bounded agentic workflow; preparation/approval state only.
    agentic_workflow: Optional[dict[str, Any]] = None
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


class OrganisationFormatResponse(BaseModel):
    id: UUID
    name: str
    format_type: str
    source_filename: str
    slide_count: int
    status: Literal["ready"]
    created_at: Optional[datetime] = None


class OrganisationFormatRenderRequest(BaseModel):
    format_id: UUID


class DecisionFormatRequest(BaseModel):
    format_name: Literal["decision_cockpit", "cfo_brief", "category_review", "supplier_meeting", "one_page", "executive_60_second"]


class CustomFormatRequest(BaseModel):
    template: str = Field(..., min_length=1, max_length=12000)


class MissingField(BaseModel):
    field: str
    prompt: str
    why: str


class IngestionArtifactResponse(BaseModel):
    id: UUID
    filename: str
    media_type: str
    byte_size: int
    extraction_method: str
    status: Literal["ready", "failed"]
    extracted_characters: int
    content_preview: str
    warnings: list[str] = Field(default_factory=list)


class CommercialDecisionResponse(BaseModel):
    id: UUID
    status: Status
    raw_question: str
    ingestion_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    parent_decision_id: Optional[UUID] = None
    classified_content_type: Optional[ContentType] = None
    classified_decision_type: Optional[DecisionType] = None
    # Phase 1 / R41 foundation: the returned mode, and how it was
    # determined -- an explicit buyer selection or a fallback inference.
    # This is the final, authoritative step of the lifecycle: selected
    # -> stored -> restored -> processed -> returned. If this doesn't
    # match what was actually selected, mode has been lost somewhere
    # upstream, which is exactly what this phase exists to prevent.
    case_mode: Optional[CaseMode] = None
    case_mode_source: Optional[CaseModeSource] = None
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
    ingestion_artifact_ids: list[UUID] = Field(default_factory=list, max_length=10)


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
