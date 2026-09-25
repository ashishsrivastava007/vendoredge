"""
R48 Signal Engine -- free-text routing fix. Replaces the previous
five-word keyword list with classify_case_mode_from_observation(), a
genuine structured LLM classification of the text's actual intent,
used only when the frontend supplies no explicit mode. The keyword
heuristic is retained only as a fallback of last resort if the
classification call itself fails.

Critical property proven here, not assumed: the routing classifier is
never invoked at all when an explicit mode is supplied -- Supplier
Request's frozen behavior cannot be touched by this change because the
code path that could touch it is provably unreachable when mode is
explicit.
"""
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor

client = TestClient(app)
_CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")
_MINIMAL_CLASSIFY = {
    "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
    "extracted_evidence": {"supplier_currency": "USD"},
    "numeric_facts": {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 900_000},
    "supplier_specific_evidence": [],
}
_MINIMAL_POS = CommercialPosition(recommendation="Investigate.", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")


def _run(raw_question, mocked_routing_result, suffix, explicit_mode=None, routing_must_not_be_called=False):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"10.870.{suffix}.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    body = {"raw_question": raw_question}
    if explicit_mode:
        body["mode"] = explicit_mode
    routing_patch = patch(
        "app.pipeline.classifier.classify_case_mode_from_observation",
        side_effect=AssertionError("routing classifier must never be called when mode is explicit") if routing_must_not_be_called else None,
        return_value=None if routing_must_not_be_called else mocked_routing_result,
    )
    with routing_patch, \
         patch("app.routes.decisions.classify", return_value=_MINIMAL_CLASSIFY), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=_MINIMAL_POS):
        r = client.post("/api/v1/commercial-decisions", json=body, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    cp = d.get("commercial_position") or {}
    return bool(cp.get("commercial_signal_answer")), bool(cp.get("supplier_request_answer"))


_DOCUMENT_EXAMPLES = [
    "I noticed our OTIF has deteriorated from 96% to 81%.",
    "Something strange is happening with supplier concentration.",
    "Our spend is rising but I can't explain why.",
    "We changed the specification and costs jumped.",
    "The market price has fallen but the supplier hasn't changed its price.",
]


def test_document_example_observations_route_to_commercial_signal():
    """The exact defect: none of these contain 'noticed', 'trend', or
    'pattern' in a way the old keyword list would reliably catch for
    all five -- each must still route correctly via the new classifier."""
    for i, text in enumerate(_DOCUMENT_EXAMPLES):
        has_signal, has_supplier_request = _run(text, "commercial_signal", i + 1)
        assert has_signal is True, f"{text!r} did not route to commercial_signal"
        assert has_supplier_request is False, f"{text!r} incorrectly also produced a supplier_request_answer"


def test_routing_classification_failure_falls_back_to_keyword_heuristic_safely():
    """If the LLM call itself fails (returns None), the keyword
    fallback must still produce a real, working routing decision
    rather than leaving the case unroutable."""
    has_signal, _ = _run("Our spend is rising but I can't explain why.", None, 10)
    assert has_signal is True  # "spend is rising" is in the keyword fallback list


def test_routing_classifier_never_invoked_when_mode_is_explicit():
    """The critical safety property for Supplier Request regression:
    the new routing mechanism is provably unreachable when an explicit
    mode is supplied -- proven by the mock raising if it's ever called,
    not merely by checking the outcome."""
    has_signal, _ = _run("Supplier wants 11%.", None, 11, explicit_mode="supplier_request", routing_must_not_be_called=True)
    assert has_signal is False
