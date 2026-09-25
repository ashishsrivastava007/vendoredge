"""
R48 Signal Engine -- final structural fixes: evidence sufficiency
(ACT_NOW/INVESTIGATE/WATCH), decision-relevant uncertainty (not
catalogue-dependent), and a generalized impact representation
replacing the borrowed scenario_annual_impact mechanism.
"""
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor

client = TestClient(app)
_CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _run(numeric_facts, insights, recommendation, suffix, supplier_evidence=None, extra_evidence=None):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"11.040.{suffix}.1"}).json()
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


def test_dominant_explanation_resolved_yields_act_now_despite_residual_unknowns():
    """The exact case that motivated this pass: price is established,
    spec change ruled out -- mix-shift and generic hypotheses remain
    honestly UNKNOWN in the list, but must not force investigation
    work since nothing decision-relevant remains open."""
    a = _run(
        {"category_annual_spend_usd": 1_180_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_000, "category_prior_annual_volume_units": 10_000},
        ["Price clearly rose; no spec change reported."], "Proceed to negotiate.", 1,
    )
    assert a["decision_state"] == "ACT_NOW"
    assert "sufficient to act" in a["first_investigation"]
    assert any(h["status"] == "UNKNOWN" for h in a["hypotheses"])  # residuals still honestly represented


def test_unresolved_material_dimension_yields_investigate():
    a = _run({}, ["OTIF collapsed."], "Investigate root cause.", 2,
             supplier_evidence=[{"supplier_name": "S2", "is_incumbent": True, "otif_percent": 40.0, "prior_otif_percent": 95.0}])
    assert a["decision_state"] == "INVESTIGATE"


def test_weak_signal_yields_watch_not_act_now_or_investigate():
    a = _run(
        {"category_annual_spend_usd": 1_005_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_050, "category_prior_annual_volume_units": 10_000},
        ["Normal variation."], "No action needed.", 3,
    )
    assert a["decision_state"] == "WATCH"
    assert "sufficient to act" not in a["first_investigation"]


def test_material_contradiction_forces_investigate_even_with_no_other_open_hypothesis():
    """The bug found and fixed during the stress test: a real price-
    claim-vs-calculation conflict was being missed because materiality
    was checked via the narrow spend-vs-volume gate rather than the
    contradiction's own real calculated magnitude."""
    a = _run(
        {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 12_000, "category_prior_annual_volume_units": 10_000},
        ["a"], "Reconcile.", 4,
        extra_evidence={"suppliers_stated_justification": "The supplier insists their price increased significantly."},
    )
    assert a["decision_state"] == "INVESTIGATE"
    assert len(a["contradictions"]) == 1


def test_resolved_dimension_does_not_reintroduce_investigation_when_a_separate_dimension_needs_it():
    """Multiple unknowns, only one decision-relevant: price is
    explained; OTIF is separate, unresolved, and material. The engine
    must investigate OTIF, not re-litigate the already-explained price."""
    a = _run(
        {"category_annual_spend_usd": 1_180_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_000, "category_prior_annual_volume_units": 10_000},
        ["Price rose (explained); OTIF also collapsed separately."], "Proceed on price; investigate OTIF separately.", 5,
        supplier_evidence=[{"supplier_name": "S5", "is_incumbent": True, "otif_percent": 45.0, "prior_otif_percent": 95.0}],
    )
    assert a["decision_state"] == "INVESTIGATE"
    assert "otif" in a["first_investigation"].lower()


def test_generalized_impact_activates_from_spend_evidence_alone_no_requested_change_percent():
    """The document's exact example: 'Annual spend is EUR 4.2M and
    spend increased 18%' should be understood as meaningful financial
    exposure without any requested_change_percent field."""
    a = _run(
        {"category_annual_spend_usd": 4_200_000, "category_prior_annual_spend_usd": 3_559_322, "category_annual_volume_units": 10_300, "category_prior_annual_volume_units": 10_000},
        ["Large spend base."], "Investigate.", 6,
    )
    assert "dollar impact" in a["commercial_risk"][0].lower() or "calculated dollar" in a["commercial_risk"][0].lower()


def test_large_operational_deterioration_investigated_even_with_zero_financial_data():
    """Impact must not depend on a dollar figure existing -- a large
    OTIF collapse with no spend data at all must still investigate."""
    a = _run({}, ["OTIF collapsed, no spend data available."], "Investigate.", 7,
             supplier_evidence=[{"supplier_name": "S7", "is_incumbent": True, "otif_percent": 35.0, "prior_otif_percent": 96.0}])
    assert a["decision_state"] == "INVESTIGATE"


def test_decision_state_stable_across_three_runs():
    def run(suffix):
        return _run(
            {"category_annual_spend_usd": 1_180_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_000, "category_prior_annual_volume_units": 10_000},
            ["Price clearly rose; no spec change reported."], "Proceed to negotiate.", suffix,
        )
    r1, r2, r3 = run(8), run(9), run(10)
    assert r1 == r2 == r3
    assert r1["decision_state"] == "ACT_NOW"
