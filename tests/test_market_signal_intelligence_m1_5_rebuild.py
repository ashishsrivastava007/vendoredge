"""
Market Signal Intelligence M1.5-rebuild -- proposition-based evidence
integrity.

The prior M1.5 slice used regex/keyword matching, which the second
independent validation showed is trivially bypassed by ordinary
paraphrase (9/10, 6/7, 5/5 bypass rates across the semantic-evasion,
non-numeric, and causal-fabrication attack classes), plus a domain-
spoofing defect and a direct truth-inversion defect.

This rebuild replaces surface-text matching with structured-proposition
comparison: execute_research() and synthesize_and_translate() now both
extract structured fields (subject/predicate/scope/quantitative_value/
causal_claim/entitlement_claim/negated/attribution), and deterministic
code compares those FIELDS -- not the raw sentences -- which is what
generalizes across paraphrase, since two different sentences expressing
the same fabrication should extract to the same structured claim.

Honest, stated limitation: this makes the deterministic layer only as
good as the extraction feeding it. Every test below either exercises
the deterministic comparison functions directly with hand-constructed
propositions (proven, reproducible) or simulates a plausible extraction
for a given sentence (illustrative of intended behavior, not proof of
real model output, since no live API key exists in this environment).
"""
from app.pipeline.market_signal_intelligence import (
    validate_procurement_implication, _parse_implication_proposition,
    _parse_evidence_proposition, classify_evidence, _classify_source_tier,
)
from tests._market_signal_intelligence_verifier_fixture import _default_safe_verifier  # noqa: F401 -- pytest autouse fixture


def _ev(**kwargs):
    base = {"subject": "", "predicate": "", "quantitative_value": None, "scope": "global_market",
            "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"}
    base.update(kwargs)
    return _parse_evidence_proposition(base)


def _im(**kwargs):
    base = {"subject": "", "scope": "market", "quantitative_value": None, "causal_claim": False, "entitlement_claim": False}
    base.update(kwargs)
    return _parse_implication_proposition(base)


# ---------------------------------------------------------------------
# A. Semantic paraphrase -- the class that broke the prior guardrail
# ---------------------------------------------------------------------

def test_A_semantic_paraphrase_customer_exposure_rejected():
    evidence = _ev(subject="global steel market", predicate="price increased", quantitative_value="8%", scope="global_market")
    for scope_word, subj in [("customer", "the buyer"), ("customer", "you")]:
        implication = _im(subject=subj, scope=scope_word, quantitative_value="8%")
        assert validate_procurement_implication(implication, evidence, "Global steel index increased 8%.") is False


def test_A_market_fact_restatement_allowed():
    evidence = _ev(subject="global steel market", predicate="price increased", quantitative_value="8%", scope="global_market")
    implication = _im(subject="global steel market", scope="market", quantitative_value="8%")
    assert validate_procurement_implication(implication, evidence, "Global steel index increased 8%.") is True


# ---------------------------------------------------------------------
# B. Non-numeric fabrication
# ---------------------------------------------------------------------

def test_B_non_numeric_customer_exposure_rejected():
    evidence = _ev(subject="global steel market", predicate="price increased", quantitative_value=None, scope="global_market")
    implication = _im(subject="the buyer", scope="customer", quantitative_value=None)
    assert validate_procurement_implication(implication, evidence, "Steel prices increased globally.") is False


def test_B_non_numeric_supplier_justification_entitlement_rejected():
    evidence = _ev(subject="global steel market", predicate="price increased", scope="global_market")
    implication = _im(subject="the supplier", scope="supplier", entitlement_claim=True)
    assert validate_procurement_implication(implication, evidence, "Steel prices increased globally.") is False


# ---------------------------------------------------------------------
# C. Causal fabrication
# ---------------------------------------------------------------------

def test_C_causal_claim_always_rejected_in_phase_1():
    evidence = _ev(subject="global steel market", predicate="price increased", scope="global_market")
    implication = _im(subject="the supplier", scope="supplier", causal_claim=True)
    assert validate_procurement_implication(implication, evidence, "Global steel prices increased.") is False


def test_C_non_causal_observation_allowed_when_scope_grounded():
    """"The two movements are directionally consistent" -- a supplier-
    scoped observation with no causal assertion, grounded in a finding
    that is itself supplier-specific -- should be allowed."""
    evidence = _ev(subject="the supplier", predicate="price increased", scope="supplier_specific")
    implication = _im(subject="the supplier", scope="supplier", causal_claim=False, entitlement_claim=False)
    assert validate_procurement_implication(implication, evidence, "The supplier's price increased, coinciding with the steel index rise.") is True


# ---------------------------------------------------------------------
# D. Party/scope expansion
# ---------------------------------------------------------------------

def test_D_supplier_scope_rejected_without_grounding():
    evidence = _ev(subject="European steel market", predicate="price increased", scope="regional_market", geography="Europe")
    implication = _im(subject="Supplier X", scope="supplier", quantitative_value=None)
    assert validate_procurement_implication(implication, evidence, "European steel prices increased.") is False


def test_D_category_scope_rejected():
    evidence = _ev(subject="global steel market", predicate="price increased", scope="global_market")
    implication = _im(subject="the category", scope="category", quantitative_value="8%")
    assert validate_procurement_implication(implication, evidence, "Global steel index increased 8%.") is False


# ---------------------------------------------------------------------
# E. Quantity invention
# ---------------------------------------------------------------------

def test_E_ungrounded_quantity_rejected():
    evidence = _ev(subject="global steel market", predicate="price increased", quantitative_value=None, scope="global_market")
    implication = _im(subject="global steel market", scope="market", quantitative_value="15%")
    assert validate_procurement_implication(implication, evidence, "Steel prices increased.") is False


def test_E_grounded_quantity_allowed():
    evidence = _ev(subject="global steel market", predicate="price increased", quantitative_value="8%", scope="global_market")
    implication = _im(subject="global steel market", scope="market", quantitative_value="8%")
    assert validate_procurement_implication(implication, evidence, "Global steel index increased 8%.") is True


# ---------------------------------------------------------------------
# H. Negation / I. Contradiction -- the truth-inversion fix
# ---------------------------------------------------------------------

def test_H_negated_evidence_forces_contradicted_regardless_of_verdict():
    findings = classify_evidence([{
        "question": "Did steel prices increase?", "why_it_matters": "x", "answer_found": True,
        "finding": "Steel prices did not increase during the period.",
        "evidence_proposition": {"subject": "global steel market", "predicate": "price increase", "quantitative_value": None, "scope": "global_market", "geography": None, "timeframe": None, "negated": True, "attribution": "third_party_report"},
        "supports_or_contradicts_signal": "supports",  # deliberately mislabeled, as in the reproduction case
        "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
    }])
    assert findings[0]["evidence_state"] == "CONTRADICTED"


def test_I_genuine_contradiction_preserved():
    findings = classify_evidence([{
        "question": "Did steel prices increase?", "why_it_matters": "x", "answer_found": True,
        "finding": "Independent source reports steel prices fell.",
        "evidence_proposition": {"subject": "global steel market", "predicate": "price fell", "quantitative_value": None, "scope": "global_market", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"},
        "supports_or_contradicts_signal": "contradicts",
        "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
    }])
    assert findings[0]["evidence_state"] == "CONTRADICTED"


# ---------------------------------------------------------------------
# J. Supplier claim promotion
# ---------------------------------------------------------------------

def test_J_supplier_claim_capped_regardless_of_attached_source_tier():
    findings = classify_evidence([{
        "question": "Did supplier X's steel costs increase 10%?", "why_it_matters": "x", "answer_found": True,
        "finding": "Supplier says steel costs increased 10%, therefore our price must increase 10%.",
        "evidence_proposition": {"subject": "Supplier X", "predicate": "input cost increased", "quantitative_value": "10%", "scope": "supplier_specific", "geography": None, "timeframe": None, "negated": False, "attribution": "supplier_claim"},
        "supports_or_contradicts_signal": "supports",
        "sources": [{"title": "Tier-1 source", "url": "https://www.sec.gov/filing"}],  # even a genuine Tier-1 source attached
    }])
    assert findings[0]["evidence_state"] != "EXTERNAL_MARKET_EVIDENCE"
    assert findings[0]["evidence_state"] != "VERIFIED"


# ---------------------------------------------------------------------
# K. Irrelevant keyword overlap / L. high-quality source, irrelevant / M. low-quality, relevant
# ---------------------------------------------------------------------

def test_K_irrelevant_keyword_overlap_resolves_unknown():
    findings = classify_evidence([{
        "question": "Does the new semiconductor fab increase wafer supply?", "why_it_matters": "x", "answer_found": True,
        "finding": "The semiconductor industry employs thousands of workers.",
        "evidence_proposition": {"subject": "semiconductor industry", "predicate": "employment increased", "quantitative_value": None, "scope": "industry_general", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"},
        "supports_or_contradicts_signal": "supports",
        "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
    }])
    assert findings[0]["evidence_state"] == "UNKNOWN"


def test_L_tier_1_source_but_irrelevant_still_unknown():
    findings = classify_evidence([{
        "question": "Did steel costs increase for this category?", "why_it_matters": "x", "answer_found": True,
        "finding": "Unrelated pharmaceutical labeling regulation filing.",
        "evidence_proposition": {"subject": "pharmaceutical regulator", "predicate": "labeling requirement changed", "quantitative_value": None, "scope": "industry_general", "geography": None, "timeframe": None, "negated": False, "attribution": "official_source"},
        "supports_or_contradicts_signal": "supports",
        "sources": [{"title": "x", "url": "https://www.sec.gov/filing"}],
    }])
    assert findings[0]["evidence_state"] == "UNKNOWN"


def test_M_low_quality_source_relevant_content_becomes_inferred_not_external():
    findings = classify_evidence([{
        "question": "Did steel prices increase?", "why_it_matters": "x", "answer_found": True,
        "finding": "A blog claims steel prices increased.",
        "evidence_proposition": {"subject": "global steel market", "predicate": "price increased", "quantitative_value": None, "scope": "global_market", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"},
        "supports_or_contradicts_signal": "supports",
        "sources": [{"title": "Blog", "url": "https://randomblog.net/post"}],
    }])
    assert findings[0]["evidence_state"] == "INFERRED"


# ---------------------------------------------------------------------
# N. Domain spoofing
# ---------------------------------------------------------------------

def test_N_domain_spoofing_rejected():
    assert _classify_source_tier("https://fake-sec.gov.evil.com/filing") != "TIER_1_PRIMARY"
    assert _classify_source_tier("https://example.com/sec.gov/filing") != "TIER_1_PRIMARY"
    assert _classify_source_tier("https://sec.gov/filing") == "TIER_1_PRIMARY"  # genuine case still works


# ---------------------------------------------------------------------
# Q. Model says SUPPORTS but evidence does not / R. says CONTRADICTS but evidence supports
# ---------------------------------------------------------------------

def test_Q_supports_verdict_on_topic_but_weak_content_still_relevant_but_bounded():
    """A finding that shares the topic but doesn't establish the
    specific numeric claim -- this module validates RELEVANCE
    (predicate-level), not the TRUTH of the self-reported verdict on
    genuinely on-topic content; that remains a stated, honest boundary
    (see the report), not silently hidden."""
    findings = classify_evidence([{
        "question": "Did steel prices increase 8%?", "why_it_matters": "x", "answer_found": True,
        "finding": "Steel remains an important input across manufacturing.",
        "evidence_proposition": {"subject": "steel", "predicate": "important input", "quantitative_value": None, "scope": "industry_general", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"},
        "supports_or_contradicts_signal": "supports",
        "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
    }])
    # predicate "important input" shares no significant word with the
    # question's core claim ("increase", "8"), so relevance correctly
    # fails here too -- this is the fix working as intended.
    assert findings[0]["evidence_state"] == "UNKNOWN"


def test_R_contradicts_verdict_is_trusted_as_given():
    findings = classify_evidence([{
        "question": "Did steel prices increase?", "why_it_matters": "x", "answer_found": True,
        "finding": "Steel prices increased according to the index.",
        "evidence_proposition": {"subject": "global steel market", "predicate": "price increased", "quantitative_value": None, "scope": "global_market", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"},
        "supports_or_contradicts_signal": "contradicts",  # mislabeled by the research step
        "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
    }])
    assert findings[0]["evidence_state"] == "CONTRADICTED"  # trusted as given; catching a mislabeled verdict on genuinely on-topic content is an explicit, stated boundary


# ---------------------------------------------------------------------
# S. Missing evidence / T. Malformed evidence / U. LLM failure / V. Research failure
# ---------------------------------------------------------------------

def test_S_missing_evidence_proposition_falls_back_safely():
    findings = classify_evidence([{
        "question": "Did steel prices increase?", "why_it_matters": "x", "answer_found": True,
        "finding": "Steel prices increased according to the index.",
        "supports_or_contradicts_signal": "supports", "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
    }])
    assert findings[0]["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE"  # whole-text fallback still works


def test_T_malformed_evidence_proposition_defaults_conservatively():
    findings = classify_evidence([{
        "question": "Did steel prices increase?", "why_it_matters": "x", "answer_found": True,
        "finding": "Steel prices increased.",
        "evidence_proposition": "not a dict at all",  # malformed
        "supports_or_contradicts_signal": "supports", "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
    }])
    assert findings[0]["evidence_state"] in ("EXTERNAL_MARKET_EVIDENCE", "UNKNOWN")  # does not crash; falls back safely


def test_U_implication_proposition_malformed_defaults_to_market_scope():
    ip = _parse_implication_proposition("not a dict")
    assert ip["scope"] == "market"
    assert ip["causal_claim"] is False
    assert ip["entitlement_claim"] is False


# ---------------------------------------------------------------------
# W. Unknown/unfamiliar category -- structural validator doesn't
# depend on any sector vocabulary
# ---------------------------------------------------------------------

def test_W_unfamiliar_category_structural_validation_unaffected():
    evidence = _ev(subject="global rare-earth market", predicate="export quota reduced", quantitative_value="15%", scope="global_market")
    rejected = _im(subject="the buyer", scope="customer", quantitative_value="15%")
    allowed = _im(subject="global rare-earth market", scope="market", quantitative_value="15%")
    assert validate_procurement_implication(rejected, evidence, "Global rare-earth export quota reduced 15%.") is False
    assert validate_procurement_implication(allowed, evidence, "Global rare-earth export quota reduced 15%.") is True
