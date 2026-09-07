from pathlib import Path

from app.models import CommercialPosition, Confidence, NegotiationDimension
from app.pipeline.commercial_answer import build_commercial_answer
from app.pipeline.normalized_evidence import (
    NormalizedEvidence,
    CommonEvidence,
    PriceIncreaseEvidence,
    SupplierEvidence,
    DerivedEvidence,
    StakeholderView,
)


def _nordic():
    raw = """Nordic Industrial Components AB has requested a 9.2% price increase. If we sign a new 3-year agreement, the requested increase reduces from 9.2% to 6.5%. Annual spend is USD 4.20 million."""
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(
            supplier_name="Nordic Industrial Components AB",
            supplier_region_or_market="Sweden",
            incoterm="DAP",
        ),
        case=PriceIncreaseEvidence(
            requested_increase_percent=9.2,
            annual_spend_usd=4_200_000,
            suppliers_stated_justification="higher stainless-steel and alloy costs; electricity and labour; freight; FX; inflation",
        ),
        derived=DerivedEvidence(
            resolved_annual_spend_usd=4_200_000,
            annual_spend_resolution_method="direct",
            currency_calculation_safe=True,
        ),
        suppliers=[
            SupplierEvidence(supplier_name="Nordic Industrial Components AB", is_incumbent=True, otif_percent=96),
            SupplierEvidence(supplier_name="Alternative Supplier A", is_incumbent=False, capacity_percent=25, qualification_status="complete"),
            SupplierEvidence(supplier_name="Alternative Supplier B", is_incumbent=False, capacity_percent=15, qualification_status="unknown"),
        ],
        stakeholder_views=[StakeholderView(stakeholder_name="Finance", role="Finance", view_type="preference", statement="Minimize effective cost.")],
    ), raw


def _position():
    return CommercialPosition(
        recommendation="Negotiate the increase; do not accept the blanket 9.2% request as-is.",
        commercial_insights=[
            "The supplier has not substantiated the requested increase at product level.",
            "Alternative supply exists for part of the category, but coverage must be validated.",
        ],
        reasoning="Protect continuity while preserving competitive tension.",
        confidence=Confidence(level="medium", factors=[{"factor":"Evidence gap","value":"No product-level cost evidence","weight":"decreases confidence"}], derivation_note="Based on current evidence."),
        assumptions=["The supplier cost basis remains unvalidated."],
        decision_type="optimization",
        disconfirming_condition="Reassess if credible supplier-specific cost evidence materially supports the request.",
        opening_position="Request product-level support before agreeing to any adjustment.",
        negotiation_intelligence={
            "objective": "Minimize total effective cost while protecting critical supply.",
            "opening_position": "Request product-level support before agreeing to any adjustment.",
            "dimensions": [
                {"dimension":"Contract duration","target":"Short bridge or evidenced term","boundary":"No unconditional 3-year commitment","trading_rule":"Trade only for measurable value."}
            ],
        },
        decision_audit={
            "evidence_integrity_status": "UNKNOWN",
            "material_evidence": [],
            "uncertainties":["Alternative Supplier B qualification status was not provided."],
            "reversal_conditions":["Reassess if credible supplier-specific cost evidence materially supports the request."],
            "stakeholder_tradeoffs": [],
            "inferred_signals": [],
            "normalization_warnings": [],
        },
        model_orchestration={
            "alternative_frame":"Supply continuity may justify a controlled negotiation rather than an immediate rebid."
        },
    )


def test_r38_commercial_answer_calculates_requested_exposure():
    n, raw = _nordic()
    answer = build_commercial_answer(n, _position(), raw)
    assert answer["money"]["available"] is True
    assert answer["money"]["annual_impact_usd"] == 386400
    assert answer["money"]["monthly_impact_usd"] == 32200


def test_r38_commercial_answer_calculates_explicit_supplier_alternative():
    n, raw = _nordic()
    answer = build_commercial_answer(n, _position(), raw)
    scenario = answer["money"]["explicit_scenario"]
    assert scenario["from_percent"] == 9.2
    assert scenario["to_percent"] == 6.5
    assert scenario["annual_impact_to_usd"] == 273000
    assert scenario["annual_difference_usd"] == 113400


def test_r38_supplier_response_is_editable_and_does_not_invent_a_target():
    n, raw = _nordic()
    answer = build_commercial_answer(n, _position(), raw)
    draft = answer["supplier_response"]
    assert draft["status"].startswith("DRAFT")
    assert "Nordic Industrial Components AB" in draft["subject"]
    assert "9.2%" in draft["body"]
    assert "4-5%" not in draft["body"]
    assert "6-7%" not in draft["body"]


def test_r38_frontend_has_single_answer_surface_and_no_object_object_render_for_evidence():
    html = Path(__file__).resolve().parents[1].joinpath("app/static/index.html").read_text()
    assert 'id="pos-commercial-answer"' in html
    assert "renderCommercialAnswer(pos)" in html
    assert "typeof x === \"object\"" in html
    assert "[object Object]" not in html


def test_r38_answer_separates_stakeholder_views_from_verified_facts():
    n, raw = _nordic()
    answer = build_commercial_answer(n, _position(), raw)
    assert "Finance" not in " | ".join(answer["evidence"]["verified"])
    assert answer["evidence"]["stakeholder_views"] == ["Minimize effective cost."]


def test_r38_supports_proactive_generic_questions_with_one_answer_packet():
    from app.pipeline.commercial_answer import build_commercial_answer
    class GenericPosition:
        recommendation = "Protect margin and investigate the category shift before committing to a sourcing change."
        commercial_insights = ["The observed pattern warrants investigation before a consequential commitment."]
        opening_position = "Validate the pattern with category data, supplier allocation and demand drivers before changing allocation."
        walk_away_threshold = None
        commercial_hypothesis = "The current pattern may indicate an opportunity to rebalance allocation."
        negotiation_intelligence = None
        decision_audit = None
        model_orchestration = None
        reasoning_loop = None
        commercial_decision_engine = {"next_move": "Validate the underlying category pattern and quantify the commercial impact."}
        disconfirming_condition = "Reassess if validated category data does not support the observed pattern."
        confidence = type("C", (), {"level": "medium"})()
        financial_impact = None
    answer = build_commercial_answer(None, GenericPosition(), "I noticed category spend is up 18% this year. What should I do?")
    assert answer["status"] == "READY"
    assert answer["decision"]
    assert answer["what_to_do"]
    assert any("general commercial triage" in x.lower() for x in answer["evidence"]["unknown"])


def test_r38_answer_withholds_unsupported_numeric_strategy():
    n, raw = _nordic()
    p = _position()
    p.negotiation_intelligence = {
        "objective": "Minimize effective cost.",
        "opening_position": "Challenge the unsupported request.",
        "target": "4-5%",
        "walk_away": "Above 6-7%",
    }
    answer = build_commercial_answer(n, p, raw)
    assert answer["strategy_integrity"] == "REVIEW_REQUIRED"
    assert answer["negotiation"]["target"] is None
    assert answer["negotiation"]["walk_away"] is None
