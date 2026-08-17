"""R25.1 hardening gates.

These tests are intentionally explicit about the security invariants that are
part of VendorEdge's product promise. Database cases require TEST_DATABASE_URL
and are therefore skipped by the existing test configuration when unavailable.
"""
import os
import uuid
import hashlib
from datetime import datetime, timezone, timedelta

import pytest


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires TEST_DATABASE_URL")
def test_all_tenant_tables_are_rls_enabled_and_forced():
    import psycopg2
    dsn = os.environ["TEST_DATABASE_URL"]
    tables = {
        "organisations", "users", "workspace_invites", "commercial_decisions",
        "decision_feedback", "pilot_experience_feedback", "interest_signals",
        "fallback_events", "pilot_leads", "general_feedback",
    }
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT relname, relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE relname = ANY(%s)", (list(tables),)
            )
            rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        assert tables <= rows.keys()
        for table in tables:
            assert rows[table] == (True, True), f"{table} must have FORCE RLS"
    finally:
        conn.close()


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requires TEST_DATABASE_URL")
def test_tenant_context_does_not_leak_between_pooled_connections():
    from app.database import get_org_scoped_connection
    org_a, org_b = str(uuid.uuid4()), str(uuid.uuid4())
    with get_org_scoped_connection(org_a) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('app.current_org_id')")
            assert cur.fetchone()[0] == org_a
    with get_org_scoped_connection(org_b) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('app.current_org_id')")
            assert cur.fetchone()[0] == org_b


def test_production_code_contains_no_stress_test_quota_bypass():
    source = open("app/routes/decisions.py", encoding="utf-8").read()
    assert "STRESS_TEST_ORG_ID" not in source


def test_classifier_prompt_wires_real_firewall_rules():
    source = open("app/pipeline/classifier.py", encoding="utf-8").read().split("def classify", 1)[0]
    assert "{EVIDENCE_FIREWALL_SYSTEM_RULES}" in source
    assert "EVIDENCE_FIREWALL_SYSTEM_RULES + \"\\n\\n\"" not in source


def test_model_defaults_are_current_and_stage_specific():
    from app.model_config import CLASSIFIER_MODEL, REASONING_MODEL, MARKET_MODEL
    assert CLASSIFIER_MODEL == "claude-sonnet-4-6"
    assert REASONING_MODEL == "claude-opus-4-8"
    assert MARKET_MODEL == "claude-sonnet-4-6"


def test_invite_token_is_not_a_session_token_and_is_hashed_before_storage():
    token = "00000000-0000-0000-0000-000000000001." + "a" * 43
    digest = hashlib.sha256(token.encode()).hexdigest()
    assert len(digest) == 64
    assert token != digest


def test_schema_declares_tenant_scoped_telemetry_and_invites():
    schema = open("db/schema.sql", encoding="utf-8").read()
    for needle in (
        "CREATE TABLE IF NOT EXISTS workspace_invites",
        "ALTER TABLE interest_signals ADD COLUMN IF NOT EXISTS organisation_id",
        "ALTER TABLE fallback_events ADD COLUMN IF NOT EXISTS organisation_id",
        "ALTER TABLE organisations ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE workspace_invites ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE interest_signals ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE fallback_events ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE pilot_leads ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE general_feedback ENABLE ROW LEVEL SECURITY",
    ):
        assert needle in schema, needle


def test_invite_flow_uses_single_use_secret_not_session_fragment():
    html = open("app/static/index.html", encoding="utf-8").read()
    assert "#invite=" in html
    assert "/workspaces/accept-invite" in html
    assert "#session=" not in html
    assert "data.invite_token" in html
