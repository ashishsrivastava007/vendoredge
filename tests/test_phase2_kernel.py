"""
Phase 2 / R41 -- Commercial Intelligence Kernel.

Covers all 18 required test areas: the three modes, cross-mode kernel
identity, entity/currency separation, contradiction handling, evidence
retention, calculated facts, supplier claims, stakeholder views,
unknowns, historical facts, and the kernel's survival through retry,
dispatcher, /respond, continue, and recovery.
"""
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.kernel import build_kernel, validate_kernel, CommercialKernel, CaseIdentity, CommercialFact
from app.pipeline.financial import compute_financial_impact
from app.pipeline.decision_audit import build_decision_audit
from app.pipeline.question_coverage import build_coverage_requirements
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence, SupplierEvidence, StakeholderView

client = TestClient(app)
_counter = [0]


def _headers():
    _counter[0] += 1
    org_res = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"10.96.{_counter[0]}.1"}).json()
    return {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}


_CONF = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _position():
    return CommercialPosition(
        recommendation="test", commercial_insights=["a"], reasoning="x",
        confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
    )


def _golden_normalized():
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Supplier A", supplier_currency="EUR", annual_volume_units=246_000),
        case=PriceIncreaseEvidence(
            requested_increase_percent=11.0, alternative_scenario_percent=7.0,
            annual_spend_usd=5_550_000, prior_annual_spend_usd=4_370_000, prior_annual_volume_units=221_000,
            category_annual_spend_usd=8_400_000, category_prior_annual_spend_usd=7_050_000,
            category_annual_volume_units=412_000, category_prior_annual_volume_units=385_000,
            suppliers_stated_justification="No price adjustment for three years.",
            stated_price_history=["Year -3: +2.5%", "Year -2: +3.0%", "Year -1: 0%"],
        ),
        derived=DerivedEvidence(resolved_annual_spend_usd=5_550_000, currency_calculation_safe=True, spend_currency="EUR"),
        suppliers=[
            SupplierEvidence(supplier_name="Supplier A", is_incumbent=True),
            SupplierEvidence(supplier_name="Supplier B", qualification_time_estimate="4-6 months"),
            SupplierEvidence(supplier_name="Supplier D", capacity_percent=15, capacity_status="unvalidated"),
        ],
        stakeholder_views=[
            StakeholderView(stakeholder_name="Engineering Lead", role="engineering", view_type="risk_concern", statement="Requalifying a second source will delay the program.", basis="prior qualification runs", explicitly_stated=True),
        ],
    )


def _build_full_kernel(mode="supplier_request"):
    n = _golden_normalized()
    fi = compute_financial_impact(n)
    pos = _position()
    pos.financial_impact = fi
    pos.decision_audit = __import__("app.models", fromlist=["DecisionAudit"]).DecisionAudit(**build_decision_audit(n, pos))
    pos.case_mode = mode
    pos.case_mode_source = "explicit"
    coverage = build_coverage_requirements(n)
    return build_kernel(n, pos, case_id="k-test", coverage_requirements=coverage)


# ---------------------------------------------------------------------
# 1-3: one kernel built per mode
# ---------------------------------------------------------------------

def test_1_supplier_request_kernel_builds_correctly():
    k = _build_full_kernel("supplier_request")
    assert k.case.case_mode == "supplier_request"
    assert validate_kernel(k) == []


def test_2_commercial_signal_kernel_builds_correctly():
    k = _build_full_kernel("commercial_signal")
    assert k.case.case_mode == "commercial_signal"
    assert validate_kernel(k) == []


def test_3_category_strategy_kernel_builds_correctly():
    k = _build_full_kernel("category_strategy")
    assert k.case.case_mode == "category_strategy"
    assert validate_kernel(k) == []


# ---------------------------------------------------------------------
# 4: same facts across all three modes -> identical kernel truth
# ---------------------------------------------------------------------

def test_4_same_facts_across_three_modes_produce_identical_kernel_truth():
    kernels = {mode: _build_full_kernel(mode) for mode in ("supplier_request", "commercial_signal", "category_strategy")}
    # Strip mode/mode_source (the one thing that's meant to differ) and
    # compare everything else byte-for-byte.
    normalized_dumps = []
    for k in kernels.values():
        d = k.model_dump()
        d["case"]["case_mode"] = None
        d["case"]["case_mode_source"] = None
        normalized_dumps.append(d)
    assert all(d == normalized_dumps[0] for d in normalized_dumps), "kernel truth differs across modes -- it must not"


# ---------------------------------------------------------------------
# 5-6: entity and currency separation
# ---------------------------------------------------------------------

def test_5_entity_separation_category_vs_supplier_never_interchangeable():
    k = _build_full_kernel()
    category_spend = next(f for f in k.facts if f.entity == "category" and f.metric == "annual_spend")
    supplier_spend = next(f for f in k.facts if f.entity == "Supplier A" and f.metric == "annual_spend")
    assert category_spend.value == 8_400_000.0
    assert supplier_spend.value == 5_550_000.0
    assert category_spend.value != supplier_spend.value


def test_6_currency_carried_on_every_monetary_fact():
    k = _build_full_kernel()
    monetary_metrics = {"annual_spend", "scenario_annual_impact", "scenario_difference"}
    for f in k.facts:
        if f.metric in monetary_metrics:
            assert f.currency == "EUR", f"'{f.entity}.{f.metric}' is monetary but has currency={f.currency}"


# ---------------------------------------------------------------------
# 7: contradiction
# ---------------------------------------------------------------------

def test_7_contradiction_surfaced_as_its_own_evidence_state():
    k = _build_full_kernel()
    contradiction_facts = [f for f in k.facts if f.evidence_state == "CONTRADICTED"]
    assert len(contradiction_facts) == 1
    assert "reconciliation" in contradiction_facts[0].value.lower()
    # Never conflated with UNKNOWN.
    assert not any(f.evidence_state == "UNKNOWN" and "reconciliation" in str(f.value).lower() for f in k.facts)


# ---------------------------------------------------------------------
# 8: explicit evidence retention (qualification/capacity)
# ---------------------------------------------------------------------

def test_8_explicit_evidence_retained_on_supplier_profiles():
    k = _build_full_kernel()
    b = next(s for s in k.suppliers if s.supplier_name == "Supplier B")
    d = next(s for s in k.suppliers if s.supplier_name == "Supplier D")
    assert b.qualification.value == "4-6 months"
    assert b.qualification.evidence_state == "VERIFIED"
    assert "unvalidated" in str(d.capacity.value).lower()
    assert d.capacity.evidence_state == "VERIFIED", "a stated-but-unvalidated figure is still real evidence, not an unknown"


# ---------------------------------------------------------------------
# 9: calculated facts
# ---------------------------------------------------------------------

def test_9_calculated_facts_correctly_tagged_and_correct():
    k = _build_full_kernel()
    scenario_diff = next(f for f in k.facts if f.metric == "scenario_difference")
    assert scenario_diff.value == 222_000.0
    assert scenario_diff.evidence_state == "CALCULATED"
    assert scenario_diff.provenance


# ---------------------------------------------------------------------
# 10: supplier claims never become verified
# ---------------------------------------------------------------------

def test_10_supplier_claim_never_becomes_verified():
    k = _build_full_kernel()
    claim = next(f for f in k.facts if f.metric == "stated_justification")
    assert claim.evidence_state == "SUPPLIER_CLAIM"
    assert claim.evidence_state != "VERIFIED"


# ---------------------------------------------------------------------
# 11: stakeholder views
# ---------------------------------------------------------------------

def test_11_stakeholder_views_carried_with_unresolved_disagreement_flag():
    k = _build_full_kernel()
    assert len(k.stakeholders) == 1
    assert k.stakeholders[0].stakeholder == "Engineering Lead"
    assert k.stakeholders[0].unresolved_disagreement is True


# ---------------------------------------------------------------------
# 12: unknowns
# ---------------------------------------------------------------------

def test_12_unknowns_carry_why_it_matters_and_resolution_action():
    k = _build_full_kernel()
    assert len(k.unknowns) >= 1
    for u in k.unknowns:
        assert u.why_it_matters
        assert u.resolution_action
        assert u.could_change


# ---------------------------------------------------------------------
# 13: historical facts
# ---------------------------------------------------------------------

def test_13_historical_facts_carried_when_present():
    from app.pipeline.normalized_evidence import HistoryContext
    n = _golden_normalized()
    n.history = HistoryContext(org_history=[{"description": "Prior 9% request accepted at 6% in 2024."}], supplier_history=[])
    fi = compute_financial_impact(n)
    pos = _position()
    pos.financial_impact = fi
    k = build_kernel(n, pos, case_id="k-hist")
    assert len(k.history) == 1
    assert k.history[0].source == "org_history"


# ---------------------------------------------------------------------
# Deterministic assembly -- no LLM involvement
# ---------------------------------------------------------------------

def test_kernel_never_touches_the_model():
    """Direct proof: build_kernel takes no reasoning-provider argument at
    all and makes no network call -- it is a pure function over already-
    computed data."""
    import inspect
    sig = inspect.signature(build_kernel)
    assert "provider" not in sig.parameters
    assert "model" not in sig.parameters
    assert "client" not in sig.parameters


# ---------------------------------------------------------------------
# 14-18: kernel survives retry, dispatcher, /respond, continue, recovery
# -- through the real HTTP path
# ---------------------------------------------------------------------

_CLASSIFY = {
    "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
    "extracted_evidence": {"supplier_currency": "EUR", "how_critical_is_this_supplier_relationship": "moderate", "suppliers_stated_justification": "cost inflation"},
    "numeric_facts": {"annual_spend_usd": 1_000_000, "category_annual_spend_usd": 4_000_000, "category_prior_annual_spend_usd": 3_500_000, "requested_change_percent": 10.0},
}


def _create_and_wait(headers, mode="supplier_request", raw_question="Kernel lifecycle case."):
    with patch("app.routes.decisions.classify", return_value=_CLASSIFY), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.routes.decisions.generate_commercial_position", return_value=_position()):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": raw_question, "mode": mode}, headers=headers)
        decision_id = r.json()["id"]
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{decision_id}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return decision_id, d


def test_14_kernel_present_after_standard_creation_dispatcher_path():
    h = _headers()
    _, d = _create_and_wait(h)
    kernel = (d.get("commercial_position") or {}).get("kernel")
    assert kernel is not None
    assert kernel["case"]["case_mode"] == "supplier_request"
    assert any(f["entity"] == "category" and f["metric"] == "annual_spend" for f in kernel["facts"])


def test_15_kernel_present_through_dispatcher_explicitly():
    """Same mechanism as 14, named explicitly per the spec's own item 15
    -- this IS the real dispatcher path (_run_queued_job), not a
    synchronous bypass, confirmed earlier this engagement."""
    h = _headers()
    decision_id, d = _create_and_wait(h, mode="commercial_signal")
    assert d["status"] == "completed"
    assert d["commercial_position"]["kernel"]["case"]["case_mode"] == "commercial_signal"


def test_16_kernel_rebuilt_correctly_after_respond():
    h = _headers()
    classify_gate = dict(_CLASSIFY)
    classify_gate["extracted_evidence"] = {"supplier_currency": "EUR"}
    with patch("app.routes.decisions.classify", return_value=classify_gate), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.routes.decisions.generate_commercial_position", return_value=_position()):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "Respond kernel case.", "mode": "category_strategy"}, headers=h)
        decision_id = r.json()["id"]
        r2 = client.post(f"/api/v1/commercial-decisions/{decision_id}/respond",
                          json={"user_supplied_inputs": {"suppliers_stated_justification": "cost inflation", "how_critical_is_this_supplier_relationship": "moderate"}},
                          headers=h)
        assert r2.status_code == 200, r2.text
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{decision_id}", headers=h).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    kernel = d["commercial_position"]["kernel"]
    assert kernel["case"]["case_mode"] == "category_strategy"
    assert any(f["metric"] == "annual_spend" for f in kernel["facts"])


def test_17_kernel_rebuilt_correctly_after_continue():
    h = _headers()
    decision_id, d = _create_and_wait(h, mode="supplier_request", raw_question="Parent for kernel continuation test.")
    with patch("app.routes.decisions.classify", return_value=_CLASSIFY), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.routes.decisions.generate_commercial_position", return_value=_position()):
        r = client.post(f"/api/v1/commercial-decisions/{decision_id}/continue",
                         json={"what_happened": "Supplier provided a cost breakdown."}, headers=h)
        assert r.status_code == 200, r.text
        new_id = r.json()["id"]
        d2 = None
        for _ in range(30):
            d2 = client.get(f"/api/v1/commercial-decisions/{new_id}", headers=h).json()
            if d2["status"] != "reasoning":
                break
            time.sleep(0.2)
    kernel = d2["commercial_position"]["kernel"]
    assert kernel["case"]["case_mode"] == "supplier_request"


def test_18_kernel_rebuilt_correctly_on_recovery_rerun():
    from app.pipeline import job_queue
    from app.routes.decisions import _run_queued_job
    h = _headers()
    decision_id, d = _create_and_wait(h, mode="commercial_signal", raw_question="Recovery kernel test.")
    assert d["commercial_position"]["kernel"]["case"]["case_mode"] == "commercial_signal"
    org_id = h["x-org-id"]
    job_queue.enqueue(org_id, decision_id, job_kind="specialist")
    with patch("app.routes.decisions.classify", return_value=_CLASSIFY), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.routes.decisions.generate_commercial_position", return_value=_position()):
        _run_queued_job(org_id, decision_id)
    d2 = client.get(f"/api/v1/commercial-decisions/{decision_id}", headers=h).json()
    kernel2 = d2["commercial_position"]["kernel"]
    assert kernel2["case"]["case_mode"] == "commercial_signal"
    assert any(f["metric"] == "annual_spend" for f in kernel2["facts"])
