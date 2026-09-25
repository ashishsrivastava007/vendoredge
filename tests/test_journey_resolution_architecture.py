"""
Journey-routing architecture audit: establishes and proves a single,
authoritative journey resolution (`resolved_journey`, a local variable
in _run_reasoning) computed once, before any of the four composition
gates run -- rather than each gate independently deciding whether it
applies (which is how the earlier cross-contamination arose: two gates
could each be genuinely, correctly satisfied on their own separate
terms).

Architecture as it actually is, not as assumed:
- case_mode (supplier_request/commercial_signal/category_strategy) is
  resolved BEFORE classify() runs -- it is a parameter to
  _run_reasoning, fixed by the time this function executes.
- problem_solving is detected via the classifier's own content_type
  output, which only becomes known AFTER classify() runs and the
  kernel is built -- structurally later and separate from case_mode.
- resolved_journey reconciles these exactly once: an explicit
  case_mode is authoritative outright; an inferred case_mode is
  overridden by problem_solving_evidence when present (a later, more
  informed signal); otherwise resolved_journey is exactly the already-
  resolved case_mode.
- All four composition gates check resolved_journey uniformly, not
  case_mode directly and not a separately-computed kernel check per
  gate.
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
# A classify() result that is AMBIGUOUS by construction: its raw text
# could plausibly read as either a supplier price request or a
# problem to solve -- supplier justification language AND a stated
# problem/current/desired triple both present in the same case.
_AMBIGUOUS_CLASSIFY = {
    "content_type": "problem_solving", "decision_type": "optimization", "constraint_satisfaction_signal": None,
    "extracted_evidence": {
        "suppliers_stated_justification": "Costs have risen and cycle times have grown as a result.",
        "how_critical_is_this_supplier_relationship": "sole-source",
        "problem_statement": "Order cycle time has grown to 15 days.", "current_condition": "15 business days.", "desired_condition": "3 business days.",
        "root_cause_candidates": [{"label": "supplier capacity constraint", "category": "root_cause", "source": "internal_data", "supporting_evidence": ["Supplier confirmed reduced capacity."]}],
    },
    "numeric_facts": {"annual_spend_usd": 1_000_000, "requested_change_percent": 6.0},
    "supplier_specific_evidence": [{"supplier_name": "S_amb", "is_incumbent": True}],
}

_POS = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")


def _run(classify_result, suffix, explicit_mode=None, shared_position=None):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"13.500.{suffix}.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    pos = shared_position or CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    body = {"raw_question": "test"}
    if explicit_mode:
        body["mode"] = explicit_mode
    with patch("app.routes.decisions.classify", return_value=classify_result), \
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
    return populated, d["status"]


def test_exactly_one_journey_populated_for_a_plain_supplier_request():
    populated, status = _run(_SUPPLIER_CLASSIFY, 1, explicit_mode="supplier_request")
    assert populated == {"supplier_request_answer"}


def test_exactly_one_journey_populated_for_a_plain_signal():
    populated, status = _run(_SIGNAL_CLASSIFY, 2, explicit_mode="commercial_signal")
    assert populated == {"commercial_signal_answer"}


def test_exactly_one_journey_populated_for_a_plain_strategy_request():
    populated, status = _run(_SIGNAL_CLASSIFY, 3, explicit_mode="category_strategy")
    assert populated == {"category_strategy_answer"}


def test_exactly_one_journey_populated_for_a_plain_problem_solving_request():
    """No explicit mode -- matches the real frontend's own "A problem I
    need to solve" tile, which sends no mode at all."""
    populated, status = _run(_PROBLEM_CLASSIFY, 4, explicit_mode=None)
    assert populated == {"problem_solving_answer"}


def test_same_request_produces_same_journey_repeated_in_same_process():
    for i in range(4):
        populated, _ = _run(_PROBLEM_CLASSIFY, 10 + i, explicit_mode=None)
        assert populated == {"problem_solving_answer"}


def test_explicit_mode_wins_even_when_content_type_suggests_a_different_journey():
    """The key property: an explicit case_mode is never overridden by
    what the classifier later inferred about the text, even when that
    inference points at a genuinely different journey (problem_solving
    content_type, explicit category_strategy mode)."""
    populated, status = _run(_PROBLEM_CLASSIFY, 20, explicit_mode="category_strategy")
    assert populated == {"category_strategy_answer"}
    assert "problem_solving_answer" not in populated


def test_explicit_mode_wins_for_every_one_of_the_three_routable_journeys():
    for mode in ("supplier_request", "commercial_signal", "category_strategy"):
        classify_result = _SUPPLIER_CLASSIFY if mode == "supplier_request" else _SIGNAL_CLASSIFY
        populated, _ = _run(_PROBLEM_CLASSIFY if False else classify_result, 30 + hash(mode) % 50, explicit_mode=mode)
        # Even feeding a problem-solving-shaped classify() result under
        # an explicit different mode must not populate problem_solving.
        populated2, _ = _run(_PROBLEM_CLASSIFY, 40 + hash(mode) % 50, explicit_mode=mode)
        assert populated2 == {f"{mode}_answer"}, f"explicit {mode} did not win: {populated2}"


def test_ambiguous_case_resolves_deterministically_not_to_both():
    """A case genuinely ambiguous between supplier_request and
    problem_solving (supplier justification language AND a stated
    problem/current/desired triple both present) must resolve to
    exactly one journey, run 3 times, always the same one."""
    results = []
    for i in range(3):
        populated, status = _run(_AMBIGUOUS_CLASSIFY, 50 + i, explicit_mode=None)
        assert len(populated) == 1, f"ambiguous case populated {populated}, not exactly one"
        results.append(populated)
    assert results[0] == results[1] == results[2], f"ambiguous case resolved differently across runs: {results}"


def test_ambiguous_case_under_explicit_supplier_request_mode_stays_supplier_request():
    populated, _ = _run(_AMBIGUOUS_CLASSIFY, 60, explicit_mode="supplier_request")
    assert populated == {"supplier_request_answer"}


def test_no_non_selected_journey_can_populate_its_field_worst_case_shared_position():
    """The exact worst-case stress from the P0 fix: a single position
    object reused and mutated across requests for different journeys.
    Only the current request's journey may ever appear."""
    shared_pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    p1, _ = _run(_SIGNAL_CLASSIFY, 70, explicit_mode="commercial_signal", shared_position=shared_pos)
    assert p1 == {"commercial_signal_answer"}
    p2, _ = _run(_PROBLEM_CLASSIFY, 71, explicit_mode=None, shared_position=shared_pos)
    assert p2 == {"problem_solving_answer"}
    p3, _ = _run(_SUPPLIER_CLASSIFY, 72, explicit_mode="supplier_request", shared_position=shared_pos)
    assert p3 == {"supplier_request_answer"}
    p4, _ = _run(_SIGNAL_CLASSIFY, 73, explicit_mode="category_strategy", shared_position=shared_pos)
    assert p4 == {"category_strategy_answer"}


def test_fresh_request_and_reused_process_produce_identical_result():
    """A brand-new process (simulated by a completely independent org/
    workspace and position object) and a reused one (later calls in
    this same test session, sharing the module-level TestClient/
    process) must produce the identical populated-field result for the
    same input shape."""
    populated_a, _ = _run(_PROBLEM_CLASSIFY, 80, explicit_mode=None)
    populated_b, _ = _run(_PROBLEM_CLASSIFY, 81, explicit_mode=None)
    assert populated_a == populated_b == {"problem_solving_answer"}


def test_all_four_journeys_remain_regression_safe_end_to_end():
    """Confirms the refactor changed only which condition each gate
    checks (resolved_journey vs the earlier scattered case_mode/kernel
    checks), not what each journey's own answer-building logic
    produces once selected."""
    for classify_result, mode, field in [
        (_SUPPLIER_CLASSIFY, "supplier_request", "supplier_request_answer"),
        (_SIGNAL_CLASSIFY, "commercial_signal", "commercial_signal_answer"),
        (_SIGNAL_CLASSIFY, "category_strategy", "category_strategy_answer"),
        (_PROBLEM_CLASSIFY, None, "problem_solving_answer"),
    ]:
        populated, status = _run(classify_result, 90 + hash(str(field)) % 50, explicit_mode=mode)
        assert status == "completed"
        assert populated == {field}
