"""
Hardening-pass regression tests.

Covers three genuine defects found and fixed after the scenario-engine
currency fix: (1) model_orchestration.py silently comparing a non-USD
financial figure against USD-denominated thresholds, (2)
'CommercialPosition' object has no attribute 'supplier_name' in
agentic_workflow.py's real call path, (3) outcome_intelligence.py and
sensitivity.py's currency handling.
"""
from unittest.mock import patch

from app.pipeline.model_orchestration import challenge_trigger
from app.pipeline.financial import compute_financial_impact
from app.pipeline.agentic_workflow import build_agentic_workflow
from app.pipeline.negotiation_intelligence import build_negotiation_intelligence
from app.pipeline.outcome_intelligence import build_outcome_intelligence
from app.pipeline.sensitivity import build_sensitivity_analysis
from app.pipeline.stress_test import build_stress_test
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence
from app.models import CommercialPosition, Confidence, ConfidenceFactor


def _eur_normalized(alt_percent=None, alt_label=None):
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Supplier A", supplier_currency="EUR"),
        case=PriceIncreaseEvidence(
            current_price_or_terms="EUR 19.77/unit", requested_increase_percent=11.0,
            alternative_scenario_percent=alt_percent, alternative_scenario_label=alt_label,
        ),
        derived=DerivedEvidence(resolved_annual_spend_usd=5_550_000, currency_calculation_safe=True, spend_currency="EUR"),
    )


def _usd_normalized():
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Acme"),
        case=PriceIncreaseEvidence(requested_increase_percent=15.0),
        derived=DerivedEvidence(resolved_annual_spend_usd=4_000_000, currency_calculation_safe=True, spend_currency="USD"),
    )


def _position(financial_impact=None):
    return CommercialPosition(
        recommendation="test", commercial_insights=["a"], reasoning="r",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")], derivation_note="n"),
        assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
        financial_impact=financial_impact,
    )


# ---------------------------------------------------------------------
# model_orchestration.py -- currency-unresolved comparison state
# ---------------------------------------------------------------------

def test_eur_exposure_never_silently_compared_against_usd_threshold():
    n = _eur_normalized()
    fi = compute_financial_impact(n)  # 610,500 EUR -- well above both USD thresholds' magnitude
    pos = _position(fi)
    should_run, reasons = challenge_trigger(n, pos)
    assert should_run is True
    assert not any("exceeds the challenge threshold" in r for r in reasons), \
        "must never silently compare a EUR figure against a USD threshold"
    assert not any("price-increase exposure warrants" in r for r in reasons), \
        "must never silently compare a EUR figure against a USD threshold"
    assert any("unresolved" in r and "EUR" in r for r in reasons), \
        "must surface an explicit, named unresolved-comparison reason"


def test_usd_exposure_threshold_comparison_still_works_correctly():
    """Regression guard: the currency-safety fix must not break the
    original, correct USD comparison."""
    n = _usd_normalized()
    fi = compute_financial_impact(n)  # 600,000 USD -- above both thresholds
    pos = _position(fi)
    should_run, reasons = challenge_trigger(n, pos)
    assert should_run is True
    assert any("exceeds the challenge threshold" in r for r in reasons)
    assert any("price-increase exposure warrants" in r for r in reasons)
    assert not any("unresolved" in r for r in reasons)


def test_no_financial_impact_at_all_triggers_no_threshold_reason_and_no_crash():
    n = _usd_normalized()
    pos = _position(None)
    should_run, reasons = challenge_trigger(n, pos)
    assert not any("threshold" in r or "unresolved" in r for r in reasons)


# ---------------------------------------------------------------------
# agentic_workflow.py / negotiation_intelligence.py -- supplier_name,
# exercised through the real call chain, not the isolated function alone
# ---------------------------------------------------------------------

def test_agentic_workflow_real_path_no_longer_raises_and_uses_real_supplier_name():
    """Directly reproduces the original crash's exact call shape (the
    real negotiation-intelligence + agentic-workflow pair, called
    together, exactly as decisions.py invokes them) and confirms both
    the exception is gone AND the real supplier name is genuinely used,
    not merely suppressed with a generic getattr default."""
    n = _eur_normalized()
    fi = compute_financial_impact(n)
    pos = _position(fi)
    pos.opening_position = "Hold at current terms"
    pos.negotiation_intelligence = build_negotiation_intelligence(pos)
    # This is the exact call shape from decisions.py's try block.
    workflow = build_agentic_workflow(pos, n.common.supplier_name)
    assert workflow["mode"] == "BOUNDED_AGENTIC_WORKFLOW"
    drafts = [a.get("prepared_output", "") for a in workflow.get("actions", [])]
    assert any("Supplier A" in d for d in drafts), \
        "the real supplier name must reach the drafted message, not a generic 'the supplier' fallback"


def test_agentic_workflow_falls_back_gracefully_with_no_supplier_name():
    """When no supplier name is available at all (e.g. a general
    commercial-signal case with no single named supplier), this must
    still work -- generic fallback text, not a crash."""
    n = _eur_normalized()
    fi = compute_financial_impact(n)
    pos = _position(fi)
    workflow = build_agentic_workflow(pos, None)
    assert workflow["mode"] == "BOUNDED_AGENTIC_WORKFLOW"


def test_commercial_position_genuinely_has_no_supplier_name_field():
    """Documents the actual root cause directly: CommercialPosition never
    had this field, and must not gain one as a superficial patch --
    the fix is threading the real value through as an explicit
    parameter, not adding a field that doesn't belong on the model."""
    pos = _position(None)
    assert not hasattr(pos, "supplier_name") or "supplier_name" not in type(pos).model_fields


# ---------------------------------------------------------------------
# outcome_intelligence.py -- expected/actual currency safety
# ---------------------------------------------------------------------

def test_eur_case_shows_display_value_but_never_compares_cross_currency():
    n = _eur_normalized()
    fi = compute_financial_impact(n)
    pos = _position(fi)
    result = build_outcome_intelligence(pos, {"actual_financial_impact_usd": 400_000})
    # The currency-aware display value is genuinely present...
    assert result["expected_financial_impact_display"] == 610_500.0
    assert result["expected_financial_impact_currency"] == "EUR"
    # ...but the legacy USD-only comparison field is correctly None, so
    # no variance is silently computed between a EUR expectation and a
    # USD-labeled actual.
    assert result["expected_financial_impact_usd"] is None
    assert result["financial_variance_available"] is False
    assert result["realization_status"] == "NO_EXPECTATION"


def test_usd_case_variance_comparison_still_works_correctly():
    """Regression guard: the currency-safety fix must not break the
    original, correct USD-vs-USD variance comparison."""
    n = _usd_normalized()
    fi = compute_financial_impact(n)
    pos = _position(fi)
    result = build_outcome_intelligence(pos, {"actual_financial_impact_usd": 590_000})
    assert result["expected_financial_impact_usd"] == 600_000.0
    assert result["financial_variance_available"] is True
    assert result["financial_variance_usd"] == -10_000.0


# ---------------------------------------------------------------------
# sensitivity.py -- currency-correct price-increase scenarios
# ---------------------------------------------------------------------

def test_sensitivity_eur_case_uses_eur_throughout():
    n = _eur_normalized()
    result = build_sensitivity_analysis(n)
    assert result["available"] is True
    assert result["currency"] == "EUR"
    for s in result["scenarios"]:
        assert s["currency"] == "EUR"


def test_sensitivity_quote_comparison_branch_unchanged_and_still_usd_gated():
    """Regression guard: the deliberately USD-only quote_comparison
    branch (a genuinely different feature -- comparing supplier prices,
    not a price-increase scenario) must remain untouched and still
    correctly refuse mixed-currency supplier comparisons."""
    from app.pipeline.normalized_evidence import SupplierEvidence, QuoteComparisonEvidence
    n = NormalizedEvidence(
        content_type="quote_comparison",
        common=CommonEvidence(annual_volume_units=1000),
        case=QuoteComparisonEvidence(),
        derived=DerivedEvidence(),
        suppliers=[
            SupplierEvidence(supplier_name="A", price_usd=10.0, currency="EUR"),
            SupplierEvidence(supplier_name="B", price_usd=12.0, currency="USD"),
        ],
    )
    result = build_sensitivity_analysis(n)
    assert result["available"] is False
    assert "not all explicitly USD" in result["reason"]


# ---------------------------------------------------------------------
# stress_test.py -- found during the final static audit: this uses the
# same currency_calculation_safe flag fixed earlier, meaning it now
# correctly computes for EUR/GBP cases too -- but was never updated to
# label the currency, the exact same defect class already fixed once in
# sensitivity.py.
# ---------------------------------------------------------------------

def test_stress_test_eur_case_uses_eur_throughout():
    n = _eur_normalized()
    pos = _position(compute_financial_impact(n))
    result = build_stress_test(n, pos)
    assert result["available"] is True
    assert result["currency"] == "EUR"
    for t in result["tests"]:
        if t.get("annual_impact_usd") is not None:
            assert t["currency"] == "EUR"


def test_stress_test_usd_case_unchanged():
    n = _usd_normalized()
    pos = _position(compute_financial_impact(n))
    result = build_stress_test(n, pos)
    assert result["available"] is True
    assert result["currency"] == "USD"
