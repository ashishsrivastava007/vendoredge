"""
Market Signal Intelligence M1.5.1 -- source-grounded proposition
verification.

The M1.5-rebuild independent validation proved that structured
extraction alone is not trustworthy: a single-pass extraction that
mislabels scope/negated/causal_claim/entitlement_claim/attribution is
accepted unconditionally, since nothing checks the extraction against
the source text it claims to describe.

M1.5.1 adds a second, independent verification pass
(verify_proposition_claims) for the four fields proven most
exploitable (negated, causal_claim, entitlement_claim, attribution/
self-report), reconciled conservatively: either pass flagging the
risky property is enough to treat it as present. These tests exercise
that reconciliation directly, simulating BOTH "first pass lies,
verifier catches it" and "verifier itself is unavailable" scenarios --
the fixture in _market_signal_intelligence_verifier_fixture.py supplies
a safe default for any test that doesn't override it.

Honestly scoped out of this pass, stated plainly rather than hidden:
full source-grounding verification for scope/geography/subject
extraction remains unimplemented (these fields still trust the
single-pass extraction); the negation/causal/entitlement/attribution
fields the second independent validation specifically proved
exploitable are what this pass covers.
"""
import json
from unittest.mock import patch, MagicMock
from app.pipeline.market_signal_intelligence import classify_evidence, verify_proposition_claims
from tests._market_signal_intelligence_verifier_fixture import _default_safe_verifier  # noqa: F401


def _mk_text(text):
    r = MagicMock()
    b = MagicMock()
    b.type = "text"
    b.text = text
    r.content = [b]
    return r


def _verifier_client(negates=False, causation=False, entitlement=False, self_report=False):
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mk_text(json.dumps({
        "negates_claim": negates, "asserts_causation": causation,
        "asserts_entitlement": entitlement, "is_self_report": self_report,
    }))
    return fake_client


# ---------------------------------------------------------------------
# 1. Negation inversion laundering -- the exact reproduction case
# ---------------------------------------------------------------------

def test_negation_laundering_caught_by_independent_verifier():
    """First pass lies negated=False; independent verifier, reading
    only the raw text, correctly identifies the negation."""
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_verifier_client(negates=True)):
        findings = classify_evidence([{
            "question": "Did steel prices increase?", "why_it_matters": "x", "answer_found": True,
            "finding": "Steel prices did not increase.",
            "evidence_proposition": {"subject": "global steel market", "predicate": "price increased", "quantitative_value": None, "scope": "global_market", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"},
            "supports_or_contradicts_signal": "supports",
            "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
        }])
    assert findings[0]["evidence_state"] == "CONTRADICTED"


def test_negation_variant_declined_caught():
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_verifier_client(negates=True)):
        findings = classify_evidence([{
            "question": "Did steel prices increase?", "why_it_matters": "x", "answer_found": True,
            "finding": "Steel prices declined this quarter.",
            "evidence_proposition": {"subject": "global steel market", "predicate": "price increased", "quantitative_value": None, "scope": "global_market", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"},
            "supports_or_contradicts_signal": "supports", "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
        }])
    assert findings[0]["evidence_state"] == "CONTRADICTED"


def test_genuine_non_negated_case_unaffected():
    """Both passes correctly agree there's no negation -- the fix
    doesn't create false positives for genuinely positive evidence."""
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_verifier_client(negates=False)):
        findings = classify_evidence([{
            "question": "Did steel prices increase?", "why_it_matters": "x", "answer_found": True,
            "finding": "Steel prices increased according to the index.",
            "evidence_proposition": {"subject": "global steel market", "predicate": "price increased", "quantitative_value": None, "scope": "global_market", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"},
            "supports_or_contradicts_signal": "supports", "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
        }])
    assert findings[0]["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE"


# ---------------------------------------------------------------------
# 2. Attribution laundering -- supplier's own claim mislabeled as
# third-party report
# ---------------------------------------------------------------------

def test_attribution_laundering_caught_by_independent_verifier():
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_verifier_client(self_report=True)):
        findings = classify_evidence([{
            "question": "Did supplier A's steel costs increase 8%?", "why_it_matters": "x", "answer_found": True,
            "finding": "Supplier A claims that steel costs increased 8%.",
            "evidence_proposition": {"subject": "Supplier A", "predicate": "input cost increased", "quantitative_value": "8%", "scope": "supplier_specific", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"},
            "supports_or_contradicts_signal": "supports",
            "sources": [{"title": "Reuters", "url": "https://www.reuters.com/x"}],  # even with a real, credible source attached
        }])
    assert findings[0]["evidence_state"] != "EXTERNAL_MARKET_EVIDENCE"
    assert findings[0]["evidence_state"] != "VERIFIED"


def test_genuine_third_party_report_unaffected():
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=_verifier_client(self_report=False)):
        findings = classify_evidence([{
            "question": "Did steel prices increase?", "why_it_matters": "x", "answer_found": True,
            "finding": "Independent index shows steel prices increased.",
            "evidence_proposition": {"subject": "global steel market", "predicate": "price increased", "quantitative_value": None, "scope": "global_market", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"},
            "supports_or_contradicts_signal": "supports", "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
        }])
    assert findings[0]["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE"


# ---------------------------------------------------------------------
# 3. Verifier unavailability -- fails closed to UNKNOWN, not to a
# false specific claim
# ---------------------------------------------------------------------

def test_verifier_unavailable_fails_closed_to_unknown_not_contradicted():
    """Critical distinction: an unreachable verifier must produce
    UNKNOWN (honest "cannot confirm"), never CONTRADICTED (a false,
    SPECIFIC claim that is just as much a fabrication as trusting the
    unverified extraction would have been)."""
    def raising_client():
        raise RuntimeError("verifier unavailable")
    with patch("app.pipeline.market_signal_intelligence._get_client", side_effect=raising_client):
        findings = classify_evidence([{
            "question": "Did steel prices increase?", "why_it_matters": "x", "answer_found": True,
            "finding": "Steel prices increased according to the index.",
            "evidence_proposition": {"subject": "global steel market", "predicate": "price increased", "quantitative_value": None, "scope": "global_market", "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"},
            "supports_or_contradicts_signal": "supports", "sources": [{"title": "x", "url": "https://www.reuters.com/x"}],
        }])
    assert findings[0]["evidence_state"] == "UNKNOWN"
    assert findings[0]["evidence_state"] != "CONTRADICTED"
    assert findings[0]["evidence_state"] != "EXTERNAL_MARKET_EVIDENCE"


def test_verify_proposition_claims_malformed_json_returns_none():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mk_text("not json at all")
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=fake_client):
        result = verify_proposition_claims("some source text")
    assert result is None


# ---------------------------------------------------------------------
# 4. Span-existence check (deterministic layer)
# ---------------------------------------------------------------------

def test_span_exists_true_case():
    from app.pipeline.market_signal_intelligence import _span_exists
    assert _span_exists("prices did not increase", "Steel prices did not increase this quarter.") is True


def test_span_exists_hallucinated_span_rejected():
    from app.pipeline.market_signal_intelligence import _span_exists
    assert _span_exists("prices tripled overnight", "Steel prices did not increase this quarter.") is False


def test_span_exists_normalizes_whitespace_and_case():
    from app.pipeline.market_signal_intelligence import _span_exists
    assert _span_exists("PRICES   DID NOT\n  increase", "Steel prices did not increase this quarter.") is True


def test_span_exists_empty_inputs():
    from app.pipeline.market_signal_intelligence import _span_exists
    assert _span_exists(None, "some text") is False
    assert _span_exists("some span", "") is False
    assert _span_exists("", "some text") is False


# ---------------------------------------------------------------------
# 5. Reconciliation helper -- direct
# ---------------------------------------------------------------------

def test_reconcile_conservatively_either_true_wins():
    from app.pipeline.market_signal_intelligence import _reconcile_conservatively
    assert _reconcile_conservatively(False, True) is True
    assert _reconcile_conservatively(True, False) is True
    assert _reconcile_conservatively(True, True) is True
    assert _reconcile_conservatively(False, False) is False


def test_reconcile_conservatively_unavailable_verifier_treated_as_risky():
    from app.pipeline.market_signal_intelligence import _reconcile_conservatively
    assert _reconcile_conservatively(False, None) is True  # cannot confirm safety -> treated as present
