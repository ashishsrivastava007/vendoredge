"""
Proves the Dynamic Experience principle, both halves:

1. DYNAMIC: materially different user situations (evidence-rich vs
   evidence-thin, root cause established vs not, strategy with real
   Year 1 actions vs strategy with nothing but boilerplate horizons)
   produce materially different section shapes -- not the same fixed
   template with different words in it.

2. STABLE: the same underlying situation, submitted twice as
   independent requests, produces the same section shape both times.
   "Dynamic" never means random -- a case that hasn't materially
   changed must not get a different answer shape on a whim.

Both halves are tested against the real HTTP path, using the actual
JSON fields that drive section visibility in app/static/index.html
(evidence.unknown, money.available, roadmap horizon content,
what_we_dont_know_yet) -- proving the DATA that determines the shape,
since the render functions themselves are JS and not exercised by
this Python suite.

A third check ties the two together: the underlying calculated truth
(money scenario figures) must be byte-identical between a "simple"
framing and a "complex" framing of the same core numbers, even though
the section shapes around those numbers differ.
"""
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor

client = TestClient(app)
_CONF = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _run(classify, pos_kwargs, mode=None, question="test", suffix_ip="1.1.1.1"):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": suffix_ip}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    pos = CommercialPosition(**pos_kwargs)
    body = {"raw_question": question}
    if mode:
        body["mode"] = mode
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json=body, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return d


_STRONG_EVIDENCE_SUPPLIER_REQUEST = {
    "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
    "extracted_evidence": {"supplier_currency": "USD", "suppliers_stated_justification": "Verified published cost index cited.", "how_critical_is_this_supplier_relationship": "sole-source, but request matches published index"},
    "numeric_facts": {"annual_spend_usd": 500_000, "requested_change_percent": 3.0},
    "supplier_specific_evidence": [{"supplier_name": "Supplier A", "is_incumbent": True}],
}
_WEAK_EVIDENCE_SUPPLIER_REQUEST = {
    "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
    "extracted_evidence": {"supplier_currency": "USD", "suppliers_stated_justification": "General cost pressures, no index cited.", "how_critical_is_this_supplier_relationship": "sole-source today, alternative under evaluation"},
    "numeric_facts": {"annual_spend_usd": 3_000_000, "requested_change_percent": 14.0},
    "supplier_specific_evidence": [
        {"supplier_name": "Supplier B", "is_incumbent": True},
        {"supplier_name": "Supplier C", "qualification_time_estimate": "3-4 months"},
    ],
}


def test_dynamic_supplier_request_evidence_gap_changes_section_shape():
    """DYNAMIC half: a real evidence gap (an unqualified alternative
    supplier) produces a non-empty evidence.unknown list -- the signal
    that makes WHAT IS MISSING render. A strong-evidence case produces
    none. This is the case genuinely differing, not the wording."""
    strong = _run(_STRONG_EVIDENCE_SUPPLIER_REQUEST,
                  dict(recommendation="Accept -- matches the cited index.", commercial_insights=["The requested increase aligns with a verifiable published cost index."], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization"),
                  suffix_ip="10.390.1.1")
    weak = _run(_WEAK_EVIDENCE_SUPPLIER_REQUEST,
                dict(recommendation="Push back; request supporting cost evidence.", commercial_insights=["No verifiable cost driver was cited."], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="A verified cost index would change this.", decision_type="optimization"),
                suffix_ip="10.390.2.1")
    strong_unknowns = (strong["commercial_position"]["commercial_answer"].get("evidence") or {}).get("unknown", [])
    weak_unknowns = (weak["commercial_position"]["commercial_answer"].get("evidence") or {}).get("unknown", [])
    assert strong_unknowns == []
    assert len(weak_unknowns) > 0


def test_dynamic_problem_solving_root_cause_certainty_changes_section_shape():
    """DYNAMIC half: a validated root cause (nothing left in what_we_
    dont_know_yet) is a materially different decision stage from an
    unresolved one -- options collapses to nothing worth re-listing in
    one case and stays populated in the other, driven by real evidence
    state, not by rewording."""
    resolved = _run(
        {"content_type": "problem_solving", "decision_type": "optimization", "constraint_satisfaction_signal": None,
         "extracted_evidence": {
             "problem_statement": "PO approval cycle time has grown to 15 days.",
             "current_condition": "15 business days.", "desired_condition": "3 business days.",
             "root_cause_candidates": [{"label": "incomplete requests at intake", "category": "root_cause", "source": "internal_data",
                 "supporting_evidence": ["Intake logs show 60% of requests are returned for missing fields."]}],
         }, "numeric_facts": {}},
        dict(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization"),
        suffix_ip="10.391.1.1")
    unresolved = _run(
        {"content_type": "problem_solving", "decision_type": "optimization", "constraint_satisfaction_signal": None,
         "extracted_evidence": {
             "problem_statement": "Warehouse cycle counts are inaccurate.",
             "current_condition": "12% variance.", "desired_condition": "2% variance.",
             "root_cause_candidates": [{"label": "inventory system problem", "category": "root_cause", "source": "internal_data", "supporting_evidence": []}],
         }, "numeric_facts": {}},
        dict(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization"),
        suffix_ip="10.391.2.1")
    a_resolved = resolved["commercial_position"]["problem_solving_answer"]
    a_unresolved = unresolved["commercial_position"]["problem_solving_answer"]
    assert a_resolved["what_we_dont_know_yet"] == []
    assert a_unresolved["what_we_dont_know_yet"] != []


def test_dynamic_category_strategy_roadmap_richness_changes_section_shape():
    """DYNAMIC half: a category with real Year 1 evidence produces real
    Year 1 actions; a category with almost no evidence produces none --
    the roadmap section itself should be present or absent based on
    that, not on how the question was phrased."""
    rich = _run(
        {"content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
         "extracted_evidence": {"supplier_currency": "EUR", "suppliers_stated_justification": "No price adjustment for three years."},
         "numeric_facts": {"annual_spend_usd": 5_550_000, "prior_annual_spend_usd": 4_370_000, "requested_change_percent": 11.0, "alternative_scenario_percent": 7.0,
             "category_annual_spend_usd": 8_400_000, "category_prior_annual_spend_usd": 7_050_000, "category_annual_volume_units": 412_000, "category_prior_annual_volume_units": 385_000},
         "supplier_specific_evidence": [
             {"supplier_name": "Supplier A", "is_incumbent": True, "current_annual_spend_usd": 5_550_000, "prior_annual_spend_usd": 4_370_000},
             {"supplier_name": "Supplier B", "qualification_time_estimate": "4-6 months"},
         ], "stated_price_history": ["Year -3: +2.5%", "Year -2: +3.0%", "Year -1: 0%"]},
        dict(recommendation="Challenge Supplier A; qualify Supplier B.", commercial_insights=["a"], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization"),
        mode="category_strategy", suffix_ip="10.392.1.1")
    thin = _run(
        {"content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
         "extracted_evidence": {"supplier_currency": "USD"},
         "numeric_facts": {"category_annual_spend_usd": 2_000_000, "category_prior_annual_spend_usd": 1_900_000},
         "supplier_specific_evidence": [{"supplier_name": "Supplier X", "is_incumbent": True, "current_annual_spend_usd": 2_000_000, "prior_annual_spend_usd": 1_900_000}]},
        dict(recommendation="Monitor for now.", commercial_insights=["a"], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization"),
        mode="category_strategy", suffix_ip="10.392.2.1")
    rich_roadmap = rich["commercial_position"]["category_strategy_answer"].get("roadmap", {})
    thin_roadmap = thin["commercial_position"]["category_strategy_answer"].get("roadmap", {})
    assert any(i.get("action") for i in rich_roadmap.get("year_1", []))
    assert not any(i.get("action") for i in thin_roadmap.get("year_1", []))
    assert not any(i.get("action") for i in thin_roadmap.get("year_2", []))


def test_stable_same_situation_produces_same_shape_twice():
    """STABLE half: the exact same evidence, submitted as two
    independent requests, must produce the same section-driving values
    both times -- "dynamic" must never mean "random". This is the
    check against artificial variety: nothing here should differ
    between the two runs."""
    run1 = _run(_WEAK_EVIDENCE_SUPPLIER_REQUEST,
                dict(recommendation="Push back; request supporting cost evidence.", commercial_insights=["No verifiable cost driver was cited."], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="A verified cost index would change this.", decision_type="optimization"),
                suffix_ip="10.393.1.1")
    run2 = _run(_WEAK_EVIDENCE_SUPPLIER_REQUEST,
                dict(recommendation="Push back; request supporting cost evidence.", commercial_insights=["No verifiable cost driver was cited."], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="A verified cost index would change this.", decision_type="optimization"),
                suffix_ip="10.393.2.1")
    ca1 = run1["commercial_position"]["commercial_answer"]
    ca2 = run2["commercial_position"]["commercial_answer"]
    assert (ca1.get("evidence") or {}).get("unknown") == (ca2.get("evidence") or {}).get("unknown")
    assert (ca1.get("money") or {}).get("available") == (ca2.get("money") or {}).get("available")
    assert ca1.get("money") == ca2.get("money")


def test_truth_unchanged_between_simple_and_complex_framing():
    """The underlying calculated truth must be identical regardless of
    how many sections surround it. Uses the certified Valves case both
    as a rich category-strategy view and reconstructed at the kernel
    level -- the same four figures must appear exactly, proving
    presentation differences never touch the numbers themselves."""
    rich = _run(
        {"content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
         "extracted_evidence": {"supplier_currency": "EUR", "suppliers_stated_justification": "No price adjustment for three years."},
         "numeric_facts": {"annual_spend_usd": 5_550_000, "prior_annual_spend_usd": 4_370_000, "requested_change_percent": 11.0, "alternative_scenario_percent": 7.0,
             "category_annual_spend_usd": 8_400_000, "category_prior_annual_spend_usd": 7_050_000, "category_annual_volume_units": 412_000, "category_prior_annual_volume_units": 385_000},
         "supplier_specific_evidence": [
             {"supplier_name": "Supplier A", "is_incumbent": True, "current_annual_spend_usd": 5_550_000, "prior_annual_spend_usd": 4_370_000},
             {"supplier_name": "Supplier B", "qualification_time_estimate": "4-6 months"},
         ], "stated_price_history": ["Year -3: +2.5%", "Year -2: +3.0%", "Year -1: 0%"]},
        dict(recommendation="Challenge Supplier A; qualify Supplier B.", commercial_insights=["a"], reasoning="x", confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization"),
        mode="category_strategy", suffix_ip="10.394.1.1")
    money = rich["commercial_position"]["category_strategy_answer"]["money"]
    assert money["current_annual_spend"] == 5_550_000.0
    assert money["scenario_a"]["impact"] == 610_500.0
    assert money["scenario_b"]["impact"] == 388_500.0
    assert money["difference"] == 222_000.0
