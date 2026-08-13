"""
Attempt Fencing — the real safety mechanism behind the job lifecycle
redesign.

Core guarantee: an old, superseded reasoning attempt can NEVER overwrite
a newer one's work, no matter how long it has been running or how late
it wakes up. This is not achieved by preventing two workers from ever
running concurrently -- that cannot be guaranteed with certainty in any
real system. It's achieved by making every write conditioned on the
writer's own attempt_id still matching the row's current_attempt_id. A
reclaim doesn't just mark the old attempt "stale" -- it atomically
replaces current_attempt_id, permanently invalidating every future write
the old attempt could ever attempt.

Requirement 1 (explicit): heartbeat writes are strictly observability/
recovery metadata. A heartbeat failure must NEVER fail, interrupt, alter,
or retry the actual reasoning. Every heartbeat function here is wrapped
so it can never raise -- a transient DB hiccup during a heartbeat write
is silently absorbed, and the real reasoning work continues completely
unaffected.
"""
import threading
import uuid
from datetime import datetime, timezone

# Derived from the real execution model, not chosen independently --
# see JOB_LIFECYCLE_DESIGN.md for the full justification.
HEARTBEAT_TICK_INTERVAL_SECONDS = 15
RECOVERY_GRACE_PERIOD_SECONDS = 6 * HEARTBEAT_TICK_INTERVAL_SECONDS  # 90s
OPERATION_TIMEOUT_SECONDS = 20 * 60  # hard ceiling for a single SDK call


def new_attempt_id() -> str:
    return str(uuid.uuid4())


def start_new_attempt(org_id: str, decision_id, from_status: str = "awaiting_user_input") -> str | None:
    """
    Atomic claim -- generates a fresh attempt_id and stores it as the
    row's current_attempt_id in the same atomic statement that flips
    status to 'reasoning'. Returns the new attempt_id if this caller won
    the claim, None if someone else already did (a genuine double-click
    or racing duplicate).

    from_status is the real precondition for this specific call site --
    a follow-up answer claims from 'awaiting_user_input', while a fresh
    case whose evidence was complete from the start claims from
    'classifying' (its actual status immediately after creation, since
    it never passed through 'awaiting_user_input' at all).
    """
    from app.database import get_org_scoped_connection
    attempt_id = new_attempt_id()
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE commercial_decisions
                   SET status = 'reasoning', reasoning_started_at = now(),
                       current_attempt_id = %s, last_heartbeat_at = now(),
                       current_stage = 'starting'
                   WHERE id = %s AND status = %s
                   RETURNING current_attempt_id""",
                (attempt_id, str(decision_id), from_status),
            )
            row = cur.fetchone()
    return attempt_id if row else None


def try_reclaim(org_id: str, decision_id) -> str | None:
    """
    Reclaims a genuinely stale (heartbeat-based, not time-only) or
    known-failed case. Generates a NEW attempt_id and atomically replaces
    current_attempt_id -- this is the exact instant any prior attempt's
    writes become permanently invalid, regardless of when it wakes up.
    Returns the new attempt_id if this caller won the reclaim, None
    otherwise.
    """
    from app.database import get_org_scoped_connection
    attempt_id = new_attempt_id()
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE commercial_decisions
                   SET status = 'reasoning', reasoning_started_at = now(),
                       current_attempt_id = %s, last_heartbeat_at = now(),
                       current_stage = 'starting'
                   WHERE id = %s
                   AND (
                       status = 'provider_unavailable'
                       OR (status = 'reasoning' AND (
                           last_heartbeat_at IS NULL
                           OR last_heartbeat_at < now() - make_interval(secs => %s)
                       ))
                   )
                   RETURNING current_attempt_id""",
                (attempt_id, str(decision_id), RECOVERY_GRACE_PERIOD_SECONDS),
            )
            row = cur.fetchone()
    return attempt_id if row else None


def is_stale(org_id: str, decision_id) -> tuple[bool, float | None]:
    """Read-only check: is this case's reasoning genuinely stale right
    now, and what's the real elapsed time since the last heartbeat.
    Never mutates anything -- purely informational, used for the honest
    user-facing message and for deciding whether a reclaim is even worth
    attempting."""
    from app.database import get_org_scoped_connection
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_heartbeat_at, status FROM commercial_decisions WHERE id = %s",
                (str(decision_id),),
            )
            row = cur.fetchone()
    if not row or row["status"] != "reasoning":
        return False, None
    last_beat = row["last_heartbeat_at"]
    if last_beat is None:
        return True, None
    now = datetime.now(timezone.utc)
    if last_beat.tzinfo is None:
        last_beat = last_beat.replace(tzinfo=timezone.utc)
    elapsed = (now - last_beat).total_seconds()
    return elapsed >= RECOVERY_GRACE_PERIOD_SECONDS, elapsed


def write_heartbeat(org_id: str, decision_id, attempt_id: str, stage: str) -> None:
    """
    Requirement 1, enforced directly: this function can NEVER raise. A
    heartbeat write is genuinely optional from reasoning's perspective --
    if it fails (transient DB issue), the ticker simply tries again on
    its next scheduled tick, and the real reasoning work is completely
    unaffected either way. Attempt-fenced: if this attempt has already
    been superseded, this heartbeat correctly becomes a silent no-op,
    never an error.
    """
    try:
        from app.database import get_org_scoped_connection
        with get_org_scoped_connection(org_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE commercial_decisions
                       SET last_heartbeat_at = now(), current_stage = %s
                       WHERE id = %s AND current_attempt_id = %s""",
                    (stage, str(decision_id), attempt_id),
                )
    except Exception:
        pass  # requirement 1: never let a heartbeat failure propagate, ever


def write_final_result(org_id: str, decision_id, attempt_id: str, position_json: str, provenance_json: str) -> bool:
    """
    The completion write, attempt-fenced. Returns True if this attempt
    was still current at the moment of writing (the write genuinely
    happened), False if it had already been superseded -- in which case
    this attempt's result is correctly, silently discarded, and the
    caller should NOT treat this as an error requiring its own recovery;
    a newer attempt already owns this case.
    """
    from app.database import get_org_scoped_connection
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE commercial_decisions
                   SET status = 'completed', commercial_position = %s,
                       evidence_provenance = %s, completed_at = now()
                   WHERE id = %s AND current_attempt_id = %s""",
                (position_json, provenance_json, str(decision_id), attempt_id),
            )
            return cur.rowcount > 0


def write_provider_unavailable(org_id: str, decision_id, attempt_id: str) -> bool:
    """Same fencing discipline as the completion write -- a failure from
    an already-superseded attempt must not be allowed to mark a case
    'provider_unavailable' out from under a newer, possibly still-live
    attempt."""
    from app.database import get_org_scoped_connection
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE commercial_decisions SET status = 'provider_unavailable'
                   WHERE id = %s AND current_attempt_id = %s""",
                (str(decision_id), attempt_id),
            )
            return cur.rowcount > 0


class HeartbeatTicker:
    """
    Context manager: starts a lightweight background thread that writes
    a heartbeat at a fixed interval, decoupled entirely from whatever
    blocking call happens inside the `with` block. Stops the instant the
    block exits, success or exception.

    This is the actual mechanism that makes a legitimately long LLM/
    search call (5, 10, 15 minutes) provably distinguishable from a dead
    worker: if the whole process dies, this thread dies with it and
    heartbeats stop immediately; if only the network call is slow, this
    thread keeps ticking on its own independent schedule regardless.
    """
    def __init__(self, org_id: str, decision_id, attempt_id: str, stage: str):
        self.org_id = org_id
        self.decision_id = decision_id
        self.attempt_id = attempt_id
        self.stage = stage
        self._stop_event = threading.Event()
        self._thread = None

    def _tick_loop(self):
        while not self._stop_event.wait(HEARTBEAT_TICK_INTERVAL_SECONDS):
            write_heartbeat(self.org_id, self.decision_id, self.attempt_id, self.stage)

    def __enter__(self):
        write_heartbeat(self.org_id, self.decision_id, self.attempt_id, self.stage)
        self._thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        return False  # never suppress an exception from the wrapped work
