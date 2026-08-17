"""
normalize_evidence() — the single evidence-normalization boundary.

This is the ONLY function in the entire codebase permitted to call a
deterministic fallback, resolve a conflict between LLM and fallback
extraction, or derive freight/duty relevance and resolved annual spend.
Everything downstream (evidence-gate, reasoning, financial calculation,
methodology contracts) consumes the NormalizedEvidence object this
produces and does no independent extraction, derivation, or
reinterpretation of its own.
"""
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, QuoteComparisonEvidence,
    DerivedEvidence, HistoryContext, FieldProvenance, SupplierEvidence, StakeholderView,
)
from app.pipeline.region_fallback import detect_supplier_region_fallback
from app.pipeline.incoterm_fallback import detect_incoterm_fallback, normalize_incoterm
from app.pipeline.duty_fallback import detect_duty_rate_fallback
from app.pipeline.currency_fallback import detect_currency_fallback
from app.pipeline.volume_fallback import detect_annual_volume_fallback
from app.pipeline.financial_fallback import (
    extract_annual_spend_fallback, extract_requested_change_percent_fallback,
)
from app.pipeline.numeric_parsing import parse_numeric_value
from app.pipeline.evidence import INCOTERMS_WHERE_BUYER_BEARS_FREIGHT
from app import caps
import math
import re

# Real, small epsilon for numeric agreement checks -- two extraction
# methods producing 2000000.0 vs 2000000.01 should count as agreement,
# not a spurious conflict from floating-point noise.
_NUMERIC_AGREEMENT_TOLERANCE = 0.01
_NUMERIC_STRING_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def _coerce_number(value, field_name: str, warnings: list[str], *, allow_percent_suffix: bool = False):
    """Accept only a real numeric scalar or a strictly numeric string.

    LLM JSON is an external, model-generated boundary. Numeric fields are
    deliberately strict: we accept harmless representation drift (2 vs
    "2", 0.8 vs "0.8") but never reinterpret arbitrary prose such as
    "35 weeks" or "EUR 52" as a number. Invalid values become UNKNOWN at
    the evidence layer and are surfaced as a normalization warning rather
    than crashing the request.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        warnings.append(f"schema:{field_name}:boolean_for_numeric")
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            warnings.append(f"schema:{field_name}:non_finite_numeric")
            return None
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if allow_percent_suffix and text.endswith("%"):
            text = text[:-1].strip()
        if _NUMERIC_STRING_RE.fullmatch(text):
            try:
                number = float(text)
                if math.isfinite(number):
                    return number
            except ValueError:
                pass
        warnings.append(f"schema:{field_name}:invalid_numeric_scalar")
        return None
    warnings.append(f"schema:{field_name}:unexpected_type")
    return None


def _coerce_text(value, field_name: str, warnings: list[str], *, numeric_scalar_ok: bool = False):
    """Keep text fields textual; only convert numeric scalars where the
    extraction contract explicitly permits a number-shaped answer."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if numeric_scalar_ok and isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            warnings.append(f"schema:{field_name}:non_finite_numeric_text")
            return None
        return str(value)
    warnings.append(f"schema:{field_name}:unexpected_text_type")
    return None


def _safe_enum(value, allowed: set[str], default: str, field_name: str, warnings: list[str]):
    if isinstance(value, str) and value in allowed:
        return value
    if value is not None:
        warnings.append(f"schema:{field_name}:invalid_enum")
    return default


def _resolve_field(raw_question, llm_value, fallback_value, field_name, provenance, is_numeric=False):
    """
    Implements the exact conflict-resolution rule from the approved
    design:
      - only one present -> use it
      - both present, agree -> use LLM value, mark both_agree
      - both present, disagree -> use LLM value as primary, mark
        conflicting=True, retain BOTH values in provenance, log a
        telemetry event (handled by the caller, which has DB access)
    Returns (resolved_value, is_conflict: bool).
    """
    if llm_value is None and fallback_value is None:
        return None, False

    if llm_value is not None and fallback_value is None:
        provenance[field_name] = FieldProvenance(source="llm_extraction", stage_captured="normalize_evidence")
        return llm_value, False

    if llm_value is None and fallback_value is not None:
        provenance[field_name] = FieldProvenance(source="deterministic_fallback", stage_captured="normalize_evidence")
        return fallback_value, False

    # Both present.
    values_agree = False
    if is_numeric:
        try:
            values_agree = abs(float(llm_value) - float(fallback_value)) < _NUMERIC_AGREEMENT_TOLERANCE
        except (TypeError, ValueError):
            values_agree = False
    else:
        values_agree = str(llm_value).strip().lower() == str(fallback_value).strip().lower()

    if values_agree:
        provenance[field_name] = FieldProvenance(source="both_agree", stage_captured="normalize_evidence")
        return llm_value, False

    # Genuine disagreement -- never silently pick one and forget the other.
    provenance[field_name] = FieldProvenance(
        source="llm_extraction",
        conflicting=True,
        conflicting_values=(llm_value, fallback_value),
        stage_captured="normalize_evidence",
    )
    return llm_value, True


def normalize_evidence(
    raw_question: str,
    content_type: str,
    llm_extracted_evidence: dict,
    llm_numeric_facts: dict,
    history: HistoryContext | None = None,
    supplier_specific_evidence: list[dict] | None = None,
    stakeholder_views: list[dict] | None = None,
) -> tuple[NormalizedEvidence, list[str]]:
    """
    THE single evidence-normalization boundary. Returns the
    NormalizedEvidence object and a list of field names where a genuine
    LLM-vs-fallback conflict was detected (the caller logs telemetry for
    these, since normalize_evidence() itself stays free of DB access to
    keep it a pure, easily-testable function).
    """
    provenance: dict[str, FieldProvenance] = {}
    conflicts: list[str] = []
    normalization_warnings: list[str] = []

    # Never let malformed model JSON become a production 500. These are
    # model-output contracts, not trusted application inputs. A bad shape is
    # downgraded to missing evidence and remains visible to the caller.
    if not isinstance(llm_extracted_evidence, dict):
        normalization_warnings.append("schema:extracted_evidence:expected_object")
        llm_extracted_evidence = {}
    if not isinstance(llm_numeric_facts, dict):
        normalization_warnings.append("schema:numeric_facts:expected_object")
        llm_numeric_facts = {}
    if supplier_specific_evidence is not None and not isinstance(supplier_specific_evidence, list):
        normalization_warnings.append("schema:supplier_specific_evidence:expected_array")
        supplier_specific_evidence = []

    numeric_field_specs = {
        "duty_or_tax_rate_percent": True,
        "annual_volume_units": False,
        "unit_price_usd": False,
        "annual_spend_usd": False,
        "requested_change_percent": True,
        "switching_cost_usd": False,
    }
    for _field, _allow_percent in numeric_field_specs.items():
        if _field in llm_numeric_facts:
            llm_numeric_facts[_field] = _coerce_number(llm_numeric_facts.get(_field), f"numeric_facts.{_field}", normalization_warnings, allow_percent_suffix=_allow_percent)
    if stakeholder_views is not None and not isinstance(stakeholder_views, list):
        normalization_warnings.append("schema:stakeholder_views:expected_array")
        stakeholder_views = []

    def mark_llm_or_followup(field_name, present_in_dict):
        if field_name in present_in_dict:
            provenance[field_name] = FieldProvenance(source="llm_extraction", stage_captured="normalize_evidence")

    # ---- Multi-supplier evidence model (Quality Gate Guarantee #2) ----
    # Direct architectural fix for the confirmed Case 5 finding: a real,
    # verbatim case showed FerroSteel=FOB and NordicMetals=CIF -- two
    # genuinely different, both-correct Incoterms, one per supplier. The
    # old single-value common.incoterm field had no way to represent
    # this, so any extraction pass that noticed both values looked like
    # a "conflict" needing resolution, when the real issue was that the
    # data model itself was too narrow. This builds real SupplierEvidence
    # objects instead, and -- critically -- skips the single-value
    # conflict logic below for whichever of incoterm/region/currency
    # genuinely differ across suppliers, since disagreement between two
    # DIFFERENT suppliers' real attributes is not an extraction conflict
    # at all.
    suppliers: list[SupplierEvidence] = []
    multi_supplier_fields_handled: set[str] = set()
    if supplier_specific_evidence:
        for entry in supplier_specific_evidence:
            if not isinstance(entry, dict):
                normalization_warnings.append("schema:supplier_specific_evidence:entry_expected_object")
                continue
            name = _coerce_text(entry.get("supplier_name"), "supplier_specific_evidence.supplier_name", normalization_warnings)
            if not name:
                continue
            # Fix for the confirmed master-case bug: freight is
            # per-supplier evidence, resolved with the SAME rigor as
            # every other per-supplier fact -- never a second-class
            # field. Two real sources, correctly distinguished:
            #   1. The initial bulk extraction (supplier_specific_evidence
            #      itself) -- shares the same provenance entry as the
            #      rest of this supplier's data, exactly like incoterm,
            #      region, price, etc. already do.
            #   2. A LATER, specific follow-up answer via the composite
            #      key "freight_cost_or_estimate__<supplier_name>" --
            #      genuinely more trusted than a bulk extraction (the
            #      user directly confirmed this one fact), and gets its
            #      OWN distinct provenance entry marked user_followup,
            #      matching the same upgrade already given to other
            #      directly-confirmed facts elsewhere in this function.
            freight_from_extraction = entry.get("freight_cost_or_estimate")
            followup_key = f"freight_cost_or_estimate__{name}"
            freight_from_followup = llm_extracted_evidence.get(followup_key)
            resolved_freight = freight_from_followup or freight_from_extraction
            if freight_from_followup:
                provenance[followup_key] = FieldProvenance(
                    source="user_followup", stage_captured="normalize_evidence", supplier_name=name,
                )

            _price_display = _coerce_text(entry.get("price_display"), f"supplier:{name}:price_display", normalization_warnings, numeric_scalar_ok=True)
            suppliers.append(SupplierEvidence(
                supplier_name=name,
                incoterm=normalize_incoterm(_coerce_text(entry.get("incoterm"), f"supplier:{name}:incoterm", normalization_warnings)),
                region=_coerce_text(entry.get("region"), f"supplier:{name}:region", normalization_warnings),
                currency=_coerce_text(entry.get("currency"), f"supplier:{name}:currency", normalization_warnings),
                price_display=_coerce_text(entry.get("price_display"), f"supplier:{name}:price_display", normalization_warnings, numeric_scalar_ok=True),
                price_amount=parse_numeric_value(str(_coerce_text(entry.get("price_display"), f"supplier:{name}:price_display", normalization_warnings, numeric_scalar_ok=True))) if entry.get("price_display") is not None else None,
                lead_time_weeks=_coerce_number(entry.get("lead_time_weeks"), f"supplier:{name}:lead_time_weeks", normalization_warnings),
                otif_percent=_coerce_number(entry.get("otif_percent"), f"supplier:{name}:otif_percent", normalization_warnings, allow_percent_suffix=True),
                defect_rate_percent=_coerce_number(entry.get("defect_rate_percent"), f"supplier:{name}:defect_rate_percent", normalization_warnings, allow_percent_suffix=True),
                payment_terms=_coerce_text(entry.get("payment_terms"), f"supplier:{name}:payment_terms", normalization_warnings, numeric_scalar_ok=True),
                capacity_percent=_coerce_number(entry.get("capacity_percent"), f"supplier:{name}:capacity_percent", normalization_warnings, allow_percent_suffix=True),
                qualification_status=_safe_enum(entry.get("qualification_status"), {"not_started", "in_progress", "complete", "unknown"}, "unknown", f"supplier:{name}:qualification_status", normalization_warnings),
                qualification_percent=_coerce_number(entry.get("qualification_percent"), f"supplier:{name}:qualification_percent", normalization_warnings, allow_percent_suffix=True),
                is_incumbent=entry.get("is_incumbent") if isinstance(entry.get("is_incumbent"), bool) else False,
                freight_cost_or_estimate=_coerce_text(resolved_freight, f"supplier:{name}:freight_cost_or_estimate", normalization_warnings, numeric_scalar_ok=True),
                production_history_status=_safe_enum(entry.get("production_history_status"), {"established", "limited", "none", "unknown"}, "unknown", f"supplier:{name}:production_history_status", normalization_warnings),
                certification_status=_safe_enum(entry.get("certification_status"), {"certified", "not_certified", "unknown"}, "unknown", f"supplier:{name}:certification_status", normalization_warnings),
                certification_detail=_coerce_text(entry.get("certification_detail"), f"supplier:{name}:certification_detail", normalization_warnings, numeric_scalar_ok=True),
                preferred_supplier_status=_safe_enum(entry.get("preferred_supplier_status"), {"preferred", "not_preferred", "unknown"}, "unknown", f"supplier:{name}:preferred_supplier_status", normalization_warnings),
            ))
            provenance[f"supplier:{name}"] = FieldProvenance(
                source="llm_extraction", stage_captured="normalize_evidence", supplier_name=name,
            )

        # For each of the three fields that can legitimately vary by
        # supplier, check whether the suppliers we just built genuinely
        # DIFFER -- only then is the single-value path skipped. If every
        # supplier happens to share the same Incoterm, there's no reason
        # to avoid the normal single-value handling.
        for field_name, attr in (("incoterm", "incoterm"), ("region", "region"), ("currency", "currency")):
            real_values = {getattr(s, attr) for s in suppliers if getattr(s, attr)}
            if len(real_values) >= 2:
                multi_supplier_fields_handled.add(field_name)

    # ---- stakeholder views: attributed, never promoted to fact ----
    normalized_stakeholder_views: list[StakeholderView] = []
    for entry in (stakeholder_views or [])[:caps.MAX_STAKEHOLDER_VIEWS]:
        if not isinstance(entry, dict):
            normalization_warnings.append("schema:stakeholder_views:entry_expected_object")
            continue
        name = str(entry.get("stakeholder_name") or "").strip()
        statement = str(entry.get("statement") or "").strip()
        view_type = entry.get("view_type")
        if not name or not statement or view_type not in {
            "objective", "preference", "risk_concern", "constraint",
            "experience", "rumor", "recommendation",
        }:
            continue
        normalized_stakeholder_views.append(StakeholderView(
            stakeholder_name=name,
            role=_coerce_text(entry.get("role"), "stakeholder_views.role", normalization_warnings, numeric_scalar_ok=True),
            view_type=view_type,
            statement=statement,
            basis=_coerce_text(entry.get("basis"), "stakeholder_views.basis", normalization_warnings, numeric_scalar_ok=True),
            explicitly_stated=bool(entry.get("explicitly_stated", True)),
        ))

    # ---- common: region (existing fallback, moved here) ----
    if "region" in multi_supplier_fields_handled:
        region = None
        provenance["supplier_region_or_market"] = FieldProvenance(
            source="llm_extraction", stage_captured="normalize_evidence",
        )
    else:
        llm_region = llm_extracted_evidence.get("supplier_region_or_market")
        fallback_region = detect_supplier_region_fallback(raw_question)
        region, conflict = _resolve_field(raw_question, llm_region, fallback_region, "supplier_region_or_market", provenance)
        if conflict:
            conflicts.append("supplier_region_or_market")

    # ---- common: currency (NEW fallback) ----
    if "currency" in multi_supplier_fields_handled:
        currency = None
        provenance["supplier_currency"] = FieldProvenance(
            source="llm_extraction", stage_captured="normalize_evidence",
        )
    else:
        llm_currency = llm_extracted_evidence.get("supplier_currency")
        fallback_currency = detect_currency_fallback(raw_question)
        currency, conflict = _resolve_field(raw_question, llm_currency, fallback_currency, "supplier_currency", provenance)
        if conflict:
            conflicts.append("supplier_currency")

    # ---- common: incoterm (NEW fallback -- Critical Finding #1) ----
    if "incoterm" in multi_supplier_fields_handled:
        incoterm = None
        provenance["incoterm"] = FieldProvenance(
            source="llm_extraction", stage_captured="normalize_evidence",
        )
    else:
        llm_incoterm = normalize_incoterm(llm_extracted_evidence.get("incoterm"))
        fallback_incoterm = detect_incoterm_fallback(raw_question)
        incoterm, conflict = _resolve_field(raw_question, llm_incoterm, fallback_incoterm, "incoterm", provenance)
        if conflict:
            conflicts.append("incoterm")

    # ---- common: duty rate (NEW fallback) ----
    llm_duty = llm_numeric_facts.get("duty_or_tax_rate_percent")
    fallback_duty = detect_duty_rate_fallback(raw_question)
    duty_rate, conflict = _resolve_field(raw_question, llm_duty, fallback_duty, "duty_or_tax_rate_percent", provenance, is_numeric=True)
    if conflict:
        conflicts.append("duty_or_tax_rate_percent")

    # ---- common: annual volume (NEW fallback -- Critical Finding #3) ----
    llm_volume = llm_numeric_facts.get("annual_volume_units")
    fallback_volume = detect_annual_volume_fallback(raw_question)
    volume, conflict = _resolve_field(raw_question, llm_volume, fallback_volume, "annual_volume_units", provenance, is_numeric=True)
    if conflict:
        conflicts.append("annual_volume_units")

    unit_price = llm_numeric_facts.get("unit_price_usd")
    mark_llm_or_followup("unit_price_usd", llm_numeric_facts)
    mark_llm_or_followup("supplier_name", llm_extracted_evidence)

    common = CommonEvidence(
        supplier_name=_coerce_text(llm_extracted_evidence.get("supplier_name"), "supplier_name", normalization_warnings),
        supplier_region_or_market=_coerce_text(region, "supplier_region_or_market", normalization_warnings),
        supplier_currency=_coerce_text(currency, "supplier_currency", normalization_warnings),
        incoterm=_coerce_text(incoterm, "incoterm", normalization_warnings),
        duty_or_tax_rate_percent=duty_rate,
        annual_volume_units=volume,
        unit_price_usd=unit_price,
    )

    # ---- case-specific ----
    if content_type == "price_increase":
        llm_spend = llm_numeric_facts.get("annual_spend_usd")
        fallback_spend = extract_annual_spend_fallback(raw_question)
        spend, conflict = _resolve_field(raw_question, llm_spend, fallback_spend, "annual_spend_usd", provenance, is_numeric=True)
        if conflict:
            conflicts.append("annual_spend_usd")

        # Real bug found while testing Guarantee #4: numeric_facts uses
        # "requested_change_percent", but the resolved value gets stored
        # in the flat dict under the case field name
        # "requested_increase_percent" instead. A fresh classifier
        # response has the first key; a round-tripped stored flat dict
        # (from /respond or continue_case re-normalizing) only has the
        # second. Checking both here means either shape resolves
        # correctly, not just the first-ever call.
        llm_percent = llm_numeric_facts.get("requested_change_percent")
        if llm_percent is None:
            # Only trust this as a pre-resolved value if it's genuinely
            # numeric -- "requested_increase_percent" is ALSO the
            # evidence-gate's field key for a raw text answer like "12%"
            # (a string, from a real user typing an answer to "What
            # increase percentage is being requested?"). A raw string
            # here must fall through to the normal text-parsing fallback
            # below, not be mistaken for an already-resolved number.
            candidate = llm_numeric_facts.get("requested_increase_percent")
            if isinstance(candidate, (int, float)):
                llm_percent = candidate
        fallback_percent = extract_requested_change_percent_fallback(raw_question)
        percent, conflict = _resolve_field(raw_question, llm_percent, fallback_percent, "requested_increase_percent", provenance, is_numeric=True)
        if conflict:
            conflicts.append("requested_increase_percent")

        for f in ("current_price_or_terms", "suppliers_stated_justification", "how_critical_is_this_supplier_relationship"):
            mark_llm_or_followup(f, llm_extracted_evidence)

        # Real fix, carried forward from the original evidence-gate fix:
        # a resolved NUMBER alone doesn't satisfy the evidence-gate, which
        # checks human-readable TEXT fields. Without this, the evidence-gate
        # would re-ask for price/percentage even when a real number was
        # already resolved -- the exact original live bug this whole
        # migration traces back to. Only backfills when the text field is
        # genuinely empty, never overwriting a real answer already present.
        current_price_text = llm_extracted_evidence.get("current_price_or_terms")
        if not current_price_text and spend is not None:
            current_price_text = f"${spend:,.0f} annual spend"
        requested_percent_text_source = llm_extracted_evidence.get("requested_increase_percent")

        case_evidence = PriceIncreaseEvidence(
            current_price_or_terms=_coerce_text(current_price_text, "current_price_or_terms", normalization_warnings, numeric_scalar_ok=True),
            requested_increase_percent=percent,
            suppliers_stated_justification=_coerce_text(llm_extracted_evidence.get("suppliers_stated_justification"), "suppliers_stated_justification", normalization_warnings, numeric_scalar_ok=True),
            how_critical_is_this_supplier_relationship=_coerce_text(llm_extracted_evidence.get("how_critical_is_this_supplier_relationship"), "how_critical_is_this_supplier_relationship", normalization_warnings, numeric_scalar_ok=True),
            annual_spend_usd=spend,
            switching_cost_usd=llm_numeric_facts.get("switching_cost_usd"),
            freight_cost_or_estimate=_coerce_text(llm_extracted_evidence.get("freight_cost_or_estimate"), "freight_cost_or_estimate", normalization_warnings, numeric_scalar_ok=True),
        )
    else:
        for f in ("number_of_suppliers_being_compared", "price_per_supplier", "payment_terms_per_supplier",
                   "lead_time_per_supplier", "quality_or_defect_history_per_supplier",
                   "is_this_a_new_or_incumbent_relationship"):
            mark_llm_or_followup(f, llm_extracted_evidence)
        case_evidence = QuoteComparisonEvidence(
            number_of_suppliers_being_compared=_coerce_text(llm_extracted_evidence.get("number_of_suppliers_being_compared"), "number_of_suppliers_being_compared", normalization_warnings, numeric_scalar_ok=True),
            price_per_supplier=_coerce_text(llm_extracted_evidence.get("price_per_supplier"), "price_per_supplier", normalization_warnings, numeric_scalar_ok=True),
            payment_terms_per_supplier=_coerce_text(llm_extracted_evidence.get("payment_terms_per_supplier"), "payment_terms_per_supplier", normalization_warnings, numeric_scalar_ok=True),
            lead_time_per_supplier=_coerce_text(llm_extracted_evidence.get("lead_time_per_supplier"), "lead_time_per_supplier", normalization_warnings, numeric_scalar_ok=True),
            quality_or_defect_history_per_supplier=_coerce_text(llm_extracted_evidence.get("quality_or_defect_history_per_supplier"), "quality_or_defect_history_per_supplier", normalization_warnings, numeric_scalar_ok=True),
            is_this_a_new_or_incumbent_relationship=_coerce_text(llm_extracted_evidence.get("is_this_a_new_or_incumbent_relationship"), "is_this_a_new_or_incumbent_relationship", normalization_warnings, numeric_scalar_ok=True),
        )

    # ---- derived: annual spend resolution (exactly the approved priority) ----
    resolved_spend = None
    resolution_method = "unresolved"
    direct_spend = getattr(case_evidence, "annual_spend_usd", None)
    if direct_spend is not None:
        resolved_spend = direct_spend
        resolution_method = "direct"
    elif common.unit_price_usd is not None and common.annual_volume_units is not None:
        resolved_spend = common.unit_price_usd * common.annual_volume_units
        resolution_method = "derived_from_price_and_volume"
        provenance["resolved_annual_spend_usd"] = FieldProvenance(source="derived_calculation", stage_captured="normalize_evidence")

    # ---- derived: freight/duty relevance (exactly the approved rule) ----
    single_value_freight_relevant = incoterm is not None and incoterm.strip().upper() in INCOTERMS_WHERE_BUYER_BEARS_FREIGHT
    # Real extension for the multi-supplier model: if any named supplier
    # individually has a buyer-pays-freight Incoterm, freight is genuinely
    # relevant to that supplier's scenario, even when the case-wide
    # common.incoterm is None because suppliers legitimately differ.
    per_supplier_freight_relevant = any(
        (s.incoterm or "").strip().upper() in INCOTERMS_WHERE_BUYER_BEARS_FREIGHT for s in suppliers
    )
    freight_relevant = single_value_freight_relevant or per_supplier_freight_relevant
    duty_relevant = bool(region or currency or incoterm)
    currency_mismatch = currency is not None
    # Production Hardening fix: only unsafe when a real currency mismatch
    # exists AND no literal dollar sign appears anywhere in the raw text.
    # A genuine "$460,000" alongside foreign-currency context is safe --
    # the user explicitly gave a real dollar figure, not an ambiguous one.
    currency_calculation_safe = not (currency_mismatch and "$" not in raw_question)

    # ---- derived: parsed freight cost (existing numeric_parsing.py, moved here) ----
    freight_per_unit = None
    freight_text = getattr(case_evidence, "freight_cost_or_estimate", None)
    if freight_text:
        freight_per_unit = parse_numeric_value(freight_text)
        if freight_per_unit is not None:
            provenance["freight_cost_per_unit_usd"] = FieldProvenance(
                source="user_followup", stage_captured="normalize_evidence",
            )

    derived = DerivedEvidence(
        resolved_annual_spend_usd=resolved_spend,
        annual_spend_resolution_method=resolution_method,
        freight_relevant=freight_relevant,
        duty_relevant=duty_relevant,
        currency_mismatch=currency_mismatch,
        currency_calculation_safe=currency_calculation_safe,
        freight_cost_per_unit_usd=freight_per_unit,
    )

    # Deterministic safety net, not solely a prompt instruction: the
    # primary/incumbent supplier must always be checkable by the
    # claim-integrity firewall, exactly as symmetrically as any
    # alternative supplier. Model prompt-following isn't guaranteed, so
    # if the incumbent's name is known (common.supplier_name) but never
    # made it into supplier_specific_evidence, add a minimal entry here
    # -- all fields unknown/null except the name and is_incumbent, since
    # nothing else is safely inferable from the case-level fields alone.
    if common.supplier_name and not any(
        s.supplier_name.strip().lower() == common.supplier_name.strip().lower() for s in suppliers
    ):
        suppliers.append(SupplierEvidence(supplier_name=common.supplier_name, is_incumbent=True))
        provenance[f"supplier:{common.supplier_name}"] = FieldProvenance(
            source="deterministic_fallback", stage_captured="normalize_evidence", supplier_name=common.supplier_name,
        )

    normalized = NormalizedEvidence(
        content_type=content_type,
        common=common,
        case=case_evidence,
        derived=derived,
        history=history or HistoryContext(),
        provenance=provenance,
        suppliers=suppliers,
        stakeholder_views=normalized_stakeholder_views,
        normalization_warnings=normalization_warnings[:caps.MAX_NORMALIZATION_WARNINGS],
    )
    return normalized, conflicts
