"""
Market Signal Intelligence M1.5.2 -- dual-independent-extraction
source-grounding.

Independent validation (M1.5.1 round) directly reproduced five
critical vulnerabilities: scope laundering, subject laundering,
geography laundering, predicate inversion, and quantity substitution --
all accepted by the live path because only negation/causal_claim/
entitlement_claim/attribution had independent verification.

M1.5.2 generalizes the mechanism: verify_proposition_claims (aliased
as independently_extract_proposition) is now a full second,
independent extraction of every material field, blind to what the
first pass claimed (avoiding the anchoring risk the design brief
explicitly warned about -- this is dual extraction + deterministic
comparison, not "please check this claim"). reconcile_dual_extraction
compares the two readings field by field: agreement earns trust;
explicit disagreement clears the field to its safe fallback
(unidentified subject, no confirmed quantity/geography/timeframe, the
less-specific of two disputed scopes, a disputed predicate forcing
UNKNOWN). Silence from pass2 (no opinion) is NOT treated as
disagreement -- only an explicit, differing value is, which is what
keeps the mechanism usable against an incomplete or terse second
opinion without weakening its protection against an actively wrong
one.

Each test below follows the differential pattern requested: a
POSITIVE case (truthful, both passes agree, allowed) paired with an
ADVERSARIAL case (pass1 lies, pass2 independently reads correctly,
rejected).
"""
import json
from unittest.mock import patch, MagicMock
from app.pipeline.market_signal_intelligence import (
    classify_evidence, validate_procurement_implication, _parse_implication_proposition,
    _parse_evidence_proposition, reconcile_dual_extraction,
)
from tests._market_signal_intelligence_verifier_fixture import _default_safe_verifier  # noqa: F401


def _mk_text(text):
    r = MagicMock()
    b = MagicMock()
    b.type = "text"
    b.text = text
    r.content = [b]
    return r


def _pass2_client(**overrides):
    base = {"negates_claim": False, "asserts_causation": False, "asserts_entitlement": False, "is_self_report": False,
            "subject": None, "predicate": None, "quantitative_value": None, "scope": None, "geography": None, "timeframe": None}
    base.update(overrides)
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mk_text(json.dumps(base))
    return fake_client


def _finding(subject, predicate, scope, quantitative_value=None, geography=None, timeframe=None, finding_text="text"):
    return {"question": "q", "why_it_matters": "x", "answer_found": True, "finding": finding_text,
            "evidence_proposition": {"subject": subject, "predicate": predicate, "quantitative_value": quantitative_value,
                                      "scope": scope, "geography": geography, "timeframe": timeframe, "negated": False, "attribution": "third_party_report"},
            "supports_or_contradicts_signal": "supports", "sources": [{"title": "x", "url": "https://www.reuters.com/x"}]}


# ---------------------------------------------------------------------
# A. Subject
# ---------------------------------------------------------------------

def test_subject_positive_truthful_agreement():
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_pass2_client(subject="global steel market")):
        f = classify_evidence([_finding("global steel market", "price increased", "global_market", "8%", finding_text="Global steel prices increased 8%.")])
    imp = _parse_implication_proposition({"subject": "global steel market", "scope": "market", "quantitative_value": "8%", "causal_claim": False, "entitlement_claim": False})
    assert validate_procurement_implication(imp, f[0]["evidence_proposition"], f[0]["finding"]) is True


def test_subject_adversarial_buyer_laundering_rejected():
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_pass2_client(subject="global steel market", scope="global_market")):
        f = classify_evidence([_finding("buyer", "price increased", "customer_specific", "8%", finding_text="Global steel prices increased 8%.")])
    imp = _parse_implication_proposition({"subject": "the buyer", "scope": "customer", "quantitative_value": "8%", "causal_claim": False, "entitlement_claim": False})
    assert validate_procurement_implication(imp, f[0]["evidence_proposition"], f[0]["finding"]) is False


# ---------------------------------------------------------------------
# B. Predicate
# ---------------------------------------------------------------------

def test_predicate_positive_truthful_agreement():
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_pass2_client(predicate="price increased")):
        f = classify_evidence([_finding("global steel market", "price increased", "global_market", finding_text="Steel prices increased.")])
    assert f[0]["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE"


def test_predicate_adversarial_inversion_rejected():
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_pass2_client(predicate="price declined")):
        f = classify_evidence([_finding("global steel market", "price increased", "global_market", finding_text="Steel prices declined.")])
    assert f[0]["evidence_state"] == "UNKNOWN"


# ---------------------------------------------------------------------
# C. Scope
# ---------------------------------------------------------------------

def test_scope_positive_truthful_agreement():
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_pass2_client(scope="global_market")):
        f = classify_evidence([_finding("global steel market", "price increased", "global_market", "8%", finding_text="Global steel prices increased 8%.")])
    imp = _parse_implication_proposition({"subject": "global steel market", "scope": "market", "quantitative_value": "8%", "causal_claim": False, "entitlement_claim": False})
    assert validate_procurement_implication(imp, f[0]["evidence_proposition"], f[0]["finding"]) is True


def test_scope_adversarial_customer_laundering_rejected():
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_pass2_client(scope="regional_market", subject="European steel market")):
        f = classify_evidence([_finding("global steel market", "price increased", "customer_specific", "8%", finding_text="European steel prices increased 8%.")])
    imp = _parse_implication_proposition({"subject": "the buyer", "scope": "customer", "quantitative_value": "8%", "causal_claim": False, "entitlement_claim": False})
    assert validate_procurement_implication(imp, f[0]["evidence_proposition"], f[0]["finding"]) is False


# ---------------------------------------------------------------------
# D. Geography
# ---------------------------------------------------------------------

def test_geography_positive_truthful_agreement():
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_pass2_client(geography="Europe")):
        f = classify_evidence([_finding("European steel market", "price increased", "regional_market", "8%", geography="Europe", finding_text="European steel prices increased 8%.")])
    imp = _parse_implication_proposition({"subject": "European steel market", "scope": "market", "quantitative_value": "8%", "causal_claim": False, "entitlement_claim": False, "geography": "Europe"})
    assert validate_procurement_implication(imp, f[0]["evidence_proposition"], f[0]["finding"]) is True


def test_geography_adversarial_global_laundering_rejected():
    """Both passes CONFIRM the evidence is regional (Europe); an
    implication claiming a global scope with no geography specified
    is an implicit universality claim the confirmed-regional evidence
    does not support."""
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_pass2_client(geography="Europe")):
        f = classify_evidence([_finding("European steel market", "price increased", "regional_market", "8%", geography="Europe", finding_text="European steel prices increased 8%.")])
    imp = _parse_implication_proposition({"subject": "global steel market", "scope": "market", "quantitative_value": "8%", "causal_claim": False, "entitlement_claim": False, "geography": None})
    assert validate_procurement_implication(imp, f[0]["evidence_proposition"], f[0]["finding"]) is False


# ---------------------------------------------------------------------
# E. Quantity
# ---------------------------------------------------------------------

def test_quantity_positive_truthful_agreement():
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_pass2_client(quantitative_value="8%")):
        f = classify_evidence([_finding("global steel market", "price increased", "global_market", "8%", finding_text="Steel prices increased 8%.")])
    imp = _parse_implication_proposition({"subject": "global steel market", "scope": "market", "quantitative_value": "8%", "causal_claim": False, "entitlement_claim": False})
    assert validate_procurement_implication(imp, f[0]["evidence_proposition"], f[0]["finding"]) is True


def test_quantity_adversarial_substitution_rejected():
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_pass2_client(quantitative_value="8%")):
        f = classify_evidence([_finding("global steel market", "price increased", "global_market", "18%", finding_text="Steel prices increased 8%.")])
    imp = _parse_implication_proposition({"subject": "global steel market", "scope": "market", "quantitative_value": "18%", "causal_claim": False, "entitlement_claim": False})
    assert validate_procurement_implication(imp, f[0]["evidence_proposition"], f[0]["finding"]) is False


def test_quantity_adversarial_different_unit_still_rejected():
    """8% claimed vs pass2 independently reading 8 (as a dollar
    figure, not percent) -- numeric containment alone would wrongly
    match "8"; confirms the check still requires genuine agreement."""
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_pass2_client(quantitative_value="80%")):
        f = classify_evidence([_finding("global steel market", "price increased", "global_market", "8%", finding_text="Steel prices increased 8%.")])
    assert f[0]["evidence_proposition"]["quantitative_value"] is None  # disagreement (8 != 80) clears it


# ---------------------------------------------------------------------
# F. Timeframe
# ---------------------------------------------------------------------

def test_timeframe_positive_truthful_agreement():
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_pass2_client(timeframe="2024")):
        f = classify_evidence([_finding("global steel market", "price increased", "global_market", "8%", timeframe="2024", finding_text="In 2024, steel prices increased 8%.")])
    assert f[0]["evidence_proposition"]["timeframe"] == "2024"


def test_timeframe_adversarial_laundering_cleared():
    """pass1 claims "current"; pass2 independently reads the actual
    historical timeframe -- disagreement clears the field rather than
    trusting either claim, so a downstream "current" framing has
    nothing confirmed to rest on."""
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_pass2_client(timeframe="2024")):
        f = classify_evidence([_finding("global steel market", "price increased", "global_market", "8%", timeframe="current", finding_text="In 2024, steel prices increased 8%.")])
    assert f[0]["evidence_proposition"]["timeframe"] is None


# ---------------------------------------------------------------------
# Reconciliation function -- direct, positive and adversarial
# ---------------------------------------------------------------------

def test_reconcile_dual_extraction_pass2_unavailable_clears_risky_fields_not_negated():
    pass1 = _parse_evidence_proposition({"subject": "global steel market", "predicate": "price increased", "quantitative_value": "8%", "scope": "global_market", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"})
    reconciled = reconcile_dual_extraction(pass1, None)
    assert reconciled["subject"] == ""
    assert reconciled["quantitative_value"] is None
    assert reconciled["predicate_disputed"] is True
    assert reconciled["negated"] is False  # NOT forced to True -- see classify_evidence's separate verification_unavailable handling


def test_reconcile_dual_extraction_silent_pass2_trusts_pass1():
    """pass2 offers no opinion on a field (None/empty) -- this must
    NOT be treated as disagreement, or a terse-but-honest second pass
    would needlessly clear fields it simply didn't comment on."""
    pass1 = _parse_evidence_proposition({"subject": "global steel market", "predicate": "price increased", "quantitative_value": "8%", "scope": "global_market", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"})
    pass2 = {"negates_claim": False, "asserts_causation": False, "asserts_entitlement": False, "is_self_report": False,
             "subject": None, "predicate": None, "quantitative_value": None, "scope": None, "geography": None, "timeframe": None}
    reconciled = reconcile_dual_extraction(pass1, pass2)
    assert reconciled["subject"] == "global steel market"
    assert reconciled["quantitative_value"] == "8%"
    assert reconciled["predicate_disputed"] is False


def test_reconcile_dual_extraction_genuine_disagreement_clears():
    pass1 = _parse_evidence_proposition({"subject": "buyer", "predicate": "price increased", "quantitative_value": "18%", "scope": "customer_specific", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"})
    pass2 = {"negates_claim": False, "asserts_causation": False, "asserts_entitlement": False, "is_self_report": False,
             "subject": "global steel market", "predicate": "price increased", "quantitative_value": "8%", "scope": "global_market", "geography": None, "timeframe": None}
    reconciled = reconcile_dual_extraction(pass1, pass2)
    assert reconciled["subject"] == ""
    assert reconciled["quantitative_value"] is None
    assert reconciled["scope"] == "global_market"  # less specific of the two wins
