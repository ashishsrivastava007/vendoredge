"""
Test INFRA-01 / INFRA-02 from VE-503A, now real code — not a described test case.
This test exists specifically because the bug it checks for was found via live
testing during MVP build: connecting as a Postgres superuser silently bypasses
Row-Level Security, even when the policy is written correctly. This must run
in CI on every single change that touches the schema or connection setup —
per the Definition of Done (Session 11), a Tier 1 test failure blocks
everything else, no exceptions.

Requires a real Postgres test database with the schema loaded, and a
non-superuser `vendoredge_app` role created per db/schema.sql's instructions.
Set TEST_DATABASE_URL to point at it before running.
"""
import os
import uuid
import psycopg2
import pytest

TEST_DSN = os.environ.get("TEST_DATABASE_URL")


def _connect():
    return psycopg2.connect(TEST_DSN)


@pytest.fixture
def two_orgs_with_data():
    org_a = str(uuid.uuid4())
    org_b = str(uuid.uuid4())
    user_a = str(uuid.uuid4())
    marker = f"SECRET-{uuid.uuid4()}"

    conn = _connect()
    with conn.cursor() as cur:
        # organisations itself is RLS-protected (org_isolation_organisations),
        # and its policy has no separate WITH CHECK, so Postgres defaults the
        # WITH CHECK to the same USING expression: id = current_setting(...).
        # A brand-new org can only ever satisfy that check if the session's
        # tenant context is already set to that exact org's own (pre-generated)
        # id before the row is inserted -- this is the same pattern the real
        # app already uses correctly in app/routes/decisions.py's workspace
        # creation route. Each org must be created under its own context.
        cur.execute("SET app.current_org_id = %s", (org_a,))
        cur.execute("INSERT INTO organisations (id, name) VALUES (%s, 'Org A')", (org_a,))
        cur.execute(
            "INSERT INTO users (id, organisation_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
            (user_a, org_a, "a@test.com"),
        )
        cur.execute(
            "INSERT INTO commercial_decisions (organisation_id, created_by_user_id, raw_question) "
            "VALUES (%s, %s, %s)",
            (org_a, user_a, marker),
        )
        cur.execute("SET app.current_org_id = %s", (org_b,))
        cur.execute("INSERT INTO organisations (id, name) VALUES (%s, 'Org B')", (org_b,))
    conn.commit()
    yield {"org_a": org_a, "org_b": org_b, "marker": marker}
    # Cleanup -- each org's rows can only be deleted under that org's own
    # context, since org_isolation_organisations restricts DELETE the same
    # way it restricts INSERT and SELECT.
    with conn.cursor() as cur:
        cur.execute("SET app.current_org_id = %s", (org_a,))
        cur.execute("DELETE FROM commercial_decisions WHERE raw_question = %s", (marker,))
        cur.execute("DELETE FROM users WHERE id = %s", (user_a,))
        cur.execute("DELETE FROM organisations WHERE id = %s", (org_a,))
        cur.execute("SET app.current_org_id = %s", (org_b,))
        cur.execute("DELETE FROM organisations WHERE id = %s", (org_b,))
    conn.commit()
    conn.close()


def test_infra01_org_b_cannot_see_org_a_data(two_orgs_with_data):
    """THE single most important test in this whole codebase. If this fails,
    nothing else matters until it's fixed."""
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("SET app.current_org_id = %s", (two_orgs_with_data["org_b"],))
        cur.execute(
            "SELECT count(*) FROM commercial_decisions WHERE raw_question = %s",
            (two_orgs_with_data["marker"],),
        )
        count = cur.fetchone()[0]
    conn.close()
    assert count == 0, (
        "CRITICAL SECURITY FAILURE: Organisation B could see Organisation A's "
        "private data. Do not deploy until this passes."
    )


def test_infra01_org_a_can_still_see_its_own_data(two_orgs_with_data):
    """Confirms the fix didn't accidentally break legitimate access too."""
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("SET app.current_org_id = %s", (two_orgs_with_data["org_a"],))
        cur.execute(
            "SELECT count(*) FROM commercial_decisions WHERE raw_question = %s",
            (two_orgs_with_data["marker"],),
        )
        count = cur.fetchone()[0]
    conn.close()
    assert count == 1


def test_infra02_rls_is_actually_enabled_and_forced_on_tenant_tables():
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname IN ('users', 'commercial_decisions')"
        )
        rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    conn.close()
    for table in ("users", "commercial_decisions"):
        rls_enabled, rls_forced = rows[table]
        assert rls_enabled, f"{table}: RLS is not enabled at all"
        assert rls_forced, f"{table}: RLS is enabled but NOT forced — superuser/owner bypass risk"
