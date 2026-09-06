from pathlib import Path

from app.models import CommercialPosition, NegotiationDimension, Confidence
from app.pipeline.claim_integrity import check_unsupported_strategy_numbers, sanitize_unsupported_strategy_numbers, check_market_context_attribution
from app.pipeline.decision_audit import build_decision_audit
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, SupplierEvidence, FieldProvenance, DerivedEvidence


def _normalized_case():
    n = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="ABC Marine Supplies B.V."),
        case=PriceIncreaseEvidence(
            current_price_or_terms="Current catalogue pricing",
            requested_increase_percent=8.5,
            suppliers_stated_justification="stainless steel, brass and manufacturing costs have increased",
            annual_spend_usd=1_850_000,
        ),
        derived=DerivedEvidence(resolved_annual_spend_usd=1_850_000, annual_spend_resolution_method="direct"),
        suppliers=[SupplierEvidence(
            supplier_name="ABC Marine Supplies B.V.", is_incumbent=True,
            otif_percent=94, qualification_status="unknown",
            production_history_status="unknown", certification_status="unknown",
        ), SupplierEvidence(
            supplier_name="Alternative Supplier", is_incumbent=False,
            capacity_percent=35, qualification_status="unknown",
            production_history_status="unknown", certification_status="unknown",
        )],
        provenance={
            "requested_increase_percent": FieldProvenance(source="llm_extraction", stage_captured="test"),
            "annual_spend_usd": FieldProvenance(source="llm_extraction", stage_captured="test"),
        },
    )
    return n


def _position(**kwargs):
    base = dict(
        recommendation="Do not accept the requested increase as submitted.",
        commercial_insights=["The supplier's request is unsupported at the level presented."],
        reasoning="Commercial: challenge the blanket increase. Operational: continuity matters.",
        confidence=Confidence(level="medium", factors=[{"factor":"Missing cost evidence","value":"No detailed breakdown was provided","weight":"decreases confidence"}], derivation_note="Evidence is incomplete."),
        assumptions=["Supplier cost evidence is incomplete"],
        decision_type="optimization",
        disconfirming_condition="Reassess if credible cost evidence materially supports the requested increase.",
    )
    base.update(kwargs)
    return CommercialPosition(**base)


def test_unsupported_numeric_strategy_is_detected():
    n = _normalized_case()
    p = _position(
        negotiation_dimensions=[NegotiationDimension(
            dimension="Price increase", opening_ask="Challenge 8.5%", target_outcome="4-5%", walk_away="Above 6-7% flat"
        )],
        walk_away_threshold="Do not accept above 6-7%",
    )
    issues = check_unsupported_strategy_numbers(p, n, "Supplier requests 8.5% increase. Annual spend is USD 1,850,000. Alternative capacity is 35%.")
    assert issues
    assert any("4-5%" in x or "6-7%" in x for x in issues)


def test_unsupported_numeric_strategy_is_safely_scrubbed():
    p = _position(
        negotiation_dimensions=[NegotiationDimension(
            dimension="Price increase", opening_ask="Challenge 8.5%", target_outcome="4-5%", walk_away="Above 6-7% flat"
        )],
        walk_away_threshold="Do not accept above 6-7%",
    )
    changed = sanitize_unsupported_strategy_numbers(p, "Supplier requests 8.5% increase.")
    assert changed
    assert "4-5%" not in p.negotiation_dimensions[0].target_outcome
    assert "6-7%" not in p.walk_away_threshold


def test_decision_audit_does_not_turn_every_absent_attribute_into_noise():
    n = _normalized_case()
    p = _position(reasoning="Do not accept the request; the alternative supplier's stated 35% capacity is only a potential lever until qualification is confirmed.")
    audit = build_decision_audit(n, p)
    assert any("qualification status was not provided" in x for x in audit["uncertainties"])
    assert not any("certification status is unknown" in x for x in audit["uncertainties"])
    assert not any("production history is unknown" in x for x in audit["uncertainties"])
    assert len(audit["uncertainties"]) == len(set(audit["uncertainties"]))


def test_frontend_has_unique_supplier_comparison_id_and_market_surface():
    html = Path(__file__).resolve().parents[1].joinpath("app/static/index.html").read_text()
    assert html.count('id="pos-supplier-comparison"') == 1
    assert 'id="pos-market-verification"' in html
    assert 'renderMarketVerification(pos)' in html


def test_external_market_claim_must_be_explicitly_labelled():
    p = _position(
        reasoning="European stainless steel prices fell, so the supplier's request is overstated.",
        market_verification={"finding":"supported", "verified_note":"External market data indicates movement."},
    )
    issues = check_market_context_attribution(p)
    assert issues


def test_external_market_context_can_be_used_when_scoped_and_labelled():
    p = _position(
        reasoning="The external market check indicates some stainless steel prices moved down; this is context only and does not establish ABC's actual cost base.",
        market_verification={"finding":"supported", "verified_note":"External market data indicates movement."},
    )
    assert check_market_context_attribution(p) == []
