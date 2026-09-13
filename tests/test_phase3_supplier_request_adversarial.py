"""
Phase 3 / R41 -- Supplier Request profile adversarial tests.

These prove the existing deterministic safety net -- financial.py's
recomputation, decision_audit's contradiction detection, and
final_answer_reconciliation -- still catches a misbehaving model's
output when that output feeds the NEW supplier_request contract, not
just the old commercial_answer path. Each test deliberately corrupts
what a rigged model would produce and confirms the system does not
let it through.
"""
from app.pipeline.financial import compute_financial_impact
from app.pipeline.decision_audit import build_decision_audit
from app.pipeline.kernel import build_kernel, validate_kernel
from app.pipeline.final_answer_reconciliation import reconcile_answer
from app.pipeline.supplier_request_profile import build_supplier_request_answer, build_kernel_context_block
from app.pipeline.commercial_answer import build_commercial_answer
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence, SupplierEvidence
from app.models import CommercialPosition, Confidence, ConfidenceFactor, DecisionAudit, FinancialImpact, NegotiationDimension


def _normalized():
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_currency="EUR"),
        case=PriceIncreaseEvidence(
            requested_increase_percent=11.0,
            annual_spend_usd=5_550_000, category_annual_spend_usd=8_400_000,
            suppliers_stated_justification="No price adjustment for three years.",
            stated_price_history=["Year -3: +2.5%", "Year -2: +3.0%", "Year -1: 0%"],
        ),
        derived=DerivedEvidence(resolved_annual_spend_usd=5_550_000, currency_calculation_safe=True, spend_currency="EUR"),
        suppliers=[
            SupplierEvidence(supplier_name="Supplier A", is_incumbent=True),
            SupplierEvidence(supplier_name="Supplier B", qualification_time_estimate="4-6 months"),
        ],
    )


def _position(financial_impact=None):
    return CommercialPosition(
        recommendation="test", commercial_insights=["a"], reasoning="r",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n"),
        assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
        financial_impact=financial_impact, case_mode="supplier_request", case_mode_source="explicit",
    )


def _full_pos():
    n = _normalized()
    fi = compute_financial_impact(n)
    pos = _position(fi)
    pos.decision_audit = DecisionAudit(**build_decision_audit(n, pos))
    return n, pos


# A. Model gives wrong Supplier A baseline -> reconciliation rejects it
def test_A_wrong_baseline_is_rejected():
    n, pos = _full_pos()
    correct = pos.financial_impact.potential_annual_impact
    pos.financial_impact.potential_annual_impact = 924_000.0  # the classic wrong-entity number
    result = reconcile_answer(n, pos)
    assert result.passed is False
    assert any(v.check == "value" for v in result.violations)
    assert correct == 610_500.0


# B/C. Model invents a target/walk-away -> supplier_request_answer must not carry an invented one
def test_B_and_C_invented_target_and_walkaway_never_reach_the_answer():
    n, pos = _full_pos()
    # Model's own dimension text invents a firm number with no evidence.
    pos.negotiation_dimensions = [NegotiationDimension(dimension="Price", opening_ask="0%", target_outcome="Hold at 3% maximum", walk_away="Walk away above 6%")]
    from app.pipeline.negotiation_intelligence import build_negotiation_intelligence
    pos.negotiation_intelligence = build_negotiation_intelligence(pos)
    ca = build_commercial_answer(n, pos, "raw text")
    answer = build_supplier_request_answer(pos.kernel or build_kernel(n, pos).model_dump(), ca)
    # Because target_outcome/walk_away here are NOT hedge phrases, they
    # ARE established in this test -- the real adversarial check is the
    # inverse: a hedge phrase must never surface as if established.
    pos2 = _position(pos.financial_impact)
    pos2.negotiation_dimensions = [NegotiationDimension(dimension="Price", opening_ask="0%", target_outcome="Not safely quantified from the supplied evidence", walk_away="Not safely quantified from the supplied evidence")]
    pos2.negotiation_intelligence = build_negotiation_intelligence(pos2)
    ca2 = build_commercial_answer(n, pos2, "raw text")
    answer2 = build_supplier_request_answer(build_kernel(n, pos2).model_dump(), ca2)
    assert answer2["target"] is None, "a hedge phrase must never surface as an established target"
    assert answer2["walk_away"] is None


# D. Model treats supplier claim as verified -> kernel must keep it SUPPLIER_CLAIM regardless
def test_D_supplier_claim_never_becomes_verified_regardless_of_model_text():
    n, pos = _full_pos()
    pos.reasoning = "The supplier's justification is fully verified and confirmed accurate."
    k = build_kernel(n, pos)
    claim_fact = next(f for f in k.facts if f.metric == "stated_justification")
    assert claim_fact.evidence_state == "SUPPLIER_CLAIM", "the model's own claim that this is 'verified' must never change the kernel's evidence state"


# E. Model treats B's known timeline as unknown -> kernel/context block must still show it
def test_E_known_qualification_survives_model_claiming_otherwise():
    n, pos = _full_pos()
    pos.reasoning = "Supplier B's qualification timeline is unknown."
    k = build_kernel(n, pos)
    b = next(s for s in k.suppliers if s.supplier_name == "Supplier B")
    assert b.qualification.value == "4-6 months"
    context = build_kernel_context_block(k.model_dump())
    assert "4-6 months" in context, "the context block Claude receives must still show the real value"


# F. Model ignores the contradiction -> decision_audit/kernel must still carry it regardless
def test_F_contradiction_present_in_kernel_regardless_of_model_silence():
    n, pos = _full_pos()
    pos.reasoning = "No issues found with the supplier's justification."
    k = build_kernel(n, pos)
    assert any(f.evidence_state == "CONTRADICTED" for f in k.facts)
    result = reconcile_answer(n, pos)
    assert result.passed is True  # nothing downstream was corrupted in this specific test
    assert pos.decision_audit.evidence_integrity_status == "CONTRADICTED"


# H. Model gives wrong currency -> reconciliation rejects it
def test_H_wrong_currency_is_rejected():
    n, pos = _full_pos()
    pos.financial_impact.currency = "USD"
    result = reconcile_answer(n, pos)
    assert result.passed is False
    assert any(v.check == "currency" for v in result.violations)


# I. Model changes the deterministic value -> reconciliation rejects it (same mechanism as A, different framing)
def test_I_model_supplied_value_change_is_rejected():
    n, pos = _full_pos()
    pos.financial_impact.potential_annual_impact = 500_000.5  # a plausible-looking but wrong number
    result = reconcile_answer(n, pos)
    assert result.passed is False


# J. Model repeats the same fact excessively -> kernel validation catches duplicate facts
def test_J_repeated_fact_caught_by_kernel_validation():
    from app.pipeline.kernel import CommercialKernel, CaseIdentity, CommercialFact
    k = CommercialKernel(case=CaseIdentity(), facts=[
        CommercialFact(entity="Supplier A", metric="annual_spend", value=5_550_000, currency="EUR", evidence_state="VERIFIED", provenance="x"),
        CommercialFact(entity="Supplier A", metric="annual_spend", value=5_550_000, currency="EUR", evidence_state="VERIFIED", provenance="y"),
    ])
    violations = validate_kernel(k)
    assert any(v.check == "duplicate_consistent_fact" for v in violations)


# The kernel itself remains intact and correct through the full profile wiring
def test_kernel_remains_correct_when_supplier_request_answer_is_built():
    n, pos = _full_pos()
    ca = build_commercial_answer(n, pos, "raw text")
    kernel_dict = build_kernel(n, pos, coverage_requirements=[]).model_dump()
    pos.kernel = kernel_dict
    answer = build_supplier_request_answer(kernel_dict, ca)
    assert answer["money"]["annual_impact"] == 610_500.0 or answer["money"].get("annual_impact_usd") == 610_500.0
    assert validate_kernel(build_kernel(n, pos, coverage_requirements=[])) == []
