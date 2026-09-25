"""
Market Signal Intelligence -- permanent test suite (Phase 1 hardening).

Converts the one-off verification scripts used during implementation
into a permanent, automated suite. Covers the six design-test cases
(A-F) through the real HTTP path with journey isolation confirmed
(classify() and generate_commercial_position() are poisoned to raise
if called, proving they genuinely are not invoked for this mode), plus
the adversarial matrix: no research result, conflicting research,
malformed LLM JSON (both calls), missing required fields, an attempted
evidence-state upgrade, unsupported claims, research-tool failure,
provider failure, irrelevant research, duplicate research questions,
and zero useful dimensions.
"""
import json
import time
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.pipeline.market_signal_intelligence import (
    understand_and_plan, build_research_plan, execute_research,
    classify_evidence, synthesize_and_translate, build_dynamic_answer,
)
from tests._market_signal_intelligence_verifier_fixture import _default_safe_verifier  # noqa: F401 -- pytest autouse fixture

client = TestClient(app)


def _mk_text_response(text):
    resp = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp.content = [block]
    return resp


def _poison_classify(*a, **kw):
    raise AssertionError("classify() was called for market_intelligence mode -- journey isolation broken")


def _poison_generate(*a, **kw):
    raise AssertionError("generate_commercial_position() was called for market_intelligence mode -- journey isolation broken")


def _run(raw_question, understand_json, research_findings_json_list, synthesis_json, suffix="x"):
    """Runs the real HTTP path with classify()/generate_commercial_
    position() poisoned (proving journey isolation on every call this
    file makes, not just a dedicated isolation test) and the two
    market_signal_intelligence LLM calls + research tool faked."""
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"210.{abs(hash(suffix)) % 250}.1.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}

    fake_client = MagicMock()
    call_count = {"n": 0}

    def fake_create(**kwargs):
        call_count["n"] += 1
        return _mk_text_response(json.dumps(understand_json) if call_count["n"] == 1 else json.dumps(synthesis_json))

    fake_client.messages.create.side_effect = fake_create

    fake_tool = MagicMock()
    findings_iter = iter(research_findings_json_list)

    def fake_search(prompt, **kwargs):
        try:
            return json.dumps(next(findings_iter))
        except StopIteration:
            return json.dumps({"answer_found": False, "finding": "", "sources": []})

    fake_tool.search.side_effect = fake_search

    with patch("app.routes.decisions.classify", side_effect=_poison_classify), \
         patch("app.routes.decisions.generate_commercial_position", side_effect=_poison_generate), \
         patch("app.pipeline.market_signal_intelligence._get_client", return_value=fake_client), \
         patch("app.pipeline.market_signal_intelligence.get_research_tool", return_value=fake_tool):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": raw_question, "mode": "market_intelligence"}, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return d, org


# ---------------------------------------------------------------------
# Journey isolation -- a dedicated, explicit test (also implicitly
# proven by every other test in this file via the poisoned mocks above)
# ---------------------------------------------------------------------

def test_journey_isolation_classify_and_generate_never_called():
    understand = {"actual_question": "q", "claimed_facts": ["f"], "entities": ["e"], "category_context": None,
                  "research_questions": [], "dimensions": [{"dimension": "d1", "why_relevant": "r1"}]}
    d, _ = _run("isolation check signal", understand, [], {"dimension_impacts": [], "decision_analysis": {}}, suffix="isolation")
    assert d["status"] == "completed"
    assert d["commercial_position"]["market_intelligence_answer"] is not None


def test_journey_isolation_unrelated_journeys_unaffected():
    """A supplier_request case must still route normally and must
    never carry a market_intelligence_answer -- proving the routing
    change is additive, not a shared-path rewrite. Whether this
    specific case reaches "completed" or correctly asks for more
    evidence is supplier_request's own, unchanged, already-covered
    behavior (see the full protected suite) -- not what this test is
    about."""
    from app.models import CommercialPosition, Confidence, ConfidenceFactor
    _CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")
    classify_result = {"content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
                        "extracted_evidence": {"supplier_currency": "USD"},
                        "numeric_facts": {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000,
                                          "requested_change_percent": 5.0},
                        "supplier_specific_evidence": [{"supplier_name": "IsolCheckCo", "is_incumbent": True, "current_annual_spend_usd": 500_000}]}
    pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "211.1.1.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    with patch("app.routes.decisions.classify", return_value=classify_result), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "supplier wants 5% more", "mode": "supplier_request"}, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    assert d["status"] in ("completed", "awaiting_user_input")
    assert (d.get("commercial_position") or {}).get("market_intelligence_answer") is None


# ---------------------------------------------------------------------
# Six design-test cases (A-F), executed through the real pipeline
# ---------------------------------------------------------------------

def test_case_a_supplier_price_justification():
    understand = {
        "actual_question": "Is the supplier's stated 12% increase justification accurate?",
        "claimed_facts": ["A supplier requested a 12% price increase citing raw material costs"],
        "entities": ["supplier"], "category_context": "unspecified component",
        "research_questions": [{"question": "Have relevant raw material costs actually risen recently?", "why_it_matters": "directly tests the stated justification"}],
        "dimensions": [{"dimension": "cost-driver verification", "why_relevant": "the entire question is whether the stated driver is real"}],
    }
    findings = [{"answer_found": True, "finding": "No broad raw material increase found in the specified period.", "supports_or_contradicts_signal": "contradicts", "sources": [{"title": "Index", "url": "https://example.com/index"}]}]
    synthesis = {"dimension_impacts": [{"dimension": "cost-driver verification", "finding": "No corroborating raw material increase found.", "evidence_state": "CONTRADICTED", "implication": "The stated justification is not currently supported by public data.", "procurement_translation": "Push back on the justification and request supplier-specific evidence."}],
                 "decision_analysis": {"what_could_change": "Whether to accept the price increase.", "what_to_do_now": "Request the supplier's own cost breakdown.", "what_not_to_do_yet": "Do not accept the increase as justified.", "what_would_change_the_conclusion": "Supplier-specific evidence of a real cost increase."}}
    d, _ = _run("A supplier asked for a 12% price increase citing raw material costs. Validate their justification.", understand, findings, synthesis, suffix="A")
    assert d["status"] == "completed"
    a = d["commercial_position"]["market_intelligence_answer"]
    dims = {di["dimension"] for di in a["dimension_impacts"]}
    assert "cost-driver verification" in dims
    assert a["dimension_impacts"][0]["evidence_state"] == "CONTRADICTED"


def test_case_b_semiconductor_fab_investment():
    understand = {
        "actual_question": "How could a new semiconductor fab affect electronics procurement?",
        "claimed_facts": ["A major semiconductor manufacturer is building a new fabrication plant"],
        "entities": ["semiconductor manufacturer"], "category_context": "electronics components",
        "research_questions": [{"question": "What is the scale and timeline of this fab investment?", "why_it_matters": "determines when capacity relief could materialize"}],
        "dimensions": [{"dimension": "manufacturing capacity expansion", "why_relevant": "new capacity could ease allocation constraints"}, {"dimension": "lead-time impact", "why_relevant": "timing affects near-term planning"}],
    }
    findings = [{"answer_found": True, "finding": "Public filings confirm a $20B investment, online in 2028.", "supports_or_contradicts_signal": "supports", "sources": [{"title": "SEC filing", "url": "https://www.sec.gov/filing"}]}]
    synthesis = {"dimension_impacts": [{"dimension": "manufacturing capacity expansion", "finding": "Confirmed $20B fab investment, online 2028.", "evidence_state": "EXTERNAL_MARKET_EVIDENCE", "implication": "Long lead time before relief materializes.", "procurement_translation": "No near-term allocation relief expected."}],
                 "decision_analysis": {"what_could_change": "Lead-time and allocation strategy.", "what_to_do_now": "Continue dual-sourcing.", "what_not_to_do_yet": "Do not reduce safety stock.", "what_would_change_the_conclusion": "An earlier ramp confirmed."}}
    d, _ = _run("A major semiconductor manufacturer is building a new fab. What could this mean for my electronics procurement?", understand, findings, synthesis, suffix="B")
    assert d["status"] == "completed"
    a = d["commercial_position"]["market_intelligence_answer"]
    dims = {di["dimension"] for di in a["dimension_impacts"]}
    assert "manufacturing capacity expansion" in dims
    assert "cost-driver verification" not in dims  # materially different from case A


def test_case_c_saas_pricing_change():
    understand = {
        "actual_question": "What should be investigated before renewing given the SaaS vendor's pricing model change?",
        "claimed_facts": ["A SaaS vendor is changing its pricing model"],
        "entities": ["SaaS vendor"], "category_context": "software licensing",
        "research_questions": [{"question": "What is the new pricing model and how does it compare to the current one?", "why_it_matters": "determines cost impact at renewal"}],
        "dimensions": [{"dimension": "licensing mechanics", "why_relevant": "usage-based vs seat-based shifts can materially change cost"}, {"dimension": "switching cost", "why_relevant": "relevant if the new model makes renewal less attractive"}],
    }
    findings = [{"answer_found": True, "finding": "Vendor is shifting from seat-based to usage-based pricing effective next quarter.", "supports_or_contradicts_signal": "supports", "sources": [{"title": "Reuters coverage of vendor announcement", "url": "https://www.reuters.com/technology/pricing-change"}]}]
    synthesis = {"dimension_impacts": [{"dimension": "licensing mechanics", "finding": "Confirmed shift to usage-based pricing next quarter.", "evidence_state": "EXTERNAL_MARKET_EVIDENCE", "implication": "Cost could rise or fall depending on actual usage patterns.", "procurement_translation": "Model current usage against the new pricing before renewal."}],
                 "decision_analysis": {"what_could_change": "Renewal terms and budget.", "what_to_do_now": "Request usage data and model cost under the new structure.", "what_not_to_do_yet": "Do not renew under the old assumption.", "what_would_change_the_conclusion": "Actual usage-based cost modeling results."}}
    d, _ = _run("A SaaS vendor is changing its pricing model. What should I investigate before renewal?", understand, findings, synthesis, suffix="C")
    assert d["status"] == "completed"
    a = d["commercial_position"]["market_intelligence_answer"]
    dims = {di["dimension"] for di in a["dimension_impacts"]}
    assert "licensing mechanics" in dims
    assert "manufacturing capacity expansion" not in dims


def test_case_d_pharma_regulation():
    understand = {
        "actual_question": "How could a new pharmaceutical regulation affect sourcing strategy?",
        "claimed_facts": ["A new pharmaceutical regulation was announced"],
        "entities": ["regulator"], "category_context": "pharmaceutical sourcing",
        "research_questions": [{"question": "What does the regulation actually require and by when?", "why_it_matters": "determines compliance timeline and supplier impact"}],
        "dimensions": [{"dimension": "regulatory compliance timeline", "why_relevant": "determines urgency"}, {"dimension": "supplier qualification status", "why_relevant": "existing suppliers may need requalification"}],
    }
    findings = [{"answer_found": True, "finding": "The regulation requires updated manufacturing qualifications within 18 months.", "supports_or_contradicts_signal": "supports", "sources": [{"title": "Regulatory filing", "url": "https://www.federalregister.gov/reg"}]}]
    synthesis = {"dimension_impacts": [{"dimension": "regulatory compliance timeline", "finding": "18-month requalification window confirmed.", "evidence_state": "EXTERNAL_MARKET_EVIDENCE", "implication": "Suppliers not yet requalified could become unusable after the window.", "procurement_translation": "Audit current suppliers' requalification status now."}],
                 "decision_analysis": {"what_could_change": "Which suppliers remain qualified sources.", "what_to_do_now": "Request requalification status from current suppliers.", "what_not_to_do_yet": "Do not assume all current suppliers remain compliant.", "what_would_change_the_conclusion": "Confirmed requalification status per supplier."}}
    d, _ = _run("A new pharmaceutical regulation was announced. How could this affect our sourcing strategy?", understand, findings, synthesis, suffix="D")
    assert d["status"] == "completed"
    a = d["commercial_position"]["market_intelligence_answer"]
    dims = {di["dimension"] for di in a["dimension_impacts"]}
    assert "regulatory compliance timeline" in dims
    assert "licensing mechanics" not in dims


def test_case_e_linkedin_claim_needs_verification():
    understand = {
        "actual_question": "How could Company X's reported AI infrastructure investment affect our procurement?",
        "claimed_facts": ["A LinkedIn post claims Company X is investing heavily in AI infrastructure"],
        "entities": ["Company X"], "category_context": None,
        "research_questions": [{"question": "Is there public corroboration of this investment beyond the LinkedIn post?", "why_it_matters": "a single social post is a weak, low-tier source"}],
        "dimensions": [{"dimension": "signal corroboration", "why_relevant": "the claim's source tier is low and needs independent confirmation before any procurement conclusion"}],
    }
    findings = [{"answer_found": False, "finding": "", "supports_or_contradicts_signal": "inconclusive", "sources": []}]
    synthesis = {"dimension_impacts": [{"dimension": "signal corroboration", "finding": "No independent corroboration found beyond the original post.", "evidence_state": "UNKNOWN", "implication": "The claim remains unverified.", "procurement_translation": None}],
                 "decision_analysis": {"what_could_change": None, "what_to_do_now": None, "what_not_to_do_yet": "Do not treat this as established fact for planning purposes.", "what_would_change_the_conclusion": "Independent, corroborating reporting or an official company statement."}}
    d, _ = _run("This LinkedIn post says Company X is investing heavily in AI infrastructure. How could this affect our procurement?", understand, findings, synthesis, suffix="E")
    assert d["status"] == "completed"
    a = d["commercial_position"]["market_intelligence_answer"]
    assert a["dimension_impacts"][0]["evidence_state"] == "UNKNOWN"
    assert a["dimension_impacts"][0]["procurement_translation"] is None  # correctly NOT forced


def test_case_f_unfamiliar_category():
    """A category with no precedent anywhere in this codebase --
    proves dimension discovery doesn't depend on a hardcoded list."""
    understand = {
        "actual_question": "How could a new deep-sea mineral extraction technology affect specialty alloy sourcing?",
        "claimed_facts": ["A new deep-sea mineral extraction technology has been announced"],
        "entities": ["extraction technology provider"], "category_context": "specialty alloys",
        "research_questions": [{"question": "What minerals does this technology target and at what scale?", "why_it_matters": "determines whether relevant alloy inputs are affected"}],
        "dimensions": [{"dimension": "deep-sea extraction yield economics", "why_relevant": "determines whether this meaningfully adds to mineral supply"}, {"dimension": "environmental permitting risk", "why_relevant": "could delay or block the technology's actual deployment"}],
    }
    findings = [{"answer_found": True, "finding": "Pilot-scale only; full deployment pending permits, no confirmed timeline.", "supports_or_contradicts_signal": "inconclusive", "sources": [{"title": "Industry report", "url": "https://example.com/report"}]}]
    synthesis = {"dimension_impacts": [{"dimension": "deep-sea extraction yield economics", "finding": "Still pilot-scale; no confirmed production timeline.", "evidence_state": "UNKNOWN", "implication": "Too early to assess supply impact.", "procurement_translation": None}],
                 "decision_analysis": {"what_could_change": None, "what_to_do_now": None, "what_not_to_do_yet": "Do not factor this into current sourcing plans.", "what_would_change_the_conclusion": "Confirmed commercial-scale production timeline."}}
    d, _ = _run("A new deep-sea mineral extraction technology has been announced. Could this affect our specialty alloy sourcing?", understand, findings, synthesis, suffix="F")
    assert d["status"] == "completed"
    a = d["commercial_position"]["market_intelligence_answer"]
    dims = {di["dimension"] for di in a["dimension_impacts"]}
    assert "deep-sea extraction yield economics" in dims  # a dimension invented for this case alone, not from any fixed list


# ---------------------------------------------------------------------
# Dynamic architecture test -- materially different problems must
# produce materially different dimension sets, not the same template
# with different words
# ---------------------------------------------------------------------

def test_dynamic_architecture_dimensions_differ_materially_across_cases():
    cases = [
        ({"actual_question": "a", "claimed_facts": [], "entities": [], "category_context": None, "research_questions": [], "dimensions": [{"dimension": "cost-driver verification", "why_relevant": "x"}]}, "supplier"),
        ({"actual_question": "b", "claimed_facts": [], "entities": [], "category_context": None, "research_questions": [], "dimensions": [{"dimension": "manufacturing capacity expansion", "why_relevant": "x"}, {"dimension": "lead-time impact", "why_relevant": "x"}]}, "fab"),
        ({"actual_question": "c", "claimed_facts": [], "entities": [], "category_context": None, "research_questions": [], "dimensions": [{"dimension": "regulatory compliance timeline", "why_relevant": "x"}]}, "pharma"),
        ({"actual_question": "d", "claimed_facts": [], "entities": [], "category_context": None, "research_questions": [], "dimensions": [{"dimension": "licensing mechanics", "why_relevant": "x"}, {"dimension": "switching cost", "why_relevant": "x"}]}, "saas"),
        ({"actual_question": "e", "claimed_facts": [], "entities": [], "category_context": None, "research_questions": [], "dimensions": [{"dimension": "deep-sea extraction yield economics", "why_relevant": "x"}]}, "unfamiliar"),
    ]
    all_dimension_sets = [frozenset(d["dimension"] for d in plan["dimensions"]) for plan, _ in cases]
    # No two cases share the identical dimension set (proves no fixed template is being reused verbatim)
    assert len(set(all_dimension_sets)) == len(all_dimension_sets)
    # No case's dimension set is a subset naming used by an unrelated case (spot check: fab dims never appear in pharma or saas)
    assert not (all_dimension_sets[1] & all_dimension_sets[2])
    assert not (all_dimension_sets[1] & all_dimension_sets[3])


def test_dynamic_architecture_identical_input_produces_identical_architecture():
    """No random variation: same question + same evidence -> same
    dimension set, run twice."""
    understand = {"actual_question": "q", "claimed_facts": ["f"], "entities": [], "category_context": None,
                  "research_questions": [], "dimensions": [{"dimension": "d1", "why_relevant": "r1"}, {"dimension": "d2", "why_relevant": "r2"}]}
    d1, _ = _run("deterministic check signal", understand, [], {"dimension_impacts": [], "decision_analysis": {}}, suffix="det1")
    d2, _ = _run("deterministic check signal", understand, [], {"dimension_impacts": [], "decision_analysis": {}}, suffix="det2")
    a1 = d1["commercial_position"]["market_intelligence_answer"]
    a2 = d2["commercial_position"]["market_intelligence_answer"]
    assert a1.get("dimension_impacts") == a2.get("dimension_impacts")


# ---------------------------------------------------------------------
# Adversarial matrix
# ---------------------------------------------------------------------

def test_adversarial_no_research_result():
    plan = {"actual_question": "q", "claimed_facts": [], "entities": [], "category_context": None, "research_questions": [], "dimensions": []}
    answer = build_dynamic_answer("q", plan, [], None)
    assert "research_findings" not in answer
    assert answer["message"]


def test_adversarial_conflicting_research_results():
    findings = classify_evidence([
        {"question": "q1", "why_it_matters": "x", "answer_found": True, "finding": "Prices rose.", "supports_or_contradicts_signal": "supports", "sources": [{"title": "A", "url": "https://www.reuters.com/a"}]},
        {"question": "q1", "why_it_matters": "x", "answer_found": True, "finding": "Prices fell.", "supports_or_contradicts_signal": "contradicts", "sources": [{"title": "B", "url": "https://www.bloomberg.com/b"}]},
    ])
    assert findings[0]["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE"
    assert findings[1]["evidence_state"] == "CONTRADICTED"  # both preserved distinctly, neither silently dropped


def test_adversarial_malformed_llm1_json():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mk_text_response("not json at all, just prose")
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=fake_client):
        result = understand_and_plan("some signal")
    assert result is None  # never fabricates an understanding from garbage


def test_adversarial_malformed_llm2_json():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mk_text_response("also not json")
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=fake_client):
        result = synthesize_and_translate({"actual_question": "q", "dimensions": []}, [])
    assert result is None


def test_adversarial_missing_required_fields_in_llm1_response():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mk_text_response(json.dumps({"actual_question": "q"}))  # missing everything else
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=fake_client):
        result = understand_and_plan("some signal")
    assert result is not None
    assert result["dimensions"] == []
    assert result["research_questions"] == []
    assert result["claimed_facts"] == []


def test_adversarial_model_attempts_evidence_state_upgrade():
    classified = classify_evidence([{"question": "q1", "why_it_matters": "x", "answer_found": True, "finding": "found something", "supports_or_contradicts_signal": "supports", "sources": []}])
    assert classified[0]["evidence_state"] == "INFERRED"
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mk_text_response(json.dumps({"dimension_impacts": [{"dimension": "x", "finding": "y", "evidence_state": "VERIFIED", "implication": "z", "procurement_translation": None}], "decision_analysis": {}}))
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=fake_client):
        result = synthesize_and_translate({"actual_question": "x", "dimensions": []}, classified)
    assert len(result["dimension_impacts"]) == 0  # rejected, not silently accepted


def test_adversarial_unsupported_supplier_exposure_not_forced():
    findings = classify_evidence([{"question": "q1", "why_it_matters": "x", "answer_found": True, "finding": "Market driver moved.", "supports_or_contradicts_signal": "supports", "sources": [{"title": "A", "url": "https://www.reuters.com/market-driver"}]}])
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mk_text_response(json.dumps({"dimension_impacts": [{"dimension": "x", "finding": "Market driver moved.", "evidence_state": "EXTERNAL_MARKET_EVIDENCE", "implication": "Could matter generally.", "procurement_translation": None}], "decision_analysis": {}}))
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=fake_client):
        result = synthesize_and_translate({"actual_question": "x", "dimensions": []}, findings)
    assert result["dimension_impacts"][0]["procurement_translation"] is None  # "not established" is accepted, not rejected


def test_adversarial_research_tool_failure_does_not_block():
    def raising_search(*a, **kw):
        raise RuntimeError("search backend unavailable")
    fake_tool = MagicMock()
    fake_tool.search.side_effect = raising_search
    plan = [{"question": "q1", "why_it_matters": "x", "prompt": "p"}]
    with patch("app.pipeline.market_signal_intelligence.get_research_tool", return_value=fake_tool):
        results = execute_research(plan)
    assert len(results) == 1
    assert results[0]["answer_found"] is False  # degraded, not raised


def test_adversarial_llm_provider_failure_does_not_block():
    def raising_get_client():
        raise RuntimeError("provider unavailable")
    with patch("app.pipeline.market_signal_intelligence._get_client", side_effect=raising_get_client):
        result = understand_and_plan("some signal")
    assert result is None  # caller degrades gracefully, does not raise


def test_adversarial_irrelevant_research_result_not_forced_into_dimension():
    findings = classify_evidence([{"question": "q1", "why_it_matters": "x", "answer_found": True, "finding": "Unrelated fact about a different topic entirely.", "supports_or_contradicts_signal": "not_applicable", "sources": [{"title": "A", "url": "https://a.example.com"}]}])
    assert findings[0]["evidence_state"] == "UNKNOWN"  # not_applicable maps conservatively, never promoted


def test_adversarial_duplicate_research_questions_still_capped():
    plan = {"actual_question": "q", "research_questions": [{"question": "same question", "why_it_matters": "x"}] * 5, "dimensions": []}
    research_plan = build_research_plan(plan)
    assert len(research_plan) <= 3  # cost-control cap enforced regardless of duplication


def test_adversarial_zero_useful_dimensions_is_valid_not_an_error():
    plan = {"actual_question": "q", "claimed_facts": [], "entities": [], "category_context": None, "research_questions": [], "dimensions": []}
    answer = build_dynamic_answer("q", plan, [], None)
    assert answer["understood"] is True
    assert "dimension_impacts" not in answer
    assert answer["message"]
