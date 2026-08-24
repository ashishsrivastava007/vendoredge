"""Continuous background dispatcher for the durable reasoning_jobs queue.

What already existed and is deliberately left unchanged: the queue table
itself (reasoning_jobs), atomic per-job claim/complete/fail_or_retry with
bounded retry and backoff (job_queue.py), attempt fencing and heartbeat
liveness (attempt_fencing.py), and a one-time startup recovery sweep
(recoverable_jobs(), called from app.main's lifespan) that requeues
anything abandoned by a previous process before this one accepts traffic.

What was actually missing, and is the entire purpose of this module: a
dedicated worker that keeps watching for due work for as long as the
process is alive -- not just once at startup, and not only reactively
when a web request happens to touch the specific decision in question
(create_decision / respond / continue_case each dispatch immediately via
FastAPI BackgroundTasks, which remains the fast, low-latency path for the
common case). If a job's lease expires *while the app is already running*
-- a worker thread died from something outside _run_reasoning_safe's own
broad guard, or a request's BackgroundTasks dispatch itself never fired --
nothing previously noticed until either the process restarted or a user
happened to poll/respond against that exact decision. This dispatcher is
the safety net for that gap: a single daemon thread, polling on a fixed
interval, for the life of the process.

This intentionally introduces no new infrastructure -- no queue broker, no
scheduler service, nothing beyond one more daemon thread reusing every
piece of already-proven logic. Discovery (find_next_due_job) and the one
real atomic mutation (claim(), called inside _run_queued_job) are
deliberately kept separate -- see job_queue.find_next_due_job's own
docstring for why that split makes the discovery step safe without needing
its own locking.
"""
import threading

from app.pipeline.job_queue import find_next_due_job

# How often the dispatcher checks for due work. Chosen as a real trade-off,
# not an arbitrary number: frequent enough that a job stranded mid-run by a
# dead worker thread is picked back up within a handful of seconds of its
# lease actually expiring, infrequent enough that an idle app performs one
# trivial indexed query every 5 seconds -- negligible load, not a concern
# at any pilot-relevant scale. Independent of HEARTBEAT_TICK_INTERVAL_SECONDS
# (attempt_fencing.py) and LEASE_SECONDS (job_queue.py), which govern
# liveness *within* an already-claimed job, not discovery of new work.
DISPATCH_POLL_INTERVAL_SECONDS = 5


def run_dispatcher_loop(stop_event: threading.Event, poll_interval: float = DISPATCH_POLL_INTERVAL_SECONDS) -> None:
    """Runs until stop_event is set (graceful shutdown -- see
    start_dispatcher and app.main's lifespan). Each iteration discovers at
    most one due job and dispatches it through _run_queued_job -- the
    exact same atomic claim(), heartbeat, attempt-fencing, and
    retry/terminal-state logic every other call site already uses. No new
    execution path is introduced; this only decides *when* to call the
    existing one.
    """
    # Imported here, not at module load time: app.routes.decisions imports
    # from app.pipeline.job_queue, and this module also depends on
    # job_queue -- a top-level import of decisions.py here would risk a
    # circular import the moment this module is loaded. main.py's existing
    # one-time startup sweep uses this same local-import pattern for
    # exactly the same reason.
    from app.routes.decisions import _run_queued_job

    while not stop_event.wait(poll_interval):
        try:
            due = find_next_due_job()
            if due:
                org_id, decision_id = due
                _run_queued_job(org_id, decision_id)
        except Exception as exc:
            # A dispatcher-loop failure must never permanently stop the
            # loop itself -- that would silently recreate exactly the gap
            # this module exists to close. Mirrors attempt_fencing's
            # heartbeat requirement: infrastructure hiccups are absorbed
            # and retried on the next tick, never allowed to propagate.
            print(f"WARNING: dispatcher loop iteration failed, continuing: {exc}")


def start_dispatcher(stop_event: threading.Event) -> threading.Thread:
    """Starts the continuous dispatcher as a daemon thread and returns it.

    Returning the thread (rather than firing-and-forgetting, as the
    existing one-time startup sweep does) lets app.main's lifespan join it
    with a bounded timeout on shutdown, and lets tests deterministically
    stop and wait for it instead of racing a bare sleep.
    """
    thread = threading.Thread(target=run_dispatcher_loop, args=(stop_event,), daemon=True)
    thread.start()
    return thread
