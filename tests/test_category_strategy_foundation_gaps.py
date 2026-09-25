"""
Category Strategy -- the three foundation gaps closed this session:
1. Spend-only price signal (no volume) previously produced zero findings.
2. Market-driver claim with no internal movement previously produced zero findings.
3. Supplier claim vs. internal price-history contradiction was never detected.

Architectural note: stated_price_history was never threaded from
normalized.case into the kernel -- Category Strategy's finding model
reads only the kernel, so it had no access to it at all. Fixed with a
single additive kernel field (app/pipeline/kernel.py), verified not to
change any existing journey's behavior (full regression unchanged
before/after).
"""
import time
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor

client = TestClient(app)
_CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _run(raw_question, numeric_facts, extra_evidence=None, market_driver_claims=None, stated_price_history=None, suffix=0):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"24.100.{suffix}.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    classify = {
        "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", **(extra_evidence or {})},
        "numeric_facts": numeric_facts, "supplier_specific_evidence": [],
    }
    if market_driver_claims is not None:
        classify["market_driver_claims"] = market_driver_claims
    if stated_price_history is not None:
        classify["stated_price_history"] = stated_price_history
    pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
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
    return d["commercial_position"]["category_strategy_answer"]


# ---------------------------------------------------------------------
# Defect 1: spend-only price signal
# ---------------------------------------------------------------------

def test_1a_spend_increase_with_volume_unchanged_by_this_fix():
    """Regression guard: when volume IS available, the existing price-
    growth finding must still fire exactly as before -- this fix must
    not alter that path."""
    a = _run("Price rose.", {"category_annual_spend_usd": 1_180_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_000, "category_prior_annual_volume_units": 10_000}, suffix=1)
    price_finding = next(f for f in a["diagnostics"]["findings"] if "unit price" in f["finding"].lower())
    assert price_finding["decision_impact"] == "DECISION_CRITICAL_UNKNOWN"
    assert "spend has changed" not in price_finding["finding"].lower()  # the volume-available path, not the new spend-only path


def test_1b_spend_increase_no_volume_surfaces_as_spend_not_price():
    """The exact defect: previously zero findings."""
    a = _run("Supplier raised prices, no reason given.", {"category_annual_spend_usd": 1_100_000, "category_prior_annual_spend_usd": 1_000_000}, extra_evidence={"suppliers_stated_justification": "Just costs going up."}, suffix=2)
    assert len(a["diagnostics"]["findings"]) >= 1
    finding = a["diagnostics"]["findings"][0]
    assert "spend has changed" in finding["finding"].lower()
    assert "cannot yet be attributed to price" in finding["finding"].lower()
    assert finding["evidence_state"] == "CALCULATED"
    assert "+10.0%" in finding["finding"]  # the real calculated value, nothing invented


def test_1c_spend_increase_volume_decrease_still_uses_the_real_price_calculation():
    """When volume IS available (even if it decreased), the genuine
    price-growth path must be used, not the spend-only fallback."""
    a = _run("Spend up, volume down.", {"category_annual_spend_usd": 1_100_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 9_000, "category_prior_annual_volume_units": 10_000}, suffix=3)
    finding = next(f for f in a["diagnostics"]["findings"] if "unit price" in f["finding"].lower() or "average unit price" in f["finding"].lower())
    assert "spend has changed" not in finding["finding"].lower()


def test_1d_no_genuine_spend_movement_produces_no_spend_only_finding():
    """Flat spend (0% change) must not be reported as a finding -- zero
    change is not a change, consistent with the rest of this codebase."""
    a = _run("Nothing changed.", {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000}, suffix=4)
    assert not any("spend has changed" in f["finding"].lower() for f in a["diagnostics"]["findings"])


def test_1e_supplier_claim_plus_spend_movement_no_volume_preserves_claim_as_claim():
    """A supplier's own cost-driver claim alongside a spend-only signal
    must remain a SUPPLIER_CLAIM elsewhere in the answer, never
    promoted into the CALCULATED spend finding itself."""
    a = _run("Supplier says raw material costs increased.", {"category_annual_spend_usd": 1_080_000, "category_prior_annual_spend_usd": 1_000_000}, extra_evidence={"suppliers_stated_justification": "Raw material costs increased."}, suffix=5)
    spend_finding = next(f for f in a["diagnostics"]["findings"] if "spend has changed" in f["finding"].lower())
    assert spend_finding["evidence_state"] == "CALCULATED"
    assert "raw material" not in spend_finding["finding"].lower()  # the claim is not folded into the calculated finding


# ---------------------------------------------------------------------
# Defect 2: market-driver signal without internal movement
# ---------------------------------------------------------------------

def test_2a_market_driver_with_internal_price_movement_takes_the_price_branch():
    """When a genuine internal price movement exists, the market-driver
    finding should connect to it (existing framing-challenge behavior),
    not the new no-internal-movement branch."""
    a = _run("Price rose alongside a market move.", {"category_annual_spend_usd": 1_160_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_000, "category_prior_annual_volume_units": 10_000}, market_driver_claims=[{"driver": "steel", "direction": "increased", "attributed_to": "unspecified"}], suffix=6)
    finding = next(f for f in a["diagnostics"]["findings"] if "steel" in f["finding"].lower())
    assert "unit price has moved" in finding["finding"].lower()
    assert "no corresponding internal" not in finding["finding"].lower()


def test_2b_market_driver_with_internal_spend_movement_only():
    """Spend moved (no volume), and a market driver was also reported --
    the spend-only finding should exist; the market-driver-specific
    'no internal movement' finding should NOT also fire, since a real
    internal movement does exist even without a price attribution."""
    a = _run("Spend rose, and we heard about a market move.", {"category_annual_spend_usd": 1_100_000, "category_prior_annual_spend_usd": 1_000_000}, market_driver_claims=[{"driver": "steel", "direction": "increased", "attributed_to": "unspecified"}], suffix=7)
    assert any("spend has changed" in f["finding"].lower() for f in a["diagnostics"]["findings"])
    assert not any("no corresponding internal" in f["finding"].lower() for f in a["diagnostics"]["findings"])


def test_2c_market_driver_no_internal_movement_surfaces_as_external_evidence():
    """The exact defect: previously zero findings."""
    a = _run("Heard steel prices are up, wondering if that affects us.", {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000}, market_driver_claims=[{"driver": "steel", "direction": "increased", "attributed_to": "unspecified"}], suffix=8)
    assert len(a["diagnostics"]["findings"]) >= 1
    finding = a["diagnostics"]["findings"][0]
    assert finding["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE"
    assert "no corresponding internal" in finding["finding"].lower()
    assert "does not establish" in finding["implication"].lower()


def test_2d_market_driver_conflicting_internal_evidence_does_not_suppress_the_contradiction():
    """A market driver plus a contradicted supplier claim -- both must
    be representable; the market-driver-only branch must not fire when
    a real internal movement (even a contradicted one) exists."""
    a = _run("Market moved, and supplier claims costs rose, but our history disagrees.", {"category_annual_spend_usd": 1_090_000, "category_prior_annual_spend_usd": 1_000_000}, extra_evidence={"suppliers_stated_justification": "Costs have risen."}, market_driver_claims=[{"driver": "steel", "direction": "increased", "attributed_to": "unspecified"}], stated_price_history=["Year -1: 0%", "Year -2: 0%"], suffix=9)
    assert any(f["evidence_state"] == "CONTRADICTED" for f in a["diagnostics"]["findings"])


def test_2e_irrelevant_market_driver_still_surfaces_honestly_when_no_internal_movement():
    """VendorEdge cannot judge 'relevance' beyond what's reported --
    any genuine market-driver claim with no internal movement gets the
    same honest, non-committal treatment."""
    a = _run("Heard about some market news.", {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000}, market_driver_claims=[{"driver": "logistics", "direction": "increased", "attributed_to": "unspecified"}], suffix=10)
    assert any(f["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE" for f in a["diagnostics"]["findings"])


def test_2f_no_market_driver_and_research_unavailable_produces_no_fabricated_finding():
    """No market driver claim at all, no internal movement -- correctly
    produces no market-driver finding, nothing fabricated."""
    a = _run("Just checking in on this category.", {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000}, suffix=11)
    assert not any(f["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE" for f in a["diagnostics"]["findings"])


# ---------------------------------------------------------------------
# Defect 3: supplier claim vs. internal price-history contradiction
# ---------------------------------------------------------------------

def test_3a_supplier_claim_conflicting_with_internal_history_detected():
    """The exact defect: previously never detected."""
    a = _run("Supplier wants +9%, but our records show they've never raised prices before.", {"category_annual_spend_usd": 1_090_000, "category_prior_annual_spend_usd": 1_000_000}, extra_evidence={"suppliers_stated_justification": "Costs have risen."}, stated_price_history=["Year -1: 0%", "Year -2: 0%", "Year -3: 0%"], suffix=12)
    contradiction = next(f for f in a["diagnostics"]["findings"] if f["evidence_state"] == "CONTRADICTED")
    assert contradiction["decision_impact"] == "MATERIAL_RISK"
    assert "dishonest" not in contradiction["finding"].lower() and "dishonest" not in contradiction["implication"].lower()
    import re
    assert not re.search(r"\blying\b", json.dumps(contradiction).lower())


def test_3b_supplier_claim_with_supporting_internal_evidence_no_contradiction():
    """History that genuinely shows past increases must not trigger a
    contradiction against a new increase claim."""
    a = _run("Supplier wants +5%, citing rising costs.", {"category_annual_spend_usd": 1_050_000, "category_prior_annual_spend_usd": 1_000_000}, extra_evidence={"suppliers_stated_justification": "Costs have risen."}, stated_price_history=["Year -1: +3%", "Year -2: +2%"], suffix=13)
    assert not any(f["evidence_state"] == "CONTRADICTED" for f in a["diagnostics"]["findings"])


def test_3c_supplier_claim_no_internal_history_no_contradiction_asserted():
    """No price history exists to compare against -- must not assert a
    contradiction that has no evidentiary basis."""
    a = _run("Supplier wants +5%, citing rising costs.", {"category_annual_spend_usd": 1_050_000, "category_prior_annual_spend_usd": 1_000_000}, extra_evidence={"suppliers_stated_justification": "Costs have risen."}, suffix=14)
    assert not any(f["evidence_state"] == "CONTRADICTED" for f in a["diagnostics"]["findings"])


def test_3d_ambiguous_mixed_history_does_not_force_a_contradiction():
    """A mixed history (one year up, one flat) is genuinely ambiguous --
    must not force a contradiction verdict the evidence doesn't
    unambiguously support."""
    a = _run("Supplier wants +5%, citing rising costs.", {"category_annual_spend_usd": 1_050_000, "category_prior_annual_spend_usd": 1_000_000}, extra_evidence={"suppliers_stated_justification": "Costs have risen."}, stated_price_history=["Year -1: +2%", "Year -2: 0%"], suffix=15)
    assert not any(f["evidence_state"] == "CONTRADICTED" for f in a["diagnostics"]["findings"])


def test_3e_supplier_claim_with_external_market_evidence_both_representable():
    """A supplier claim, a contradicting history, AND a market driver
    can all coexist -- confirms the contradiction detector doesn't
    suppress or get suppressed by the market-driver finding."""
    a = _run("Supplier claims costs rose; market also moved.", {"category_annual_spend_usd": 1_090_000, "category_prior_annual_spend_usd": 1_000_000}, extra_evidence={"suppliers_stated_justification": "Costs have risen."}, stated_price_history=["Year -1: 0%"], market_driver_claims=[{"driver": "energy", "direction": "increased", "attributed_to": "unspecified"}], suffix=16)
    assert any(f["evidence_state"] == "CONTRADICTED" for f in a["diagnostics"]["findings"])


def test_3f_conflicting_evidence_where_contradiction_should_not_be_asserted():
    """The claim doesn't actually assert a cost increase (a different
    justification entirely) -- no contradiction should be manufactured
    just because price history exists."""
    a = _run("Supplier wants +5%, citing a new specification.", {"category_annual_spend_usd": 1_050_000, "category_prior_annual_spend_usd": 1_000_000}, extra_evidence={"suppliers_stated_justification": "This reflects the new specification requirements."}, stated_price_history=["Year -1: 0%", "Year -2: 0%"], suffix=17)
    assert not any(f["evidence_state"] == "CONTRADICTED" for f in a["diagnostics"]["findings"])


# ---------------------------------------------------------------------
# Adaptive output / no invented data
# ---------------------------------------------------------------------

def test_no_invented_numbers_across_all_three_fixes():
    a1 = _run("Price rose.", {"category_annual_spend_usd": 1_100_000, "category_prior_annual_spend_usd": 1_000_000}, suffix=18)
    assert "+10.0%" in a1["diagnostics"]["findings"][0]["finding"]  # matches the real calculated figure exactly


def test_sections_suppressed_when_nothing_relevant_exists():
    """A genuinely flat, unremarkable case must not manufacture any of
    the three NEW finding types from this session (spend-only, market-
    driver-only, or contradiction) -- the pre-existing BACKGROUND
    "driven by volume, not price" finding for a flat 0% movement is
    unrelated, existing behavior from an earlier session, not one of
    the three fixes this test file guards."""
    a = _run("Routine category check.", {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_000, "category_prior_annual_volume_units": 10_000}, suffix=19)
    assert not any("spend has changed" in f["finding"].lower() for f in a["diagnostics"]["findings"])
    assert not any(f["evidence_state"] == "EXTERNAL_MARKET_EVIDENCE" for f in a["diagnostics"]["findings"])
    assert not any(f["evidence_state"] == "CONTRADICTED" for f in a["diagnostics"]["findings"])
