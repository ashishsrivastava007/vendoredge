"""
NormalizedEvidence — the single evidence-normalization boundary.

This is the architectural fix for the class of bug found and fixed
one-by-one throughout tonight: the same evidence extracted, interpreted,
or derived differently at different pipeline stages. After this module,
no downstream component may independently re-extract, re-derive, or
reinterpret evidence -- every stage consumes the same NormalizedEvidence
object, produced exactly once, immediately after classification.

Three-tier structure, deliberately not one giant schema:
- common: genuinely case-independent (one supplier, one shipping lane,
  one currency, one Incoterm -- true regardless of content_type)
- case: PriceIncreaseEvidence or QuoteComparisonEvidence, genuinely
  different in shape between the two content types (price is singular
  in a price-increase case, per-supplier in a quote comparison) --
  forcing these into one shared shape would distort one of the two cases
- derived: computed ONCE, here, from common+case -- never re-derived
  downstream (freight_relevant, duty_relevant, resolved annual spend)
- history: from the database, not from this question's text at all
- provenance: a parallel traceability ledger, not fields wrapped inline,
  so downstream business logic reads clean typed values while still
  being fully auditable
"""
from __future__ import annotations
from typing import Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator


EvidenceSource = Literal[
    "llm_extraction",
    "deterministic_fallback",
    "user_followup",
    "database_history",
    "derived_calculation",
    "both_agree",
]


class FieldProvenance(BaseModel):
    """
    One entry per field name, in NormalizedEvidence.provenance. Answers,
    for any value at any point downstream: did this come from the user's
    original text via the model, a regex fallback, a follow-up answer, or
    a calculation -- without guessing from context or re-inspecting raw
    dictionaries.

    Deliberately no numeric confidence score per field -- that would
    invite the same false-precision problem Hard Rule 1 exists to
    prevent. Verification standing is a direct, honest consequence of
    source, not a separately invented number.

    supplier_name: which named supplier this specific fact is about, when
    applicable -- Quality Gate Guarantee #1 requires provenance to answer
    "where did this number come from" INCLUDING which entity it describes,
    not just which extraction method found it. None for case-level facts
    that aren't about a specific supplier (e.g. Finance's savings target).
    """
    source: EvidenceSource
    conflicting: bool = False
    conflicting_values: Optional[tuple] = None
    stage_captured: str
    supplier_name: Optional[str] = None


QualificationStatus = Literal["not_started", "in_progress", "complete", "unknown"]

# Material Caveat Ledger: a plain boolean would force "we never discussed
# this" and "we confirmed there is none" into the same false value --
# exactly the fabrication-by-omission Hard Rule 1 exists to prevent. Four
# genuinely distinct states, defaulting to "unknown," never to "none."
ProductionHistoryStatus = Literal["established", "limited", "none", "unknown"]

StakeholderViewType = Literal[
    "objective",
    "preference",
    "risk_concern",
    "constraint",
    "experience",
    "rumor",
    "recommendation",
]


class StakeholderView(BaseModel):
    """
    A directly attributed internal/external stakeholder view.

    This is deliberately NOT treated as supplier/commercial fact. A stakeholder
    may have valuable insider knowledge, a strong operational preference, or a
    risk concern, but VendorEdge must preserve the source and type of the view
    so the reasoner can weigh it rather than silently promote it into evidence.
    """
    stakeholder_name: str
    role: Optional[str] = None
    view_type: StakeholderViewType
    statement: str
    basis: Optional[str] = None
    explicitly_stated: bool = True


class SupplierEvidence(BaseModel):
    """
    Evidence specific to ONE named supplier within a multi-supplier case.

    Direct architectural fix for the confirmed Case 5 finding: Incoterm
    and region were modeled as single, case-wide values in
    CommonEvidence, but a real, verbatim case showed two different
    suppliers genuinely having two different Incoterms (FerroSteel=FOB,
    NordicMetals=CIF) and two different regions. Forcing that into one
    field made a real disagreement look like an extraction error, when
    the extraction was actually correct and the data model was too
    narrow to represent it. This is the fix: per-supplier fields for
    everything that legitimately varies by supplier, common.* remains
    for the genuinely single-supplier price_increase case and for
    anything that's true for the whole transaction regardless of which
    supplier (e.g. the buyer's own reporting currency).

    qualification_status is deliberately a structured enum, not free
    text -- this is what makes Guarantee #4 (claim-strength integrity)
    checkable deterministically: "qualified" used in prose can be
    directly compared against a real status value, not parsed out of a
    sentence after the fact.
    """
    supplier_name: str
    incoterm: Optional[str] = None
    region: Optional[str] = None
    currency: Optional[str] = None
    price_usd: Optional[float] = None
    # Currency-neutral numeric price parsed from the explicit display string.
    # This is used only when comparing suppliers quoted in the same currency;
    # it is never silently converted to USD.
    price_amount: Optional[float] = None
    price_display: Optional[str] = None
    lead_time_weeks: Optional[float] = None
    otif_percent: Optional[float] = None
    defect_rate_percent: Optional[float] = None
    payment_terms: Optional[str] = None
    capacity_percent: Optional[float] = None
    qualification_status: QualificationStatus = "unknown"
    qualification_percent: Optional[float] = None
    # Evidence-retention fix, confirmed root cause: a case can state a
    # qualification TIMEFRAME ("4-6 months", "approximately 6 months")
    # independently of, and in addition to, qualification_status's
    # categorical state. There was previously nowhere in the schema to
    # put this fact at all -- not a classifier failure, a genuine
    # missing field -- so an explicitly stated timeframe was silently
    # dropped, and the case's own qualification_status defaulted to
    # "unknown", which then read back as "qualification status was not
    # provided" even though it plainly was. Free text deliberately, not
    # a structured min/max duration: cases state timeframes in enough
    # different shapes ("4-6 months", "approximately 6 months", "one
    # quarter") that forcing a numeric structure here would risk losing
    # exactly the kind of nuance this fix exists to preserve.
    qualification_time_estimate: Optional[str] = None
    # Same fix, for capacity: a stated capacity_percent can be either a
    # validated figure or an unvalidated claim -- two different evidence
    # states that were previously conflated into one plain number. Same
    # explicit-only discipline as certification_status/preferred_supplier_
    # status directly above: only moves off "unknown" on an explicit
    # statement, never inferred from the presence or absence of a number.
    capacity_status: Literal["validated", "unvalidated", "unknown"] = "unknown"
    is_incumbent: bool = False
    # Phase 4 / R41 (Commercial Signal profile): a genuinely new need --
    # a multi-supplier commercial-signal case (e.g. "why is category
    # spend rising faster than volume") needs each named supplier's OWN
    # current/prior spend and volume, not just the one "subject
    # supplier" price_increase already tracked on case.annual_spend_usd/
    # case.prior_annual_spend_usd. Additive and optional; a
    # price_increase case naming only one supplier is entirely
    # unaffected.
    current_annual_spend_usd: Optional[float] = None
    prior_annual_spend_usd: Optional[float] = None
    current_annual_volume_units: Optional[float] = None
    prior_annual_volume_units: Optional[float] = None
    # Fix for the confirmed master-case bug: freight is inherently a
    # per-supplier fact (it depends on THAT supplier's own Incoterm), not
    # a case-wide value. The original single-value
    # PriceIncreaseEvidence.freight_cost_or_estimate field had no
    # equivalent here, meaning a quote_comparison case could never
    # represent a supplier's stated freight cost at all -- the
    # evidence-gate always saw it as missing regardless of what the user
    # actually said, since there was structurally nowhere to store it.
    freight_cost_or_estimate: Optional[str] = None
    # Material Caveat Ledger: separate from qualification_status deliberately --
    # a supplier can be technically qualified while genuinely having no
    # production track record; the two facts must never be conflated.
    production_history_status: ProductionHistoryStatus = "unknown"
    # Evidence-to-claim firewall (supplier-claim taxonomy). Same
    # discipline as qualification_status throughout: a genuine three-way
    # split so silence ("unknown") is never converted into a negative
    # ("not_certified"/"not_preferred") by inference. Only an explicit
    # statement in either direction moves a field off "unknown".
    certification_status: Literal["certified", "not_certified", "unknown"] = "unknown"
    certification_detail: Optional[str] = None
    preferred_supplier_status: Literal["preferred", "not_preferred", "unknown"] = "unknown"


class CommonEvidence(BaseModel):
    """
    Genuinely case-independent. A quote_comparison case's supplier
    region, currency, Incoterm, and duty rate matter exactly as much as
    a price_increase case's do -- these describe the shipping lane and
    transaction context, not the specific commercial ask.
    """
    supplier_name: Optional[str] = None
    supplier_region_or_market: Optional[str] = None
    supplier_currency: Optional[str] = None
    incoterm: Optional[str] = None
    duty_or_tax_rate_percent: Optional[float] = None
    annual_volume_units: Optional[float] = None
    unit_price_usd: Optional[float] = None


class MarketDriverClaim(BaseModel):
    """Phase 5B / R41: one market-driver claim, exactly as the case
    stated it. Never independently verified against a live source (none
    exists in this environment) -- attributed_to distinguishes a
    supplier's own claim from the buyer's own citation, which the
    kernel maps to different evidence states (SUPPLIER_CLAIM vs
    VERIFIED-as-in-stated-in-the-case, matching the same convention
    already used for every other case fact)."""
    driver: str  # e.g. "steel", "electricity", "freight", "EUR/SEK"
    direction: Optional[str] = None  # e.g. "increased", "decreased"
    magnitude: Optional[str] = None  # e.g. "12%" -- kept as stated text, never assumed to be precise
    geography: Optional[str] = None
    period: Optional[str] = None
    source: Optional[str] = None  # e.g. "LME", "the supplier", "not specified"
    attributed_to: Literal["supplier", "buyer_cited", "unspecified"] = "unspecified"
    # A driver contributing a stated SHARE of a supplier's cost --
    # ONLY ever populated when the case itself states this weight
    # explicitly (e.g. "steel is 30% of our cost"). Never inferred,
    # never assumed, never defaulted -- see market_intelligence.py's
    # explicit refusal to estimate an unstated weight.
    stated_cost_share_percent: Optional[float] = None
    # Foundation-completion fields (evidence-policy provenance
    # requirement: source + date + period + geography + unit/currency +
    # driver/category mapping, all explicit). Each is None unless the
    # case genuinely states it -- never defaulted, never inferred.
    publication_or_retrieval_date: Optional[str] = None  # e.g. "2023-06" or "three years ago" -- kept as stated, used for stale-data detection
    unit_or_currency: Optional[str] = None  # e.g. "EUR/tonne", "USD" -- for currency-mismatch detection against the case's own currency
    # Which specific supplier this claim is about, if any. None means
    # the claim is category/market-wide and must NEVER be silently
    # applied to one supplier's exposure -- see
    # market_intelligence.py's unsupported-attribution guard.
    applies_to_supplier: Optional[str] = None
    # The category/commodity this driver is being claimed to affect,
    # as the case itself frames it (e.g. "industrial valves"). Used
    # only to check the claim was made in the context of the case's
    # own category -- never used to independently classify or
    # reclassify what category the case is about.
    stated_category_context: Optional[str] = None


class ESGClaim(BaseModel):
    """Category strategy / ESG architecture: one ESG or sustainability
    fact, exactly as the case stated it. Modeled directly on
    MarketDriverClaim -- same discipline, same reasoning chain shape
    (ESG fact -> category relevance -> supplier exposure -> commercial
    implication -> action). Never independently verified; there is no
    live ESG data, certification registry, or emissions database
    connected in this environment. Nothing here invents an emissions
    figure, a certification, a score, or a regulatory obligation --
    this exists purely to retain what the case itself already states."""
    dimension: Literal["environmental", "social", "governance"]
    topic: str
    statement: str
    direction: Optional[str] = None
    magnitude: Optional[str] = None
    source: Optional[str] = None
    attributed_to: Literal["supplier", "buyer_cited", "unspecified"] = "unspecified"
    applies_to_supplier: Optional[str] = None
    publication_or_retrieval_date: Optional[str] = None
    geography: Optional[str] = None
    stated_requirement: Optional[str] = None


class PriceIncreaseEvidence(BaseModel):
    """Case-specific for price_increase. Price and terms are singular --
    one existing relationship, one current price -- unlike quote_comparison
    where they're inherently per-supplier."""
    current_price_or_terms: Optional[str] = None
    requested_increase_percent: Optional[float] = None
    suppliers_stated_justification: Optional[str] = None
    how_critical_is_this_supplier_relationship: Optional[str] = None
    annual_spend_usd: Optional[float] = None
    switching_cost_usd: Optional[float] = None
    freight_cost_or_estimate: Optional[str] = None
    # Added for the scenario engine: a case can genuinely present two
    # numbers to compare, not one -- e.g. Supplier A's "we'll drop 11%
    # to 7% if you commit to a 3-year term." Optional and additive; a
    # case with only one percentage (the overwhelmingly common shape)
    # is entirely unaffected -- this stays None and financial.py falls
    # back to its existing single-scenario calculation exactly as before.
    alternative_scenario_percent: Optional[float] = None
    alternative_scenario_label: Optional[str] = None
    # Entity-aware calculation fix: `annual_spend_usd` above is ambiguous
    # by construction -- it has no entity/subject tag, and a case that
    # states BOTH a category-level total and a specific supplier's own
    # total (e.g. "category spend is EUR 8.40M; Supplier A's own spend
    # is EUR 5.55M") gives the classifier no structured way to know
    # which one belongs in that one field. Confirmed root cause of a
    # real, reproduced defect: a supplier-specific scenario calculation
    # silently used the category total instead, producing a correct-
    # looking but semantically wrong number (EUR 924,000 instead of the
    # correct EUR 610,500). category_annual_spend_usd is additive and
    # optional; when a case has no genuine category/supplier ambiguity
    # at all (the overwhelming majority of price_increase cases), it
    # stays None and every existing case is entirely unaffected.
    category_annual_spend_usd: Optional[float] = None
    # Contradiction/reconciliation fix, confirmed root cause: a case can
    # state a supplier's own pricing history directly in the text (e.g.
    # "Year -3: +2.5%, Year -2: +3.0%, Year -1: 0%") which is a
    # genuinely different fact from HistoryContext (database-recalled
    # prior VendorEdge decisions) -- there was previously nowhere in the
    # schema for THIS-CASE-STATED historical figures at all, meaning a
    # supplier's own claim ("no price adjustment for three years") could
    # never be checked against the case's own documented history, even
    # when the case supplied both. Free text list, one entry per stated
    # historical fact, deliberately not a structured year/percent pair --
    # cases state this in enough different shapes that forcing a rigid
    # structure risks losing exactly the nuance this exists to preserve.
    stated_price_history: list[str] = Field(default_factory=list)
    # Item 1 fix: a genuine, structured conflict between two stated
    # values for the same fact -- extracted directly by the classifier's
    # own reading of the text (see the prompt instruction), not detected
    # via a currency-specific regex. Currency-agnostic by construction:
    # nothing here depends on which currency symbol appears, since the
    # LLM is judging whether the NUMBERS disagree, not pattern-matching
    # a symbol. Empty list is the overwhelming normal case.
    unresolved_value_conflicts: list[dict] = Field(default_factory=list)
    # Question-coverage fix: category/supplier YoY growth calculations
    # (spend growth, volume growth, average-price growth, spend-share
    # change) did not exist anywhere in the codebase -- there was no
    # prior-year figure for either a category or a specific supplier at
    # all, only a single current-year annual_spend_usd. Same entity-
    # scoping discipline as category_annual_spend_usd above: category
    # and supplier figures are always kept in explicitly separate
    # fields, never conflated.
    category_prior_annual_spend_usd: Optional[float] = None
    category_annual_volume_units: Optional[float] = None
    category_prior_annual_volume_units: Optional[float] = None
    prior_annual_spend_usd: Optional[float] = None  # the specific supplier's own prior-year spend
    prior_annual_volume_units: Optional[float] = None  # the specific supplier's own prior-year volume
    # Phase 5B / R41: market driver evidence -- ONLY ever populated from
    # what the case text itself genuinely states (a claim the supplier
    # made, or a source the buyer themselves cited when writing the
    # case) -- there is no live external market-data feed anywhere in
    # this environment, and nothing here invents, looks up, or
    # fabricates a market figure. This is structurally identical in
    # spirit to stated_price_history: evidence retention of what the
    # case already says, never new information VendorEdge introduces.
    market_driver_claims: list[MarketDriverClaim] = Field(default_factory=list)
    # Category strategy / ESG architecture: same evidence-retention
    # discipline as market_driver_claims -- only ever populated from
    # what the case text genuinely states, never invented, never
    # looked up against a live ESG data source (none exists here).
    esg_claims: list[ESGClaim] = Field(default_factory=list)


class RootCauseCandidateEvidence(BaseModel):
    """Phase 7: one candidate root cause, exactly as the case states it.
    Structured, not free text with keyword detection -- category and
    supporting_evidence are explicit fields the extraction step (or the
    caller) must populate directly, replacing an earlier design that
    guessed "is this a generic label" from substring matching on the
    label text. A candidate with no supporting_evidence is never
    upgraded to a validated cause regardless of how specific or generic
    its label sounds -- the label's wording is no longer a signal this
    system reasons from at all."""
    label: str
    category: Literal["symptom", "direct_cause", "contributing_cause", "root_cause", "unspecified"] = "unspecified"
    supporting_evidence: list[str] = Field(default_factory=list)
    source: Literal["oem_or_supplier", "internal_data", "stakeholder_view", "unspecified"] = "unspecified"


class AlternativeLeverEvidence(BaseModel):
    """Phase 7: one non-resource alternative genuinely considered before
    a resource/system countermeasure. `lever_type` is an explicit,
    stated classification -- never inferred from the lever's wording --
    so the countermeasure gate checks a real field, not a keyword
    match against free text."""
    description: str
    lever_type: Literal[
        "process_change", "specification_change", "governance", "sequencing",
        "existing_system_use", "supplier_change", "alternate_component",
        "refurbish", "defer_with_mitigation", "other",
    ] = "other"
    why_insufficient: Optional[str] = None
    evaluated: bool = True


class CountermeasureProposalEvidence(BaseModel):
    """Phase 7: one proposed countermeasure. `resource_type` is an
    explicit, stated field -- "headcount"/"system_or_infrastructure"
    versus "process"/"governance"/"supplier"/"specification"/"other" --
    never guessed from the proposal's wording. This is the structural
    fix requested: the Maersk-principle gate now reads a real
    classification field, not a substring match against free text that
    a differently-phrased resource proposal could evade."""
    proposal: str
    resource_type: Literal["headcount", "system_or_infrastructure", "process", "governance", "supplier", "specification", "other"] = "other"
    alternatives_considered: list[AlternativeLeverEvidence] = Field(default_factory=list)
    why_alternatives_insufficient: Optional[str] = None
    evidence: Optional[str] = None


class ProblemSolvingEvidence(BaseModel):
    """Phase 7: case-specific evidence for a complex problem-solving
    case. Problem/current/desired/impact are retained exactly as
    stated, never invented -- diagnose_problem() in problem_solving.py
    computes the gap only when both current and desired conditions are
    genuinely present."""
    problem_statement: Optional[str] = None
    current_condition: Optional[str] = None
    desired_condition: Optional[str] = None
    stated_impact: Optional[str] = None
    root_cause_candidates: list[RootCauseCandidateEvidence] = Field(default_factory=list)
    countermeasure_proposals: list[CountermeasureProposalEvidence] = Field(default_factory=list)
    # Outcome tracking: expected/target/actual/sustained, each only
    # ever populated from what the case explicitly states -- never one
    # derived from another.
    expected_outcome: Optional[str] = None
    target_outcome: Optional[str] = None
    actual_outcome: Optional[str] = None
    outcome_sustained: Optional[bool] = None


class QuoteComparisonEvidence(BaseModel):
    """Case-specific quote-comparison evidence.

    The classifier may return scalar numeric values as JSON (for example,
    ``2`` rather than ``"2"``) even though these normalized fields are
    intentionally human-readable strings. Numeric scalars are normalized
    at this boundary so valid extraction cannot crash the decision pipeline.
    Structured lists/dicts are not coerced because they indicate a schema
    mismatch that should remain visible.
    """
    number_of_suppliers_being_compared: Optional[str] = None
    price_per_supplier: Optional[str] = None
    payment_terms_per_supplier: Optional[str] = None
    lead_time_per_supplier: Optional[str] = None
    quality_or_defect_history_per_supplier: Optional[str] = None
    is_this_a_new_or_incumbent_relationship: Optional[str] = None

    @field_validator(
        "number_of_suppliers_being_compared",
        "price_per_supplier",
        "payment_terms_per_supplier",
        "lead_time_per_supplier",
        "quality_or_defect_history_per_supplier",
        "is_this_a_new_or_incumbent_relationship",
        mode="before",
    )
    @classmethod
    def _normalize_scalar_evidence(cls, value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        return value


AnnualSpendResolutionMethod = Literal["direct", "derived_from_price_and_volume", "unresolved"]


class DerivedEvidence(BaseModel):
    """
    Computed exactly once, here, from common+case. Every downstream
    consumer (evidence-gate, financial calculation, methodology
    contracts) reads these directly and never re-derives them -- this is
    the direct fix for the class of bug where the same derivation logic
    existed independently in three separate places and only agreed by
    coincidence.
    """
    resolved_annual_spend_usd: Optional[float] = None
    annual_spend_resolution_method: AnnualSpendResolutionMethod = "unresolved"
    freight_relevant: bool = False
    duty_relevant: bool = False
    currency_mismatch: bool = False
    # The currency the resolved annual spend figure is genuinely
    # denominated in -- distinct from common.supplier_currency, which
    # describes what currency the SUPPLIER bills/quotes in and can
    # legitimately differ from the spend total's own currency (e.g. "the
    # supplier bills in EUR but our tracked annual spend is a genuinely
    # stated USD figure"). Computed once, with a clear priority, so
    # financial.py and every other consumer never has to re-derive it or
    # guess: a genuine dollar figure present alongside the resolved spend
    # number takes priority (matches the extraction contract's own
    # "annual_spend_usd" naming intent); otherwise the case's single
    # stated currency; otherwise the existing conventional USD default.
    spend_currency: str = "USD"
    # Whether currency_mismatch (genuine LLM-vs-fallback extraction
    # conflict, not merely "a currency was mentioned") makes the resolved
    # spend figure unsafe to calculate against at all. A single, clearly
    # stated currency -- of any kind -- is safe; this only goes False on
    # a real, detected disagreement about what currency is actually in
    # play, which spend_currency above cannot resolve on its own.
    currency_calculation_safe: bool = True
    # Parsed once, here, from case.freight_cost_or_estimate (free text the
    # user typed into the evidence-gate, e.g. "€35/unit") -- closes the
    # loop so the guaranteed calculation reads a real number directly,
    # never re-parsing the same text a second time downstream.
    freight_cost_per_unit_usd: Optional[float] = None


class HistoryContext(BaseModel):
    """
    From the database, not from this question's text -- genuinely
    different in kind from everything else in NormalizedEvidence, so
    kept as its own top-level section rather than folded into derived.
    """
    org_history: list[dict] = Field(default_factory=list)
    supplier_history: list[dict] = Field(default_factory=list)
    confidence_calibration_note: Optional[str] = None


class NormalizedEvidence(BaseModel):
    """
    The single evidence-normalization boundary. Produced exactly once,
    immediately after classification, by normalize_evidence() below.
    Every downstream stage (evidence-gate, reasoning, financial
    calculation, methodology contracts) consumes this object directly --
    none of them may independently call a fallback function, re-derive a
    relevance flag, or re-interpret raw extraction dictionaries.
    """
    content_type: Literal["price_increase", "quote_comparison", "problem_solving"]
    common: CommonEvidence
    case: Union[PriceIncreaseEvidence, QuoteComparisonEvidence, ProblemSolvingEvidence]
    derived: DerivedEvidence
    history: HistoryContext = Field(default_factory=HistoryContext)
    provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    # Per-supplier evidence, populated when the case genuinely names
    # multiple suppliers with differing attributes -- empty for a plain
    # single-supplier price_increase case, where common.* already covers
    # everything correctly.
    suppliers: list[SupplierEvidence] = Field(default_factory=list)
    # Stakeholder views are evidence about stakeholder positions, not facts.
    # They remain separately attributable so conflicting views can be surfaced
    # and weighed without creating false consensus.
    stakeholder_views: list[StakeholderView] = Field(default_factory=list)
    # Model-output contract warnings. These are intentionally separate from
    # LLM-vs-fallback conflicts: a malformed extraction is downgraded to
    # missing evidence and surfaced here, rather than becoming a 500 or an
    # invented value. Downstream trust logic may display these warnings.
    normalization_warnings: list[str] = Field(default_factory=list)

    def supplier_by_name(self, name: str) -> Optional[SupplierEvidence]:
        for s in self.suppliers:
            if s.supplier_name == name:
                return s
        return None

    def as_flat_evidence_dict(self) -> dict:
        """
        Backward-compatible view for any code path that still needs a
        flat dict shape during migration (e.g. the existing evidence-gate
        prompt-building text, or storage into the existing
        user_supplied_inputs JSONB column). This is a genuine, temporary
        adapter -- not a second source of truth, since it's always
        derived fresh from the real object, never stored or read back
        independently.
        """
        flat = {}
        flat.update(self.common.model_dump(exclude_none=True))
        flat.update(self.case.model_dump(exclude_none=True))
        return flat
