"""
Item 1 fix: extraction conflicts must not silently select one value.

Root cause: the existing conflict-detection mechanism (_resolve_field)
worked for currency and was regex-based for spend, meaning it was
implicitly dollar-sign-dependent and, even when it fired, never blocked
the dependent financial calculation or surfaced as a contradiction.

Fixed with a structured, currency-agnostic mechanism: the classifier's
own extraction contract now includes "unresolved_value_conflicts", a
list the LLM populates when it judges two stated values for the same
fact to genuinely, unresolvably disagree -- never based on parsing a
currency symbol, purely on the LLM's structured judgment. Wired through
normalize.py, decision_audit.py (surfaces as CONTRADICTED), and
financial.py (blocks the dependent calculation entirely).
"""
from app.pipeline.normalize import normalize_evidence
from app.pipeline.financial import compute_financial_impact
from app.pipeline.decision_audit import build_decision_audit
from app.models import CommercialPosition, Confidence, ConfidenceFactor


def _position():
    return CommercialPosition(
        recommendation="test", commercial_insights=["a"], reasoning="r",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n"),
        assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
    )


def _run(currency, conflicts):
    ne, _ = normalize_evidence(
        "test case", "price_increase", {"supplier_currency": currency},
        {"annual_spend_usd": 5_000_000, "requested_change_percent": 10.0},
        unresolved_value_conflicts=conflicts,
    )
    return ne, compute_financial_impact(ne), build_decision_audit(ne, _position())


def test_A_eur_conflicting_annual_spend_blocks_calculation():
    conflict = [{"field": "annual_spend_usd", "values_found": [5_000_000, 5_500_000], "note": "stated twice, disagreeing"}]
    ne, fi, audit = _run("EUR", conflict)
    assert fi is None, "calculation must be blocked when its dependent value is disputed"
    assert audit["evidence_integrity_status"] == "CONTRADICTED"
    assert any("UNRESOLVED VALUE CONFLICT" in c for c in audit["contradictions"])


def test_B_usd_conflicting_annual_spend_blocks_calculation():
    conflict = [{"field": "annual_spend_usd", "values_found": [5_000_000, 5_500_000], "note": "stated twice, disagreeing"}]
    ne, fi, audit = _run("USD", conflict)
    assert fi is None
    assert audit["evidence_integrity_status"] == "CONTRADICTED"


def test_C_gbp_conflicting_annual_spend_blocks_calculation():
    """Proves the mechanism is genuinely currency-agnostic -- identical
    behavior for GBP as for EUR/USD, since nothing here inspects a
    currency symbol at all."""
    conflict = [{"field": "annual_spend_usd", "values_found": [5_000_000, 5_500_000], "note": "stated twice, disagreeing"}]
    ne, fi, audit = _run("GBP", conflict)
    assert fi is None
    assert audit["evidence_integrity_status"] == "CONTRADICTED"


def test_D_consistent_duplicate_is_not_a_contradiction():
    """The same value stated twice is confirmation, not conflict -- the
    classifier is explicitly instructed never to report this as a
    conflict, and the downstream system must not block anything when
    unresolved_value_conflicts is genuinely empty."""
    ne, fi, audit = _run("EUR", [])
    assert fi is not None
    assert fi.potential_annual_impact == 500_000.0
    assert audit["evidence_integrity_status"] == "PROVEN"


def test_H_unresolved_conflict_specifically_blocks_the_dependent_calculation_not_everything():
    """A conflict on a field the calculation doesn't depend on must not
    block it -- proving this is a targeted, not a blanket, safety
    mechanism."""
    conflict = [{"field": "switching_cost_usd", "values_found": [10_000, 20_000], "note": "irrelevant to the main calculation"}]
    ne, fi, audit = _run("EUR", conflict)
    assert fi is not None, "a conflict on an unrelated field must not block the annual-impact calculation"
    assert fi.potential_annual_impact == 500_000.0
    assert audit["evidence_integrity_status"] == "CONTRADICTED", "the conflict itself must still be surfaced, even though it didn't block this specific calculation"


def test_no_conflicts_field_at_all_is_the_normal_unaffected_case():
    """Regression guard: the overwhelming majority of cases never
    populate unresolved_value_conflicts at all."""
    ne, _ = normalize_evidence("normal case", "price_increase", {}, {"annual_spend_usd": 1_000_000, "requested_change_percent": 10.0})
    assert ne.case.unresolved_value_conflicts == []
    fi = compute_financial_impact(ne)
    assert fi is not None
    assert fi.potential_annual_impact == 100_000.0
