"""
Regression tests for the live-test defect report (Supplier B, 12% request,
"increase in raw material costs over the past year", no cost evidence).

Observed: VendorEdge advised "negotiate any adjustment down toward
mid-single digits", the Model Review Gate did not activate, a "Not stated"
criticality was shown as VERIFIED, market driver claims rendered as the
default object-tag string, the supplier draft section was empty, and
negotiation target/walk_away were blank strings.

Root causes (each fixed generically, none keyed to 12% or raw materials):
1. The strategy-number checks matched only digit percentages, so a verbal
   range ("mid-single digits") passed; the sanitizer never covered
   opening_position; and it ran only as a side effect of an unrelated retry.
2. The Model Review Gate triggered only on case complexity/size, never on
   evidence sufficiency; its verdict changed a label but never confidence.
3. The Trust Engine derived state from provenance source, never the value.
4. A frontend summary interpolated structured values directly.
5. The draft was suppressed for "investigate" recommendations.
6. Withheld target/walk_away were serialised as None/blank.

What these tests prove vs. not: every deterministic path is exercised for
real, including the HTTP route. No live model is available, so where a
challenger opinion is needed it is scripted; the tests prove the gate
fires, the challenger receives the conflicting evidence, and whatever the
challenger reports is enforced -- not what a real model would say.
"""
import json
import re
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.claim_integrity import check_unsupported_strategy_numbers, sanitize_unsupported_strategy_numbers
from app.pipeline.model_orchestration import (
    ChallengerOpinion, apply_challenger_outcome, build_model_orchestration, challenge_trigger, run_challenger,
)
from app.pipeline.normalize import normalize_evidence
from app.pipeline.trust_engine import build_trust_engine

client = TestClient(app)
INDEX_HTML = Path(__file__).parents[1] / "app" / "static" / "index.html"

SUPPLIER_B_QUESTION = (
    "Supplier B has requested a 12% price increase citing increase in raw material costs over the past year. "
    "Current price is USD 100/unit. No cost breakdown has been provided."
)


def _conf(level="high"):
    return Confidence(level=level, factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _position(opening=None, walk_away=None, level="high", recommendation="Challenge the increase before agreeing to any adjustment."):
    return CommercialPosition(
        recommendation=recommendation, commercial_insights=["a"], reasoning="x", confidence=_conf(level),
        assumptions=["a"], disconfirming_condition="New supplier cost evidence would change this.",
        decision_type="optimization", opening_position=opening, walk_away_threshold=walk_away,
    )


def _supplier_b_classification(extra_evidence=None, market_driver_claims=None, pct=12.0):
    ev = {
        "supplier_currency": "USD",
        "suppliers_stated_justification": "Increase in raw material costs over the past year.",
        "how_critical_is_this_supplier_relationship": "Not stated",
    }
    ev.update(extra_evidence or {})
    c = {
        "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": ev,
        "numeric_facts": {"unit_price_usd": 100, "annual_spend_usd": 1_200_000, "requested_change_percent": pct},
        "supplier_specific_evidence": [{"supplier_name": "Supplier B", "is_incumbent": True}],
    }
    if market_driver_claims is not None:
        c["market_driver_claims"] = market_driver_claims
    return c


def _run_http(question, classification, position, suffix, challenger=None):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"10.915.{suffix}.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}

    def _unavailable(*a, **kw):
        raise RuntimeError("challenger provider unavailable in test")

    with patch("app.routes.decisions.classify", return_value=classification), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=position), \
         patch("app.routes.decisions.run_challenger", side_effect=challenger or _unavailable):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": question}, headers=headers)
        d = None
        for _ in range(40):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    assert d["status"] == "completed", d.get("status")
    return d["commercial_position"]


def _percents(text):
    return set(re.findall(r"\d+(?:\.\d+)?\s*%", text or ""))


# ---------------------------------------------------------------------
# Case A -- 12% request, no evidence -> no numerical counter-target
# ---------------------------------------------------------------------

def test_A_no_evidence_no_numeric_counter_target_end_to_end():
    pos = _position(opening="We would like to negotiate any adjustment down toward mid-single digits.")
    cp = _run_http(SUPPLIER_B_QUESTION, _supplier_b_classification(), pos, 1)
    opening = cp.get("opening_position") or ""
    assert "single digit" not in opening.lower() and "single-digit" not in opening.lower()
    assert opening == "No defensible counter-price can be established from the evidence currently available."
    sra = cp["supplier_request_answer"]
    for field in ("target", "walk_away"):
        assert sra[field], f"{field} must never be blank"
        assert "not determinable" in sra[field].lower()
        assert _percents(sra[field]) <= {"12%"}
    # The internal "no defensible counter-price" note must not leak into the supplier email.
    draft = sra["draft_response"]
    assert draft is not None and "no defensible" not in draft["body"].lower()
    assert _percents(draft["body"]) <= {"12%"}


@pytest.mark.parametrize("phrase", [
    "mid-single digits", "low single digits", "high single-digit", "low double digits",
    "a few percent", "a couple of percent", "several percentage points",
])
def test_A_verbal_numeric_ranges_are_detected_and_removed(phrase):
    pos = _position(opening=f"Aim to settle in the {phrase} range.")
    assert check_unsupported_strategy_numbers(pos, None, SUPPLIER_B_QUESTION)
    assert "opening_position" in sanitize_unsupported_strategy_numbers(pos, SUPPLIER_B_QUESTION)
    assert phrase.split()[0] not in pos.opening_position.lower() or "no defensible" in pos.opening_position.lower()


@pytest.mark.parametrize("pct,question_driver", [(7.0, "freight"), (15.0, "labour"), (4.0, "energy")])
def test_A_generic_across_other_requests_not_just_12_percent(pct, question_driver):
    q = f"Supplier requests a {pct:g}% increase citing {question_driver} costs. No breakdown given."
    pos = _position(opening="Counter at 3% and hold there.", walk_away="Walk away above 5%.")
    assert check_unsupported_strategy_numbers(pos, None, q)
    changed = sanitize_unsupported_strategy_numbers(pos, q)
    assert {"opening_position", "walk_away_threshold"} <= set(changed)
    assert _percents(pos.opening_position) == set() and _percents(pos.walk_away_threshold) == set()


def test_A_qualitative_language_is_not_over_blocked():
    pos = _position(opening="Push for a materially lower adjustment, conditional on cost evidence.")
    assert check_unsupported_strategy_numbers(pos, None, SUPPLIER_B_QUESTION) == []


# ---------------------------------------------------------------------
# Case B -- documented weighted cost drivers and indices -> numbers allowed
# ---------------------------------------------------------------------

WEIGHTED_QUESTION = (
    "Supplier requests an 8% increase. Steel is 60% of unit cost and the steel index rose 10%; "
    "labour is 40% of unit cost and rose 5%. Weighted impact: 60% x 10% + 40% x 5% = 8%."
)
WEIGHTED_DRIVERS = [
    {"driver": "steel", "direction": "increased", "magnitude": "10%", "attributed_to": "supplier", "stated_cost_share_percent": 60},
    {"driver": "labour", "direction": "increased", "magnitude": "5%", "attributed_to": "supplier", "stated_cost_share_percent": 40},
]


def test_B_documented_weighted_drivers_allow_numeric_analysis():
    pos = _position(opening="The documented weighted impact of 60% steel at 10% and 40% labour at 5% supports 8%.")
    assert check_unsupported_strategy_numbers(pos, None, WEIGHTED_QUESTION) == []
    assert sanitize_unsupported_strategy_numbers(pos, WEIGHTED_QUESTION) == []
    assert "8%" in pos.opening_position


def test_B_substantiated_justification_does_not_raise_unverified_trigger():
    ne, _ = normalize_evidence(
        WEIGHTED_QUESTION, "price_increase",
        {"supplier_currency": "USD", "suppliers_stated_justification": "Steel and labour cost increases."},
        {"annual_spend_usd": 1_000_000, "requested_change_percent": 8.0},
        supplier_specific_evidence=[{"supplier_name": "S", "is_incumbent": True}],
        market_driver_claims=WEIGHTED_DRIVERS,
    )
    _, reasons = challenge_trigger(ne, _position())
    assert not any("justification is unverified" in r for r in reasons)


def test_B_end_to_end_numeric_opening_survives_when_evidenced():
    pos = _position(opening="The documented weighted impact supports 8%, not more.", level="medium")
    cp = _run_http(WEIGHTED_QUESTION, _supplier_b_classification(
        {"how_critical_is_this_supplier_relationship": "sole-source"}, WEIGHTED_DRIVERS, pct=8.0), pos, 2)
    assert "8%" in (cp.get("opening_position") or "")


# ---------------------------------------------------------------------
# Case C -- justification contradicted by relevant evidence
# ---------------------------------------------------------------------

def _contradiction_normalized():
    ne, _ = normalize_evidence(
        "Supplier claims steel costs rose 10% and requests 10%. Our steel index data shows steel fell 8% over the same period.",
        "price_increase",
        {"supplier_currency": "USD", "suppliers_stated_justification": "Steel costs rose 10%."},
        {"annual_spend_usd": 500_000, "requested_change_percent": 10.0},
        supplier_specific_evidence=[{"supplier_name": "S", "is_incumbent": True}],
        market_driver_claims=[
            {"driver": "steel", "direction": "increased", "magnitude": "10%", "attributed_to": "supplier"},
            {"driver": "steel", "direction": "decreased", "magnitude": "8%", "attributed_to": "buyer_cited"},
        ],
    )
    return ne


def test_C_gate_fires_and_challenger_receives_both_sides_of_the_contradiction():
    ne = _contradiction_normalized()
    pos = _position(level="medium")
    pos.market_verification = {"finding": "Steel index fell 8% over the period.", "scope": "market"}
    should, reasons = challenge_trigger(ne, pos)
    assert should
    assert any("external market context" in r for r in reasons)
    assert any("justification is unverified" in r for r in reasons)

    captured = {}

    class _FakeMessages:
        def create(self, **kw):
            captured["prompt"] = kw["messages"][0]["content"]
            captured["system"] = kw["system"]

            class R:
                content = [type("B", (), {"text": json.dumps({
                    "challenge_level": "critical", "verdict": "requires_human_review",
                    "challenged_claims": ["Supplier claims steel rose 10%, but buyer-cited index shows steel fell 8%."],
                })})()]
                usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()
            return R()

    with patch("app.pipeline.model_orchestration._get_client", return_value=type("C", (), {"messages": _FakeMessages()})()):
        opinion = run_challenger(ne, pos)
    prompt = captured["prompt"].lower()
    assert "increased" in prompt and "decreased" in prompt and "fell 8%" in prompt
    assert "market_context_treated_as_supplier_evidence" in captured["system"] or "MANDATORY CHECKS" in captured["system"]

    pos.model_orchestration = build_model_orchestration(ne, pos, opinion=opinion, trigger_reasons=reasons)
    assert pos.model_orchestration["challenged_claims"]
    assert "fell 8%" in pos.model_orchestration["challenged_claims"][0]
    apply_challenger_outcome(pos, "")
    assert pos.confidence.level == "low"
    assert any("challenger" in f.factor.lower() for f in pos.confidence.factors)


# ---------------------------------------------------------------------
# Case D -- missing supplier criticality -> UNKNOWN, never VERIFIED
# ---------------------------------------------------------------------

@pytest.mark.parametrize("absent", ["Not stated", "not stated.", "N/A", "Unknown", "not provided", ""])
def test_D_absent_criticality_is_unknown_never_verified(absent):
    ne, _ = normalize_evidence(
        SUPPLIER_B_QUESTION, "price_increase",
        {"supplier_currency": "USD", "suppliers_stated_justification": "Raw materials.",
         "how_critical_is_this_supplier_relationship": absent},
        {"unit_price_usd": 100, "requested_change_percent": 12.0},
        supplier_specific_evidence=[{"supplier_name": "Supplier B", "is_incumbent": True}],
    )
    ledger = build_trust_engine(ne, _position())
    crit = [e for e in ledger["entries"] if e["field"] == "how_critical_is_this_supplier_relationship"]
    for e in crit:
        assert e["state"] == "UNKNOWN"
        assert e["state"] != "VERIFIED"


def test_D_real_criticality_value_remains_verified():
    ne, _ = normalize_evidence(
        SUPPLIER_B_QUESTION, "price_increase",
        {"supplier_currency": "USD", "suppliers_stated_justification": "Raw materials.",
         "how_critical_is_this_supplier_relationship": "sole-source, critical to production"},
        {"unit_price_usd": 100, "requested_change_percent": 12.0},
        supplier_specific_evidence=[{"supplier_name": "Supplier B", "is_incumbent": True}],
    )
    ledger = build_trust_engine(ne, _position())
    crit = [e for e in ledger["entries"] if e["field"] == "how_critical_is_this_supplier_relationship"]
    assert crit and all(e["state"] == "VERIFIED" for e in crit)


def test_D_counts_match_the_returned_ledger_exactly_and_states_are_distinct():
    ne, _ = normalize_evidence(
        SUPPLIER_B_QUESTION, "price_increase",
        {"supplier_currency": "USD", "suppliers_stated_justification": "Raw materials.",
         "how_critical_is_this_supplier_relationship": "Not stated"},
        {"unit_price_usd": 100, "requested_change_percent": 12.0},
        supplier_specific_evidence=[{"supplier_name": "Supplier B", "is_incumbent": True}],
    )
    pos = _position()
    pos.market_verification = {"finding": "Commodity index rose.", "scope": "market"}
    ledger = build_trust_engine(ne, pos)
    recount = {}
    for e in ledger["entries"]:
        recount[e["state"]] = recount.get(e["state"], 0) + 1
    for state, n in ledger["counts"].items():
        assert recount.get(state, 0) == n, state
    assert sum(ledger["counts"].values()) == len(ledger["entries"]) == ledger["entry_count"]
    market = [e for e in ledger["entries"] if e["field"] == "external_market_context"]
    assert market and market[0]["state"] == "EXTERNAL_MARKET_EVIDENCE"


# ---------------------------------------------------------------------
# Case E -- structured market-driver object renders readably
# ---------------------------------------------------------------------

def _extract_js_function(name):
    text = INDEX_HTML.read_text()
    start = text.index(f"function {name}(")
    depth, i = 0, text.index("{", start)
    while True:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1


def test_E_market_driver_claims_render_human_readable():
    fn = _extract_js_function("humanReadableValue")
    claims = [{"driver": "raw materials", "direction": "increased", "magnitude": None, "attributed_to": "supplier"}]
    script = fn + f"\nconsole.log(humanReadableValue({json.dumps(claims)}));\nconsole.log(`${{{json.dumps(claims)}}}`);"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout.splitlines()
    assert out[0] == "driver: raw materials, direction: increased, attributed to: supplier"
    assert out[1] == "[object " + "Object]"  # proves the raw interpolation was the defect


def test_E_evidence_summary_uses_the_formatter_and_no_object_tag_ships():
    text = INDEX_HTML.read_text()
    assert "${humanReadableValue(currentEvidence[k])}" in text
    assert "${currentEvidence[k]}`" not in text
    assert "[object " + "Object]" not in text


# ---------------------------------------------------------------------
# Case F -- weak evidence -> Model Review Gate activates
# ---------------------------------------------------------------------

def test_F_weak_evidence_activates_gate_and_caps_confidence_end_to_end():
    pos = _position(level="high", recommendation="Challenge the 12% until Supplier B provides a cost breakdown.")
    cp = _run_http(SUPPLIER_B_QUESTION, _supplier_b_classification(), pos, 3)
    orch = cp["model_orchestration"]
    assert orch["challenger_invoked"] is True
    assert orch["review_required"] is True
    assert any("justification is unverified" in r for r in orch["trigger_reasons"])
    # A warranted-but-unavailable second opinion must not leave high confidence standing.
    assert cp["confidence"]["level"] in ("medium", "low")


def test_F_challenger_flagged_target_is_removed_even_when_pattern_check_misses_it():
    """The challenger quotes a phrasing the deterministic pattern does not
    recognise; its quote is used only as a locator for removal."""
    q = "Supplier requests 9% citing packaging costs."
    pos = _position(opening="Counter at around five points below their ask.")
    assert check_unsupported_strategy_numbers(pos, None, q) == []  # pattern alone misses it
    pos.model_orchestration = {
        "challenger_invoked": True, "mode": "DUAL_MODEL_REVIEW", "challenge_level": "material",
        "verdict": "supports_with_caveat", "unsupported_numeric_targets": ["around five points below their ask"],
    }
    actions = apply_challenger_outcome(pos, q)
    assert "challenger_located:opening_position" in actions
    assert "five points" not in pos.opening_position
    assert pos.confidence.level == "low"


def test_F_challenger_never_raises_confidence():
    pos = _position(level="low")
    pos.model_orchestration = {"challenger_invoked": True, "mode": "DUAL_MODEL_REVIEW",
                               "challenge_level": "none", "verdict": "supports_primary"}
    assert apply_challenger_outcome(pos, "") == []
    assert pos.confidence.level == "low"


def test_F_strong_evidence_single_supplier_does_not_force_the_gate():
    ne, _ = normalize_evidence(
        WEIGHTED_QUESTION, "price_increase",
        {"supplier_currency": "USD", "suppliers_stated_justification": "Steel and labour.",
         "how_critical_is_this_supplier_relationship": "sole-source"},
        {"annual_spend_usd": 50_000, "requested_change_percent": 8.0},
        supplier_specific_evidence=[{"supplier_name": "S", "is_incumbent": True}],
        market_driver_claims=WEIGHTED_DRIVERS,
    )
    should, reasons = challenge_trigger(ne, _position(level="medium"))
    assert not should, reasons
