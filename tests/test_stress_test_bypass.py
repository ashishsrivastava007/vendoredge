"""
Regression tests for the STRESS_TEST_ORG_ID escape hatch added for the
10-case manual validation exercise. The critical things proven here:
1. Without the env var set, the pilot limit works exactly as before --
   completely unaffected by this change.
2. With the env var set to a DIFFERENT org, that org's limit still
   applies -- the bypass does not leak to any org other than the one
   explicitly named.
3. With the env var set to MATCH the org under test, the bypass
   correctly allows more than 3 decisions.

Zero real LLM calls -- classify() and generate_commercial_position() are
mocked throughout, per the explicit no-real-API-calls-during-development
instruction. Only the deterministic count-and-compare logic is under
test here.
"""
import os
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor

client = TestClient(app)

_CONF = Confidence(
    level="medium",
    factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
    derivation_note="n",
)
_MOCK_POSITION = CommercialPosition(
    recommendation="x", commercial_insights=["a"], reasoning="...",
    confidence=_CONF, assumptions=["a"],
    disconfirming_condition="...", decision_type="optimization",
)
_MOCK_CLASSIFICATION = {
    "content_type": "price_increase", "decision_type": "optimization",
    "constraint_satisfaction_signal": None,
    "extracted_evidence": {
        "current_price_or_terms": "x", "requested_increase_percent": "10%",
        "suppliers_stated_justification": "x", "how_critical_is_this_supplier_relationship": "x",
    },
    "numeric_facts": {},
}


def _create_n_decisions(headers, n):
    """Creates n decisions for the given org, fully mocked, zero real
    API calls, returning the list of response status codes."""
    statuses = []
    with patch("app.routes.decisions.classify", return_value=_MOCK_CLASSIFICATION), \
         patch("app.routes.decisions.generate_commercial_position", return_value=_MOCK_POSITION):
        for i in range(n):
            r = client.post(
                "/api/v1/commercial-decisions",
                json={"raw_question": f"Test question number {i}"},
                headers=headers,
            )
            statuses.append(r.status_code)
    return statuses


def test_normal_org_still_blocked_at_the_real_limit_without_the_env_var():
    """The critical, most important test: with STRESS_TEST_ORG_ID unset
    (the real production state), a normal org still gets blocked exactly
    at its real limit -- completely unaffected by this change."""
    os.environ.pop("STRESS_TEST_ORG_ID", None)
    org_res = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "10.99.99.1"}).json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}

    # Default limit is 3 -- the 4th must be rejected.
    statuses = _create_n_decisions(headers, 4)
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429


def test_different_org_is_not_affected_by_another_orgs_stress_test_flag():
    """Critical isolation proof: setting STRESS_TEST_ORG_ID to one org
    must NOT loosen the limit for any OTHER org -- the bypass must be
    genuinely narrow, not a global toggle."""
    org_a = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "10.99.99.1"}).json()
    org_b = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "10.99.99.1"}).json()
    headers_b = {"x-org-id": org_b["organisation_id"], "x-user-id": org_b["user_id"]}

    # Stress-test mode is enabled, but for org A, not org B.
    os.environ["STRESS_TEST_ORG_ID"] = org_a["organisation_id"]
    try:
        statuses = _create_n_decisions(headers_b, 4)
        assert statuses[:3] == [200, 200, 200]
        assert statuses[3] == 429, "Org B must still be blocked at 3 -- the bypass leaked to an unnamed org"
    finally:
        os.environ.pop("STRESS_TEST_ORG_ID", None)


def test_named_stress_test_org_can_exceed_the_normal_limit():
    """The actual bypass working correctly, for the one org it's meant for."""
    org_res = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "10.99.99.1"}).json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}

    os.environ["STRESS_TEST_ORG_ID"] = org_res["organisation_id"]
    try:
        # 10 real cases for the stress test, well beyond the normal
        # limit of 3 -- every one should succeed.
        statuses = _create_n_decisions(headers, 10)
        assert all(s == 200 for s in statuses), f"Expected all 10 to succeed, got {statuses}"
    finally:
        os.environ.pop("STRESS_TEST_ORG_ID", None)


def test_removing_the_env_var_restores_normal_enforcement_for_the_same_org():
    """Proves the bypass is genuinely reversible -- once the env var is
    unset, even the previously-exempted org goes back to normal
    enforcement, not permanently grandfathered in."""
    org_res = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "10.99.99.1"}).json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}

    os.environ["STRESS_TEST_ORG_ID"] = org_res["organisation_id"]
    _create_n_decisions(headers, 3)  # use up the normal limit while exempted
    os.environ.pop("STRESS_TEST_ORG_ID", None)  # turn the exemption off

    # This org already has 3 decisions this month; without the exemption,
    # the 4th must now be correctly rejected again.
    with patch("app.routes.decisions.classify", return_value=_MOCK_CLASSIFICATION), \
         patch("app.routes.decisions.generate_commercial_position", return_value=_MOCK_POSITION):
        r = client.post(
            "/api/v1/commercial-decisions",
            json={"raw_question": "One more, after the exemption is removed"},
            headers=headers,
        )
    assert r.status_code == 429
