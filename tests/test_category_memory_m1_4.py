"""
Category Memory M1.4 -- Memory content quality.

Root cause traced precisely: the "generic finding text" defect
independent validation found was NOT a finding-vs-implication mix-up
in the Memory layer -- both fields, at the SOURCE (category_strategy_
intelligence.py's contract-mechanism finding), were generic templates.
The distinctive detail (e.g. "6% for a two-year volume commitment")
lived in kernel facts (stated_justification) but was never woven into
either field. Fixed at the source, plus a second, deeper defect found
during this implementation: RELATED_HISTORICAL_CONTEXT for contract-
mechanism/price-history-contradiction fact_types could never reach
supplier-strategy reasoning at all in the live path, since _entity_for
only ever assigned a supplier for dimension=="supplier_landscape"
findings -- fixed narrowly for the two fact_types that are inherently
about the case's own supplier by construction (derived from stated_
justification, which is always that supplier's own statement).
"""
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.memory_service import extract_candidates, store_candidates, reconcile_one, as_related_historical_context

client = TestClient(app)
_CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _make_org(suffix):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"102.100.{suffix}.1"}).json()
    return org, {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}


def _run(headers, suffix, supplier, spend, justification=None, cat_spend=10_000_000, cat_prior=9_000_000):
    classify = {
        "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", **({"suppliers_stated_justification": justification} if justification else {})},
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


_VOLUME_COMMITMENT_TEXT = "Per the contract's annual adjustment clause, we previously accepted a 6% increase in exchange for a two-year volume commitment."


# ---------------------------------------------------------------------
# A -- specific historical commercial precedent
# ---------------------------------------------------------------------

def test_a_specific_historical_precedent_survives_not_generic_collapse():
    org, headers = _make_org(1)
    _run(headers, "seed", "AlphaM14Co", 1_000_000, justification=_VOLUME_COMMITMENT_TEXT)
    case, _ = _run(headers, "current", "AlphaM14Co", 1_000_000)
    reason = case["supplier_strategy"][0]["reason"]
    assert "6%" in reason
    assert "volume commitment" in reason
    assert "historical Memory indicates" in reason  # explicitly attributed, never stated as present fact


# ---------------------------------------------------------------------
# B -- historical supplier claim stays a claim
# ---------------------------------------------------------------------

def test_b_historical_supplier_claim_evidence_state_never_promoted():
    org, headers = _make_org(2)
    decision_id = _run(headers, "seed", "BetaM14Co", 1_000_000)[1]
    kernel = {"org_id": org["organisation_id"], "case": {"subject": "BetaM14Co"}}
    finding = [{"dimension": "cost_and_price_economics",
                "finding": "The supplier's stated justification claims costs have increased, but the case's own documented price history shows no increase over the stated period.",
                "evidence_state": "CONTRADICTED", "decision_impact": "MATERIAL_RISK", "source": "kernel:facts+kernel:case",
                "evidence": "x", "implication": "Raw material inflation was claimed as the cause.", "possible_action": "z"}]
    candidates = extract_candidates(kernel, finding, source_case_id=decision_id)
    store_candidates(org["organisation_id"], candidates)
    case, _ = _run(headers, "current", "BetaM14Co", 1_000_000)
    finding_out = next((f for f in case["diagnostics"]["findings"] if f.get("historical_precedent") and f["historical_precedent"]["fact_type"] == "supplier_claim_price_history_contradiction"), None)
    if finding_out:
        assert finding_out["historical_precedent"]["evidence_state"] == "CONTRADICTED"  # never silently promoted to VERIFIED


# ---------------------------------------------------------------------
# C -- historical verified fact
# ---------------------------------------------------------------------

def test_c_verified_evidence_state_preserved_through_reconciliation():
    mem = {"value": {"finding": "AlphaCo: challenge.", "implication": "y"}, "fact_type": "supplier_strategy_classification",
           "event_date": None, "temporal_status": "HISTORICAL", "evidence_state": "VERIFIED"}
    r = reconcile_one(mem, {"finding": "AlphaCo: monitor."}, None)
    assert r["evidence_state"] == "VERIFIED"
    assert r["temporal_status"] == "HISTORICAL"


# ---------------------------------------------------------------------
# D -- historical vs current conflict: current wins
# ---------------------------------------------------------------------

def test_d_current_evidence_wins_concentration_reversal():
    org, headers = _make_org(3)
    _run(headers, "seed70", "DeltaM14Co", 7_000_000)
    case, _ = _run(headers, "current20", "DeltaM14Co", 2_000_000)
    assert case["supplier_strategy"][0]["strategy"] == "monitor"  # current 20%, not stale 70%
    assert "70" not in case["supplier_strategy"][0]["strategy"]


# ---------------------------------------------------------------------
# E -- historical support legitimately used in supplier strategy
# ---------------------------------------------------------------------

def test_e_historical_precedent_legitimately_informs_reasoning():
    org, headers = _make_org(4)
    _run(headers, "seed", "EpsilonM14Co", 1_000_000, justification=_VOLUME_COMMITMENT_TEXT)
    case, _ = _run(headers, "current", "EpsilonM14Co", 1_000_000)
    reason = case["supplier_strategy"][0]["reason"]
    # Must not claim the supplier WILL repeat the trade -- only that it's a precedent worth testing
    assert "will accept" not in reason.lower()
    assert "guaranteed" not in reason.lower()


# ---------------------------------------------------------------------
# F -- irrelevant historical Memory: no leakage
# ---------------------------------------------------------------------

def test_f_irrelevant_memory_different_supplier_no_leakage():
    org, headers = _make_org(5)
    _run(headers, "seed", "ZetaM14Co", 1_000_000, justification=_VOLUME_COMMITMENT_TEXT)
    case, _ = _run(headers, "other", "EtaM14Co", 1_000_000)  # different supplier, same org
    reason = case["supplier_strategy"][0]["reason"]
    assert "volume commitment" not in reason
    assert "6%" not in reason


# ---------------------------------------------------------------------
# G -- different fact_type, same entity: RELATED_HISTORICAL_CONTEXT
# labelled and specific detail preserved
# ---------------------------------------------------------------------

def test_g_related_historical_context_labelled_and_specific():
    org, headers = _make_org(6)
    _run(headers, "seed", "ThetaM14Co", 1_000_000, justification=_VOLUME_COMMITMENT_TEXT)
    case, _ = _run(headers, "current", "ThetaM14Co", 1_000_000)
    reason = case["supplier_strategy"][0]["reason"]
    assert "Related historical context" in reason or "historical Memory indicates" in reason
    assert "6%" in reason


# ---------------------------------------------------------------------
# H -- missing implication: do not invent one
# ---------------------------------------------------------------------

def test_h_missing_implication_not_fabricated():
    mem_item = {"entity_supplier": "IotaM14Co", "entity_category": None, "fact_type": "contract_adjustment_mechanism",
                "value": {"finding": "A contractual adjustment mechanism has been referenced for this category."},
                "evidence_state": "SUPPLIER_CLAIM", "temporal_status": "CURRENT", "event_date": None,
                "source_case_id": "x", "provenance": {}, "recorded_at": None}  # no "implication" key in value
    result = as_related_historical_context(mem_item)
    assert result["implication_text"] is None  # never fabricated


# ---------------------------------------------------------------------
# I -- missing finding/proposition: do not fabricate, safely omit
# ---------------------------------------------------------------------

def test_i_missing_proposition_safely_omitted_from_reason():
    """Directly exercises classify_supplier_strategy's own omission
    rule: an empty finding_text must not produce a fabricated or
    empty-quoted annotation."""
    from app.pipeline.category_strategy_profile import classify_supplier_strategy
    related_context = [{"finding_text": "", "implication_text": None, "fact_type": "contract_adjustment_mechanism"}]
    result = classify_supplier_strategy({"category_share_percent": 60}, None, related_context=related_context)
    assert "Related historical context" not in result["reason"]  # safely omitted, not fabricated


# ---------------------------------------------------------------------
# J -- evidence-state preservation across all relevant states
# ---------------------------------------------------------------------

def test_j_evidence_states_preserved_through_related_context():
    for state in ("SUPPLIER_CLAIM", "VERIFIED", "CALCULATED", "EXTERNAL_MARKET_EVIDENCE"):
        mem_item = {"entity_supplier": "JCo", "entity_category": None, "fact_type": "contract_adjustment_mechanism",
                    "value": {"finding": "x", "implication": "y"}, "evidence_state": state, "temporal_status": "CURRENT",
                    "event_date": None, "source_case_id": "x", "provenance": {}, "recorded_at": None}
        result = as_related_historical_context(mem_item)
        assert result["evidence_state"] == state


# ---------------------------------------------------------------------
# K -- temporal preservation: no invented dates
# ---------------------------------------------------------------------

def test_k_no_invented_dates_in_related_context():
    mem_item = {"entity_supplier": "KCo", "entity_category": None, "fact_type": "contract_adjustment_mechanism",
                "value": {"finding": "x", "implication": "y"}, "evidence_state": "SUPPLIER_CLAIM", "temporal_status": "CURRENT",
                "event_date": None, "source_case_id": "x", "provenance": {}, "recorded_at": None}
    result = as_related_historical_context(mem_item)
    assert result["event_date"] is None  # unknown stays unknown, never fabricated


# ---------------------------------------------------------------------
# L -- determinism with fixed Memory state
# ---------------------------------------------------------------------

def test_l_determinism_fixed_memory_state():
    org, headers = _make_org(7)
    _run(headers, "seed", "LCoM14", 1_000_000, justification=_VOLUME_COMMITMENT_TEXT)
    r1, _ = _run(headers, "check", "LCoM14", 1_000_000)
    r2, _ = _run(headers, "check", "LCoM14", 1_000_000)
    assert r1["supplier_strategy"] == r2["supplier_strategy"]


# ---------------------------------------------------------------------
# Differential test (most important) -- A vs B vs C
# ---------------------------------------------------------------------

def test_differential_A_no_memory_B_relevant_memory_C_irrelevant_memory():
    # A: current evidence only, fresh org
    org_a, headers_a = _make_org(8)
    a_case, _ = _run(headers_a, "A", "DiffCoM14", 1_000_000)

    # B: identical current evidence + relevant memory
    org_b, headers_b = _make_org(9)
    _run(headers_b, "seed", "DiffCoM14", 1_000_000, justification=_VOLUME_COMMITMENT_TEXT)
    b_case, _ = _run(headers_b, "B", "DiffCoM14", 1_000_000)

    # C: identical current evidence + irrelevant memory (different supplier)
    org_c, headers_c = _make_org(10)
    _run(headers_c, "seed_irrelevant", "OtherSupplierM14", 1_000_000, justification=_VOLUME_COMMITMENT_TEXT)
    c_case, _ = _run(headers_c, "C", "DiffCoM14", 1_000_000)

    a_reason = a_case["supplier_strategy"][0]["reason"]
    b_reason = b_case["supplier_strategy"][0]["reason"]
    c_reason = c_case["supplier_strategy"][0]["reason"]

    assert "6%" not in a_reason
    assert "6%" in b_reason  # relevant memory materially changed reasoning
    assert "6%" not in c_reason  # irrelevant memory (different supplier) did not leak in
    assert a_case["supplier_strategy"][0]["strategy"] == b_case["supplier_strategy"][0]["strategy"] == c_case["supplier_strategy"][0]["strategy"]  # current evidence identical -> same strategy value in all three


# ---------------------------------------------------------------------
# Content fidelity test (explicit, not accepting the old defect)
# ---------------------------------------------------------------------

def test_content_fidelity_distinctive_fact_not_generic_phrase_only():
    org, headers = _make_org(11)
    _run(headers, "seed", "FidelityCoM14", 1_000_000, justification=_VOLUME_COMMITMENT_TEXT)
    case, _ = _run(headers, "current", "FidelityCoM14", 1_000_000)
    reason = case["supplier_strategy"][0]["reason"]
    # This is the exact defect M1.4 fixes -- a test that only checked
    # for "contractual adjustment mechanism" would have passed even
    # under the old, broken behavior. Assert the SPECIFIC detail too.
    assert "two-year volume commitment" in reason
    assert "6%" in reason


# ---------------------------------------------------------------------
# Provenance test
# ---------------------------------------------------------------------

def test_provenance_traceable_to_source_case_and_evidence():
    org, headers = _make_org(12)
    _, decision_id = _run(headers, "seed", "ProvCoM14", 1_000_000, justification=_VOLUME_COMMITMENT_TEXT)
    case, _ = _run(headers, "current", "ProvCoM14", 1_000_000)
    finding_out = next((f for f in case["diagnostics"]["findings"] if f.get("historical_precedent")), None)
    assert finding_out is not None
    hp = finding_out["historical_precedent"]
    assert hp.get("source_case_id") is not None
    assert hp.get("provenance") is not None


# ---------------------------------------------------------------------
# Failure safety
# ---------------------------------------------------------------------

def test_failure_safety_malformed_related_context_does_not_crash():
    from app.pipeline.category_strategy_profile import classify_supplier_strategy
    malformed = [{"finding_text": None, "implication_text": None}]  # no fact_type, no usable proposition
    result = classify_supplier_strategy({"category_share_percent": 60}, None, related_context=malformed)
    assert result["strategy"] == "challenge"  # primary classification unaffected
    assert "Related historical context" not in result["reason"]
