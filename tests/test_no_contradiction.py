"""
Quality Gate Guarantee #3 — No Internal Contradiction Guarantee.

Direct fix for the confirmed Case 5 finding: "Financial Impact: Not
calculable" appeared in the same response as a real, guaranteed
$4,345,200 figure computed two sections later. Locks in the exact real
reconstruction, the honest negative case, and a real deliberate-break
proof of the retry mechanism.
"""
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor, FinancialImpact
from app.pipeline.contradiction_check import check_all_contradictions
from tests._async_test_helpers import poll_until_terminal

import os
os.environ.setdefault("DATABASE_URL", "host=localhost dbname=vendoredge_test user=vendoredge_app password=apppass")

client = TestClient(app)
_CONF = Confidence(
    level="medium",
    factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
    derivation_note="n",
)


def test_exact_real_case_5_contradiction_is_detected():
    position = CommercialPosition(
        recommendation="Reject FerroSteel increase.", commercial_insights=["a"],
        financial_impact=FinancialImpact(
            annual_spend_usd=25_560_000.0, requested_change_percent=17.0,
            potential_annual_impact_usd=4_345_200.0, note="...",
        ),
        reasoning="Financial Impact: Not calculable from evidence given.",
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    contradictions = check_all_contradictions(position)
    assert len(contradictions) > 0
    assert "4,345,200" in contradictions[0]


def test_genuinely_honest_not_calculable_is_never_flagged():
    """The negative case: no guaranteed figure exists, so the claim is
    true, not contradictory. Must never be a false positive."""
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        financial_impact=None,
        reasoning="Financial impact is not calculable from evidence given.",
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    assert check_all_contradictions(position) == []


def test_populated_scenario_table_without_headline_figure_is_also_caught():
    """The second, related pattern: real scenarios exist but the prose
    still claims nothing could be calculated."""
    from app.models import FinancialScenario
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        financial_scenarios=[
            FinancialScenario(scenario="Accept 17%", annual_spend="$29.9M", vs_baseline="+$4.3M"),
        ],
        reasoning="No financial impact could be determined from the evidence given.",
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    contradictions = check_all_contradictions(position)
    assert len(contradictions) > 0


def test_deliberate_break_the_retry_mechanism_genuinely_fires_and_corrects():
    """
    MANDATORY deliberate-break proof. Simulates the exact real Case 5
    contradiction through the full live endpoint (mocked LLM calls, real
    DB, real retry logic) and proves: (1) the first attempt genuinely
    contains the contradiction, (2) a second call is genuinely made, and
    (3) the corrected response is the one actually returned.
    """
    org_res = client.post("/api/v1/workspaces").json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}

    first_attempt = CommercialPosition(
        recommendation="Reject increase.", commercial_insights=["a"],
        reasoning="Financial Impact: Not calculable from evidence given.",
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    second_attempt = CommercialPosition(
        recommendation="Reject increase.", commercial_insights=["a"],
        reasoning="The guaranteed calculation shows a real $4,345,200 annual impact if accepted.",
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    call_count = {"n": 0}

    def mock_generate(*args, **kwargs):
        call_count["n"] += 1
        return first_attempt if call_count["n"] == 1 else second_attempt

    with patch("app.routes.decisions.classify") as mock_classify, \
         patch("app.routes.decisions.generate_commercial_position", side_effect=mock_generate):
        mock_classify.return_value = {
            "content_type": "price_increase", "decision_type": "optimization",
            "constraint_satisfaction_signal": None,
            "extracted_evidence": {
                "current_price_or_terms": "$1,420/tonne", "requested_increase_percent": "17%",
                "suppliers_stated_justification": "x", "how_critical_is_this_supplier_relationship": "x",
            },
            "numeric_facts": {"unit_price_usd": 1420, "annual_volume_units": 18000},
        }
        r = client.post(
            "/api/v1/commercial-decisions",
            json={"raw_question": "FerroSteel $1,420/tonne, 18,000 tonnes, 17% increase requested."},
            headers=headers,
        )
        r = poll_until_terminal(client, headers, r.json()["id"])

    assert call_count["n"] == 2, "The retry must genuinely fire -- exactly one correction attempt"
    final_reasoning = r.json()["commercial_position"]["reasoning"]
    assert "not calculable" not in final_reasoning.lower(), (
        "The corrected response must be the one actually returned to the user"
    )
