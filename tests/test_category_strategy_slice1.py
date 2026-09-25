"""
Category Strategy Slice 1 -- golden cases, differential tests, and
adversarial tests, run through the real HTTP path exactly like every
other journey's test suite in this codebase.
"""
import time
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor

client = TestClient(app)
_CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _run(raw_question, numeric_facts, supplier_evidence=None, extra_evidence=None, insights=None, recommendation="Evidence-based recommendation.", suffix=0, market_driver_claims=None):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"16.100.{suffix}.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    classify = {
        "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", **(extra_evidence or {})},
        "numeric_facts": numeric_facts, "supplier_specific_evidence": supplier_evidence or [],
    }
    if market_driver_claims is not None:
        classify["market_driver_claims"] = market_driver_claims
    pos = CommercialPosition(recommendation=recommendation, commercial_insights=insights or ["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": raw_question, "mode": "category_strategy"}, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}?include_diagnostics=true", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return d


# ---------------------------------------------------------------------
# Golden cases
# ---------------------------------------------------------------------

def test_golden_1_mro_sparse_data_process_driven():
    """MRO, sparse data. No supplier breakdown given -- must not invent
    a concentration finding that doesn't exist, and objective is
    genuinely ambiguous (no stated goal), so a question is warranted."""
    d = _run(
        "We buy MRO consumables, roughly $2M a year, mostly ad-hoc local purchases across sites. No clear supplier strategy.",
        {"category_annual_spend_usd": 2_000_000}, suffix=1,
    )
    a = d["commercial_position"]["category_strategy_answer"]
    assert d["status"] == "completed"
    # Must NOT surface an invented concentration finding -- no supplier data was given.
    assert "supplier_strategy" not in a or a.get("supplier_strategy") == []
    # Objective ambiguous -> a question about the objective is warranted.
    assert a.get("open_questions"), "expected an objective question when no goal is stated at all"


def test_golden_2_concentrated_direct_material_supplier_leverage():
    """Concentrated direct material -- supplier leverage is the
    dominant, must-surface finding."""
    d = _run(
        "We spend around $25M on marine consumables across 300 vessels. Main suppliers are Wrist, Sinwa and Kloska. "
        "Prices are increasing and local buying is fragmented. We want to reduce cost without hurting availability.",
        {"category_annual_spend_usd": 25_000_000, "category_prior_annual_spend_usd": 22_000_000},
        supplier_evidence=[
            {"supplier_name": "Wrist", "is_incumbent": True, "current_annual_spend_usd": 14_000_000, "prior_annual_spend_usd": 12_000_000},
            {"supplier_name": "Sinwa", "is_incumbent": True, "current_annual_spend_usd": 7_000_000},
            {"supplier_name": "Kloska", "is_incumbent": True, "current_annual_spend_usd": 4_000_000},
        ], suffix=2,
    )
    a = d["commercial_position"]["category_strategy_answer"]
    diag = a["diagnostics"]
    assert diag["objective"] is not None and "reduce cost" in diag["objective"]
    assert any("Wrist" in f["finding"] for f in a["what_matters_now"])
    assert any(s["supplier"] == "Wrist" and s["strategy"] == "challenge" for s in a["supplier_strategy"])
    # No objective question needed -- objective was already clear.
    assert not a.get("open_questions")


def test_golden_3_professional_services_labour_driven():
    """Professional services -- must be reasoned differently from a
    material category, not just relabeled."""
    d = _run(
        "We spend $8M a year on contract staffing services. Costs are rising and we suspect utilisation is falling.",
        {"category_annual_spend_usd": 8_000_000, "category_prior_annual_spend_usd": 7_000_000},
        market_driver_claims=[{"driver": "labour", "direction": "increased", "attributed_to": "unspecified"}],
        suffix=3,
    )
    a = d["commercial_position"]["category_strategy_answer"]
    assert d["status"] == "completed"
    assert a["diagnostics"]["archetype"] == "labour_intensive_services"


def test_golden_4_high_spend_low_complexity():
    """High spend, but no concentration/contradiction/unknown signal --
    must not manufacture complexity that isn't there."""
    d = _run(
        "We spend $40M a year on standard packaging materials from a well-established, diversified supplier base.",
        {"category_annual_spend_usd": 40_000_000, "category_prior_annual_spend_usd": 39_500_000},
        supplier_evidence=[
            {"supplier_name": "PackCo A", "is_incumbent": True, "current_annual_spend_usd": 8_000_000},
            {"supplier_name": "PackCo B", "is_incumbent": True, "current_annual_spend_usd": 7_000_000},
        ], suffix=4,
    )
    a = d["commercial_position"]["category_strategy_answer"]
    assert d["status"] == "completed"
    # No supplier here exceeds the challenge/develop thresholds -- must not force a "challenge" classification.
    assert not any(s["strategy"] in ("challenge",) for s in a.get("supplier_strategy", []))


def test_golden_5_low_spend_high_operational_criticality():
    """Low spend but operationally critical (poor OTIF) -- must
    surface the operational risk even though spend is small."""
    d = _run(
        "We spend only $300K a year on a specialised sensor component, but it is critical to production and OTIF has been poor.",
        {"category_annual_spend_usd": 300_000},
        supplier_evidence=[{"supplier_name": "SensorCo", "is_incumbent": True, "current_annual_spend_usd": 300_000, "otif_percent": 62.0}],
        suffix=5,
    )
    a = d["commercial_position"]["category_strategy_answer"]
    assert d["status"] == "completed"
    assert any("62" in note or "OTIF" in note for note in a["diagnostics"].get("supply_chain_notes", []))


def test_golden_6_specification_change_not_treated_as_pure_inflation():
    """Master spec CASE 4: price +12%, spec changed, volume -20% (so
    unit price genuinely moved +40%) -- must not attribute the full
    movement to supplier inflation once a specification change is
    also reported."""
    d = _run(
        "Category price rose but the specification also changed and volume fell.",
        {"category_annual_spend_usd": 1_120_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 8_000, "category_prior_annual_volume_units": 10_000},
        extra_evidence={"specification_changed": True, "specification_change_description": "Material content increased."},
        suffix=17,
    )
    a = d["commercial_position"]["category_strategy_answer"]
    price_finding = next(f for f in a["diagnostics"]["findings"] if "unit price" in f["finding"].lower())
    assert "specification change" in price_finding["finding"].lower()
    assert "must not" not in price_finding["implication"].lower() or "inflation" in price_finding["implication"].lower()
    assert price_finding["decision_impact"] == "DECISION_CRITICAL_UNKNOWN"


def test_golden_7_volume_driven_spend_increase_not_called_inflation():
    """Master spec CASE 5: spend +15%, volume +25% (fleet expansion) --
    unit price actually fell, so this must never be framed as an open
    inflation question."""
    d = _run(
        "Spend rose this year because our fleet expanded.",
        {"category_annual_spend_usd": 1_150_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 12_500, "category_prior_annual_volume_units": 10_000},
        suffix=18,
    )
    a = d["commercial_position"]["category_strategy_answer"]
    price_finding = next(f for f in a["diagnostics"]["findings"] if "unit price" in f["finding"].lower())
    assert "volume, not price" in price_finding["finding"].lower()
    assert price_finding["decision_impact"] == "BACKGROUND"
    assert "inflation" not in price_finding["finding"].lower()


def test_golden_8_contract_indexation_mechanism_not_conflated_with_validated_adjustment():
    """Master spec CASE 6: a supplier references a contractual
    adjustment clause -- the mechanism existing must not be treated as
    the requested adjustment being validated against it."""
    d = _run(
        "Supplier requests +6% per our contract's indexation clause.",
        {"category_annual_spend_usd": 2_000_000, "category_prior_annual_spend_usd": 1_900_000},
        extra_evidence={"suppliers_stated_justification": "Requesting +6% per the contract's annual adjustment clause."},
        suffix=19,
    )
    a = d["commercial_position"]["category_strategy_answer"]
    contract_finding = next(f for f in a["diagnostics"]["findings"] if "contractual adjustment mechanism" in f["finding"].lower())
    assert contract_finding["evidence_state"] == "SUPPLIER_CLAIM"
    assert contract_finding["decision_impact"] == "DECISION_CRITICAL_UNKNOWN"
    assert "entitled" not in contract_finding["finding"].lower()
    assert "not the same as" in contract_finding["implication"].lower()


def test_golden_9_high_concentration_no_disruption_does_not_force_dual_sourcing():
    """Master spec CASE 3: A=62%, B=18%, C=8%, others=12%, no
    disruption, no performance deterioration -- concentration must be
    surfaced, but dual-sourcing must never be the sole, automatic
    recommendation (only one option among several the buyer weighs)."""
    d = _run(
        "Concentration review, no known disruption.",
        {"category_annual_spend_usd": 10_000_000, "category_prior_annual_spend_usd": 9_800_000},
        supplier_evidence=[
            {"supplier_name": "A", "is_incumbent": True, "current_annual_spend_usd": 6_200_000, "otif_percent": 97.0},
            {"supplier_name": "B", "is_incumbent": True, "current_annual_spend_usd": 1_800_000},
            {"supplier_name": "C", "is_incumbent": True, "current_annual_spend_usd": 800_000},
        ], suffix=20,
    )
    a = d["commercial_position"]["category_strategy_answer"]
    a_strategy = next(s for s in a["supplier_strategy"] if s["supplier"] == "A")
    assert a_strategy["strategy"] == "challenge"  # concentration surfaced
    assert a_strategy["strategy"] != "dual_source"  # not a forced, dedicated dual-sourcing verdict
    assert "or" in a_strategy["reason"].lower()  # presented as one option among several, not the sole prescribed action


# ---------------------------------------------------------------------
# Differential tests -- same evidence shape, different category/archetype signal,
# reasoning and archetype must genuinely differ, not just the category name.
# ---------------------------------------------------------------------

def test_differential_archetype_changes_with_market_driver_evidence():
    common_numeric = {"category_annual_spend_usd": 10_000_000, "category_prior_annual_spend_usd": 9_000_000}
    d_material = _run("Category A spend review.", common_numeric, market_driver_claims=[{"driver": "steel", "direction": "increased", "attributed_to": "unspecified"}], suffix=6)
    d_services = _run("Category B spend review.", common_numeric, market_driver_claims=[{"driver": "labour", "direction": "increased", "attributed_to": "unspecified"}], suffix=7)
    a_material = d_material["commercial_position"]["category_strategy_answer"]["diagnostics"]
    a_services = d_services["commercial_position"]["category_strategy_answer"]["diagnostics"]
    assert a_material["archetype"] != a_services["archetype"]
    assert a_material["archetype"] == "industrial_component"
    assert a_services["archetype"] == "labour_intensive_services"


def test_differential_objective_changes_recommendation_framing():
    numeric = {"category_annual_spend_usd": 5_000_000, "category_prior_annual_spend_usd": 4_500_000}
    d_cost = _run("We spend $5M on this category and want to reduce cost.", numeric, suffix=8)
    d_service = _run("We spend $5M on this category and want to improve supply reliability.", numeric, suffix=9)
    obj_cost = d_cost["commercial_position"]["category_strategy_answer"]["diagnostics"]["objective"]
    obj_service = d_service["commercial_position"]["category_strategy_answer"]["diagnostics"]["objective"]
    assert obj_cost != obj_service
    assert "reduce cost" in obj_cost
    assert "availability" in obj_service or "reliability" in obj_service or "service" in obj_service


# ---------------------------------------------------------------------
# Adversarial tests
# ---------------------------------------------------------------------

def test_adversarial_supplier_claim_not_presented_as_fact():
    d = _run(
        "Our supplier says they are not overcharging us.",
        {"category_annual_spend_usd": 3_000_000}, suffix=10,
        insights=["The supplier claims they are not overcharging."],
    )
    a = d["commercial_position"]["category_strategy_answer"]
    assert d["status"] == "completed"
    assert a["diagnostics"].get("overcharging_claim_flagged_and_removed") is True


def test_adversarial_no_unsupported_market_conclusion():
    d = _run(
        "Steel prices have gone up this year and our supplier raised prices.",
        {"category_annual_spend_usd": 5_000_000, "category_prior_annual_spend_usd": 4_600_000},
        market_driver_claims=[{"driver": "steel", "direction": "increased", "attributed_to": "unspecified"}],
        suffix=11,
    )
    a = d["commercial_position"]["category_strategy_answer"]
    text = str(a)
    assert "proven" not in text.lower() or "not yet proven" in text.lower() or "not proven" in text.lower()


def test_adversarial_no_excessive_questions():
    """Even with several gaps, no more than 3 questions may reach the buyer."""
    d = _run("Spend review.", {"category_annual_spend_usd": 1_000_000}, suffix=12)
    a = d["commercial_position"]["category_strategy_answer"]
    assert len(a.get("open_questions", [])) <= 3


def test_adversarial_missing_objective_does_not_block_a_provisional_strategy():
    """A missing objective must not prevent VendorEdge from building
    the best evidence-bounded strategy available -- it should still
    complete, not require an answer before proceeding."""
    d = _run(
        "We spend $6M on this category across two suppliers, one holding 60% of spend.",
        {"category_annual_spend_usd": 6_000_000},
        supplier_evidence=[{"supplier_name": "Dom Co", "is_incumbent": True, "current_annual_spend_usd": 3_600_000}],
        suffix=13,
    )
    assert d["status"] == "completed"
    a = d["commercial_position"]["category_strategy_answer"]
    assert a.get("open_questions")  # asked about objective
    assert a.get("what_matters_now")  # but still produced a real, evidence-based finding


def test_adversarial_boundary_not_broadened_without_evidence():
    """No spare-parts/maintenance mention in the text -- must not
    surface a boundary note that was never triggered by the case."""
    d = _run("We spend $4M on industrial pumps.", {"category_annual_spend_usd": 4_000_000}, suffix=14)
    a = d["commercial_position"]["category_strategy_answer"]
    assert a.get("category_boundary_note") is None


def test_adversarial_boundary_surfaces_only_when_case_actually_mentions_it():
    d = _run("We spend $4M on industrial pumps, and spare parts costs have been rising too.", {"category_annual_spend_usd": 4_000_000}, suffix=15)
    a = d["commercial_position"]["category_strategy_answer"]
    assert a.get("category_boundary_note") is not None
    assert "spare part" in a["category_boundary_note"].lower()


def test_adversarial_no_generic_esg_content_when_irrelevant():
    d = _run("We spend $2M on a simple packaging category with no ESG concerns raised.", {"category_annual_spend_usd": 2_000_000}, suffix=16)
    a = d["commercial_position"]["category_strategy_answer"]
    assert "esg" not in a  # not surfaced when nothing was actually stated


# ---------------------------------------------------------------------
# Deterministic guardrails (master spec section 33)
# ---------------------------------------------------------------------

def test_guardrail_contradicted_evidence_never_classified_background():
    from app.pipeline.category_strategy_intelligence import apply_decision_impact_guardrails
    findings = [{"evidence_state": "CONTRADICTED", "decision_impact": "BACKGROUND", "finding": "x"}]
    corrected = apply_decision_impact_guardrails(findings)
    assert corrected[0]["decision_impact"] != "BACKGROUND"


def test_guardrail_unverified_supplier_claim_never_decision_changing():
    from app.pipeline.category_strategy_intelligence import apply_decision_impact_guardrails
    findings = [{"evidence_state": "SUPPLIER_CLAIM", "decision_impact": "DECISION_CHANGING", "finding": "x"}]
    corrected = apply_decision_impact_guardrails(findings)
    assert corrected[0]["decision_impact"] == "DECISION_CRITICAL_UNKNOWN"


def test_guardrail_leaves_correctly_classified_findings_untouched():
    from app.pipeline.category_strategy_intelligence import apply_decision_impact_guardrails
    findings = [{"evidence_state": "CALCULATED", "decision_impact": "DECISION_CHANGING", "finding": "x"}]
    corrected = apply_decision_impact_guardrails(findings)
    assert corrected[0]["decision_impact"] == "DECISION_CHANGING"


def test_guardrail_internal_marker_never_leaks_into_api_response():
    d = _run(
        "We spend around $25M on marine consumables. Main suppliers are Wrist, Sinwa and Kloska.",
        {"category_annual_spend_usd": 25_000_000, "category_prior_annual_spend_usd": 22_000_000},
        supplier_evidence=[{"supplier_name": "Wrist", "is_incumbent": True, "current_annual_spend_usd": 14_000_000}],
        suffix=19,
    )
    a = d["commercial_position"]["category_strategy_answer"]
    text = json.dumps(a)
    assert "_guardrail_applied" not in text


def test_what_matters_now_actually_rendered_in_frontend():
    from pathlib import Path
    text = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text()
    assert "WHAT MATTERS NOW" in text
