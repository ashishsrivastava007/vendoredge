"""Database-backed reasoning job lifecycle.

The database is deliberately the queue of record.  Workers can disappear at
any point; a later process can reclaim an expired lease without losing the
case, duplicating a completed result, or exposing a half-finished answer.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4
import os
import psycopg2

from app.database import get_org_scoped_connection
from app.pipeline.attempt_fencing import RECOVERY_GRACE_PERIOD_SECONDS

MAX_ATTEMPTS = 3
LEASE_SECONDS = 20 * 60


def enqueue(org_id: str, decision_id, job_kind: str) -> None:
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO reasoning_jobs
                   (id, commercial_decision_id, organisation_id, job_kind, max_attempts)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (commercial_decision_id) DO NOTHING""",
                (str(uuid4()), str(decision_id), str(org_id), job_kind, MAX_ATTEMPTS),
            )


def requeue(org_id: str, decision_id, job_kind: str = "specialist") -> None:
    """Upsert, not a plain update -- deliberately.

    Genuine production bug, found via a real end-to-end test failure, not
    a review: a case that starts with missing evidence (create_decision's
    normal, common branch) never calls enqueue() at creation time, since
    there is nothing to run yet. When /respond later completes the
    evidence and calls this function to start reasoning for the first
    time, no reasoning_jobs row exists -- a plain UPDATE ... WHERE
    commercial_decision_id = %s then silently affects zero rows, and the
    subsequent claim() inside _run_queued_job finds nothing to claim,
    leaving the case stuck at 'reasoning' forever with no error, no
    retry, and no user-visible signal. This upsert makes requeue() correct
    for both cases it is actually called for -- a genuinely new first
    dispatch (insert) and a real retry of an existing, already-tracked job
    (update) -- with the exact same resulting row state as before for any
    caller where a row already existed, so no previously-correct behavior
    changes.
    """
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO reasoning_jobs
                   (id, commercial_decision_id, organisation_id, job_kind, status, max_attempts)
                   VALUES (%s, %s, %s, %s, 'queued', %s)
                   ON CONFLICT (commercial_decision_id) DO UPDATE SET
                       status = 'queued', available_at = now(), cancel_requested_at = NULL,
                       last_error_code = NULL, last_error_detail = NULL,
                       job_kind = EXCLUDED.job_kind, updated_at = now()""",
                (str(uuid4()), str(decision_id), str(org_id), job_kind, MAX_ATTEMPTS),
            )


def claim(org_id: str, decision_id) -> dict | None:
    """Atomically lease one due job AND, when recovery is what's actually
    happening, establish the new attempt_id as part of the SAME atomic
    operation -- not as a later, separate try_reclaim() call a second
    worker can interleave with.

    Design, and why it looks like this:

    A job's *queue* lease (timeout_at, LEASE_SECONDS -- the absolute
    ceiling a single attempt is ever allowed to run) and the *worker's*
    liveness (commercial_decisions.last_heartbeat_at, ticked every
    HEARTBEAT_TICK_INTERVAL_SECONDS by a thread genuinely independent of
    the blocking LLM call) are two different signals. Gating solely on
    timeout_at means a worker that died seconds into a 20-minute lease is
    invisible to recovery for up to 20 minutes, even though its heartbeat
    stopped almost immediately.

    Two earlier versions of this fix were each proven wrong by adversarial
    testing, not by inspection, and both failures are worth keeping on
    record here:

    1. A version that added only the heartbeat-staleness condition to
       claim()'s WHERE clause, leaving attempt_id resolution to a SEPARATE,
       later attempt_fencing.try_reclaim() call in _run_queued_job. Two
       concurrent claim() calls could both match the same heartbeat-stale
       job before either had changed anything claim() itself touches,
       both incrementing attempt_count -- and even after that was
       tolerated as a minor, bounded cost, a second, subtler gap remained:
       one worker's row-read could occur AFTER a first worker's separate
       try_reclaim() had already committed, so the second worker
       legitimately read the SAME, already-current, valid attempt_id --
       there was no staleness left to detect, so it proceeded straight
       into the real reasoning call too. Attempt fencing correctly
       rejects a STALE attempt_id; it was never designed to stop two
       workers who both, correctly, hold the SAME valid one. Proven with
       an instrumented, traced two-thread run before this version was
       written -- see test_C in test_heartbeat_aware_recovery.py.
    2. A version that had claim() refresh commercial_decisions.last_
       heartbeat_at unconditionally on every successful claim, to close
       gap 1 above -- this broke recovery entirely instead: it made the
       row look fresh to _run_queued_job's own subsequent is_stale()
       check, which is what decided whether a fresh attempt_id was ever
       generated at all, silently defeating recovery for the exact case
       this whole fix exists for.

    The actual fix: eligibility, generating a new attempt_id when (and
    only when) recovery is what's happening, and both underlying table
    updates all happen inside ONE transaction, while holding a row lock
    (SELECT ... FOR UPDATE) on the specific reasoning_jobs row for the
    entire decision. A second, concurrent caller's own SELECT ... FOR
    UPDATE against the SAME row blocks until this transaction commits or
    rolls back -- there is no window between "decide" and "write" for a
    second caller to observe, because nothing is written or released
    until the whole decision is already final. This is the ownership
    authority the whole system relies on now; find_next_due_job() and
    recoverable_jobs() remain cheap, loose, non-authoritative discovery
    only -- a job either of them surfaces is not "claimed" until it wins
    here.

    LEASE_SECONDS, PROVIDER_OPERATION_TIMEOUT_SECONDS,
    HEARTBEAT_TICK_INTERVAL_SECONDS, and RECOVERY_GRACE_PERIOD_SECONDS are
    all unchanged and untouched by this function; attempt_fencing.py's
    try_reclaim()/is_stale() are also unchanged -- they remain exactly as
    they are for the independent, single-request /respond manual-recovery
    path (decisions.py's own direct use of them there is untouched and
    unaffected by anything here).
    """
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT rj.id, rj.status, rj.attempt_count, rj.max_attempts,
                          rj.cancel_requested_at, rj.available_at, rj.timeout_at, rj.job_kind,
                          cd.status AS decision_status, cd.last_heartbeat_at, cd.current_attempt_id,
                          now() AS db_now
                   FROM reasoning_jobs rj
                   JOIN commercial_decisions cd ON cd.id = rj.commercial_decision_id
                   WHERE rj.commercial_decision_id = %s
                   FOR UPDATE OF rj""",
                (str(decision_id),),
            )
            row = cur.fetchone()
            if row is None:
                return None

            # now() is transaction-scoped in Postgres (frozen at transaction
            # start, same value for every call within it) -- read once here,
            # in the same query as everything else being judged against it,
            # and reused below rather than called again.
            now = row["db_now"]

            heartbeat_stale = (
                row["last_heartbeat_at"] is None
                or row["last_heartbeat_at"] < now - timedelta(seconds=RECOVERY_GRACE_PERIOD_SECONDS)
            )
            eligible = (
                row["cancel_requested_at"] is None
                and row["attempt_count"] < row["max_attempts"]
                and (
                    (row["status"] in ("queued", "retry_scheduled") and row["available_at"] <= now)
                    or (row["status"] == "running" and (row["timeout_at"] < now or heartbeat_stale))
                )
            )
            if not eligible:
                return None

            # Recovery is happening -- as opposed to a normal first claim
            # or a normal scheduled retry -- exactly when the heartbeat is
            # stale or missing at this exact, now-locked moment. This is
            # the same distinguishing condition the previous, separate
            # is_stale() check used, evaluated once, atomically, here,
            # instead of via a second statement a racing caller could slip
            # between.
            if heartbeat_stale:
                attempt_id = str(uuid4())
                cur.execute(
                    """UPDATE commercial_decisions
                       SET current_attempt_id = %s, last_heartbeat_at = now(),
                           status = 'reasoning', reasoning_started_at = now(),
                           current_stage = 'starting'
                       WHERE id = %s""",
                    (attempt_id, str(decision_id)),
                )
            else:
                attempt_id = row["current_attempt_id"]

            cur.execute(
                """UPDATE reasoning_jobs
                   SET status = 'running', attempt_count = attempt_count + 1,
                       started_at = now(), timeout_at = now() + make_interval(secs => %s),
                       updated_at = now()
                   WHERE id = %s
                   RETURNING *""",
                (LEASE_SECONDS, row["id"]),
            )
            job = cur.fetchone()
            job["attempt_id"] = attempt_id
            return job


def complete(org_id: str, decision_id) -> None:
    _set(org_id, decision_id, "completed")


def cancel(org_id: str, decision_id) -> bool:
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE reasoning_jobs SET cancel_requested_at = now(), status = 'cancelled',
                   completed_at = now(), updated_at = now()
                   WHERE commercial_decision_id = %s AND status IN ('queued', 'retry_scheduled', 'running')
                   RETURNING id""",
                (str(decision_id),),
            )
            return bool(cur.fetchone())


def is_cancelled(org_id: str, decision_id) -> bool:
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT cancel_requested_at IS NOT NULL AS cancelled FROM reasoning_jobs WHERE commercial_decision_id = %s", (str(decision_id),))
            row = cur.fetchone()
            return bool(row and row["cancelled"])


def fail_or_retry(org_id: str, decision_id, code: str, detail: str) -> str:
    """Persist a bounded retry; terminal failure is explicit and recoverable."""
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE reasoning_jobs
                   SET status = CASE WHEN attempt_count >= max_attempts THEN 'failed' ELSE 'retry_scheduled' END,
                       available_at = CASE WHEN attempt_count >= max_attempts THEN available_at
                                           ELSE now() + make_interval(secs => LEAST(300, 15 * attempt_count)) END,
                       completed_at = CASE WHEN attempt_count >= max_attempts THEN now() ELSE NULL END,
                       last_error_code = %s, last_error_detail = %s, updated_at = now()
                   WHERE commercial_decision_id = %s
                   RETURNING status""",
                (code[:80], detail[:2000], str(decision_id)),
            )
            row = cur.fetchone()
            return row["status"] if row else "failed"


def _set(org_id: str, decision_id, status: str) -> None:
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE reasoning_jobs SET status = %s, completed_at = now(), updated_at = now() WHERE commercial_decision_id = %s",
                (status, str(decision_id)),
            )


def find_next_due_job() -> tuple[str, str] | None:
    """Read-only discovery of the single oldest due job, across every
    tenant -- deliberately NOT a claim. The one true atomic state change
    still happens inside claim(), exactly as it already does for every
    existing dispatch path (create_decision, respond, continue_case, and
    the startup recovery sweep in recoverable_jobs()). This function only
    answers "what should be looked at next"; it never mutates a row.

    This makes a discovery race harmless by construction: if two dispatch
    loop iterations (or, later, two separate worker processes) both
    discover the same due row here, only one of their subsequent calls to
    the real claim() can ever win -- Postgres serializes that UPDATE, and
    the loser's call correctly, safely returns None and does nothing. No
    new locking is introduced here because none is needed; the existing
    claim() already provides the actual safety guarantee.

    Uses the privileged migration connection solely for this cross-tenant
    read, exactly like recoverable_jobs() already does -- execution
    returns to tenant-scoped access the moment the specific org/decision
    is known, in _run_queued_job's own get_org_scoped_connection call.

    The running-lease branch also treats a job as due once its owning
    decision's heartbeat has gone stale (RECOVERY_GRACE_PERIOD_SECONDS,
    the same constant and threshold attempt_fencing.try_reclaim() already
    uses), not only once the full LEASE_SECONDS ceiling has passed. A
    dead worker's heartbeat thread dies with it and goes stale within
    that window; a genuinely alive worker keeps ticking regardless of how
    long its LLM call takes, so this never surfaces a healthy job early.
    claim() carries the identical condition -- discovering a job here
    that claim() would still reject would make this whole change inert.
    """
    dsn = os.environ.get("MIGRATION_DATABASE_URL")
    if not dsn:
        return None
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT organisation_id, commercial_decision_id
                   FROM reasoning_jobs
                   WHERE cancel_requested_at IS NULL
                     AND attempt_count < max_attempts
                     AND ((status IN ('queued', 'retry_scheduled') AND available_at <= now())
                          OR (status = 'running' AND (
                              timeout_at < now()
                              OR EXISTS (
                                  SELECT 1 FROM commercial_decisions cd
                                  WHERE cd.id = reasoning_jobs.commercial_decision_id
                                    AND cd.status = 'reasoning'
                                    AND (cd.last_heartbeat_at IS NULL
                                         OR cd.last_heartbeat_at < now() - make_interval(secs => %s))
                              )
                          )))
                   ORDER BY available_at ASC
                   LIMIT 1""",
                (RECOVERY_GRACE_PERIOD_SECONDS,),
            )
            row = cur.fetchone()
            return (str(row[0]), str(row[1])) if row else None


def recoverable_jobs() -> list[tuple[str, str]]:
    """List queued, retriable, and expired/heartbeat-stale leases at
    process startup. See find_next_due_job() for why the running-lease
    branch also checks heartbeat staleness, not only timeout_at -- the
    two functions deliberately use identical eligibility so a job
    orphaned by a crashed process is recovered the same way regardless
    of which recovery path notices it first.

    This uses the deployment migration connection solely to discover tenant
    IDs; execution immediately returns to tenant-scoped application access.
    A missing privileged URL is a deployment error, never a silent skip.
    """
    dsn = os.environ.get("MIGRATION_DATABASE_URL")
    if not dsn:
        return []
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT organisation_id, commercial_decision_id
                   FROM reasoning_jobs
                   WHERE cancel_requested_at IS NULL
                     AND attempt_count < max_attempts
                     AND ((status IN ('queued', 'retry_scheduled') AND available_at <= now())
                          OR (status = 'running' AND (
                              timeout_at < now()
                              OR EXISTS (
                                  SELECT 1 FROM commercial_decisions cd
                                  WHERE cd.id = reasoning_jobs.commercial_decision_id
                                    AND cd.status = 'reasoning'
                                    AND (cd.last_heartbeat_at IS NULL
                                         OR cd.last_heartbeat_at < now() - make_interval(secs => %s))
                              )
                          )))""",
                (RECOVERY_GRACE_PERIOD_SECONDS,),
            )
            return [(str(org_id), str(decision_id)) for org_id, decision_id in cur.fetchall()]
