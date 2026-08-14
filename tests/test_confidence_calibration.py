"""
Permanent regression tests for outcome-based confidence calibration
(Phase 3 of the gap-closing roadmap). The critical things being tested:
1. The minimum-sample-size gate -- no statistic shown until there's
   genuinely enough real data, same honesty discipline as supplier memory.
2. The math is genuinely correct, not approximate.
3. Tenant isolation is respected -- this queries decision_feedback broadly
   within RLS, and that boundary must be proven, not assumed.

These require a live database connection (uses the real RLS-enforced
connection helper), same as test_tenant_isolation.py.
"""
import os
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.routes.decisions import _compute_confidence_calibration

client = TestClient(app)


def _record_outcome(headers, verdict):
    with patch("app.routes.decisions.classify") as mock_classify, \
         patch("app.routes.decisions.generate_commercial_position") as mock_reason:
        mock_classify.return_value = {
            "content_type": "price_increase", "decision_type": "optimization",
            "constraint_satisfaction_signal": None,
            "extracted_evidence": {
                "current_price_or_terms": "x", "requested_increase_percent": "x",
                "suppliers_stated_justification": "x",
                "how_critical_is_this_supplier_relationship": "x",
            },
            "numeric_facts": {},
        }
        mock_reason.return_value = CommercialPosition(
            recommendation="x", commercial_insights=["test"], reasoning="...",
            confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")], derivation_note="n"),
            assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
        )
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "test case"}, headers=headers)
    decision_id = r.json()["id"]
    client.post(f"/api/v1/commercial-decisions/{decision_id}/feedback", json={
        "decision_alignment": "followed", "outcome_description": "test outcome",
        "validation_verdict": verdict,
    }, headers=headers)


def test_below_minimum_sample_size_returns_none():
    org_res = client.post("/api/v1/workspaces").json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}
    _record_outcome(headers, "reasoning_held")
    _record_outcome(headers, "reasoning_held")  # only 2, below the real threshold of 3
    result = _compute_confidence_calibration(org_res["organisation_id"])
    assert result is None


def test_at_minimum_sample_size_computes_correctly():
    org_res = client.post("/api/v1/workspaces").json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}
    _record_outcome(headers, "reasoning_held")
    _record_outcome(headers, "reasoning_held")
    _record_outcome(headers, "reasoning_wrong_bad_assumption")
    result = _compute_confidence_calibration(org_res["organisation_id"])
    assert result is not None
    assert "3" in result and "2" in result and "67%" in result


def test_calibration_respects_tenant_isolation():
    """Critical security test: a second, unrelated organization must never
    see another org's recorded outcomes in its own calibration -- proven
    directly here, not assumed from the general RLS tests elsewhere."""
    org_a = client.post("/api/v1/workspaces").json()
    headers_a = {"x-org-id": org_a["organisation_id"], "x-user-id": org_a["user_id"]}
    for verdict in ["reasoning_held", "reasoning_held", "reasoning_held"]:
        _record_outcome(headers_a, verdict)

    org_b = client.post("/api/v1/workspaces").json()
    result_b = _compute_confidence_calibration(org_b["organisation_id"])
    assert result_b is None, "Org B must see its own (zero) outcomes, never Org A's real data"
