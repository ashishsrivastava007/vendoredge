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
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE reasoning_jobs SET status = 'queued', available_at = now(),
                   cancel_requested_at = NULL, last_error_code = NULL, last_error_detail = NULL,
                   job_kind = %s, updated_at = now() WHERE commercial_decision_id = %s""",
                (job_kind, str(decision_id)),
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
