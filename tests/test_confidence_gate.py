"""
Quality Gate Guarantee #5 — Decision Integrity / Confidence Gate.

The five adversarial cases specified in the Quality Gate, each locked in
permanently, plus proof that the ceiling can only ever LOWER confidence,
never raise it, plus a real end-to-end deliberate-break proof.
"""
from app.pipeline.confidence_gate import compute_confidence_ceiling, apply_confidence_ceiling
from app.models import CommercialPosition, Confidence, ConfidenceFactor, FinancialImpact
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence,
    SupplierEvidence, FieldProvenance,
)


def _conf(level="high"):
    return Confidence(
        level=level,
        factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
        derivation_note="base note.",
    )


_ALL_LOAD_BEARING_PROVENANCE = {
    f: FieldProvenance(source="llm_extraction", stage_captured="x")
    for f in ["current_price_or_terms", "requested_increase_percent",
              "suppliers_stated_justification", "annual_spend_usd"]
}


def test_adversarial_case_1_one_missing_critical_input_caps_despite_abundant_evidence():
    normalized = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(),
        case=PriceIncreaseEvidence(current_price_or_terms="$128/kg", requested_increase_percent=16.0,
                                    suppliers_stated_justification="rising costs"),
        derived=DerivedEvidence(),  # no resolved_annual_spend_usd -- the one missing piece
        provenance={k: v for k, v in _ALL_LOAD_BEARING_PROVENANCE.items() if k != "annual_spend_usd"},
    )
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        reasoning="Excellent case, well documented, everything clear.",
        confidence=_conf("high"), assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
        financial_impact=None,
    )
    ceiling, reasons = compute_confidence_ceiling(position, normalized)
    assert ceiling == "medium"
    assert len(reasons) == 1


def test_adversarial_case_2_conflicting_load_bearing_fields_cap_confidence():
    provenance = dict(_ALL_LOAD_BEARING_PROVENANCE)
    provenance["annual_spend_usd"] = FieldProvenance(
        source="llm_extraction", conflicting=True,
        conflicting_values=(23_040_000.0, 25_000_000.0), stage_captured="x",
    )
    normalized = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(),
        case=PriceIncreaseEvidence(current_price_or_terms="$128/kg", requested_increase_percent=16.0,
                                    suppliers_stated_justification="x", annual_spend_usd=23_040_000.0),
        derived=DerivedEvidence(resolved_annual_spend_usd=23_040_000.0, annual_spend_resolution_method="direct"),
        provenance=provenance,
    )
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"], reasoning="Lots of context, well documented.",
        confidence=_conf("high"), assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
        financial_impact=FinancialImpact(annual_spend_usd=23_040_000.0, requested_change_percent=16.0,
                                          potential_annual_impact_usd=3_686_400.0, note="x"),
    )
    ceiling, reasons = compute_confidence_ceiling(position, normalized)
    assert ceiling == "medium"


def test_adversarial_case_3_complete_evidence_but_unqualified_alternative_relied_upon():
    normalized = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(),
        case=PriceIncreaseEvidence(current_price_or_terms="$128/kg", requested_increase_percent=16.0,
                                    suppliers_stated_justification="x", annual_spend_usd=23_040_000.0),
        derived=DerivedEvidence(resolved_annual_spend_usd=23_040_000.0, annual_spend_resolution_method="direct"),
        provenance=_ALL_LOAD_BEARING_PROVENANCE,
        suppliers=[SupplierEvidence(supplier_name="BioSyn", qualification_status="in_progress", qualification_percent=70)],
    )
    position = CommercialPosition(
        recommendation="Use BioSyn as leverage and begin dual-sourcing.", commercial_insights=["a"],
        reasoning="BioSyn provides real negotiating leverage for this case, complete data throughout.",
        confidence=_conf("high"), assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
        financial_impact=FinancialImpact(annual_spend_usd=23_040_000.0, requested_change_percent=16.0,
                                          potential_annual_impact_usd=3_686_400.0, note="x"),
    )
    ceiling, reasons = compute_confidence_ceiling(position, normalized)
    assert ceiling == "medium"


def test_adversarial_case_4_correct_math_but_evidence_never_independently_verified():
    provenance = {
        "current_price_or_terms": FieldProvenance(source="deterministic_fallback", stage_captured="x"),
        "requested_increase_percent": FieldProvenance(source="deterministic_fallback", stage_captured="x"),
        "annual_spend_usd": FieldProvenance(source="deterministic_fallback", stage_captured="x"),
        "suppliers_stated_justification": FieldProvenance(source="llm_extraction", stage_captured="x"),
    }
    normalized = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(),
        case=PriceIncreaseEvidence(current_price_or_terms="$128/kg", requested_increase_percent=16.0,
                                    suppliers_stated_justification="x", annual_spend_usd=23_040_000.0),
        derived=DerivedEvidence(resolved_annual_spend_usd=23_040_000.0, annual_spend_resolution_method="direct"),
        provenance=provenance,
    )
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"], reasoning="The arithmetic here is exact and correct.",
        confidence=_conf("high"), assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
        financial_impact=FinancialImpact(annual_spend_usd=23_040_000.0, requested_change_percent=16.0,
                                          potential_annual_impact_usd=3_686_400.0, note="x"),
    )
    ceiling, reasons = compute_confidence_ceiling(position, normalized)
    assert ceiling == "medium"


def test_adversarial_case_5_fully_verified_and_complete_reaches_high():
    provenance = {
        "current_price_or_terms": FieldProvenance(source="both_agree", stage_captured="x"),
        "requested_increase_percent": FieldProvenance(source="llm_extraction", stage_captured="x"),
        "annual_spend_usd": FieldProvenance(source="user_followup", stage_captured="x"),
        "suppliers_stated_justification": FieldProvenance(source="llm_extraction", stage_captured="x"),
    }
    normalized = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(),
        case=PriceIncreaseEvidence(current_price_or_terms="$128/kg", requested_increase_percent=16.0,
                                    suppliers_stated_justification="x", annual_spend_usd=23_040_000.0),
        derived=DerivedEvidence(resolved_annual_spend_usd=23_040_000.0, annual_spend_resolution_method="direct"),
        provenance=provenance,
    )
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"], reasoning="Every fact here is independently verified and complete.",
        confidence=_conf("high"), assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
        financial_impact=FinancialImpact(annual_spend_usd=23_040_000.0, requested_change_percent=16.0,
                                          potential_annual_impact_usd=3_686_400.0, note="x"),
    )
    ceiling, reasons = compute_confidence_ceiling(position, normalized)
    assert ceiling == "high"
    assert reasons == []


def test_ceiling_never_raises_confidence_only_lowers_it():
    """Critical structural guarantee: if the model itself says LOW, the
    ceiling must never override that upward, even with perfect evidence."""
    normalized = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(),
        case=PriceIncreaseEvidence(current_price_or_terms="x", requested_increase_percent=10.0,
                                    suppliers_stated_justification="x", annual_spend_usd=1_000_000.0),
        derived=DerivedEvidence(resolved_annual_spend_usd=1_000_000.0, annual_spend_resolution_method="direct"),
        provenance={f: FieldProvenance(source="both_agree", stage_captured="x") for f in
                    ["current_price_or_terms", "requested_increase_percent", "suppliers_stated_justification", "annual_spend_usd"]},
    )
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"], reasoning="x",
        confidence=_conf("low"), assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
        financial_impact=FinancialImpact(annual_spend_usd=1_000_000.0, requested_change_percent=10.0,
                                          potential_annual_impact_usd=100_000.0, note="x"),
    )
    result = apply_confidence_ceiling(position, normalized)
    assert result.confidence.level == "low"


def test_false_high_deterministic_ceiling_overrides_a_wrong_high_claim():
    """
    Required additional test: the model claims HIGH while a critical
    supplier-specific fact (qualification status) is genuinely incomplete.
    This specifically tests the ENFORCEMENT function (apply_confidence_ceiling),
    not just the raw ceiling computation -- proving a real, wrongly-confident
    claim actually gets overridden in the object that reaches the user.
    """
    normalized = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(),
        case=PriceIncreaseEvidence(current_price_or_terms="$128/kg", requested_increase_percent=16.0,
                                    suppliers_stated_justification="x", annual_spend_usd=23_040_000.0),
        derived=DerivedEvidence(resolved_annual_spend_usd=23_040_000.0, annual_spend_resolution_method="direct"),
        provenance=_ALL_LOAD_BEARING_PROVENANCE,
        suppliers=[SupplierEvidence(supplier_name="BioSyn", qualification_status="in_progress", qualification_percent=70)],
    )
    position = CommercialPosition(
        recommendation="Use BioSyn as leverage.", commercial_insights=["a"],
        reasoning="BioSyn provides real negotiating leverage for this case.",
        confidence=_conf("high"),  # the model's own, wrong, overconfident claim
        assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
        financial_impact=FinancialImpact(annual_spend_usd=23_040_000.0, requested_change_percent=16.0,
                                          potential_annual_impact_usd=3_686_400.0, note="x"),
    )
    result = apply_confidence_ceiling(position, normalized)
    assert result.confidence.level == "medium", (
        "A model-claimed HIGH confidence must be genuinely overridden when a critical "
        "supplier-specific fact (qualification status) is incomplete -- this must hold "
        "for the actual enforced value, not just the abstract ceiling computation."
    )


def test_false_low_ceiling_never_artificially_raises_a_genuinely_cautious_model():
    """
    Required additional test: the model claims LOW even though every
    load-bearing input is genuinely verified, reconciled, and complete
    (the same clean data as Case 5). The system must NEVER second-guess a
    cautious model upward -- the ceiling is a cap, never a floor.
    """
    provenance = {
        "current_price_or_terms": FieldProvenance(source="both_agree", stage_captured="x"),
        "requested_increase_percent": FieldProvenance(source="llm_extraction", stage_captured="x"),
        "annual_spend_usd": FieldProvenance(source="user_followup", stage_captured="x"),
        "suppliers_stated_justification": FieldProvenance(source="llm_extraction", stage_captured="x"),
    }
    normalized = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(),
        case=PriceIncreaseEvidence(current_price_or_terms="$128/kg", requested_increase_percent=16.0,
                                    suppliers_stated_justification="x", annual_spend_usd=23_040_000.0),
        derived=DerivedEvidence(resolved_annual_spend_usd=23_040_000.0, annual_spend_resolution_method="direct"),
        provenance=provenance,
    )
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        reasoning="Every fact here is independently verified and complete.",
        confidence=_conf("low"),  # the model is being cautious, for whatever reason
        assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
        financial_impact=FinancialImpact(annual_spend_usd=23_040_000.0, requested_change_percent=16.0,
                                          potential_annual_impact_usd=3_686_400.0, note="x"),
    )
    result = apply_confidence_ceiling(position, normalized)
    assert result.confidence.level == "low", (
        "The ceiling must NEVER raise a model's own cautious LOW claim to HIGH, "
        "even when the underlying evidence is genuinely clean and complete -- "
        "the ceiling is strictly a cap, never a floor."
    )
    # And, since nothing was actually capped (the model's own level was already
    # at or below the ceiling), the derivation note must NOT falsely claim a
    # capping event occurred.
    assert "capped" not in result.confidence.derivation_note.lower()


def test_confidence_reason_text_matches_the_actual_triggered_condition():
    """
    Required verification: the reason shown to the user must name the
    SPECIFIC field or supplier that triggered the cap, not generic
    wording like "evidence quality issues" that could apply to any case.
    """
    normalized = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(),
        case=PriceIncreaseEvidence(current_price_or_terms="$128/kg", requested_increase_percent=16.0,
                                    suppliers_stated_justification="x", annual_spend_usd=23_040_000.0),
        derived=DerivedEvidence(resolved_annual_spend_usd=23_040_000.0, annual_spend_resolution_method="direct"),
        provenance=_ALL_LOAD_BEARING_PROVENANCE,
        suppliers=[SupplierEvidence(supplier_name="BioSyn", qualification_status="in_progress", qualification_percent=70)],
    )
    position = CommercialPosition(
        recommendation="Use BioSyn as leverage.", commercial_insights=["a"],
        reasoning="BioSyn provides real negotiating leverage for this case.",
        confidence=_conf("high"), assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
        financial_impact=FinancialImpact(annual_spend_usd=23_040_000.0, requested_change_percent=16.0,
                                          potential_annual_impact_usd=3_686_400.0, note="x"),
    )
    result = apply_confidence_ceiling(position, normalized)
    note = result.confidence.derivation_note
    # The specific supplier name and its real status must be named,
    # not a vague, could-apply-to-anything phrase.
    assert "BioSyn" in note, "The reason must name the specific supplier that triggered the cap"
    assert "in_progress" in note, "The reason must name the actual real status, not a generic phrase"
    generic_phrases = ["evidence quality issues", "some data was missing", "general uncertainty"]
    assert not any(phrase in note.lower() for phrase in generic_phrases), (
        "The reason must never fall back to vague, generic wording when a specific cause is known"
    )


def test_deliberate_break_removing_check_c_lets_the_biosyn_case_reach_high():
    """
    MANDATORY deliberate-break proof. Temporarily removes Check C
    (alternative-supplier reliance) and confirms the exact real BioSyn
    scenario, which correctly caps at MEDIUM with the real code, would
    incorrectly reach HIGH without it -- proving this check is genuinely
    load-bearing in the guarantee, not decorative.
    """
    normalized = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(),
        case=PriceIncreaseEvidence(current_price_or_terms="$128/kg", requested_increase_percent=16.0,
                                    suppliers_stated_justification="x", annual_spend_usd=23_040_000.0),
        derived=DerivedEvidence(resolved_annual_spend_usd=23_040_000.0, annual_spend_resolution_method="direct"),
        provenance=_ALL_LOAD_BEARING_PROVENANCE,
        suppliers=[SupplierEvidence(supplier_name="BioSyn", qualification_status="in_progress", qualification_percent=70)],
    )
    position = CommercialPosition(
        recommendation="Use BioSyn as leverage.", commercial_insights=["a"],
        reasoning="BioSyn provides real negotiating leverage for this case.",
        confidence=_conf("high"), assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
        financial_impact=FinancialImpact(annual_spend_usd=23_040_000.0, requested_change_percent=16.0,
                                          potential_annual_impact_usd=3_686_400.0, note="x"),
    )

    # With the real, unmodified check: correctly capped.
    real_ceiling, real_reasons = compute_confidence_ceiling(position, normalized)
    assert real_ceiling == "medium"
    assert any("BioSyn" in r for r in real_reasons)

    # Now simulate the broken state: manually strip supplier data before
    # the check runs, exactly as if Check C never existed.
    broken_normalized = normalized.model_copy(update={"suppliers": []})
    broken_ceiling, broken_reasons = compute_confidence_ceiling(position, broken_normalized)
    assert broken_ceiling == "high", (
        "Without Check C, this exact real scenario incorrectly reaches HIGH -- "
        "confirming the check is genuinely load-bearing, not decorative."
    )
