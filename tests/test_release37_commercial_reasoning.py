from pathlib import Path

from app.models import CommercialPosition, Confidence, NegotiationDimension
from app.pipeline.commercial_reasoning import build_commercial_reasoning_loop
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, FieldProvenance,
    DerivedEvidence,
)


def _case():
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="ABC Marine Supplies B.V."),
        case=PriceIncreaseEvidence(
            requested_increase_percent=8.5,
            suppliers_stated_justification="stainless steel and brass costs",
            annual_spend_usd=1_850_000,
        ),
        derived=DerivedEvidence(resolved_annual_spend_usd=1_850_000, annual_spend_resolution_method="direct"),
        provenance={
            "requested_increase_percent": FieldProvenance(source="llm_extraction", stage_captured="test"),
            "annual_spend_usd": FieldProvenance(source="llm_extraction", stage_captured="test"),
        },
    )


def _position(**extra):
    base = dict(
        recommendation="Do not accept the requested increase as submitted.",
        commercial_insights=["The supplier has not substantiated the requested increase."],
        reasoning="Challenge the unsupported increase while protecting continuity.",
        confidence=Confidence(level="medium", factors=[{"factor":"Evidence gap","value":"No detailed cost breakdown","weight":"decreases confidence"}], derivation_note="Evidence is incomplete."),
        assumptions=["Supplier-specific cost evidence remains incomplete"],
        decision_type="optimization",
        disconfirming_condition="Reassess if credible supplier cost evidence materially supports the request.",
    )
    base.update(extra)
    return CommercialPosition(**base)


def test_reasoning_loop_exposes_economic_chain_without_inventing_thresholds():
    p = _position(
        financial_impact={
            "annual_spend_usd": 1_850_000,
            "requested_change_percent": 8.5,
            "potential_annual_impact_usd": 157_250,
            "note": "Deterministic",
        },
        decision_audit={
            "material_evidence": [{"status":"PROVEN","evidence":"Annual spend: 1850000"}],
            "reversal_conditions": ["Reassess if credible supplier cost evidence materially supports the request."],
            "uncertainties": [], "evidence_integrity_status":"PROVEN",
        },
        decision_under_uncertainty={"decision_changers": ["Credible supplier cost evidence"]},
    )
    r = build_commercial_reasoning_loop(_case(), p)
    assert r["available"] is True
    assert any("157,250" in x["finding"] for x in r["reasoning_trace"])
    assert not any("4-5%" in str(r) or "6-7%" in str(r) for _ in [0])


def test_challenger_counterargument_is_separate_from_primary_decision():
    p = _position(model_orchestration={
        "challenge_level": "watch",
        "verdict": "supports_with_caveat",
        "alternative_frame": "Supply continuity may justify a controlled negotiation rather than an immediate rebid.",
    })
    r = build_commercial_reasoning_loop(_case(), p)
    assert r["stability"] == "CONDITIONAL"
    assert r["counterargument_source"] == "independent_challenger"
    assert r["primary_recommendation"] == p.recommendation


def test_critical_challenge_requires_review_but_does_not_mutate_recommendation():
    p = _position(model_orchestration={
        "challenge_level": "critical",
        "verdict": "requires_human_review",
        "alternative_frame": "A material evidence issue needs resolution.",
    })
    r = build_commercial_reasoning_loop(_case(), p)
    assert r["stability"] == "REQUIRES_REVIEW"
    assert r["primary_recommendation"] == p.recommendation


def test_frontend_surfaces_reasoning_loop_as_primary_layer():
    html = Path(__file__).resolve().parents[1].joinpath("app/static/index.html").read_text()
    assert 'id="pos-reasoning-loop"' in html
    assert "renderCommercialReasoningLoop(pos)" in html
    assert "STRONGEST COUNTER-ARGUMENT" in html
