"""
Real, end-to-end integration test for the evidence-gate text-backfill fix.

This is DISTINCT from test_financial_fallback.py's unit tests: those prove
the raw text-extraction functions work correctly in isolation. This proves
something different and more specific -- that the evidence-gate itself
(which checks `extracted_evidence`, separate from `numeric_facts`) no
longer re-asks for a figure that was already clearly stated, using the
exact real case where this was found live.

The real, important distinction this test guards: an earlier fix only
backfilled `numeric_facts` (used for the final calculation), inside
`_run_reasoning`, which only runs AFTER the evidence-gate has already
passed. That fix never touched `extracted_evidence` (the TEXT the
evidence-gate actually checks), so the evidence-gate kept re-asking for
price and percentage even after the calculation-side fix shipped. This
test locks in the real fix: backfilling BOTH, at the earliest point,
before the evidence-gate ever runs.
"""
import os
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from tests._async_test_helpers import poll_until_terminal

client = TestClient(app)

_REAL_MERIDIAN_QUESTION = (
    "Our supplier, Meridian Components, has requested a 9% price increase "
    "on precision fasteners, citing rising steel costs. Current annual "
    "spend is $850,000. They have been a reliable supplier for 4 years "
    "with no major quality issues. Should we accept this increase, and "
    "what should our negotiation position be?"
)


def test_evidence_gate_does_not_reask_for_the_exact_real_meridian_case():
    """The exact real case, and the exact real classifier miss, from the
    live screenshot where this was found -- extracted_evidence is missing
    both price and percentage, exactly as it was live."""
    org_res = client.post("/api/v1/workspaces").json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}

    conf = Confidence(
        level="medium",
        factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
        derivation_note="n",
    )
    mock_position = CommercialPosition(
        recommendation="x", commercial_insights=["a"], reasoning="...",
        confidence=conf, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )

    with patch("app.routes.decisions.classify") as mock_classify, \
         patch("app.routes.decisions.generate_commercial_position", return_value=mock_position):
        mock_classify.return_value = {
            "content_type": "price_increase", "decision_type": "optimization",
            "constraint_satisfaction_signal": None,
            "extracted_evidence": {
                "supplier_name": "Meridian Components",
                "suppliers_stated_justification": "rising steel costs",
                "how_critical_is_this_supplier_relationship": "reliable supplier for 4 years with no major quality issues",
            },
            "numeric_facts": {},
        }
        response = client.post(
            "/api/v1/commercial-decisions",
            json={"raw_question": _REAL_MERIDIAN_QUESTION},
            headers=headers,
        )
        decision_id = response.json()["id"]
        response = poll_until_terminal(client, headers, decision_id)

    data = response.json()

    # The real bug: these must NOT be in the missing list.
    missing_fields = [m["field"] for m in (data.get("missing_inputs_requested") or [])]
    assert "current_price_or_terms" not in missing_fields
    assert "requested_increase_percent" not in missing_fields

    # The case should complete fully in one step, not stall on data that
    # was already given.
    assert data["status"] == "completed"

    # And the real numbers must have genuinely reached the guaranteed
    # calculation, not just been silently accepted as text.
    fi = data["commercial_position"]["financial_impact"]
    assert fi["annual_spend_usd"] == 850_000.0
    assert fi["requested_change_percent"] == 9.0
    assert fi["potential_annual_impact_usd"] == 76_500.0
