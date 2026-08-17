"""
Regression tests for the removal of the STRESS_TEST_ORG_ID production
quota bypass. Production code must never contain an environment-controlled
path that can silently disable a customer usage limit. Validation runs now
use their own explicitly provisioned workspace with a higher limit.

Zero real LLM calls -- classify() and generate_commercial_position() are
mocked throughout.
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


def test_stress_test_env_var_cannot_loosen_another_org_limit():
    """A leftover stress-test environment variable must not affect quotas."""
    org_a = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "10.99.99.1"}).json()
    org_b = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "10.99.99.1"}).json()
    headers_b = {"x-org-id": org_b["organisation_id"], "x-user-id": org_b["user_id"]}

    # A legacy stress-test variable is deliberately ignored by production code.
    os.environ["STRESS_TEST_ORG_ID"] = org_a["organisation_id"]
    try:
        statuses = _create_n_decisions(headers_b, 4)
        assert statuses[:3] == [200, 200, 200]
        assert statuses[3] == 429
    finally:
        os.environ.pop("STRESS_TEST_ORG_ID", None)


def test_legacy_stress_test_flag_cannot_exceed_normal_limit():
    """Even the named org remains subject to the real customer limit."""
    org_res = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "10.99.99.1"}).json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}

    os.environ["STRESS_TEST_ORG_ID"] = org_res["organisation_id"]
    try:
        statuses = _create_n_decisions(headers, 4)
        assert statuses[:3] == [200, 200, 200]
        assert statuses[3] == 429
    finally:
        os.environ.pop("STRESS_TEST_ORG_ID", None)


def test_quota_enforcement_remains_after_legacy_flag_is_removed():
    """Quota enforcement remains deterministic regardless of the old flag."""
    org_res = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "10.99.99.1"}).json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}

    os.environ["STRESS_TEST_ORG_ID"] = org_res["organisation_id"]
    _create_n_decisions(headers, 3)
    os.environ.pop("STRESS_TEST_ORG_ID", None)

    # This org already has 3 decisions this month; the 4th must be rejected.
    with patch("app.routes.decisions.classify", return_value=_MOCK_CLASSIFICATION), \
         patch("app.routes.decisions.generate_commercial_position", return_value=_MOCK_POSITION):
        r = client.post(
            "/api/v1/commercial-decisions",
            json={"raw_question": "One more, after the exemption is removed"},
            headers=headers,
        )
    assert r.status_code == 429
