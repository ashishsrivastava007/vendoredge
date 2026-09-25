"""
Market Signal Intelligence M1.5 -- evidence & procurement translation
integrity.

Independent validation confirmed three defects and this file closes
them with permanent tests:

CRITICAL: procurement_translation had no deterministic guardrail
binding it to the evidence/finding it claims to be based on --
reproduced: "steel index rose 8%" -> "your supplier's steel components
will cost 8% more," accepted unmodified.

MAJOR: evidence_state traced entirely to one unverified model
self-report (supports_or_contradicts_signal) at the research step; the
existing guardrail only ever stopped a LATER call from overriding it.

MAJOR: no source-quality discrimination existed -- a blog and a
primary filing marked "supports" were classified identically.

Fixes: validate_procurement_translation() (Part 1), a deterministic
keyword-overlap relevance check inside classify_evidence() (Part 2),
and a minimal, extensible source-tier classifier feeding into
classify_evidence()'s credibility check (Part 3). The nine-value
evidence-state taxonomy is unchanged throughout.
"""
from app.pipeline.market_signal_intelligence import (
    validate_procurement_translation, classify_evidence, synthesize_and_translate,
    _classify_source_tier, _finding_relevant_to_question,
)
from unittest.mock import patch, MagicMock
import json
from tests._market_signal_intelligence_verifier_fixture import _default_safe_verifier  # noqa: F401 -- pytest autouse fixture


def _mk_text(text):
    r = MagicMock()
    b = MagicMock()
    b.type = "text"
    b.text = text
    r.content = [b]
    return r


# ---------------------------------------------------------------------
# Part 6 -- adversarial matrix, A-L
# ---------------------------------------------------------------------

def test_A_unsupported_supplier_exposure_rejected():
    result = validate_procurement_translation("Your supplier's steel components will cost 8% more.", "Global steel index increased 8%.")
    assert result is None


def test_B_supported_market_fact_allowed():
    result = validate_procurement_translation("Steel prices increased 8% globally.", "Global steel index increased 8%.")
    assert result == "Steel prices increased 8% globally."


def test_C_named_supplier_customer_price_claim_rejected():
    result = validate_procurement_translation("Supplier X will increase your prices by 8%.", "Steel prices increased 8% globally.")
    assert result is None


def test_D_supplier_claim_stays_supplier_claim_not_external_verified():
    findings = classify_evidence([{
        "question": "Did the supplier's stated cost increase actually occur?",
        "why_it_matters": "x", "answer_found": True,
        "finding": "Supplier X states steel costs increased 8%, but this is the supplier's own claim, not independently corroborated.",
        "supports_or_contradicts_signal": "supports",
        "sources": [],  # a bare, uncorroborated supplier statement, no external source
    }])
    # No credible source -> INFERRED, not EXTERNAL_MARKET_EVIDENCE.
    # (This module does not itself assign SUPPLIER_CLAIM -- that
    # distinction belongs to the finding-construction layer that
    # labels a case's own stated_justification; here we confirm the
    # weaker of the two non-authoritative states is used, never the
    # stronger externally-verified one, for an uncorroborated claim.)
    assert findings[0]["evidence_state"] in ("INFERRED", "UNKNOWN")
    assert findings[0]["evidence_state"] != "EXTERNAL_MARKET_EVIDENCE"
    assert findings[0]["evidence_state"] != "VERIFIED"


def test_E_primary_source_still_requires_proposition_relevance():
    """A Tier 1 source alone does not bypass the relevance check --
    source quality and proposition validation are independent axes."""
    findings = classify_evidence([{
        "question": "Did steel costs increase for this category?",
        "why_it_matters": "x", "answer_found": True,
        "finding": "Completely unrelated regulatory filing about pharmaceutical labeling requirements.",
        "supports_or_contradicts_signal": "supports",
        "sources": [{"title": "Filing", "url": "https://www.sec.gov/filing"}],
    }])
    assert findings[0]["evidence_state"] == "UNKNOWN"  # Tier 1 source, but zero relevance to the actual question


def test_F_blog_source_not_equivalent_to_tier_1():
    findings = classify_evidence([{
        "question": "Did steel prices rise recently?",
        "why_it_matters": "x", "answer_found": True,
        "finding": "A blog post claims steel prices rose recently, no citation given.",
        "supports_or_contradicts_signal": "supports",
        "sources": [{"title": "Blog", "url": "https://randomblog.net/steel-post"}],
    }])
    assert findings[0]["sources"][0]["source_tier"] == "TIER_4_GENERAL"
    assert findings[0]["evidence_state"] == "INFERRED"  # not EXTERNAL_MARKET_EVIDENCE, despite "supports" and a source existing


def test_G_source_exists_but_does_not_support_proposition():
    findings = classify_evidence([{
        "question": "Did aluminum prices rise this quarter?",
        "why_it_matters": "x", "answer_found": True,
        "finding": "Commentary on currency exchange rate movements in emerging markets.",
        "supports_or_contradicts_signal": "supports",
        "sources": [{"title": "Commentary", "url": "https://www.reuters.com/x"}],
    }])
    assert findings[0]["evidence_state"] == "UNKNOWN"  # zero keyword overlap with the actual question


def test_G2_KNOWN_LIMITATION_negation_defeats_keyword_overlap_check():
    """Honest, documented limitation: the deterministic relevance
    check is pure keyword overlap, not semantic understanding (per
    the explicit "do not over-engineer semantic entailment"
    instruction). A finding that mentions the target keyword WHILE
    EXPLICITLY NEGATING its relevance ("no mention of aluminum
    pricing") still shares that keyword with the question, so this
    check cannot distinguish "aluminum is discussed" from "aluminum is
    explicitly said to be absent." This is a real, stated gap, not
    silently hidden -- a genuine semantic-negation check is out of
    scope for this slice."""
    findings = classify_evidence([{
        "question": "Did aluminum prices rise this quarter?",
        "why_it_matters": "x", "answer_found": True,
        "finding": "General market commentary about currency exchange rates, no mention of aluminum pricing.",
        "supports_or_contradicts_signal": "supports",
        "sources": [{"title": "Commentary", "url": "https://www.reuters.com/x"}],
    }])
    # Documents the actual (imperfect) current behavior rather than
    # asserting the ideal one -- this test exists so the limitation is
    # visible and cannot silently regress further without notice.
    assert findings[0]["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE"


def test_H_related_subject_not_actual_proposition():
    findings = classify_evidence([{
        "question": "Did the semiconductor fab investment proceed as announced?",
        "why_it_matters": "x", "answer_found": True,
        "finding": "Employment trends in unrelated manufacturing sectors this quarter.",
        "supports_or_contradicts_signal": "supports",
        "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
    }])
    assert findings[0]["evidence_state"] == "UNKNOWN"  # zero keyword overlap with the actual question


def test_I_model_says_supports_but_content_irrelevant():
    findings = classify_evidence([{
        "question": "Did the new regulation require requalification of existing suppliers?",
        "why_it_matters": "x", "answer_found": True,
        "finding": "Weather forecast for the coming week shows scattered rain.",
        "supports_or_contradicts_signal": "supports",  # model self-reports "supports" despite total irrelevance
        "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
    }])
    assert findings[0]["evidence_state"] == "UNKNOWN"  # deterministic relevance check overrides the model's own claim


def test_J_model_says_supports_but_content_contradicts():
    """The model's self-reported verdict and the finding's actual
    content can disagree; classify_evidence trusts the verdict field
    only after the deterministic relevance gate passes -- it does not
    itself re-derive support/contradiction from prose (that remains
    the research step's job, consistent with 'do not build a second
    LLM research system'). This test documents that boundary rather
    than asserting a specific outcome beyond the relevance gate."""
    findings = classify_evidence([{
        "question": "Did steel prices rise this quarter?",
        "why_it_matters": "x", "answer_found": True,
        "finding": "Steel prices actually fell 3% this quarter according to the index.",
        "supports_or_contradicts_signal": "supports",  # mislabeled by the research step
        "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
    }])
    # Relevance passes (shares "steel", "prices", "quarter") so the
    # verdict is trusted as given -- the known, documented limitation
    # (see M1.5 report) is that this module does not independently
    # re-read prose to catch a mislabeled verdict; it only rejects
    # verdicts on irrelevant content.
    assert findings[0]["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE"


def test_K_conflicting_sources_preserved_not_collapsed():
    findings = classify_evidence([
        {"question": "q1", "why_it_matters": "x", "answer_found": True, "finding": "Source A confirms the capacity expansion.", "supports_or_contradicts_signal": "supports", "sources": [{"title": "A", "url": "https://www.reuters.com/a"}]},
        {"question": "q1", "why_it_matters": "x", "answer_found": True, "finding": "Source B reports the capacity expansion was delayed indefinitely.", "supports_or_contradicts_signal": "contradicts", "sources": [{"title": "B", "url": "https://www.bloomberg.com/b"}]},
    ])
    assert findings[0]["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE"
    assert findings[1]["evidence_state"] == "CONTRADICTED"
    assert findings[0] != findings[1]  # neither silently dropped nor merged


def test_L_llm_attempts_verified_upgrade_rejected():
    findings = classify_evidence([{"question": "q", "why_it_matters": "x", "answer_found": True, "finding": "weak", "supports_or_contradicts_signal": "supports", "sources": []}])
    assert findings[0]["evidence_state"] == "INFERRED"
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mk_text(json.dumps({"dimension_impacts": [{"dimension": "x", "finding": "y", "evidence_state": "VERIFIED", "implication": "z", "procurement_translation": None}], "decision_analysis": {}}))
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=fake_client):
        result = synthesize_and_translate({"actual_question": "x", "dimensions": []}, findings)
    assert len(result["dimension_impacts"]) == 0


# ---------------------------------------------------------------------
# Part 7 -- procurement translation differential test (mandatory)
# ---------------------------------------------------------------------

def test_differential_supported_vs_unsupported_translations():
    finding = "Global steel index increased 8%."
    supported = validate_procurement_translation("Global steel prices rose 8%.", finding)
    unsupported_supplier = validate_procurement_translation("Your supplier will raise prices 8%.", finding)
    unsupported_category = validate_procurement_translation("Your category cost will increase 8%.", finding)
    assert supported is not None
    assert unsupported_supplier is None
    assert unsupported_category is None


# ---------------------------------------------------------------------
# End-to-end: the exact reproduction case from the independent
# validation, run through the real synthesize_and_translate() call
# ---------------------------------------------------------------------

def test_end_to_end_reproduction_case_now_rejected():
    findings = classify_evidence([{"question": "Did steel prices rise?", "why_it_matters": "x", "answer_found": True, "finding": "General steel index rose 8% this quarter.", "supports_or_contradicts_signal": "supports", "sources": [{"title": "Index", "url": "https://www.reuters.com/index"}]}])
    fake_client = MagicMock()
    overreach = {"dimension_impacts": [{"dimension": "steel cost", "finding": "General steel index rose 8%.", "evidence_state": "EXTERNAL_MARKET_EVIDENCE", "implication": "Steel costs are rising broadly.", "procurement_translation": "Your supplier's steel-based components will cost 8% more."}], "decision_analysis": {}}
    fake_client.messages.create.return_value = _mk_text(json.dumps(overreach))
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=fake_client):
        result = synthesize_and_translate({"actual_question": "x", "dimensions": []}, findings)
    assert result["dimension_impacts"][0]["procurement_translation"] is None  # the exact fabrication path is now closed


# ---------------------------------------------------------------------
# Source tier classification -- direct
# ---------------------------------------------------------------------

def test_source_tier_classification():
    assert _classify_source_tier("https://www.sec.gov/filing") == "TIER_1_PRIMARY"
    assert _classify_source_tier("https://www.federalregister.gov/x") == "TIER_1_PRIMARY"
    assert _classify_source_tier("https://www.iso.org/x") == "TIER_2_SPECIALIST"
    assert _classify_source_tier("https://www.reuters.com/x") == "TIER_3_INDEPENDENT"
    assert _classify_source_tier("https://randomblog.net/x") == "TIER_4_GENERAL"
    assert _classify_source_tier("") == "UNCLASSIFIED"


def test_relevance_gate_direct():
    assert _finding_relevant_to_question("Did steel prices rise this quarter?", "Steel prices increased significantly this quarter.") is True
    assert _finding_relevant_to_question("Did steel prices rise this quarter?", "Weather forecast shows rain.") is False
    assert _finding_relevant_to_question("", "anything at all") is True  # nothing to check against -> not manufactured as a rejection
