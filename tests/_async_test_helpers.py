"""
Shared test helper for the async reasoning architecture: POST endpoints
now return immediately with status 'reasoning' while the actual work
completes on a background thread. Tests that need the final result must
poll, exactly like a real frontend would.
"""
import time


def poll_until_terminal(client, headers, decision_id, timeout=10.0, interval=0.05):
    """
    Polls GET /commercial-decisions/{id} until status leaves 'reasoning',
    or the timeout is hit. Returns the final response object. A tight
    interval keeps tests fast -- the mocked LLM calls used throughout
    this suite complete in milliseconds, not the real seconds a live
    API call would take.
    """
    deadline = time.time() + timeout
    r = None
    while time.time() < deadline:
        r = client.get(f"/api/v1/commercial-decisions/{decision_id}", headers=headers)
        if r.json()["status"] != "reasoning":
            return r
        time.sleep(interval)
    return r
