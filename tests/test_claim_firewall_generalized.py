"""
Claim-Strength Firewall — generalized beyond qualification status.
Covers: verification/confirmation, market-support, comparative price,
certainty/guarantee, past-tense achievement, and invented contract-status
claims. Each check is proven against a real overstatement it catches and
a real honest case it must never flag.

A genuine bug was found and fixed while wiring this into the live
retry flow: the first version of the "guaranteed" check false-positived
on this codebase's own existing, legitimate phrase "the guaranteed
calculation" (meaning code-computed and verified), which is a completely
different claim from "guaranteed to save you money" (a real future-
outcome overstatement). The pattern was narrowed to target only genuine
future-outcome certainty language -- locked in here permanently.
"""
from app.pipeline.claim_integrity import (
    check_verification_overstatement, check_market_support_overstatement,
    check_comparative_price_overstatement, check_certainty_overstatement,
    check_achievement_overstatement, check_contract_status_overstatement,
    check_all_claim_overstatements,
)
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence,
    SupplierEvidence, FieldProvenance,
)

_CONF = Confidence(
    level="medium",
    factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
    derivation_note="n",
)


def _pos(reasoning, **kwargs):
    return CommercialPosition(
        recommendation="x", commercial_insights=["a"], reasoning=reasoning,
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization", **kwargs,
    )


# ---- Check: verification/confirmation ----

def test_verification_claim_on_sole_fallback_source_is_flagged():
    ne = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(), case=PriceIncreaseEvidence(), derived=DerivedEvidence(),
        provenance={"current_price_or_terms": FieldProvenance(source="deterministic_fallback", stage_captured="x")},
    )
    pos = _pos("This price has been verified against the supplier quote.")
    assert len(check_verification_overstatement(pos, ne)) > 0


def test_verification_claim_on_user_confirmed_source_is_not_flagged():
    ne = NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(), case=PriceIncreaseEvidence(), derived=DerivedEvidence(),
        provenance={"current_price_or_terms": FieldProvenance(source="user_followup", stage_captured="x")},
    )
    pos = _pos("This price has been confirmed by the buyer directly.")
    assert check_verification_overstatement(pos, ne) == []


# ---- Check: market support ----

def test_market_support_claim_without_a_real_check_is_flagged():
    pos = _pos("The market index confirms this increase is fair.", market_verification_scope=None)
    assert len(check_market_support_overstatement(pos)) > 0


def test_market_support_claim_with_a_real_check_is_not_flagged():
    pos = _pos("The market index confirms this movement.", market_verification_scope="global")
    assert check_market_support_overstatement(pos) == []


# ---- Check: comparative price ----

def test_best_price_claim_with_only_one_supplier_is_flagged():
    ne = NormalizedEvidence(
        content_type="quote_comparison", common=CommonEvidence(), case=PriceIncreaseEvidence(), derived=DerivedEvidence(),
        suppliers=[SupplierEvidence(supplier_name="Acme", price_display="$100/unit")],
    )
    pos = _pos("Acme offers the best price available.")
    assert len(check_comparative_price_overstatement(pos, ne)) > 0


def test_best_price_claim_with_two_real_suppliers_is_not_flagged():
    ne = NormalizedEvidence(
        content_type="quote_comparison", common=CommonEvidence(), case=PriceIncreaseEvidence(), derived=DerivedEvidence(),
        suppliers=[
            SupplierEvidence(supplier_name="Acme", price_display="$100/unit"),
            SupplierEvidence(supplier_name="Zenith", price_display="$120/unit"),
        ],
    )
    pos = _pos("Acme offers the best price of the two quotes received.")
    assert check_comparative_price_overstatement(pos, ne) == []


# ---- Check: certainty/guarantee ----

def test_real_future_outcome_certainty_claim_is_flagged():
    pos = _pos("This negotiation strategy is guaranteed to save $500,000.")
    assert len(check_certainty_overstatement(pos)) > 0


def test_the_codebase_own_guaranteed_calculation_language_is_never_flagged():
    """Regression test for the exact real false-positive found and fixed
    while wiring this into the live retry flow."""
    pos = _pos("The guaranteed calculation shows a real $4,345,200 annual impact if accepted.")
    assert check_certainty_overstatement(pos) == []


# ---- Check: achievement (past-tense) ----

def test_achievement_claim_on_a_fresh_case_is_flagged():
    pos = _pos("Cost savings achieved through this negotiation approach.")
    assert len(check_achievement_overstatement(pos, is_continuation=False)) > 0


def test_achievement_claim_on_a_genuine_continuation_case_is_not_flagged():
    pos = _pos("Cost savings achieved in the prior negotiation round.")
    assert check_achievement_overstatement(pos, is_continuation=True) == []


# ---- Check: contract status ----

def test_invented_contract_status_is_flagged():
    pos = _pos("This supplier is under contract for the next two years.")
    assert len(check_contract_status_overstatement(pos, "Our supplier requested a price increase.")) > 0


def test_contract_status_genuinely_stated_by_the_user_is_not_flagged():
    pos = _pos("This supplier is under contract per the terms you described.")
    assert check_contract_status_overstatement(pos, "We have a 3-year contract with this supplier.") == []


# ---- Aggregate entry point ----

def test_aggregate_entry_point_catches_multiple_overstatement_types_at_once():
    ne = NormalizedEvidence(
        content_type="quote_comparison", common=CommonEvidence(), case=PriceIncreaseEvidence(), derived=DerivedEvidence(),
        suppliers=[SupplierEvidence(supplier_name="Acme", price_display="$100/unit")],
    )
    pos = _pos(
        "Acme offers the best price available, and this is guaranteed to deliver savings.",
        market_verification_scope=None,
    )
    issues = check_all_claim_overstatements(pos, ne, raw_question="x", is_continuation=False)
    assert len(issues) >= 2  # both the comparative-price and certainty checks should fire
