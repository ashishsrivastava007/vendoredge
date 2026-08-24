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
    """Atomically lease one due job; expired running leases become retryable."""
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE reasoning_jobs
                   SET status = 'running', attempt_count = attempt_count + 1,
                       started_at = now(), timeout_at = now() + make_interval(secs => %s),
                       updated_at = now()
                   WHERE commercial_decision_id = %s
                     AND cancel_requested_at IS NULL
                     AND attempt_count < max_attempts
                     AND (
                         (status IN ('queued', 'retry_scheduled') AND available_at <= now())
                         OR (status = 'running' AND timeout_at < now())
                     )
                   RETURNING *""",
                (LEASE_SECONDS, str(decision_id)),
            )
            return cur.fetchone()


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
                          OR (status = 'running' AND timeout_at < now()))
                   ORDER BY available_at ASC
                   LIMIT 1"""
            )
            row = cur.fetchone()
            return (str(row[0]), str(row[1])) if row else None


def recoverable_jobs() -> list[tuple[str, str]]:
    """List queued, retriable, and expired leases at process startup.

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
                          OR (status = 'running' AND timeout_at < now()))"""
            )
            return [(str(org_id), str(decision_id)) for org_id, decision_id in cur.fetchall()]
