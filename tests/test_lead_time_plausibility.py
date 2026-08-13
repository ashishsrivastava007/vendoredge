"""
Production Hardening Fix #2 — Implausible Lead Time.

Confirmed red-team finding: "Overseas supplier (China-based, FOB terms)
promises 3-day delivery" passed through with zero plausibility check.
Fixed via check_lead_time_plausibility() -- deliberately narrow, only
firing on a genuine cross-border signal (the supplier's own stated
region) combined with a physically implausible lead time, and never
firing if the model already caught and flagged the concern itself.
"""
from app.pipeline.claim_integrity import check_lead_time_plausibility
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence, SupplierEvidence,
)

_CONF = Confidence(
    level="medium",
    factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
    derivation_note="n",
)


def _pos(reasoning):
    return CommercialPosition(
        recommendation="x", commercial_insights=["a"], reasoning=reasoning,
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )


def test_exact_real_red_team_scenario_is_flagged():
    """China-based, FOB, 3-day delivery -- the exact real finding."""
    ne = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(), case=PriceIncreaseEvidence(), derived=DerivedEvidence(),
        suppliers=[SupplierEvidence(supplier_name="Overseas Supplier", region="China", incoterm="FOB", lead_time_weeks=0.43)],
    )
    pos = _pos("This is a strong offer given the fast delivery timeline.")
    issues = check_lead_time_plausibility(pos, ne)
    assert len(issues) == 1
    assert "China" in issues[0]


def test_domestic_supplier_with_no_region_is_never_flagged():
    """Critical negative case: zero cross-border signal means zero
    chance of a false positive, regardless of how fast the claim is."""
    ne = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(), case=PriceIncreaseEvidence(), derived=DerivedEvidence(),
        suppliers=[SupplierEvidence(supplier_name="Local Supplier", region=None, lead_time_weeks=0.2)],
    )
    pos = _pos("Fast local delivery available.")
    assert check_lead_time_plausibility(pos, ne) == []


def test_realistic_cross_border_lead_time_is_never_flagged():
    """A genuinely realistic overseas lead time (e.g. 6 weeks) must
    never be touched by this check."""
    ne = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(), case=PriceIncreaseEvidence(), derived=DerivedEvidence(),
        suppliers=[SupplierEvidence(supplier_name="Overseas Supplier", region="China", incoterm="FOB", lead_time_weeks=6.0)],
    )
    pos = _pos("Standard overseas lead time for this category.")
    assert check_lead_time_plausibility(pos, ne) == []


def test_model_already_flagging_the_concern_is_not_double_corrected():
    """If the model already caught and stated the implausibility, no
    retry is needed -- the response is already honest."""
    ne = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(), case=PriceIncreaseEvidence(), derived=DerivedEvidence(),
        suppliers=[SupplierEvidence(supplier_name="Overseas Supplier", region="China", incoterm="FOB", lead_time_weeks=0.43)],
    )
    pos = _pos("This 3-day claim from China seems unrealistic given real customs clearance times.")
    assert check_lead_time_plausibility(pos, ne) == []


def test_deliberate_break_removing_the_region_signal_disables_detection():
    """
    MANDATORY deliberate-break proof. Confirms the check genuinely
    depends on the real region signal -- stripping it out (simulating a
    broken extraction path) makes the exact same dangerous claim
    invisible, proving the check is load-bearing, not decorative.
    """
    ne = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(), case=PriceIncreaseEvidence(), derived=DerivedEvidence(),
        suppliers=[SupplierEvidence(supplier_name="Overseas Supplier", region="China", incoterm="FOB", lead_time_weeks=0.43)],
    )
    pos = _pos("Strong, fast offer.")
    assert len(check_lead_time_plausibility(pos, ne)) > 0  # real, working state

    broken = ne.model_copy(update={"suppliers": [s.model_copy(update={"region": None}) for s in ne.suppliers]})
    assert check_lead_time_plausibility(pos, broken) == [], (
        "Without the region signal, this dangerous claim becomes invisible -- "
        "confirming the check is genuinely load-bearing."
    )
