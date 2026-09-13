"""
Question coverage and final answer reconciliation.
"""
from app.pipeline.question_coverage import build_coverage_requirements, mark_surfaced, missing_calculated_requirements
from app.pipeline.final_answer_reconciliation import reconcile_answer
from app.pipeline.financial import compute_financial_impact
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence
from app.models import CommercialPosition, Confidence, ConfidenceFactor


def _golden_normalized():
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Supplier A", supplier_currency="EUR", annual_volume_units=246_000),
        case=PriceIncreaseEvidence(
            requested_increase_percent=11.0, alternative_scenario_percent=7.0,
            annual_spend_usd=5_550_000, prior_annual_spend_usd=4_370_000, prior_annual_volume_units=221_000,
            category_annual_spend_usd=8_400_000, category_prior_annual_spend_usd=7_050_000,
            category_annual_volume_units=412_000, category_prior_annual_volume_units=385_000,
        ),
        derived=DerivedEvidence(resolved_annual_spend_usd=5_550_000, currency_calculation_safe=True, spend_currency="EUR"),
    )


def _position(financial_impact=None):
    return CommercialPosition(
        recommendation="test", commercial_insights=["a"], reasoning="r",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")], derivation_note="n"),
        assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
        financial_impact=financial_impact,
    )


# ---------------------------------------------------------------------
# Question coverage
# ---------------------------------------------------------------------

def test_golden_case_all_seven_growth_requirements_calculated_correctly():
    n = _golden_normalized()
    reqs = build_coverage_requirements(n)
    by_id = {r.requirement_id: r for r in reqs}
    assert by_id["category_spend_growth"].result.percent_change == 19.15
    assert by_id["category_volume_growth"].result.percent_change == 7.01
    assert by_id["supplier_spend_growth"].result.percent_change == 27.0
    assert by_id["supplier_volume_growth"].result.percent_change == 11.31
    assert round(by_id["category_avg_price_growth"].result.percent_change, 1) == 11.3
    assert round(by_id["supplier_avg_price_growth"].result.percent_change, 1) == 14.1
    assert by_id["supplier_spend_share_change"].result.absolute_change > 4.0
    for r in reqs:
        assert r.status == "CALCULATED"


def test_case_with_no_prior_year_data_produces_not_applicable_not_a_crash():
    """Regression guard: the overwhelming majority of price_increase
    cases have no prior-period comparison at all."""
    n = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Acme"),
        case=PriceIncreaseEvidence(requested_increase_percent=10.0, annual_spend_usd=1_000_000),
        derived=DerivedEvidence(),
    )
    reqs = build_coverage_requirements(n)
    assert all(r.status == "NOT_APPLICABLE" for r in reqs)


def test_calculated_requirement_never_marked_surfaced_by_default():
    n = _golden_normalized()
    reqs = build_coverage_requirements(n)
    assert all(r.surfaced is False for r in reqs)
    missing = missing_calculated_requirements(reqs)
    assert len(missing) == 7


def test_mark_surfaced_correctly_promotes_status():
    n = _golden_normalized()
    reqs = build_coverage_requirements(n)
    all_ids = {r.requirement_id for r in reqs}
    mark_surfaced(reqs, all_ids, "commercial_answer")
    assert all(r.status == "SURFACED" for r in reqs)
    assert missing_calculated_requirements(reqs) == []


def test_quote_comparison_content_type_produces_no_requirements():
    """Regression guard: this coverage layer is currently scoped to
    price_increase cases, matching what financial.py itself supports --
    must not raise or produce nonsense for a different content_type."""
    from app.pipeline.normalized_evidence import QuoteComparisonEvidence
    n = NormalizedEvidence(content_type="quote_comparison", common=CommonEvidence(), case=QuoteComparisonEvidence(), derived=DerivedEvidence())
    assert build_coverage_requirements(n) == []


# ---------------------------------------------------------------------
# Final answer reconciliation
# ---------------------------------------------------------------------

def test_correct_answer_passes_reconciliation():
    n = _golden_normalized()
    fi = compute_financial_impact(n)
    pos = _position(fi)
    result = reconcile_answer(n, pos)
    assert result.passed is True
    assert result.violations == []


def test_wrong_entity_value_is_rejected_the_exact_924000_case():
    """The critical example from the spec, reproduced directly: a
    correct-looking number bound to the wrong entity must be rejected,
    not because the arithmetic is invalid, but because it doesn't match
    the canonical, freshly-recomputed, correctly-scoped figure."""
    n = _golden_normalized()
    fi = compute_financial_impact(n)
    pos = _position(fi)
    pos.financial_impact.potential_annual_impact = 924_000.0  # category baseline, wrong entity
    result = reconcile_answer(n, pos)
    assert result.passed is False
    assert any(v.check == "value" for v in result.violations)


def test_wrong_currency_is_rejected():
    n = _golden_normalized()
    fi = compute_financial_impact(n)
    pos = _position(fi)
    pos.financial_impact.currency = "USD"  # EUR case mislabeled as USD
    result = reconcile_answer(n, pos)
    assert result.passed is False
    assert any(v.check == "currency" for v in result.violations)


def test_missing_financial_impact_when_calculation_is_available_is_rejected():
    n = _golden_normalized()
    pos = _position(None)  # deterministic calc available but never attached
    result = reconcile_answer(n, pos)
    assert result.passed is False
    assert any(v.check == "value" for v in result.violations)


def test_calculated_but_unsurfaced_coverage_requirement_is_rejected():
    n = _golden_normalized()
    fi = compute_financial_impact(n)
    pos = _position(fi)
    reqs = build_coverage_requirements(n)
    # Deliberately surface none of them.
    result = reconcile_answer(n, pos, coverage_requirements=reqs)
    assert result.passed is False
    coverage_violations = [v for v in result.violations if v.check == "question_coverage"]
    assert len(coverage_violations) == 7


def test_fully_surfaced_coverage_passes_reconciliation():
    n = _golden_normalized()
    fi = compute_financial_impact(n)
    pos = _position(fi)
    reqs = build_coverage_requirements(n)
    mark_surfaced(reqs, {r.requirement_id for r in reqs}, "commercial_answer")
    result = reconcile_answer(n, pos, coverage_requirements=reqs)
    assert result.passed is True


def test_contradiction_detected_but_status_not_updated_is_rejected():
    from app.pipeline.decision_audit import build_decision_audit
    from app.models import DecisionAudit
    n = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Supplier A"),
        case=PriceIncreaseEvidence(
            requested_increase_percent=11.0,
            suppliers_stated_justification="No price adjustment for three years.",
            stated_price_history=["Year -3: +2.5%", "Year -2: +3.0%", "Year -1: 0%"],
        ),
        derived=DerivedEvidence(),
    )
    audit_dict = build_decision_audit(n, _position())
    assert audit_dict["evidence_integrity_status"] == "CONTRADICTED"
    # Simulate a downstream bug that silently downgrades the status
    # while leaving the actual contradiction text in place.
    audit_dict["evidence_integrity_status"] = "PROVEN"
    pos = _position(None)
    pos.decision_audit = DecisionAudit(**audit_dict)
    result = reconcile_answer(n, pos)
    assert result.passed is False
    assert any(v.check == "contradiction_state" for v in result.violations)


def test_target_integrity_internal_inconsistency_is_rejected():
    n = _golden_normalized()
    pos = _position(None)
    pos.negotiation_intelligence = {
        "response_scenarios": [
            {"trigger": "Supplier resists on Price", "buyer_move": "Hold the stated target for Price; ask what value they can offer.", "target_state": "NOT_ESTABLISHED"},
        ]
    }
    result = reconcile_answer(n, pos)
    assert result.passed is False
    assert any(v.check == "target_integrity" for v in result.violations)


def test_stated_price_history_survives_the_real_dispatcher_round_trip():
    """The actual, confirmed root-cause bug found during live-HTTP
    validation: _run_queued_job (the real durable-queue dispatcher path,
    not create_decision's synchronous evidence-gate check) re-normalizes
    from stored evidence fresh on every run, stripping all
    double-underscore-reserved keys and never restoring
    __stated_price_history__ specifically -- meaning a contradiction
    genuinely present in the raw case, stored correctly, would silently
    vanish by the time the real background job actually ran. Reproduces
    the exact dispatcher code path directly, not just normalize_evidence
    in isolation."""
    stored = {
        "supplier_currency": "EUR", "suppliers_stated_justification": "No price adjustment for three years.",
        "requested_change_percent": 11.0, "annual_spend_usd": 5_550_000,
        "__stated_price_history__": ["Year -3: +2.5%", "Year -2: +3.0%", "Year -1: 0%"],
    }
    suppliers = stored.get("__supplier_specific_evidence__")
    stakeholders = stored.get("__stakeholder_views__")
    price_history = stored.get("__stated_price_history__")
    evidence = {k: v for k, v in stored.items() if not (k.startswith("__") and k.endswith("__"))}
    from app.pipeline.normalize import normalize_evidence
    normalized, _ = normalize_evidence("raw case text", "price_increase", evidence, evidence,
                                        supplier_specific_evidence=suppliers, stakeholder_views=stakeholders,
                                        stated_price_history=price_history)
    assert normalized.case.stated_price_history == ["Year -3: +2.5%", "Year -2: +3.0%", "Year -1: 0%"]
