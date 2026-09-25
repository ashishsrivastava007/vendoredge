"""
R48 Signal Engine -- explicit contradiction detection, kept visibly
distinct from both UNKNOWN hypotheses and ordinary competing
hypotheses (a separate list, a separate section, a different purpose).
Narrow and evidence-literal: compares a real CALCULATED fact against
the case's own stated text, never against an assumed baseline.
"""
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor

client = TestClient(app)
_CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _run(numeric_facts, insights, recommendation, suffix, supplier_evidence=None, extra_evidence=None):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"10.996.{suffix}.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    classify = {
        "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", **(extra_evidence or {})},
        "numeric_facts": numeric_facts, "supplier_specific_evidence": supplier_evidence or [],
    }
    pos = CommercialPosition(recommendation=recommendation, commercial_insights=insights, reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "test", "mode": "commercial_signal"}, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return d["commercial_position"]["commercial_signal_answer"]


def test_price_increase_claim_contradicting_calculated_price_fall_is_detected():
    a = _run(
        {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 12_000, "category_prior_annual_volume_units": 10_000},
        ["a"], "Reconcile the contradiction before concluding anything.", 1,
        extra_evidence={"suppliers_stated_justification": "The supplier insists their price increased significantly."},
    )
    assert len(a["contradictions"]) == 1
    assert "price increase" in a["contradictions"][0]["description"].lower()
    assert "-16.7%" in a["contradictions"][0]["calculated_evidence"]


def test_contradictions_kept_separate_from_hypotheses_not_merged_in():
    a = _run(
        {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 12_000, "category_prior_annual_volume_units": 10_000},
        ["a"], "Reconcile the contradiction.", 2,
        extra_evidence={"suppliers_stated_justification": "The supplier insists their price increased significantly."},
    )
    assert "contradictions" in a and "hypotheses" in a
    contradiction_texts = {c["description"] for c in a["contradictions"]}
    hypothesis_texts = {h["hypothesis"] for h in a["hypotheses"]}
    assert contradiction_texts.isdisjoint(hypothesis_texts)


def test_no_contradiction_flagged_when_claim_and_calculation_actually_agree():
    a = _run(
        {"category_annual_spend_usd": 1_180_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_300, "category_prior_annual_volume_units": 10_000},
        ["a"], "Investigate.", 3,
        extra_evidence={"suppliers_stated_justification": "The supplier says their price increased."},
    )
    assert a["contradictions"] == []


def test_otif_improvement_claim_contradicting_calculated_decline_is_detected():
    a = _run(
        {}, ["a"], "Investigate the discrepancy.", 4,
        extra_evidence={"suppliers_stated_justification": "The supplier says their OTIF improved this quarter."},
        supplier_evidence=[{"supplier_name": "Supplier X", "is_incumbent": True, "otif_percent": 81.0, "prior_otif_percent": 96.0}],
    )
    assert len(a["contradictions"]) == 1
    assert "otif" in a["contradictions"][0]["description"].lower()


def test_contradiction_markup_present_and_no_leakage_in_frontend():
    from pathlib import Path
    text = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text()
    assert "EVIDENCE CONFLICT" in text
    assert "contradictionsSection" in text
