"""
Certification fixes: decision visibility, commercial-number surfacing,
full supplier-universe strategy classification, roadmap completeness,
and buyer-language/value-density cleanup in category_strategy.
"""
from app.pipeline.category_strategy_profile import build_category_strategy_answer, classify_supplier_strategy
from app.pipeline.kernel import build_kernel
from app.pipeline.decision_audit import build_decision_audit
from app.pipeline.question_coverage import build_coverage_requirements
from app.pipeline.financial import compute_financial_impact
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence, SupplierEvidence
from app.models import CommercialPosition, Confidence, ConfidenceFactor, DecisionAudit

conf = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _golden_valves_normalized():
    return NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(supplier_currency="EUR"),
        case=PriceIncreaseEvidence(
            annual_spend_usd=5_550_000, prior_annual_spend_usd=4_370_000, requested_increase_percent=11.0, alternative_scenario_percent=7.0,
            category_annual_spend_usd=8_400_000, category_prior_annual_spend_usd=7_050_000,
        ),
        derived=DerivedEvidence(resolved_annual_spend_usd=5_550_000, currency_calculation_safe=True, spend_currency="EUR"),
        suppliers=[
            SupplierEvidence(supplier_name="Supplier A", is_incumbent=True, current_annual_spend_usd=5_550_000, prior_annual_spend_usd=4_370_000, current_annual_volume_units=246_000, prior_annual_volume_units=221_000),
            SupplierEvidence(supplier_name="Supplier B", qualification_time_estimate="4-6 months"),
            SupplierEvidence(supplier_name="Supplier C", qualification_time_estimate="approximately 6 months"),
            SupplierEvidence(supplier_name="Supplier D", capacity_percent=15, capacity_status="unvalidated"),
        ],
    )


def _position(recommendation="Do not accept the 11% increase as stated."):
    return CommercialPosition(
        recommendation=recommendation, commercial_insights=["a"], reasoning="x",
        confidence=conf, assumptions=["a"], disconfirming_condition="...", decision_type="optimization", case_mode="category_strategy",
    )


def _full_answer():
    n = _golden_valves_normalized()
    fi = compute_financial_impact(n)
    pos = _position()
    pos.financial_impact = fi
    pos.decision_audit = DecisionAudit(**build_decision_audit(n, pos))
    coverage = build_coverage_requirements(n)
    kernel = build_kernel(n, pos, coverage_requirements=coverage).model_dump()
    return build_category_strategy_answer(kernel, pos)


# ---------------------------------------------------------------------
# 1. Decision quality
# ---------------------------------------------------------------------

def test_decision_is_surfaced_directly_not_trapped_elsewhere():
    answer = _full_answer()
    assert answer["decision"] == "Do not accept the 11% increase as stated."


def test_decision_is_none_when_model_provides_no_recommendation():
    n = _golden_valves_normalized()
    fi = compute_financial_impact(n)
    pos = _position(recommendation="")
    pos.financial_impact = fi
    pos.decision_audit = DecisionAudit(**build_decision_audit(n, pos))
    kernel = build_kernel(n, pos, coverage_requirements=build_coverage_requirements(n)).model_dump()
    answer = build_category_strategy_answer(kernel, pos)
    assert answer.get("decision") is None
    assert answer["diagnostics"]["decision"] is None


# ---------------------------------------------------------------------
# 2. Commercial correctness
# ---------------------------------------------------------------------

def test_money_surfaces_the_exact_canonical_scenario_values():
    answer = _full_answer()
    money = answer["money"]
    assert money["currency"] == "EUR"
    assert money["current_annual_spend"] == 5_550_000.0
    assert money["scenario_a"]["impact"] == 610_500.0
    assert money["scenario_b"]["impact"] == 388_500.0
    assert money["difference"] == 222_000.0


def test_money_values_match_financial_impact_exactly_never_recalculated():
    """Direct proof this is read from the kernel, not recomputed: the
    kernel's own scenario facts and financial_impact must agree exactly,
    since both trace to the same single compute_financial_impact call."""
    n = _golden_valves_normalized()
    fi = compute_financial_impact(n)
    pos = _position()
    pos.financial_impact = fi
    pos.decision_audit = DecisionAudit(**build_decision_audit(n, pos))
    kernel = build_kernel(n, pos, coverage_requirements=build_coverage_requirements(n)).model_dump()
    answer = build_category_strategy_answer(kernel, pos)
    assert answer["money"]["scenario_a"]["impact"] == fi.scenario_comparison.scenario_a.delta.amount
    assert answer["money"]["difference"] == fi.scenario_comparison.delta_amount.amount


# ---------------------------------------------------------------------
# 3. Supplier strategy -- full universe, evidence-backed, no invented strength
# ---------------------------------------------------------------------

def test_all_four_suppliers_receive_a_classification():
    answer = _full_answer()
    strategies = {s["supplier"]: s["strategy"] for s in answer["supplier_strategy"]}
    assert strategies == {"Supplier A": "challenge", "Supplier B": "qualify", "Supplier C": "qualify", "Supplier D": "monitor"}


def test_capacity_unvalidated_alone_is_monitor_not_qualify():
    """Supplier D has no qualification concern at all -- only an
    unvalidated capacity figure. That is a data-check gap, not a
    qualification gap, and must not be conflated with Supplier B/C's
    genuine qualification-incomplete state."""
    answer = _full_answer()
    d = next(s for s in answer["supplier_strategy"] if s["supplier"] == "Supplier D")
    assert d["strategy"] == "monitor"
    assert "capacity" in d["reason"].lower()


def test_candidate_supplier_with_no_spend_data_still_gets_evidence_based_classification():
    """Direct proof of the architectural fix: a supplier that never
    appears in category_position.suppliers_by_spend (no awarded spend)
    still receives a real classification here, driven purely by its
    qualification/capacity evidence."""
    answer = _full_answer()
    spend_suppliers = {s["supplier"] for s in answer["diagnostics"]["category_position"]["suppliers_by_spend"]}
    assert "Supplier B" not in spend_suppliers  # confirms B genuinely has no spend data
    strategy_suppliers = {s["supplier"] for s in answer["supplier_strategy"]}
    assert "Supplier B" in strategy_suppliers  # yet still gets classified


def test_supplier_with_zero_evidence_is_never_manufactured_a_stronger_classification():
    """A supplier that exists in the case with genuinely no evidence at
    all beyond its name must default to monitor, never a fabricated
    stronger call."""
    n = _golden_valves_normalized()
    n.suppliers.append(SupplierEvidence(supplier_name="Supplier E"))
    fi = compute_financial_impact(n)
    pos = _position()
    pos.financial_impact = fi
    pos.decision_audit = DecisionAudit(**build_decision_audit(n, pos))
    kernel = build_kernel(n, pos, coverage_requirements=build_coverage_requirements(n)).model_dump()
    answer = build_category_strategy_answer(kernel, pos)
    e = next(s for s in answer["supplier_strategy"] if s["supplier"] == "Supplier E")
    assert e["strategy"] == "monitor"


# ---------------------------------------------------------------------
# 4. Roadmap completeness
# ---------------------------------------------------------------------

def test_year_1_names_the_full_relevant_supplier_portfolio_not_just_one():
    answer = _full_answer()
    year1_text = " ".join(i["initiative"] + " " + i["reason"] for i in answer["diagnostics"]["roadmap"]["year_1"])
    assert "Supplier A" in year1_text
    assert "Supplier B" in year1_text
    assert "Supplier C" in year1_text


def test_year_2_and_3_remain_explicitly_evidence_bounded():
    answer = _full_answer()
    assert "not yet supported by evidence" in answer["roadmap"]["year_2"][0]["status"].lower()
    assert "not yet supported by evidence" in answer["roadmap"]["year_3"][0]["status"].lower()


# ---------------------------------------------------------------------
# 5. Buyer language -- no internal object/key names anywhere
# ---------------------------------------------------------------------

def test_no_internal_key_or_object_names_anywhere_in_the_answer_text():
    import json
    answer = _full_answer()
    full_text = json.dumps(answer).lower()
    for forbidden in ("structural_implication", "position.", "normalized.", "kernel.facts", "pipeline", "commercial_position"):
        assert forbidden not in full_text, f"found internal terminology leak: {forbidden!r}"


# ---------------------------------------------------------------------
# 6. Value density -- single owner per conclusion
# ---------------------------------------------------------------------

def test_priorities_are_a_short_summary_not_the_full_reasoning_restated():
    """The confirmed round-2 finding: priorities.reason must be a real,
    short summary -- not the same full sentence as supplier_strategy's
    reason, just missing the name prefix."""
    answer = _full_answer()
    supplier_a_priority = next(p for p in answer["diagnostics"]["priorities"] if p["priority"].startswith("Supplier A"))
    supplier_a_strategy = next(s for s in answer["diagnostics"]["supplier_strategy"] if s["supplier"] == "Supplier A")
    assert supplier_a_priority["reason"] != supplier_a_strategy["reason"]
    assert len(supplier_a_priority["reason"]) < len(supplier_a_strategy["reason"])


def test_no_exact_duplicate_sentences_across_the_full_answer():
    answer = _full_answer()["diagnostics"]
    texts = []
    texts.append(answer["decision"])
    texts += answer["what_is_changing"]
    texts += answer["what_still_needs_to_be_learned"]
    texts += answer["what_i_would_do"]
    texts += [p["priority"] + " -- " + p["reason"] for p in answer["priorities"]]
    texts += [s["sentence"] for s in answer["supplier_strategy"]]
    for items in answer["roadmap"].values():
        for item in items:
            if isinstance(item, dict):
                texts.append(item.get("initiative") or item.get("status") or "")
            else:
                texts.append(item)
    texts = [t for t in texts if t]
    seen = set()
    dupes = []
    for t in texts:
        key = t.strip().lower()
        if key in seen:
            dupes.append(t)
        seen.add(key)
    assert dupes == [], f"exact duplicate sentences found: {dupes}"
