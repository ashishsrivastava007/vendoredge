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
from pydantic import BaseModel, Field


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
    is_incumbent: bool = False
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


class QuoteComparisonEvidence(BaseModel):
    """Case-specific for quote_comparison. Genuinely per-supplier in
    real-world shape -- kept separate from price_increase's singular
    fields rather than forced into a shared structure."""
    number_of_suppliers_being_compared: Optional[str] = None
    price_per_supplier: Optional[str] = None
    payment_terms_per_supplier: Optional[str] = None
    lead_time_per_supplier: Optional[str] = None
    quality_or_defect_history_per_supplier: Optional[str] = None
    is_this_a_new_or_incumbent_relationship: Optional[str] = None


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
    # Production Hardening fix for the confirmed red-team finding: when
    # currency_mismatch is True (a non-USD currency was genuinely
    # detected) AND the raw text contains no literal "$" sign anywhere,
    # any number in a "_usd"-suffixed field is suspect -- it may have
    # been lifted directly from a foreign-currency figure without
    # conversion. Computed once, here, so financial.py never has to
    # re-derive this itself; it just refuses to calculate when this is
    # False. Deliberately narrow: if a real "$" appears anywhere in the
    # text (the user genuinely gave a dollar figure alongside foreign
    # context), this stays True and the calculation proceeds normally.
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
    content_type: Literal["price_increase", "quote_comparison"]
    common: CommonEvidence
    case: Union[PriceIncreaseEvidence, QuoteComparisonEvidence]
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
