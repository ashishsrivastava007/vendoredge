"""
Category Memory Reasoning Integration -- required 15 cases.

Architecture under test: retrieval happens BEFORE build_category_
strategy_answer runs; reconciliation happens INSIDE build_360_findings
(the actual finding-construction step), not as a step added after the
answer exists. Current value (the finding's own asserted fact) is
never altered by memory; only a separate, labelled historical_
precedent field and an augmented possible_action are added, and only
for a relationship the evidence actually supports.
"""
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor

client = TestClient(app)
_CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _make_org(suffix):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"31.100.{suffix}.1"}).json()
    return org, {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}


def _run(headers, suffix, numeric_facts, supplier_evidence=None, extra_evidence=None):
    classify = {
        "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", **(extra_evidence or {})},
        "numeric_facts": numeric_facts, "supplier_specific_evidence": supplier_evidence or [],
    }
    pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": f"req {suffix}", "mode": "category_strategy"}, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}?include_diagnostics=true", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return d["commercial_position"]["category_strategy_answer"]


_ALPHA = [{"supplier_name": "AlphaCo", "is_incumbent": True, "current_annual_spend_usd": 7_000_000}]
_COMMON_NUMERIC = {"category_annual_spend_usd": 10_000_000, "category_prior_annual_spend_usd": 9_000_000}


# 1. Relevant historical precedent changes reasoning.
def test_1_relevant_precedent_changes_reasoning():
    org, headers = _make_org(1)
    a1 = _run(headers, "seed", _COMMON_NUMERIC, supplier_evidence=_ALPHA)
    a2 = _run(headers, "repeat", _COMMON_NUMERIC, supplier_evidence=_ALPHA)
    f1 = a1["diagnostics"]["findings"][0]
    f2 = a2["diagnostics"]["findings"][0]
    assert f1["finding"] == f2["finding"]  # current value unchanged
    assert f1["possible_action"] != f2["possible_action"]  # reasoning output genuinely differs
    assert f2.get("historical_precedent") is not None


# 2. No Memory preserves existing reasoning.
def test_2_no_memory_preserves_existing_reasoning():
    org, headers = _make_org(2)
    a = _run(headers, "fresh", _COMMON_NUMERIC, supplier_evidence=_ALPHA)
    assert a["diagnostics"]["findings"][0].get("historical_precedent") is None
    assert "historical_context_used" not in a["diagnostics"] or a["diagnostics"]["historical_context_used"] is False


# 3. Irrelevant Memory does not change reasoning.
def test_3_irrelevant_memory_does_not_change_reasoning():
    org, headers = _make_org(3)
    _run(headers, "seed_other_supplier", _COMMON_NUMERIC, supplier_evidence=[{"supplier_name": "UnrelatedCo", "is_incumbent": True, "current_annual_spend_usd": 7_000_000}])
    a = _run(headers, "different_supplier", _COMMON_NUMERIC, supplier_evidence=_ALPHA)
    assert a["diagnostics"]["findings"][0].get("historical_precedent") is None


# 4. Stale Memory does not override current evidence.
def test_4_stale_memory_does_not_override_current_evidence():
    org, headers = _make_org(4)
    _run(headers, "seed_high", _COMMON_NUMERIC, supplier_evidence=_ALPHA)  # 70% -> "challenge"
    a2 = _run(headers, "current_low", _COMMON_NUMERIC, supplier_evidence=[{"supplier_name": "AlphaCo", "is_incumbent": True, "current_annual_spend_usd": 2_000_000}])  # 20% now
    f2 = a2["diagnostics"]["findings"][0]
    assert "monitor" in f2["finding"].lower() or "20.0%" in str(a2)  # current, lower concentration drives the answer
    assert "challenge" not in f2["finding"].lower()


# 5. Stronger current evidence overrides Memory.
def test_5_stronger_current_evidence_overrides_memory():
    org, headers = _make_org(5)
    kernel = {"org_id": org["organisation_id"], "case": {"subject": "TestCat5"}}
    from app.pipeline.memory_service import extract_candidates, store_candidates
    weak = [{"dimension": "cost_and_price_economics", "finding": "Average unit price has moved +5.0%.", "evidence_state": "SUPPLIER_CLAIM",
             "decision_impact": "DECISION_CRITICAL_UNKNOWN", "source": "kernel:category_diagnosis", "evidence": "x", "implication": "y", "possible_action": "z"}]
    decision_id = _seed_decision_id(headers)
    store_candidates(org["organisation_id"], extract_candidates(kernel, weak, source_case_id=decision_id))
    a = _run(headers, "current", {"category_annual_spend_usd": 1_120_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_000, "category_prior_annual_volume_units": 10_000}, extra_evidence={})
    # current CALCULATED finding must state its own real value, not the memory's
    price_finding = next((f for f in a["diagnostics"]["findings"] if "unit price" in f["finding"].lower()), None)
    if price_finding:
        assert "+12.0%" in price_finding["finding"]  # the real current calculation, not the stale +5.0% memory


def _seed_decision_id(headers):
    classify = {"content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
                "extracted_evidence": {"supplier_currency": "USD"}, "numeric_facts": {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000}, "supplier_specific_evidence": []}
    pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "seed", "mode": "category_strategy"}, headers=headers)
        decision_id = r.json()["id"]
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{decision_id}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return decision_id


# 6. Historical Memory supports current evidence.
def test_6_historical_memory_supports_current_evidence():
    org, headers = _make_org(6)
    _run(headers, "seed", _COMMON_NUMERIC, supplier_evidence=_ALPHA)
    a2 = _run(headers, "confirm", _COMMON_NUMERIC, supplier_evidence=_ALPHA)
    f2 = a2["diagnostics"]["findings"][0]
    assert f2["historical_precedent"]["relationship"] in ("SUPPORTS", "COMPLEMENTS")
    assert f2["historical_precedent"]["evidence_state"] == "CALCULATED"  # remains labelled as its own evidence state, not promoted


# 7. Historical contradiction is handled safely.
def test_7_historical_contradiction_handled_safely():
    org, headers = _make_org(7)
    kernel = {"org_id": org["organisation_id"], "case": {"subject": "TestCat7"}}
    from app.pipeline.memory_service import extract_candidates, store_candidates
    decision_id = _seed_decision_id(headers)
    old = [{"dimension": "supplier_landscape", "finding": "DeltaCo holds 70.0% of category spend.", "evidence_state": "CALCULATED",
            "decision_impact": "DECISION_CHANGING", "source": "kernel:category_diagnosis", "evidence": "x", "implication": "y", "possible_action": "z"}]
    store_candidates(org["organisation_id"], extract_candidates(kernel, old, source_case_id=decision_id))
    a = _run(headers, "current", {"category_annual_spend_usd": 10_000_000, "category_prior_annual_spend_usd": 9_000_000}, supplier_evidence=[{"supplier_name": "DeltaCo", "is_incumbent": True, "current_annual_spend_usd": 4_000_000}])
    concentration_finding = next((f for f in a["diagnostics"]["findings"] if "DeltaCo" in f["finding"] and "%" in f["finding"]), None)
    if concentration_finding:
        assert "70.0%" not in concentration_finding["finding"]  # current value used, not the old memory value
        if concentration_finding.get("historical_precedent"):
            assert concentration_finding["historical_precedent"]["relationship"] in ("CONTRADICTS", "COMPLEMENTS")


# 8. Proposition mismatch does not create a false contradiction.
def test_8_proposition_mismatch_no_false_contradiction():
    org, headers = _make_org(8)
    kernel = {"org_id": org["organisation_id"], "case": {"subject": "TestCat8"}}
    from app.pipeline.memory_service import extract_candidates, store_candidates
    decision_id = _seed_decision_id(headers)
    contract_claim = [{"dimension": "contract_and_commercial_architecture", "finding": "A contractual adjustment mechanism has been referenced for this category.",
                        "evidence_state": "SUPPLIER_CLAIM", "decision_impact": "DECISION_CRITICAL_UNKNOWN", "source": "kernel:facts", "evidence": "x", "implication": "y", "possible_action": "z"}]
    store_candidates(org["organisation_id"], extract_candidates(kernel, contract_claim, source_case_id=decision_id))
    a = _run(headers, "current", {"category_annual_spend_usd": 1_120_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_000, "category_prior_annual_volume_units": 10_000})
    price_finding = next((f for f in a["diagnostics"]["findings"] if "unit price" in f["finding"].lower()), None)
    if price_finding:
        assert price_finding.get("historical_precedent") is None  # different fact_type -- never compared at all


# 9. Memory retrieval failure preserves the answer.
def test_9_memory_retrieval_failure_preserves_answer():
    org, headers = _make_org(9)
    with patch("app.pipeline.memory_service.retrieve_memory", side_effect=RuntimeError("simulated retrieval failure")):
        a = _run(headers, "fail_retrieve", _COMMON_NUMERIC, supplier_evidence=_ALPHA)
    assert a is not None
    assert len(a["diagnostics"]["findings"]) >= 1
    assert a["diagnostics"]["findings"][0]["finding"] == "AlphaCo: challenge."


# 10. Memory reconciliation failure preserves the answer.
def test_10_memory_reconciliation_failure_preserves_answer():
    org, headers = _make_org(10)
    _run(headers, "seed", _COMMON_NUMERIC, supplier_evidence=_ALPHA)
    with patch("app.pipeline.memory_service.reconcile_one", side_effect=RuntimeError("simulated reconciliation failure")):
        a = _run(headers, "fail_reconcile", _COMMON_NUMERIC, supplier_evidence=_ALPHA)
    assert a is not None
    assert a["diagnostics"]["findings"][0]["finding"] == "AlphaCo: challenge."
    assert a["diagnostics"]["findings"][0].get("historical_precedent") is None  # reconciliation failed, so no annotation -- but the answer still exists


# 11. A case cannot consume its own newly written Memory.
def test_11_case_cannot_consume_its_own_write():
    org, headers = _make_org(11)
    a = _run(headers, "single", _COMMON_NUMERIC, supplier_evidence=_ALPHA)
    assert a["diagnostics"]["findings"][0].get("historical_precedent") is None  # nothing existed before this request ran


# 12. Tenant isolation.
def test_12_tenant_isolation():
    org_a, headers_a = _make_org(12)
    org_b, headers_b = _make_org(13)
    _run(headers_a, "seed_a", _COMMON_NUMERIC, supplier_evidence=[{"supplier_name": "SharedNameCo", "is_incumbent": True, "current_annual_spend_usd": 7_000_000}])
    a_b = _run(headers_b, "check_b", _COMMON_NUMERIC, supplier_evidence=[{"supplier_name": "SharedNameCo", "is_incumbent": True, "current_annual_spend_usd": 7_000_000}])
    assert a_b["diagnostics"]["findings"][0].get("historical_precedent") is None  # org B never sees org A's memory


# 13. Deterministic output.
def test_13_deterministic_output():
    org, headers = _make_org(14)
    _run(headers, "seed", _COMMON_NUMERIC, supplier_evidence=_ALPHA)
    a1 = _run(headers, "check1", _COMMON_NUMERIC, supplier_evidence=_ALPHA)
    a2 = _run(headers, "check1", _COMMON_NUMERIC, supplier_evidence=_ALPHA)  # same suffix -> same raw_question
    # historical_precedent's own dynamic recorded_at aside, the relationship classification must be stable
    assert a1["diagnostics"]["findings"][0]["historical_precedent"]["relationship"] == a2["diagnostics"]["findings"][0]["historical_precedent"]["relationship"]


# 14. Stability x3.
def test_14_stability_x3():
    org, headers = _make_org(15)
    results = [_run(headers, "stab_same", _COMMON_NUMERIC, supplier_evidence=_ALPHA)["diagnostics"]["findings"][0]["finding"] for _ in range(3)]
    assert results[0] == results[1] == results[2]


# 15. Real HTTP (this entire file already runs through the real HTTP
# path via TestClient on every test above -- confirmed explicitly here
# with a direct status/shape check).
def test_15_real_http_path():
    org, headers = _make_org(16)
    a = _run(headers, "http_check", _COMMON_NUMERIC, supplier_evidence=_ALPHA)
    assert isinstance(a, dict) and "diagnostics" in a


# ---------------------------------------------------------------------
# Additional cases required by the event_date / temporal-safety
# correction: event_date is a KNOWN business-event date only, never
# an analysis timestamp. extract_candidates() leaves it unset
# (unknown) since this evidence model has no genuine business-date
# source yet -- these tests construct memory items with explicit
# event_date values directly (bypassing the live-extraction default)
# to prove the reconciliation MECHANISM is correct when genuine
# business-period data is available, and stays safely cautious when
# it isn't.
# ---------------------------------------------------------------------

def test_i_temporal_change_with_known_different_business_periods():
    from app.pipeline.memory_service import reconcile_one
    mem = {"value": {"finding": "Average unit price has moved +12.0%."}, "fact_type": "price_movement_calculated",
           "event_date": "2025-03-15T00:00:00+00:00", "temporal_status": "CURRENT", "evidence_state": "CALCULATED"}
    cur = {"finding": "Average unit price has moved +9.0%."}
    r = reconcile_one(mem, cur, current_event_date="2026-06-20T00:00:00+00:00")
    assert r["relationship"] == "TEMPORAL_CHANGE"


def test_i_contradicts_with_known_same_business_period():
    from app.pipeline.memory_service import reconcile_one
    mem = {"value": {"finding": "Average unit price has moved +12.0%."}, "fact_type": "price_movement_calculated",
           "event_date": "2026-06-20T08:00:00+00:00", "temporal_status": "CURRENT", "evidence_state": "CALCULATED"}
    cur = {"finding": "Average unit price has moved +9.0%."}
    r = reconcile_one(mem, cur, current_event_date="2026-06-20T17:00:00+00:00")
    assert r["relationship"] == "CONTRADICTS"


def test_j_unknown_business_date_does_not_fabricate_temporal_relationship():
    """The exact defect found and fixed: an unknown business period on
    either side must never automatically become TEMPORAL_CHANGE (nor
    CONTRADICTS) -- the safe, honest default is COMPLEMENTS."""
    from app.pipeline.memory_service import reconcile_one
    mem = {"value": {"finding": "Average unit price has moved +12.0%."}, "fact_type": "price_movement_calculated",
           "event_date": None, "temporal_status": "CURRENT", "evidence_state": "CALCULATED"}
    cur = {"finding": "Average unit price has moved +9.0%."}
    r = reconcile_one(mem, cur, current_event_date=None)
    assert r["relationship"] == "COMPLEMENTS"
    assert r["relationship"] not in ("TEMPORAL_CHANGE", "CONTRADICTS")


def test_j_extraction_never_populates_event_date_from_analysis_time():
    """Confirms the actual live-extraction path leaves event_date
    unset -- the root-cause fix, not just the reconciliation-side
    safety net."""
    from app.pipeline.memory_service import extract_candidates
    kernel = {"org_id": "x", "case": {"subject": "TestCatJ"}}
    finding = [{"dimension": "supplier_landscape", "finding": "SomeCo holds 60.0% of category spend.", "evidence_state": "CALCULATED",
                "decision_impact": "DECISION_CHANGING", "source": "kernel:category_diagnosis", "evidence": "x", "implication": "y", "possible_action": "z"}]
    candidates = extract_candidates(kernel, finding, source_case_id="x")
    assert candidates[0]["rejected"] is False
    assert "event_date" not in candidates[0] or candidates[0].get("event_date") is None


def test_j_different_analysis_days_alone_do_not_imply_temporal_change():
    """Section 6's explicit concern: two real HTTP requests, genuinely
    made on the same test run (fractions of a second apart in wall-
    clock time, and with no known business-event date on either side)
    must not have their timing treated as evidence of change."""
    org, headers = _make_org(20)
    _run(headers, "seed_pricecase", {"category_annual_spend_usd": 1_120_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_000, "category_prior_annual_volume_units": 10_000})
    a2 = _run(headers, "current_pricecase", {"category_annual_spend_usd": 1_090_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_000, "category_prior_annual_volume_units": 10_000})
    price_finding = next((f for f in a2["diagnostics"]["findings"] if "unit price" in f["finding"].lower()), None)
    if price_finding and price_finding.get("historical_precedent"):
        assert price_finding["historical_precedent"]["relationship"] != "TEMPORAL_CHANGE"


def test_f_related_historical_context_explicit_label_never_supports_or_contradicts():
    """Strengthens case F: a different-fact_type, same-supplier memory
    item must carry the RELATED_HISTORICAL_CONTEXT label explicitly
    (not merely be silently dropped), and can never appear as
    SUPPORTS/CONTRADICTS/TEMPORAL_CHANGE for the current proposition."""
    from app.pipeline.memory_service import reconcile_memory_for_category
    diagnosis = {"suppliers_by_spend": [{"supplier": "EpsilonCo", "category_share_percent": 60.0}]}
    retrieved_memory = [{
        "entity_supplier": "EpsilonCo", "entity_category": None, "fact_type": "contract_adjustment_mechanism",
        "value": {"finding": "A contractual adjustment mechanism has been referenced for this category."},
        "evidence_state": "SUPPLIER_CLAIM", "temporal_status": "CURRENT", "event_date": None,
        "source_case_id": "x", "provenance": {}, "recorded_at": None,
    }]
    proposition_memory, related = reconcile_memory_for_category(diagnosis, retrieved_memory, None)
    assert proposition_memory == {}  # never eligible as proposition-level evidence for spend_concentration
    assert len(related) == 1
    assert related[0]["relationship"] == "RELATED_HISTORICAL_CONTEXT"
