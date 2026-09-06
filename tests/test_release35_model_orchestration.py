from app.models import CommercialPosition, Confidence, ConfidenceFactor, FinancialImpact
from app.pipeline.model_orchestration import ChallengerOpinion, build_model_orchestration, challenge_trigger
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, DerivedEvidence, PriceIncreaseEvidence


def _position(exposure=100000.0, confidence="medium"):
    return CommercialPosition(
        recommendation="Negotiate", recommendation_type="negotiate",
        commercial_insights=["Material commercial trade-off"], reasoning="Evidence-backed.",
        confidence=Confidence(level=confidence, factors=[ConfidenceFactor(factor="Evidence", value="Adequate", weight="increases confidence")], derivation_note="Test"),
        disconfirming_condition="New verified evidence materially changes the case.",
        decision_type="optimization", assumptions=["Captured evidence is accurate."],
        financial_impact=FinancialImpact(annual_spend_usd=1000000, requested_change_percent=10, potential_annual_impact_usd=exposure, note="Test"),
    )


def _normalized(warnings=None):
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(),
        case=PriceIncreaseEvidence(),
        derived=DerivedEvidence(),
        normalization_warnings=warnings or [],
    )


def test_r35_routine_case_uses_primary_only():
    pos = _position()
    n = _normalized()
    should, reasons = challenge_trigger(n, pos)
    assert should is False
    out = build_model_orchestration(n, pos, trigger_reasons=reasons)
    assert out["mode"] == "PRIMARY_ONLY"
    assert out["challenger_invoked"] is False


def test_r35_material_exposure_triggers_second_opinion():
    pos = _position(exposure=600000)
    should, reasons = challenge_trigger(_normalized(), pos)
    assert should is True
    assert any("financial exposure" in x for x in reasons)


def test_r35_critical_challenger_requires_review_without_mutating_position():
    pos = _position(exposure=600000)
    opinion = ChallengerOpinion(
        challenge_level="critical",
        challenged_claims=["Primary position relies on an unsupported supplier claim."],
        overlooked_risks=["Switching capacity was not evidenced."],
        alternative_frame="Separate continuity protection from price acceptance.",
        verdict="requires_human_review",
        evidence_basis=["Alternative capacity is only partially captured."],
    )
    out = build_model_orchestration(_normalized(), pos, opinion=opinion, trigger_reasons=["financial exposure exceeds the challenge threshold"])
    assert out["mode"] == "DUAL_MODEL_REVIEW"
    assert out["review_required"] is True
    assert pos.recommendation == "Negotiate"
