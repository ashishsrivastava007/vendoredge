"""
P0 fix -- cross-journey request isolation.

Root cause, found by direct reproduction: the four journey-specific
answer fields (supplier_request_answer, commercial_signal_answer,
category_strategy_answer, problem_solving_answer) were only ever
conditionally SET when the current case_mode matched -- never
explicitly cleared otherwise. Request isolation depended on the
position object always starting with these fields empty, which is an
assumption, not a guarantee. Confirmed directly: a position object
that already carried a value in one of these fields from a prior
mutation carried it straight through into a response for a completely
different journey. Fixed by explicitly resetting all four to None,
unconditionally, before any mode-specific composition block runs.

This test reproduces the exact failure condition (a single position
object reused/mutated across multiple requests in the same process --
the worst case, stronger than anything ordinary request handling would
produce) specifically so the regression guard does not depend on the
bug's precise real-world trigger ever being understood or reproduced
again the same way.
"""
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor

client = TestClient(app)
_CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")

_JOURNEY_ANSWER_FIELDS = ("supplier_request_answer", "commercial_signal_answer", "category_strategy_answer", "problem_solving_answer")

_SIGNAL_CLASSIFY = {
    "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
    "extracted_evidence": {"supplier_currency": "USD"},
    "numeric_facts": {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 900_000},
    "supplier_specific_evidence": [],
}
_SUPPLIER_CLASSIFY = {
    "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
    "extracted_evidence": {"supplier_currency": "USD", "suppliers_stated_justification": "General pressures.", "how_critical_is_this_supplier_relationship": "sole-source"},
    "numeric_facts": {"annual_spend_usd": 1_000_000, "requested_change_percent": 8.0},
    "supplier_specific_evidence": [{"supplier_name": "S1", "is_incumbent": True}],
}
_PROBLEM_CLASSIFY = {
    "content_type": "problem_solving", "decision_type": "optimization", "constraint_satisfaction_signal": None,
    "extracted_evidence": {
        "problem_statement": "Cycle time has grown to 15 days.", "current_condition": "15 business days.", "desired_condition": "3 business days.",
        "root_cause_candidates": [{"label": "incomplete requests at intake", "category": "root_cause", "source": "internal_data", "supporting_evidence": ["Intake logs show 60% of requests returned for missing fields."]}],
    },
    "numeric_facts": {},
}


def _classify_for(journey: str) -> dict:
    return {"supplier_request": _SUPPLIER_CLASSIFY, "commercial_signal": _SIGNAL_CLASSIFY, "category_strategy": _SIGNAL_CLASSIFY, "problem_solving": _PROBLEM_CLASSIFY}[journey]


def _run(journey: str, suffix: int, shared_position=None):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"12.600.{suffix}.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    pos = shared_position or CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    body = {"raw_question": "test"}
    mode = None if journey == "problem_solving" else journey
    if mode:
        body["mode"] = mode
    with patch("app.pipeline.classifier.classify_case_mode_from_observation", return_value=journey if journey != "problem_solving" else None), \
         patch("app.routes.decisions.classify", return_value=_classify_for(journey)), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json=body, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    cp = d.get("commercial_position") or {}
    populated = {f for f in _JOURNEY_ANSWER_FIELDS if cp.get(f)}
    return populated


_EXPECTED_FIELD = {
    "supplier_request": "supplier_request_answer",
    "commercial_signal": "commercial_signal_answer",
    "category_strategy": "category_strategy_answer",
    "problem_solving": "problem_solving_answer",
}


def test_each_journey_in_isolation_populates_only_its_own_field():
    for i, journey in enumerate(["supplier_request", "commercial_signal", "category_strategy", "problem_solving"]):
        populated = _run(journey, 100 + i)
        assert populated == {_EXPECTED_FIELD[journey]}, f"{journey} populated {populated}, expected only {_EXPECTED_FIELD[journey]}"


def test_sequence_supplier_signal_strategy_problem_no_cross_contamination():
    order = ["supplier_request", "commercial_signal", "category_strategy", "problem_solving"]
    for i, journey in enumerate(order):
        populated = _run(journey, 200 + i)
        assert populated == {_EXPECTED_FIELD[journey]}, f"[order 1] {journey} populated {populated}"


def test_reversed_sequence_no_cross_contamination():
    order = ["problem_solving", "category_strategy", "commercial_signal", "supplier_request"]
    for i, journey in enumerate(order):
        populated = _run(journey, 300 + i)
        assert populated == {_EXPECTED_FIELD[journey]}, f"[reversed order] {journey} populated {populated}"


def test_interleaved_sequence_no_cross_contamination():
    order = ["commercial_signal", "supplier_request", "problem_solving", "commercial_signal", "category_strategy", "supplier_request"]
    for i, journey in enumerate(order):
        populated = _run(journey, 400 + i)
        assert populated == {_EXPECTED_FIELD[journey]}, f"[interleaved] case {i} ({journey}) populated {populated}"


def test_exact_originally_observed_failure_is_now_fixed():
    """The precise reproduction that originally showed the defect:
    commercial_signal followed by category_strategy using the SAME
    position object instance across both requests -- the worst-case
    stress, stronger than anything ordinary traffic would produce, so
    this guard does not depend on ever reproducing the bug's exact
    real-world trigger again."""
    shared_pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    populated_1 = _run("commercial_signal", 500, shared_position=shared_pos)
    assert populated_1 == {"commercial_signal_answer"}
    populated_2 = _run("category_strategy", 501, shared_position=shared_pos)
    assert populated_2 == {"category_strategy_answer"}, f"cross-contamination reproduced: {populated_2}"
    populated_3 = _run("commercial_signal", 502, shared_position=shared_pos)
    assert populated_3 == {"commercial_signal_answer"}


def test_repeated_requests_in_same_process_match_isolated_behavior():
    """Same case, same journey, run multiple times in the same process
    -- each response must contain exactly the same populated field as
    a single isolated call, proving repetition itself introduces no
    contamination."""
    for i in range(4):
        populated = _run("category_strategy", 600 + i)
        assert populated == {"category_strategy_answer"}
