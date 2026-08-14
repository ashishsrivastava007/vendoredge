"""
Quality Gate Guarantee #4 — Evidence → Claim Integrity Gate.

Direct fix for the original Case 3 (BioSyn) concern: "qualified" must
never be used for a supplier whose real, structured qualification_status
is genuinely "in_progress" or "not_started." Now checkable
deterministically because Guarantee #2 made qualification_status a real
field, not free text to parse after the fact.
"""
import os
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.claim_integrity import check_qualification_overstatement
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence, SupplierEvidence,
)
from tests._async_test_helpers import poll_until_terminal

client = TestClient(app)
_CONF = Confidence(
    level="medium",
    factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
    derivation_note="n",
)


def _make_normalized(supplier: SupplierEvidence) -> NormalizedEvidence:
    return NormalizedEvidence(
        content_type="price_increase", common=CommonEvidence(),
        case=PriceIncreaseEvidence(), derived=DerivedEvidence(),
        suppliers=[supplier],
    )


def test_exact_biosyn_overstatement_is_caught():
    normalized = _make_normalized(
        SupplierEvidence(supplier_name="BioSyn", qualification_status="in_progress", qualification_percent=70)
    )
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        reasoning="BioSyn is a qualified supplier and can take over volume immediately.",
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    issues = check_qualification_overstatement(position, normalized)
    assert len(issues) == 1
    assert "70" in issues[0]


def test_honestly_hedged_language_is_never_flagged():
    normalized = _make_normalized(
        SupplierEvidence(supplier_name="BioSyn", qualification_status="in_progress", qualification_percent=70)
    )
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        reasoning="BioSyn is 70% through qualification, still in progress, not yet complete.",
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    assert check_qualification_overstatement(position, normalized) == []


def test_genuinely_complete_qualification_may_correctly_be_called_qualified():
    """The other honest boundary: a real, complete qualification is
    correctly allowed to use the word -- this must never over-trigger."""
    normalized = _make_normalized(
        SupplierEvidence(supplier_name="Acme", qualification_status="complete")
    )
    position = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        reasoning="Acme is a qualified supplier with a full track record.",
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    assert check_qualification_overstatement(position, normalized) == []


def test_deliberate_break_the_retry_genuinely_fires_and_corrects():
    """
    MANDATORY deliberate-break proof. Runs the exact real BioSyn scenario
    through the full live endpoint (mocked LLM, real DB, real retry
    logic) and proves the corrected response -- not the overstated one --
    is what actually gets returned.
    """
    org_res = client.post("/api/v1/workspaces").json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}

    first_attempt = CommercialPosition(
        recommendation="Use BioSyn as leverage.", commercial_insights=["a"],
        reasoning="BioSyn is a qualified supplier that can take over volume immediately.",
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    second_attempt = CommercialPosition(
        recommendation="Use BioSyn as leverage.", commercial_insights=["a"],
        reasoning="BioSyn is 70% through qualification, still in progress, not yet complete.",
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
                "current_price_or_terms": "$128/kg",
                "suppliers_stated_justification": "x", "how_critical_is_this_supplier_relationship": "x",
            },
            "numeric_facts": {"requested_change_percent": 16.0},
            "supplier_specific_evidence": [
                {"supplier_name": "BioSyn", "qualification_status": "in_progress", "qualification_percent": 70},
            ],
        }
        r = client.post(
            "/api/v1/commercial-decisions",
            json={"raw_question": "PharmaChem requests 16pct increase, BioSyn alternative available."},
            headers=headers,
        )
        decision_id = r.json()["id"]
        r = poll_until_terminal(client, headers, decision_id)

    assert call_count["n"] == 2, "The retry must genuinely fire -- exactly one correction attempt"
    final_reasoning = r.json()["commercial_position"]["reasoning"]
    assert "is a qualified supplier" not in final_reasoning.lower(), (
        "The corrected response must be the one actually returned to the user"
    )
    assert "in progress" in final_reasoning.lower()


def test_supplier_data_survives_a_followup_respond_call():
    """
    Regression test for the real ordering bug found and fixed while
    building this guarantee: per-supplier evidence must survive into a
    /respond follow-up, not be silently lost because of when it gets
    stripped from the stored dict relative to when it's saved.
    """
    org_res = client.post("/api/v1/workspaces").json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}

    with patch("app.routes.decisions.classify") as mock_classify:
        mock_classify.return_value = {
            "content_type": "price_increase", "decision_type": "optimization",
            "constraint_satisfaction_signal": None,
            "extracted_evidence": {"current_price_or_terms": "$128/kg"},
            "numeric_facts": {"requested_change_percent": 16.0},
            "supplier_specific_evidence": [
                {"supplier_name": "BioSyn", "qualification_status": "in_progress", "qualification_percent": 70},
            ],
        }
        r = client.post(
            "/api/v1/commercial-decisions",
            json={"raw_question": "PharmaChem requests 16pct increase."},
            headers=headers,
        )
    decision_id = r.json()["id"]
    missing = [m["field"] for m in (r.json().get("missing_inputs_requested") or [])]
    assert missing, "Case should still be awaiting the remaining required fields"

    mock_position = CommercialPosition(
        recommendation="x", commercial_insights=["a"], reasoning="x",
        confidence=_CONF, assumptions=["a"],
        disconfirming_condition="...", decision_type="optimization",
    )
    with patch("app.routes.decisions.generate_commercial_position", return_value=mock_position):
        r2 = client.post(
            f"/api/v1/commercial-decisions/{decision_id}/respond",
            json={"user_supplied_inputs": {f: "answer" for f in missing}},
            headers=headers,
        )
        r2 = poll_until_terminal(client, headers, decision_id)
    assert r2.json()["status"] == "completed"

    # The real, direct proof: query the actual stored evidence and
    # confirm the supplier data genuinely survived the /respond
    # round-trip -- not just that the request didn't crash.
    from app.database import get_org_scoped_connection
    with get_org_scoped_connection(org_res["organisation_id"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_supplied_inputs FROM commercial_decisions WHERE id = %s",
                (decision_id,),
            )
            stored = cur.fetchone()["user_supplied_inputs"]
    assert "__supplier_specific_evidence__" in stored, (
        "Supplier evidence was lost during /respond -- the exact ordering "
        "bug found and fixed while building this guarantee has regressed."
    )
    assert stored["__supplier_specific_evidence__"][0]["supplier_name"] == "BioSyn"
