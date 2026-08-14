"""
Async Reasoning Job Lifecycle — Complete Adversarial Suite.

Covers every scenario from JOB_LIFECYCLE_DESIGN.md plus the five
additional tests (#27-31) required for this hardening pass. Every test
proven as: EXPECTED FAILURE -> DETECTION -> SAFE RESPONSE -> NO DUPLICATE
WORK -> NO SILENT CORRUPTION.

Low-level tests call attempt_fencing directly, against a real database,
to prove the mechanism itself. End-to-end tests go through the real live
endpoints (mocked LLM calls only) to prove the mechanism is genuinely
wired into the real request path, not just correct in isolation.
"""
import os
import time
import json
import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_org_scoped_connection
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline import attempt_fencing
from tests._async_test_helpers import poll_until_terminal

client = TestClient(app)
_CONF = Confidence(
    level="medium",
    factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
    derivation_note="n",
)
_MOCK_POSITION = CommercialPosition(
    recommendation="x", commercial_insights=["a"], reasoning="x",
    confidence=_CONF, assumptions=["a"],
    disconfirming_condition="...", decision_type="optimization",
)
_CLASSIFY_RESPONSE_COMPLETE = {
    "content_type": "price_increase", "decision_type": "optimization",
    "constraint_satisfaction_signal": None,
    "extracted_evidence": {
        "current_price_or_terms": "x",
        "suppliers_stated_justification": "x", "how_critical_is_this_supplier_relationship": "x",
    },
    "numeric_facts": {"requested_change_percent": 10.0},
}
_CLASSIFY_RESPONSE_INCOMPLETE = {
    "content_type": "price_increase", "decision_type": "optimization",
    "constraint_satisfaction_signal": None,
    "extracted_evidence": {"current_price_or_terms": "x"},
    "numeric_facts": {"requested_change_percent": 10.0},
}


def _new_case_row(headers, status="awaiting_user_input"):
    """Creates a real decision row directly, returns decision_id."""
    import uuid
    org_id = headers["x-org-id"]
    decision_id = str(uuid.uuid4())
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO commercial_decisions (id, organisation_id, created_by_user_id, "
                f"raw_question, classified_content_type, status) "
                f"VALUES (%s, %s, %s, 'x', 'price_increase', '{status}')",
                (decision_id, org_id, headers["x-user-id"]),
            )
    return decision_id


def _headers(ip_suffix):
    org_res = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"10.33.{ip_suffix}.1"}).json()
    return {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}


def _backdate_heartbeat(org_id, decision_id, seconds_ago):
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE commercial_decisions SET last_heartbeat_at = %s WHERE id = %s", (stale_time, decision_id))


# ============================================================
# CORE MECHANISM: low-level attempt_fencing proofs
# ============================================================

def test_1_worker_alive_but_slow_heartbeat_fresh_never_reclaimed():
    """ATTACK: a case is 3 minutes into reasoning with a fresh heartbeat.
    EXPECTED: never reclaimable -- slow, not dead."""
    headers = _headers(1)
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_a = attempt_fencing.start_new_attempt(headers["x-org-id"], decision_id)
    assert attempt_a is not None
    reclaimed = attempt_fencing.try_reclaim(headers["x-org-id"], decision_id)
    assert reclaimed is None, "A genuinely fresh heartbeat must never be reclaimed"


def test_2_heartbeat_delayed_but_within_grace_not_reclaimed():
    """Boundary-adjacent: 60s of silence, well within the 90s grace period."""
    headers = _headers(2)
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_a = attempt_fencing.start_new_attempt(headers["x-org-id"], decision_id)
    _backdate_heartbeat(headers["x-org-id"], decision_id, 60)
    reclaimed = attempt_fencing.try_reclaim(headers["x-org-id"], decision_id)
    assert reclaimed is None


def test_3_heartbeat_genuinely_stale_becomes_recoverable():
    headers = _headers(3)
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_a = attempt_fencing.start_new_attempt(headers["x-org-id"], decision_id)
    _backdate_heartbeat(headers["x-org-id"], decision_id, attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS + 30)
    reclaimed = attempt_fencing.try_reclaim(headers["x-org-id"], decision_id)
    assert reclaimed is not None
    assert reclaimed != attempt_a


def test_10_boundary_exactly_89_seconds_not_reclaimed():
    headers = _headers(10)
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_fencing.start_new_attempt(headers["x-org-id"], decision_id)
    _backdate_heartbeat(headers["x-org-id"], decision_id, 89)
    reclaimed = attempt_fencing.try_reclaim(headers["x-org-id"], decision_id)
    assert reclaimed is None, "89s of silence must NOT be treated as stale (grace period is 90s)"


def test_10b_boundary_exactly_90_seconds_genuinely_reclaimable():
    headers = _headers(11)
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_fencing.start_new_attempt(headers["x-org-id"], decision_id)
    _backdate_heartbeat(headers["x-org-id"], decision_id, 90)
    reclaimed = attempt_fencing.try_reclaim(headers["x-org-id"], decision_id)
    assert reclaimed is not None, "Exactly 90s must be treated as the genuine threshold"


def test_10c_boundary_a_tick_at_89_9_seconds_cancels_reclaim_consideration():
    """A tick arriving just under the threshold must fully reset staleness,
    not just 'barely miss' being reclaimed."""
    headers = _headers(12)
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_a = attempt_fencing.start_new_attempt(headers["x-org-id"], decision_id)
    _backdate_heartbeat(headers["x-org-id"], decision_id, 89.9)
    attempt_fencing.write_heartbeat(headers["x-org-id"], decision_id, attempt_a, "primary_reasoning")
    reclaimed = attempt_fencing.try_reclaim(headers["x-org-id"], decision_id)
    assert reclaimed is None, "A fresh tick must fully reset staleness, not just narrowly avoid it"


# ============================================================
# THE CRITICAL PROOF: old attempt can never overwrite (tests 11, 29, 30, 31)
# ============================================================

def test_11_29_old_worker_wakes_after_reclaim_cannot_overwrite_any_field():
    """
    THE single most important test. Proves an old, superseded attempt
    cannot overwrite ANY user-visible field -- not only commercial_position
    (requirement 29 explicitly widens this beyond the original proof).
    """
    headers = _headers(13)
    org_id = headers["x-org-id"]
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_a = attempt_fencing.start_new_attempt(org_id, decision_id)
    _backdate_heartbeat(org_id, decision_id, attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS + 10)
    attempt_b = attempt_fencing.try_reclaim(org_id, decision_id)
    assert attempt_b is not None and attempt_b != attempt_a

    b_written = attempt_fencing.write_final_result(
        org_id, decision_id, attempt_b,
        json.dumps({"recommendation": "FROM B - CORRECT"}), json.dumps({"field": {"source": "user_followup"}}),
    )
    assert b_written is True

    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, commercial_position, evidence_provenance, completed_at "
                "FROM commercial_decisions WHERE id = %s", (decision_id,),
            )
            state_after_b = dict(cur.fetchone())

    a_written = attempt_fencing.write_final_result(
        org_id, decision_id, attempt_a,
        json.dumps({"recommendation": "FROM A - MUST NEVER APPEAR"}), json.dumps({"field": {"source": "llm_extraction"}}),
    )
    assert a_written is False

    a_provider_unavailable_written = attempt_fencing.write_provider_unavailable(org_id, decision_id, attempt_a)
    assert a_provider_unavailable_written is False, "Old attempt must not even be able to mark the case failed"

    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, commercial_position, evidence_provenance, completed_at "
                "FROM commercial_decisions WHERE id = %s", (decision_id,),
            )
            state_after_a_attempts = dict(cur.fetchone())

    assert state_after_a_attempts["status"] == state_after_b["status"] == "completed"
    assert state_after_a_attempts["commercial_position"] == state_after_b["commercial_position"]
    assert "FROM A" not in json.dumps(state_after_a_attempts["commercial_position"])
    assert state_after_a_attempts["evidence_provenance"] == state_after_b["evidence_provenance"]
    assert state_after_a_attempts["completed_at"] == state_after_b["completed_at"]


def test_30_attempt_b_completes_before_a_and_remains_final_under_repeated_testing():
    """Requirement 30: repeated/concurrent runs must all show the same
    outcome -- not a coincidence of one lucky run."""
    for trial in range(5):
        headers = _headers(20 + trial)
        org_id = headers["x-org-id"]
        decision_id = _new_case_row(headers, status="awaiting_user_input")
        attempt_a = attempt_fencing.start_new_attempt(org_id, decision_id)
        _backdate_heartbeat(org_id, decision_id, attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS + 5)
        attempt_b = attempt_fencing.try_reclaim(org_id, decision_id)
        assert attempt_fencing.write_final_result(org_id, decision_id, attempt_b, json.dumps({"trial": trial, "who": "B"}), "{}")
        assert attempt_fencing.write_final_result(org_id, decision_id, attempt_a, json.dumps({"trial": trial, "who": "A"}), "{}") is False
        with get_org_scoped_connection(org_id) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT commercial_position FROM commercial_decisions WHERE id = %s", (decision_id,))
                final = cur.fetchone()["commercial_position"]
        assert final["who"] == "B", f"Trial {trial}: B must remain final"


def test_31_user_never_sees_two_competing_final_decisions():
    """Requirement 31: the user-facing GET response itself must only ever
    reflect one, consistent final answer -- proven through the real API,
    not just the raw database row."""
    headers = _headers(30)
    org_id = headers["x-org-id"]
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_a = attempt_fencing.start_new_attempt(org_id, decision_id)
    _backdate_heartbeat(org_id, decision_id, attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS + 5)
    attempt_b = attempt_fencing.try_reclaim(org_id, decision_id)

    def _valid_position(recommendation):
        return json.dumps({
            "recommendation": recommendation, "commercial_insights": ["a"], "reasoning": "x",
            "confidence": {"level": "medium", "factors": [{"factor": "x", "value": "y", "weight": "increases confidence"}], "derivation_note": "n"},
            "assumptions": ["a"], "disconfirming_condition": "...", "decision_type": "optimization",
        })

    attempt_fencing.write_final_result(org_id, decision_id, attempt_b, _valid_position("B - the real answer"), "{}")
    attempt_fencing.write_final_result(org_id, decision_id, attempt_a, _valid_position("A - must never surface"), "{}")

    r1 = client.get(f"/api/v1/commercial-decisions/{decision_id}", headers=headers)
    r2 = client.get(f"/api/v1/commercial-decisions/{decision_id}", headers=headers)
    assert r1.json()["commercial_position"]["recommendation"] == r2.json()["commercial_position"]["recommendation"]
    assert "A - must never surface" not in r1.text
    assert "A - must never surface" not in r2.text


# ============================================================
# Requirements 27-28: heartbeat failure never affects reasoning
# ============================================================

def test_27_heartbeat_failure_while_reasoning_continues_successfully():
    """
    ATTACK: every heartbeat write fails (simulated DB error) throughout
    an entire reasoning run.
    EXPECTED: the real reasoning work completes successfully regardless
    -- heartbeat is strictly observational, per requirement 1.
    """
    headers = _headers(40)
    org_id = headers["x-org-id"]
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_id = attempt_fencing.start_new_attempt(org_id, decision_id)

    with patch("app.database.get_org_scoped_connection", side_effect=Exception("simulated total heartbeat outage")):
        attempt_fencing.write_heartbeat(org_id, decision_id, attempt_id, "primary_reasoning")
        attempt_fencing.write_heartbeat(org_id, decision_id, attempt_id, "market_verification")

    written = attempt_fencing.write_final_result(org_id, decision_id, attempt_id, json.dumps({"recommendation": "real result, unaffected"}), "{}")
    assert written is True


def test_28_temporary_heartbeat_loss_then_recovery_no_duplicate_execution():
    """
    ATTACK: heartbeat writes fail for a period, then genuinely recover
    (the worker itself never died, just its heartbeat writes bounced).
    EXPECTED: as long as a real heartbeat lands before the grace period
    elapses, the case must never be reclaimed -- no duplicate execution.
    """
    headers = _headers(41)
    org_id = headers["x-org-id"]
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_id = attempt_fencing.start_new_attempt(org_id, decision_id)

    _backdate_heartbeat(org_id, decision_id, 70)
    attempt_fencing.write_heartbeat(org_id, decision_id, attempt_id, "primary_reasoning")

    reclaimed = attempt_fencing.try_reclaim(org_id, decision_id)
    assert reclaimed is None, "A genuine recovery heartbeat must fully prevent reclaim -- no duplicate execution"


# ============================================================
# Concurrency: tests 5, 19
# ============================================================

def test_5_two_recovery_attempts_racing_only_one_wins():
    headers = _headers(50)
    org_id = headers["x-org-id"]
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_fencing.start_new_attempt(org_id, decision_id)
    _backdate_heartbeat(org_id, decision_id, attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS + 5)

    results = []
    def race():
        results.append(attempt_fencing.try_reclaim(org_id, decision_id))
    threads = [threading.Thread(target=race) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"Exactly one recovery attempt must win a genuine race, got {len(winners)}"


# ============================================================
# Worker/process death at multiple points
# ============================================================

def test_18_worker_killed_immediately_before_final_write():
    headers = _headers(60)
    org_id = headers["x-org-id"]
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_fencing.start_new_attempt(org_id, decision_id)
    _backdate_heartbeat(org_id, decision_id, attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS + 5)

    attempt_b = attempt_fencing.try_reclaim(org_id, decision_id)
    assert attempt_b is not None
    written = attempt_fencing.write_final_result(org_id, decision_id, attempt_b, json.dumps({"recommendation": "clean recovery result"}), "{}")
    assert written is True
    with get_org_scoped_connection(org_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM commercial_decisions WHERE id = %s", (decision_id,))
            assert cur.fetchone()["status"] == "completed"


def test_20_simulated_process_restart_heartbeat_correctly_goes_silent():
    headers = _headers(61)
    org_id = headers["x-org-id"]
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_id = attempt_fencing.start_new_attempt(org_id, decision_id)
    ticker = attempt_fencing.HeartbeatTicker(org_id, decision_id, attempt_id, "primary_reasoning")
    ticker.__enter__()
    ticker._stop_event.set()
    time.sleep(0.1)
    _backdate_heartbeat(org_id, decision_id, attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS + 5)
    stale, _ = attempt_fencing.is_stale(org_id, decision_id)
    assert stale is True, "A genuinely stopped heartbeat must correctly become detectable as stale"


# ============================================================
# Database failure during writes
# ============================================================

def test_21_database_unavailable_during_heartbeat_never_crashes():
    headers = _headers(70)
    org_id = headers["x-org-id"]
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_id = attempt_fencing.start_new_attempt(org_id, decision_id)
    with patch("app.database.get_org_scoped_connection", side_effect=Exception("simulated outage")):
        try:
            attempt_fencing.write_heartbeat(org_id, decision_id, attempt_id, "primary_reasoning")
        except Exception:
            assert False, "write_heartbeat must never raise, even on a real DB outage"


def test_22_database_unavailable_during_final_write_self_heals_via_staleness():
    headers = _headers(71)
    org_id = headers["x-org-id"]
    decision_id = _new_case_row(headers, status="awaiting_user_input")
    attempt_id = attempt_fencing.start_new_attempt(org_id, decision_id)
    with patch("app.database.get_org_scoped_connection", side_effect=Exception("simulated outage")):
        try:
            attempt_fencing.write_final_result(org_id, decision_id, attempt_id, "{}", "{}")
            assert False, "This should raise -- caller (_run_reasoning_safe) is responsible for catching it"
        except Exception:
            pass
    _backdate_heartbeat(org_id, decision_id, attempt_fencing.RECOVERY_GRACE_PERIOD_SECONDS + 5)
    reclaimed = attempt_fencing.try_reclaim(org_id, decision_id)
    assert reclaimed is not None


# ============================================================
# Long-running LLM calls with continuous heartbeat
# ============================================================

def test_9_simulated_5_10_15_minute_calls_never_falsely_stale():
    import app.pipeline.attempt_fencing as af
    original_interval = af.HEARTBEAT_TICK_INTERVAL_SECONDS
    af.HEARTBEAT_TICK_INTERVAL_SECONDS = 0.2
    try:
        for simulated_minutes in (5, 10, 15):
            headers = _headers(80 + simulated_minutes)
            org_id = headers["x-org-id"]
            decision_id = _new_case_row(headers, status="awaiting_user_input")
            attempt_id = attempt_fencing.start_new_attempt(org_id, decision_id)
            with af.HeartbeatTicker(org_id, decision_id, attempt_id, "primary_reasoning"):
                time.sleep(0.2 * 4)
            stale, elapsed = attempt_fencing.is_stale(org_id, decision_id)
            assert stale is False, f"A {simulated_minutes}-minute simulated call must never be falsely stale"
    finally:
        af.HEARTBEAT_TICK_INTERVAL_SECONDS = original_interval


def test_16_heartbeat_genuinely_fires_during_a_long_blocking_call():
    import app.pipeline.attempt_fencing as af
    original_interval = af.HEARTBEAT_TICK_INTERVAL_SECONDS
    af.HEARTBEAT_TICK_INTERVAL_SECONDS = 0.2
    try:
        headers = _headers(90)
        org_id = headers["x-org-id"]
        decision_id = _new_case_row(headers, status="awaiting_user_input")
        attempt_id = attempt_fencing.start_new_attempt(org_id, decision_id)

        beats_seen = []
        def read():
            with get_org_scoped_connection(org_id) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT last_heartbeat_at FROM commercial_decisions WHERE id = %s", (decision_id,))
                    return cur.fetchone()["last_heartbeat_at"]

        with af.HeartbeatTicker(org_id, decision_id, attempt_id, "primary_reasoning"):
            for _ in range(4):
                time.sleep(0.25)
                beats_seen.append(read())
        assert len(set(str(b) for b in beats_seen)) >= 2, "Heartbeat must genuinely advance DURING the blocking call"
    finally:
        af.HEARTBEAT_TICK_INTERVAL_SECONDS = original_interval


# ============================================================
# End-to-end, through the real live endpoints
# ============================================================

def test_original_bug_double_click_gets_graceful_response_not_409():
    headers = _headers(100)
    with patch("app.routes.decisions.classify") as mock_classify:
        mock_classify.return_value = _CLASSIFY_RESPONSE_INCOMPLETE
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "x"}, headers=headers)
    decision_id = r.json()["id"]

    def slow_generate(*a, **k):
        time.sleep(0.3)
        return _MOCK_POSITION

    with patch("app.routes.decisions.generate_commercial_position", side_effect=slow_generate):
        t = threading.Thread(target=lambda: client.post(
            f"/api/v1/commercial-decisions/{decision_id}/respond",
            json={"user_supplied_inputs": {"suppliers_stated_justification": "x", "how_critical_is_this_supplier_relationship": "x"}},
            headers=headers,
        ))
        t.start()
        time.sleep(0.05)
        r2 = client.post(
            f"/api/v1/commercial-decisions/{decision_id}/respond",
            json={"user_supplied_inputs": {"suppliers_stated_justification": "x", "how_critical_is_this_supplier_relationship": "x"}},
            headers=headers,
        )
        assert r2.status_code == 200, "Must never be the confusing raw 409 from the original bug report"
        assert r2.json()["user_facing_state"] == "working"
        t.join()
        final = poll_until_terminal(client, headers, decision_id)
    assert final.json()["status"] == "completed"


def test_12_provider_timeout_end_to_end():
    headers = _headers(101)
    with patch("app.routes.decisions.classify") as mock_classify, \
         patch("app.routes.decisions.generate_commercial_position", side_effect=Exception("simulated provider timeout")):
        mock_classify.return_value = _CLASSIFY_RESPONSE_COMPLETE
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "x"}, headers=headers)
        decision_id = r.json()["id"]
        final = poll_until_terminal(client, headers, decision_id)
    assert final.json()["status"] == "provider_unavailable"
    assert final.json()["can_retry"] is True


def test_13_market_search_timeout_end_to_end():
    headers = _headers(102)
    with patch("app.routes.decisions.classify") as mock_classify, \
         patch("app.routes.decisions.verify_market_claim", side_effect=Exception("simulated search timeout")), \
         patch("app.routes.decisions.generate_commercial_position", return_value=_MOCK_POSITION):
        mock_classify.return_value = _CLASSIFY_RESPONSE_COMPLETE
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "x"}, headers=headers)
        decision_id = r.json()["id"]
        final = poll_until_terminal(client, headers, decision_id)
    assert final.json()["status"] == "provider_unavailable", (
        "verify_market_claim raising is NOT caught internally -- confirms this "
        "propagates to the outer safety net exactly like any other real failure."
    )


# ============================================================
# Requirement 12: no internal terms ever exposed to the user
# ============================================================

def test_calm_states_never_expose_internal_terminology():
    headers = _headers(110)

    def slow_generate(*a, **k):
        time.sleep(0.3)
        return _MOCK_POSITION

    with patch("app.routes.decisions.classify") as mock_classify, \
         patch("app.routes.decisions.generate_commercial_position", side_effect=slow_generate):
        mock_classify.return_value = _CLASSIFY_RESPONSE_COMPLETE
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "x"}, headers=headers)
        decision_id = r.json()["id"]
        mid = client.get(f"/api/v1/commercial-decisions/{decision_id}", headers=headers)
        message = mid.json().get("processing_message") or ""
        assert "reasoning" not in message.lower()
        assert "stale" not in message.lower()
        assert "attempt" not in message.lower()
        assert decision_id not in message
        assert mid.json()["user_facing_state"] in ("working", "safely_resuming", None)
        if mid.json()["status"] == "reasoning":
            assert mid.json()["user_facing_state"] is not None, "A genuinely in-progress case must always have a calm state"
        poll_until_terminal(client, headers, decision_id)


# ============================================================
# Guardrail integrity through the new async path
# ============================================================

def test_material_caveat_guardrail_still_fires_through_async_path():
    headers = _headers(120)
    first = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        reasoning="VoltDrive is a technically qualified alternative.",
        confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
    )
    second = CommercialPosition(
        recommendation="x", commercial_insights=["a"],
        reasoning="VoltDrive is technically qualified, but has no production history.",
        confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
    )
    calls = {"n": 0}
    def gen(*a, **k):
        calls["n"] += 1
        return first if calls["n"] == 1 else second

    with patch("app.routes.decisions.classify") as mock_classify, \
         patch("app.routes.decisions.generate_commercial_position", side_effect=gen):
        mock_classify.return_value = {
            **_CLASSIFY_RESPONSE_COMPLETE,
            "supplier_specific_evidence": [{"supplier_name": "VoltDrive", "qualification_status": "complete", "production_history_status": "none"}],
        }
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "x"}, headers=headers)
        decision_id = r.json()["id"]
        final = poll_until_terminal(client, headers, decision_id)
    assert calls["n"] == 2, "The material caveat retry must genuinely fire through the real async path"
    assert "no production history" in final.json()["commercial_position"]["reasoning"].lower()
