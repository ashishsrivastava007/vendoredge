from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, QuoteComparisonEvidence, DerivedEvidence, SupplierEvidence, FieldProvenance
from app.pipeline.decision_under_uncertainty import build_decision_under_uncertainty
from app.pipeline.tco import build_quote_tco


def pos():
    return CommercialPosition(
        recommendation="Buy the minimum quantity required now; keep the alternative open.",
        commercial_insights=["The immediate requirement can be protected without making a long-term commitment."],
        reasoning="Incomplete evidence.",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="evidence", value="mixed", weight="decreases confidence")], derivation_note="Medium."),
        assumptions=["Operational impact of delay is not quantified."],
        disconfirming_condition="Reassess if the required delivery date changes.",
        decision_type="constraint_satisfaction",
    )


def quote(inc1="DDP", inc2="DDP"):
    return NormalizedEvidence(
        content_type="quote_comparison",
        common=CommonEvidence(annual_volume_units=1000),
        case=QuoteComparisonEvidence(number_of_suppliers_being_compared="2"),
        derived=DerivedEvidence(),
        provenance={"x": FieldProvenance(source="llm_extraction", stage_captured="test")},
        suppliers=[
            SupplierEvidence(supplier_name="A", currency="EUR", price_amount=100, incoterm=inc1, is_incumbent=True),
            SupplierEvidence(supplier_name="B", currency="EUR", price_amount=90, incoterm=inc2),
        ],
    )


def test_missing_volume_asks_only_for_decision_critical_input():
    n = quote(); n.common.annual_volume_units = None
    u = build_decision_under_uncertainty(n, pos())
    assert u["mode"] == "ASK"
    assert "annual volume" in u["question"].lower()


def test_incomplete_quote_does_not_call_raw_price_gap_savings():
    n = quote("FCA", "DDP")
    out = build_quote_tco(n)
    assert out["available"] is False
    assert "incomplete" in out["headline"].lower()
    assert "not confirmed savings" not in out["headline"].lower()
    assert "buyer-borne freight" in " ".join(out["limitations"])


def test_same_currency_ddp_quotes_can_be_compared_deterministically():
    out = build_quote_tco(quote())
    assert out["available"] is True
    assert out["amount"] == 10000
    assert out["currency"] == "EUR"
