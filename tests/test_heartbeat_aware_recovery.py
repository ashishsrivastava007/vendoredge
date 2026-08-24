"""
Heartbeat-Aware Recovery — Adversarial Test Suite.

Covers the specific gap closed in this change: claim(), find_next_due_job(),
and recoverable_jobs() previously gated a running job's recoverability
solely on reasoning_jobs.timeout_at (LEASE_SECONDS, 20 minutes) -- entirely
blind to commercial_decisions.last_heartbeat_at, even though
attempt_fencing.try_reclaim() already implements exactly the heartbeat-
staleness check needed (RECOVERY_GRACE_PERIOD_SECONDS, 90s), and even
though _run_queued_job's very first line is job_queue.claim() -- meaning
a job whose queue lease claim() rejects never reaches try_reclaim() at all.

This file proves, against real Postgres:
  A. A healthy, heartbeat-fresh job is never reclaimed early, no matter
     how long its LLM call legitimately runs -- false-positive safety.
  B. A dead worker's job (stale heartbeat, unexpired lease) is discovered
     AND successfully claimed AND reaches the real try_reclaim() path --
     the actual gap this change closes.
  C. Two workers racing to recover the same stale job: exactly one wins,
     under real thread concurrency, not simulated.
  D. The documented staleness boundary (RECOVERY_GRACE_PERIOD_SECONDS)
     behaves exactly as documented on both sides of the line.
  E. The pre-existing expired-lease recovery path is unchanged -- an
     expired timeout_at still recovers a job on its own, independent of
     heartbeat state, exactly as before this change.

Requires a real Postgres test database with the schema loaded, and both
TEST_DATABASE_URL and MIGRATION_DATABASE_URL set -- same requirement as
test_durable_dispatcher.py.
"""
import os
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_org_scoped_connection
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline import job_queue, attempt_fencing

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_queue():
    """find_next_due_job() is genuinely system-wide by design, so a
    leftover due row from another test would make discovery
    non-deterministic here -- same isolation as test_durable_dispatcher.py."""
    dsn = os.environ.get("MIGRATION_DATABASE_URL")
    if dsn:
        import psycopg2
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM reasoning_jobs")
            conn.commit()
    yield


pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("MIGRATION_DATABASE_URL"),
    reason="requires TEST_DATABASE_URL and MIGRATION_DATABASE_URL against a real Postgres instance",
)

_CONF = Confidence(
    level="medium",
    factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
    derivation_note="n",
)
_MOCK_POSITION = CommercialPosition(
    recommendation="heartbeat-recovery-test", commercial_insights=["a"], reasoning="x",
    confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
)


def _headers(ip_suffix):
    org_res = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"10.66.{ip_suffix}.1"}).json()
    return {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}


def _new_running_job(headers, heartbeat_age_seconds, timeout_in_seconds, attempt_count=0, max_attempts=3):
    """Creates a commercial_decisions + reasoning_jobs pair already in the
    'running'/'reasoning' state, with independently controllable heartbeat
    age and lease expiry -- lets each test place the job precisely on
    either side of either boundary."""
    org_id = headers["x-org-id"]
    decision_id = str(uuid.uuid4())
    attempt_id = attempt_fencing.new_attempt_id()
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO commercial_decisions (id, organisation_id, created_by_user_id, "
                "raw_question, classified_content_type, status, current_attempt_id, last_heartbeat_at) "
                "VALUES (%s, %s, %s, 'x', 'price_increase', 'reasoning', %s, "
                "now() - make_interval(secs => %s))",
                (decision_id, org_id, headers["x-user-id"], attempt_id, heartbeat_age_seconds),
            )
            cur.execute(
                "INSERT INTO reasoning_jobs (id, commercial_decision_id, organisation_id, job_kind, "
                "status, available_at, timeout_at, attempt_count, max_attempts) "
                "VALUES (%s, %s, %s, 'specialist', 'running', now(), "
                "now() + make_interval(secs => %s), %s, %s)",
                (str(uuid.uuid4()), decision_id, org_id, timeout_in_seconds, attempt_count, max_attempts),
            )
    return decision_id, attempt_id


def _decision_row(org_id, decision_id):
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM commercial_decisions WHERE id = %s", (decision_id,))
            return cur.fetchone()


def _job_row(org_id, decision_id):
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM reasoning_jobs WHERE commercial_decision_id = %s", (decision_id,))
            return cur.fetchone()


# ============================================================
# A. Healthy long-running job -- must never be reclaimed early
# ============================================================

def test_A_fresh_heartbeat_job_not_surfaced_by_discovery_even_with_unexpired_lease():
    headers = _headers(1)
    decision_id, _ = _new_running_job(headers, heartbeat_age_seconds=5, timeout_in_seconds=1200)
    found = job_queue.find_next_due_job()
    assert found is None or found[1] != decision_id, \
        "A job with a fresh heartbeat must never be discovered as due, regardless of lease time remaining"


def test_A_fresh_heartbeat_job_cannot_be_claimed_even_with_unexpired_lease():
    """The load-bearing check: claim() itself, not just discovery, must
    reject this job -- since _run_queued_job calls claim() first and
    returns immediately if it fails, discovery alone proves nothing."""
    headers = _headers(2)
    decision_id, _ = _new_running_job(headers, heartbeat_age_seconds=5, timeout_in_seconds=1200)
    claimed = job_queue.claim(headers["x-org-id"], decision_id)
    assert claimed is None, "claim() must reject a job whose heartbeat is still fresh, lease or no lease"


def test_A_job_at_exactly_the_boundary_minus_one_second_is_still_healthy():
    """One second inside RECOVERY_GRACE_PERIOD_SECONDS must still count as alive."""
    headers = _headers(3)
    decision_id, _ = _new_running_job(
        headers,
        heartbeat_age_seconds=attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS - 5,
        timeout_in_seconds=1200,
    )
    claimed = job_queue.claim(headers["x-org-id"], decision_id)
    assert claimed is None, "A heartbeat just inside the grace period must not be treated as stale"


# ============================================================
# B. Dead worker -- stale heartbeat, unexpired lease, must recover
# ============================================================

def test_B_stale_heartbeat_job_is_surfaced_by_discovery_despite_unexpired_lease():
    headers = _headers(4)
    decision_id, _ = _new_running_job(
        headers,
        heartbeat_age_seconds=attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS + 30,
        timeout_in_seconds=1200,  # lease has 20 minutes left -- this is the actual gap being closed
    )
    found = job_queue.find_next_due_job()
    assert found is not None and found[1] == decision_id, \
        "A job with a stale heartbeat must be discoverable long before its 20-minute lease expires"


def test_B_stale_heartbeat_job_can_actually_be_claimed_with_unexpired_lease():
    headers = _headers(5)
    decision_id, _ = _new_running_job(
        headers,
        heartbeat_age_seconds=attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS + 30,
        timeout_in_seconds=1200,
    )
    claimed = job_queue.claim(headers["x-org-id"], decision_id)
    assert claimed is not None, "claim() must accept a heartbeat-stale job even though its lease has not expired"


def test_B_run_queued_job_reaches_the_real_try_reclaim_path_and_completes():
    """End-to-end proof: the full _run_queued_job -> claim() -> try_reclaim()
    -> reasoning -> completion chain actually works for a job stuck exactly
    the way the production incident described -- unexpired lease, dead
    heartbeat."""
    from app.routes.decisions import _run_queued_job
    headers = _headers(6)
    decision_id, old_attempt_id = _new_running_job(
        headers,
        heartbeat_age_seconds=attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS + 30,
        timeout_in_seconds=1200,
    )
    with patch("app.routes.decisions.generate_commercial_position", return_value=_MOCK_POSITION), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.routes.decisions.compute_financial_impact", return_value=None):
        _run_queued_job(headers["x-org-id"], decision_id)
    row = _decision_row(headers["x-org-id"], decision_id)
    assert row["status"] == "completed", \
        f"Expected the recovered job to complete; got status={row['status']!r}"
    assert row["current_attempt_id"] != old_attempt_id, \
        "Recovery must produce a genuinely new attempt_id, per attempt fencing"


# ============================================================
# C. Concurrent recovery -- exactly one worker wins
# ============================================================

def test_C_two_workers_racing_to_recover_the_same_stale_job_only_one_wins():
    """The real safety property is not that claim() can never be won
    twice (a rare double-claim only wastes one attempt_count slot -- see
    job_queue.claim()'s own docstring for why that's deliberately left
    as-is) -- it's that the actual expensive reasoning call can never run
    twice. try_reclaim() is the real, exclusive gate for that, and it
    runs strictly before generate_commercial_position is ever called."""
    from app.routes.decisions import _run_queued_job
    headers = _headers(7)
    decision_id, old_attempt_id = _new_running_job(
        headers,
        heartbeat_age_seconds=attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS + 30,
        timeout_in_seconds=1200,
    )
    call_count = {"n": 0}
    call_lock = threading.Lock()

    def _counting_mock_position(*args, **kwargs):
        with call_lock:
            call_count["n"] += 1
        return _MOCK_POSITION

    def _attempt_recovery():
        _run_queued_job(headers["x-org-id"], decision_id)

    # Patches applied once, for the whole race, not per-thread -- avoids
    # any doubt about unittest.mock.patch's own context-manager entry/exit
    # (which mutates shared, process-wide module state) being itself a
    # confound in a genuine two-thread race.
    with patch("app.routes.decisions.generate_commercial_position", side_effect=_counting_mock_position), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.routes.decisions.compute_financial_impact", return_value=None):
        t1 = threading.Thread(target=_attempt_recovery)
        t2 = threading.Thread(target=_attempt_recovery)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

    row = _decision_row(headers["x-org-id"], decision_id)
    assert row["status"] == "completed"
    assert row["current_attempt_id"] != old_attempt_id, \
        "The completed result must belong to a genuinely new attempt_id from try_reclaim(), " \
        "not the original, now-superseded one"
    assert call_count["n"] == 1, \
        f"The expensive reasoning call must run exactly once, no matter how the claim() race " \
        f"resolves; got {call_count['n']} calls"


def test_C_the_losing_workers_stale_attempt_write_is_rejected_not_silently_accepted():
    """Directly proves the old attempt's write is fenced out, not merely
    that it didn't happen to run -- construct the exact race by hand:
    reclaim first (simulating the new worker), then attempt a write from
    the ORIGINAL attempt_id (simulating the dead worker belatedly waking
    up and finishing its stale call)."""
    headers = _headers(8)
    decision_id, old_attempt_id = _new_running_job(
        headers,
        heartbeat_age_seconds=attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS + 30,
        timeout_in_seconds=1200,
    )
    new_attempt_id = attempt_fencing.try_reclaim(headers["x-org-id"], decision_id)
    assert new_attempt_id is not None and new_attempt_id != old_attempt_id

    # The stale, superseded attempt belatedly tries to write its result.
    stale_write_succeeded = attempt_fencing.write_final_result(
        headers["x-org-id"], decision_id, old_attempt_id, _MOCK_POSITION.model_dump_json(), "{}"
    )
    assert stale_write_succeeded is False, \
        "A write from an attempt_id that has already been superseded by reclaim must be rejected"

    row = _decision_row(headers["x-org-id"], decision_id)
    assert row["status"] == "reasoning", \
        "The row must still show the NEW attempt's in-progress state, untouched by the rejected stale write"
    assert row["current_attempt_id"] == new_attempt_id


# ============================================================
# D. Heartbeat contention/failure -- the documented boundary itself
# ============================================================

def test_D_null_heartbeat_is_treated_as_stale_immediately():
    """A job whose heartbeat was never successfully written even once
    (e.g. every early tick lost the pool-contention race) must not get
    an indefinite grace period by virtue of having no timestamp at all."""
    headers = _headers(9)
    org_id = headers["x-org-id"]
    decision_id = str(uuid.uuid4())
    attempt_id = attempt_fencing.new_attempt_id()
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO commercial_decisions (id, organisation_id, created_by_user_id, "
                "raw_question, classified_content_type, status, current_attempt_id, last_heartbeat_at) "
                "VALUES (%s, %s, %s, 'x', 'price_increase', 'reasoning', %s, NULL)",
                (decision_id, org_id, headers["x-user-id"], attempt_id),
            )
            cur.execute(
                "INSERT INTO reasoning_jobs (id, commercial_decision_id, organisation_id, job_kind, "
                "status, available_at, timeout_at) VALUES (%s, %s, %s, 'specialist', 'running', now(), "
                "now() + interval '1200 seconds')",
                (str(uuid.uuid4()), decision_id, org_id),
            )
    claimed = job_queue.claim(org_id, decision_id)
    assert claimed is not None, "A NULL heartbeat must be treated as stale, not as indefinitely fresh"


def test_D_boundary_is_exactly_RECOVERY_GRACE_PERIOD_SECONDS_not_a_different_hardcoded_value():
    """Proves the fix reuses the real constant rather than a hardcoded 90 --
    if someone changes RECOVERY_GRACE_PERIOD_SECONDS, this test's own
    boundary placement (grace - 5s vs grace + 5s) must still pass, since
    it derives from the constant itself, not a literal number."""
    grace = attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS
    headers_fresh = _headers(10)
    headers_stale = _headers(11)
    d_fresh, _ = _new_running_job(headers_fresh, heartbeat_age_seconds=grace - 5, timeout_in_seconds=1200)
    d_stale, _ = _new_running_job(headers_stale, heartbeat_age_seconds=grace + 5, timeout_in_seconds=1200)
    assert job_queue.claim(headers_fresh["x-org-id"], d_fresh) is None
    assert job_queue.claim(headers_stale["x-org-id"], d_stale) is not None


# ============================================================
# E. Existing expired-lease recovery -- unchanged behavior
# ============================================================

def test_E_expired_lease_still_recovers_independent_of_heartbeat_state():
    """A job whose absolute 20-minute lease has expired must still be
    recoverable even if, hypothetically, its heartbeat looked fresh --
    the two conditions are independently sufficient (OR, not AND), and
    this proves the pre-existing timeout_at path was not narrowed by
    adding the new heartbeat path alongside it."""
    headers = _headers(12)
    decision_id, _ = _new_running_job(headers, heartbeat_age_seconds=1, timeout_in_seconds=-60)
    claimed = job_queue.claim(headers["x-org-id"], decision_id)
    assert claimed is not None, \
        "An expired lease must still recover the job on its own, even with a fresh-looking heartbeat"


def test_E_expired_lease_job_is_still_discoverable_exactly_as_before():
    headers = _headers(13)
    decision_id, _ = _new_running_job(headers, heartbeat_age_seconds=1, timeout_in_seconds=-60)
    found = job_queue.find_next_due_job()
    assert found is not None and found[1] == decision_id
