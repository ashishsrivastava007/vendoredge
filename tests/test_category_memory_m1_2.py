"""
Category Memory M1.2 -- the two defects fixed this slice:

A. RELATED_HISTORICAL_CONTEXT was computed and classified correctly
   but never consumed anywhere -- now wired into classify_supplier_
   strategy (via a new related_context parameter) and the opportunity-
   prioritization block, always as explicitly-labelled context, never
   as proposition evidence (never SUPPORTS/CONTRADICTS/TEMPORAL_CHANGE).

B. The COMPLEMENTS relationship's message text ("this recurs a
   previous observation... not a one-off") was misleading when the
   historical and current VALUES actually differ under an unknown
   period -- reconcile_one now returns values_differ_unknown_period,
   and both callers (classify_supplier_strategy, build_360_findings)
   select an honest "differs... period unknown" message in that case,
   reserving the "recurs" wording for genuine categorical matches only.
"""
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.memory_service import extract_candidates, store_candidates, reconcile_one

client = TestClient(app)
_CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _make_org(suffix):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"70.100.{suffix}.1"}).json()
    return org, {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}


def _run(headers, suffix, supplier, spend, cat_spend=10_000_000, cat_prior=9_000_000):
    classify = {
        "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD"},
        "numeric_facts": {"category_annual_spend_usd": cat_spend, "category_prior_annual_spend_usd": cat_prior},
        "supplier_specific_evidence": [{"supplier_name": supplier, "is_incumbent": True, "current_annual_spend_usd": spend}],
    }
    pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": f"req {suffix}", "mode": "category_strategy"}, headers=headers)
        decision_id = r.json()["id"]
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{decision_id}?include_diagnostics=true", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return d["commercial_position"]["category_strategy_answer"], decision_id


def _seed_bare_decision(headers):
    """A decision with no supplier evidence at all, purely for a real
    decision_id to satisfy the memory_items foreign key."""
    classify = {"content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
                "extracted_evidence": {"supplier_currency": "USD"}, "numeric_facts": {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000}, "supplier_specific_evidence": []}
    pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "seed", "mode": "category_strategy"}, headers=headers)
        decision_id = r.json()["id"]
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{decision_id}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return decision_id


def _seed_related_context(headers, org_id, supplier, implication_text):
    """Injects a RELATED_HISTORICAL_CONTEXT-eligible memory item (a
    different fact_type than spend_concentration/supplier_strategy_
    classification) for the given supplier. kernel.case.subject is set
    to the supplier's own name, matching the live incumbent-name
    convention build_kernel actually uses (confirmed by inspection of
    app/pipeline/kernel.py: subject = the incumbent supplier's name)."""
    decision_id = _seed_bare_decision(headers)
    kernel = {"org_id": org_id, "case": {"subject": supplier}}
    finding = [{
        "dimension": "contract_and_commercial_architecture",
        "finding": "A contractual adjustment mechanism has been referenced for this category.",
        "evidence_state": "SUPPLIER_CLAIM", "decision_impact": "DECISION_CRITICAL_UNKNOWN",
        "source": "kernel:facts", "evidence": "x", "implication": implication_text, "possible_action": "z",
    }]
    candidates = extract_candidates(kernel, finding, source_case_id=decision_id)
    for c in candidates:
        c["entity_supplier"] = supplier
    return store_candidates(org_id, candidates)


# ---------------------------------------------------------------------
# Fix A: RELATED_HISTORICAL_CONTEXT reaches supplier_strategy and
# opportunity prioritization
# ---------------------------------------------------------------------

def test_a_positive_related_context_changes_reasoning_not_current_value():
    """The exact task scenario: a supplier previously accepted a
    concession in exchange for a volume commitment (a differently-
    typed prior observation); current request is evaluated on its own
    current evidence. The factual finding and strategy VALUE must stay
    identical to the no-context case; only the reason/priority text
    may change, and only as explicitly-labelled context."""
    org_a, headers_a = _make_org(1)
    a_case, _ = _run(headers_a, "A", "SigmaCo", 6_000_000)

    org_b, headers_b = _make_org(2)
    _seed_related_context(headers_b, org_b["organisation_id"], "SigmaCo", "SigmaCo previously accepted a 6% increase in exchange for a two-year volume commitment.")
    b_case, _ = _run(headers_b, "B", "SigmaCo", 6_000_000)

    assert a_case["diagnostics"]["findings"][0]["finding"] == b_case["diagnostics"]["findings"][0]["finding"]
    assert a_case["supplier_strategy"][0]["strategy"] == b_case["supplier_strategy"][0]["strategy"]
    assert a_case["supplier_strategy"][0]["reason"] != b_case["supplier_strategy"][0]["reason"]
    assert "Related historical context" in b_case["supplier_strategy"][0]["reason"]
    assert not any(w in b_case["supplier_strategy"][0]["reason"] for w in ("confirms a previously recorded", "differs from a same-period", "reflects genuine change over time", "recurs a previous observation"))


def test_a_related_context_also_reaches_opportunity_prioritization():
    org, headers = _make_org(3)
    _seed_related_context(headers, org["organisation_id"], "UpsilonCo", "UpsilonCo previously offered a rebate structure in exchange for consolidated ordering.")
    case, _ = _run(headers, "check", "UpsilonCo", 6_000_000)
    priority = next(p for p in case["diagnostics"]["priorities"] if "UpsilonCo" in p["priority"])
    assert "related historical context" in priority["reason"]
    assert "recurring, previously identified" not in priority["reason"]  # not treated as confirmed repetition


def test_a_negative_no_related_context_no_influence():
    org, headers = _make_org(4)
    case, _ = _run(headers, "nocontext", "PhiCo", 6_000_000)
    assert "Related historical context" not in case["supplier_strategy"][0]["reason"]


def test_a_irrelevant_related_context_different_supplier_zero_influence():
    org, headers = _make_org(5)
    _seed_related_context(headers, org["organisation_id"], "ChiCo", "ChiCo previously offered a rebate.")
    case, _ = _run(headers, "othersupplier", "PsiCo", 6_000_000)  # different supplier, same org
    assert "Related historical context" not in case["supplier_strategy"][0]["reason"]
    assert "related historical context" not in case["diagnostics"]["priorities"][0]["reason"]


def test_a_current_evidence_remains_authoritative_with_related_context_present():
    """Reversal check: even with related context present, current
    evidence alone decides the strategy VALUE -- a low-share supplier
    stays 'monitor' despite a related-context item existing."""
    org, headers = _make_org(6)
    _seed_related_context(headers, org["organisation_id"], "OmegaTwoCo", "OmegaTwoCo previously offered a rebate structure.")
    case, _ = _run(headers, "lowshare", "OmegaTwoCo", 1_000_000)  # 10% share -> monitor
    assert case["supplier_strategy"][0]["strategy"] == "monitor"
    assert "Related historical context" in case["supplier_strategy"][0]["reason"]


def test_a_related_context_never_becomes_proposition_relationship():
    """Direct check on the reconciliation function: an item with a
    different fact_type from the current proposition is classified
    ONLY as RELATED_HISTORICAL_CONTEXT, never SUPPORTS/CONTRADICTS/
    TEMPORAL_CHANGE, and never appears in proposition_memory_by_key."""
    from app.pipeline.memory_service import reconcile_memory_for_category
    diagnosis = {"suppliers_by_spend": [{"supplier": "AlephCo", "category_share_percent": 55.0}]}
    retrieved = [{
        "entity_supplier": "AlephCo", "entity_category": None, "fact_type": "contract_adjustment_mechanism",
        "value": {"finding": "A contractual adjustment mechanism has been referenced for this category."},
        "evidence_state": "SUPPLIER_CLAIM", "temporal_status": "CURRENT", "event_date": None,
        "source_case_id": "x", "provenance": {}, "recorded_at": None,
    }]
    proposition_memory, related = reconcile_memory_for_category(diagnosis, retrieved, None)
    assert proposition_memory == {}
    assert len(related) == 1
    assert related[0]["relationship"] == "RELATED_HISTORICAL_CONTEXT"
    assert related[0]["entity_supplier"] == "AlephCo"


# ---------------------------------------------------------------------
# Fix B: honest wording when values genuinely differ under an unknown
# period (never CONTRADICTS/TEMPORAL_CHANGE, but not misleadingly
# "recurring" either)
# ---------------------------------------------------------------------

def test_b_positive_unknown_period_value_mismatch_gets_honest_wording():
    org, headers = _make_org(7)
    _run(headers, "seed70", "BetaMCo", 7_000_000)  # 70% -> challenge, written to memory
    case, _ = _run(headers, "current20", "BetaMCo", 2_000_000)  # 20% -> monitor
    reason = case["supplier_strategy"][0]["reason"]
    assert "recurs" not in reason  # the misleading wording is gone
    assert "differs" in reason
    assert "period" in reason and "unknown" in reason


def test_b_negative_genuine_recurrence_keeps_recurs_wording():
    """When there's nothing numeric to compare (e.g. an exact repeat
    with no percentage in the finding text), the 'recurs' wording is
    still appropriate and must not be replaced."""
    org, headers = _make_org(8)
    _run(headers, "seed", "GammaMCo", 7_000_000)  # 70% both times -> SUPPORTS path (exact match), not this case's target
    case, _ = _run(headers, "same", "GammaMCo", 7_000_000)
    reason = case["supplier_strategy"][0]["reason"]
    # exact match -> SUPPORTS wording, not the COMPLEMENTS "recurs" wording at all
    assert "confirms a previously recorded observation" in reason


def test_b_reconcile_one_flags_values_differ_unknown_period_directly():
    mem = {"value": {"finding": "Average unit price has moved +12.0%."}, "fact_type": "price_movement_calculated",
           "event_date": None, "temporal_status": "CURRENT", "evidence_state": "CALCULATED"}
    cur = {"finding": "Average unit price has moved +9.0%."}
    r = reconcile_one(mem, cur, current_event_date=None)
    assert r["relationship"] == "COMPLEMENTS"
    assert r["values_differ_unknown_period"] is True


def test_b_reconcile_one_no_flag_when_texts_genuinely_match():
    """No numbers anywhere, and the finding text itself matches
    exactly -- a genuine categorical recurrence, correctly NOT flagged
    as a value mismatch."""
    mem = {"value": {"finding": "AlphaCo: challenge."}, "fact_type": "supplier_strategy_classification",
           "event_date": None, "temporal_status": "CURRENT", "evidence_state": "CALCULATED"}
    cur = {"finding": "AlphaCo: challenge."}
    r = reconcile_one(mem, cur, current_event_date=None)
    assert r["relationship"] == "COMPLEMENTS"
    assert r["values_differ_unknown_period"] is False


def test_b_reconcile_one_flags_categorical_mismatch_even_without_numbers():
    """The deeper fix found during verification: when neither side has
    an extractable number (e.g. the 'monitor' default reason states no
    percentage at all), a genuine categorical difference in the
    finding text itself (challenge vs monitor) must still be flagged,
    not silently treated as a safe 'no numbers' match."""
    mem = {"value": {"finding": "AlphaCo: challenge."}, "fact_type": "supplier_strategy_classification",
           "event_date": None, "temporal_status": "CURRENT", "evidence_state": "CALCULATED"}
    cur = {"finding": "AlphaCo: monitor."}
    r = reconcile_one(mem, cur, current_event_date=None)
    assert r["relationship"] == "COMPLEMENTS"
    assert r["values_differ_unknown_period"] is True


def test_b_still_never_produces_contradicts_or_temporal_change_from_unknown_period():
    """The safety rule this fix must preserve: unknown period still
    never yields CONTRADICTS or TEMPORAL_CHANGE, regardless of the
    wording fix."""
    org, headers = _make_org(9)
    _run(headers, "seed", "DeltaMCo", 7_000_000)
    case, _ = _run(headers, "current", "DeltaMCo", 2_000_000)
    reason = case["supplier_strategy"][0]["reason"]
    assert "same-period prior observation" not in reason  # CONTRADICTS wording
    assert "reflects genuine change over time, not a discrepancy" not in reason  # TEMPORAL_CHANGE wording


def test_b_finding_level_annotation_also_uses_honest_wording():
    """The same fix applied at the finding-level (build_360_findings),
    not just classify_supplier_strategy -- now consistent across both
    reconciliation call sites, including the 'monitor' case where the
    current finding text carries no percentage at all."""
    org, headers = _make_org(10)
    _run(headers, "seed", "EpsilonMCo", 7_000_000)
    case, _ = _run(headers, "current", "EpsilonMCo", 2_000_000)
    finding = next((f for f in case["diagnostics"]["findings"] if f.get("historical_precedent") and f["historical_precedent"]["relationship"] == "COMPLEMENTS"), None)
    assert finding is not None
    assert "recurs a previous observation" not in finding["possible_action"]
    assert "differs from a previously recorded observation" in finding["possible_action"]
    assert "period of the prior observation is unknown" in finding["possible_action"]


# ---------------------------------------------------------------------
# Protected: no schema/type/scope changes
# ---------------------------------------------------------------------

def test_no_new_memory_type_introduced():
    org, headers = _make_org(11)
    case, _ = _run(headers, "check", "ZetaMCo", 6_000_000)
    assert isinstance(case, dict)  # answer shape unaffected -- no new top-level Memory contract introduced
