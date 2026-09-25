"""
R48 Signal Engine -- tests for the three CRITICAL defects fixed in
this pass (per the prior 360-degree audit):

1. Evidence gate structurally blocked OTIF/defect/concentration
   signals -- fixed by recognizing every signal dimension the
   evidence model actually supports, not spend alone.
2. Non-spend signals received a misleading generic "spend and volume"
   headline -- fixed with genuine multi-dimensional signal detection.
3. "Commercial risk" was a bare keyword match against the model's own
   text -- fixed with a real materiality function built from what was
   actually calculated.

Two real bugs found and fixed while building this, documented here
too: supplier performance facts (otif_change_pp, defect_rate_change_pp)
live in a separate kernel structure never merged into the facts list
this profile reads; and prior_otif_percent/prior_defect_rate_percent/
specification_changed all needed explicit field-by-field wiring in
normalize.py, the same as every other extracted field -- nothing here
is automatic.
"""
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor

client = TestClient(app)
_CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _run(numeric_facts, insights, recommendation, suffix, supplier_evidence=None, extra_evidence=None):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"10.850.{suffix}.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    classify = {
        "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", **(extra_evidence or {})},
        "numeric_facts": numeric_facts, "supplier_specific_evidence": supplier_evidence or [],
    }
    pos = CommercialPosition(recommendation=recommendation, commercial_insights=insights, reasoning="x", confidence=_CM, assumptions=["Check like-for-like drivers before concluding."], disconfirming_condition="A SKU-level comparison would change this.", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "signal test", "mode": "commercial_signal"}, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return {"status": d["status"], "missing": d.get("missing_inputs_requested"), "answer": (d.get("commercial_position") or {}).get("commercial_signal_answer")}


# ---------------------------------------------------------------------
# Critical #1: evidence gate no longer blocks OTIF/defect/concentration
# ---------------------------------------------------------------------

def test_otif_signal_no_longer_blocked_by_the_spend_only_gate():
    r = _run({}, ["OTIF dropped."], "Investigate the OTIF decline.", 1,
             supplier_evidence=[{"supplier_name": "Supplier A", "is_incumbent": True, "otif_percent": 81.0, "prior_otif_percent": 96.0}])
    assert r["status"] == "completed"


def test_defect_signal_no_longer_blocked():
    r = _run({}, ["Defects increased."], "Investigate the defect increase.", 2,
             supplier_evidence=[{"supplier_name": "Supplier B", "is_incumbent": True, "defect_rate_percent": 4.8, "prior_defect_rate_percent": 1.2}])
    assert r["status"] == "completed"


def test_signal_with_no_recognizable_evidence_dimension_still_correctly_blocked():
    """The gate fix must not become "accept anything" -- a case with
    genuinely no comparable evidence at all should still be asked for one."""
    r = _run({}, ["Something seems off."], "Not enough information yet.", 3)
    assert r["status"] == "awaiting_user_input"


# ---------------------------------------------------------------------
# Critical #2: headline is genuinely signal-specific, not a generic
# spend/volume fallback for every non-spend signal
# ---------------------------------------------------------------------

def test_otif_headline_states_the_actual_otif_change_not_generic_spend_language():
    r = _run({}, ["OTIF dropped."], "Investigate.", 4,
             supplier_evidence=[{"supplier_name": "Supplier A", "is_incumbent": True, "otif_percent": 81.0, "prior_otif_percent": 96.0}])
    signal = r["answer"]["signal"]
    assert "OTIF" in signal and "15.0" in signal
    assert "spend" not in signal.lower() and "volume" not in signal.lower()


def test_defect_headline_states_the_actual_defect_change():
    r = _run({}, ["Defects increased."], "Investigate.", 5,
             supplier_evidence=[{"supplier_name": "Supplier B", "is_incumbent": True, "defect_rate_percent": 4.8, "prior_defect_rate_percent": 1.2}])
    signal = r["answer"]["signal"]
    assert "defect rate" in signal.lower() and "3.6" in signal


def test_concentration_headline_states_the_actual_share_change():
    r = _run(
        {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 700_000, "annual_spend_usd": 640_000, "prior_annual_spend_usd": 294_000},
        ["Concentration is rising."], "Assess concentration risk.", 6,
        supplier_evidence=[{"supplier_name": "Supplier C", "is_incumbent": True}],
    )
    signal = r["answer"]["signal"]
    assert "share of category spend" in signal and "22.0" in signal


def test_specification_change_headline_mentions_specification_not_generic_spend():
    r = _run(
        {"category_annual_spend_usd": 1_150_000, "category_prior_annual_spend_usd": 1_000_000},
        ["A specification change coincided with the cost rise."], "Confirm whether the spec change explains it.", 7,
        extra_evidence={"specification_changed": True, "specification_change_description": "New tolerance specification introduced."},
    )
    signal = r["answer"]["signal"]
    assert "specification" in signal.lower()


def test_spend_volume_headline_unchanged_no_regression():
    r = _run(
        {"category_annual_spend_usd": 1_180_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_300, "category_prior_annual_volume_units": 10_000},
        ["Spend is growing faster than volume."], "Investigate price-per-unit trend by SKU.", 8,
    )
    assert r["answer"]["signal"] == "Category spend is growing faster than volume (+18.0% spend vs +3.0% volume)."


# ---------------------------------------------------------------------
# Critical #3: materiality is evidence-driven, not a "risk" keyword match
# ---------------------------------------------------------------------

def test_otif_materiality_states_real_magnitude_and_admits_unquantified_impact():
    r = _run({}, ["OTIF dropped."], "Investigate.", 9,
             supplier_evidence=[{"supplier_name": "Supplier A", "is_incumbent": True, "otif_percent": 81.0, "prior_otif_percent": 96.0}])
    risk = r["answer"]["commercial_risk"]
    assert len(risk) == 1
    assert "15.0 percentage-point" in risk[0]
    assert "has not been quantified" in risk[0]


def test_materiality_never_empty_purely_because_insight_text_lacked_the_word_risk():
    """The exact audit finding: a genuinely material spend/volume
    divergence used to produce an empty commercial_risk simply because
    the model's insight text didn't contain the literal word "risk"."""
    r = _run(
        {"category_annual_spend_usd": 1_180_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_300, "category_prior_annual_volume_units": 10_000},
        ["Spend is growing faster than volume."], "Investigate price-per-unit trend by SKU.", 10,
    )
    assert r["answer"]["commercial_risk"] != []


def test_materiality_does_not_manufacture_urgency_for_a_genuinely_weak_signal():
    r = _run(
        {"category_annual_spend_usd": 1_005_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_050, "category_prior_annual_volume_units": 10_000},
        ["Normal variation."], "No action needed.", 11,
    )
    risk = r["answer"]["commercial_risk"]
    assert risk == ["Potentially material, but current evidence is insufficient to establish impact."]


# ---------------------------------------------------------------------
# Stability
# ---------------------------------------------------------------------

def test_otif_signal_stable_across_three_runs():
    def run(suffix):
        return _run({}, ["OTIF dropped."], "Investigate.", suffix,
                     supplier_evidence=[{"supplier_name": "Supplier A", "is_incumbent": True, "otif_percent": 81.0, "prior_otif_percent": 96.0}])["answer"]
    r1, r2, r3 = run(12), run(13), run(14)
    assert r1 == r2 == r3
