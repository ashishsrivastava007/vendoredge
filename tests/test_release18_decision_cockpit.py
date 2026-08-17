from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, QuoteComparisonEvidence, DerivedEvidence, SupplierEvidence, FieldProvenance
from app.pipeline.decision_passport import build_decision_passport
from app.pipeline.decision_cockpit import build_decision_cockpit
from app.pipeline.decision_formats import render_decision, FORMATS
from app.pipeline.customer_exports import render_custom


def _n():
    return NormalizedEvidence(
        content_type="quote_comparison",
        common=CommonEvidence(annual_volume_units=8000),
        case=QuoteComparisonEvidence(number_of_suppliers_being_compared="2", price_per_supplier="Atlas €52; EuroMotion €43"),
        derived=DerivedEvidence(currency_calculation_safe=True),
        provenance={"price_per_supplier": FieldProvenance(source="llm_extraction", stage_captured="test")},
        suppliers=[
            SupplierEvidence(supplier_name="Atlas", currency="EUR", price_amount=52, price_display="€52", is_incumbent=True),
            SupplierEvidence(supplier_name="EuroMotion", currency="EUR", price_amount=43, price_display="€43"),
        ],
    )


def _p():
    return CommercialPosition(
        recommendation="Negotiate Atlas; keep EuroMotion as BATNA.",
        commercial_insights=["EuroMotion creates a direct price opportunity."],
        reasoning="Atlas has stronger evidence; EuroMotion has the lower stated price.",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="evidence", value="mixed", weight="decreases confidence")], derivation_note="Medium because qualification is incomplete."),
        assumptions=["EuroMotion qualification must complete."],
        disconfirming_condition="If EuroMotion completes qualification and confirms capacity, revisit the award.",
        decision_type="optimization",
        opening_position="Ask Atlas to move to €48.",
        walk_away_threshold="Do not accept an unsupported increase.",
    )


def test_cockpit_is_deterministic_and_answer_first():
    n, p = _n(), _p()
    p.decision_passport = build_decision_passport(n, p)
    c = build_decision_cockpit(n, p)
    assert c["verdict"] == p.recommendation
    assert c["confidence"] == "medium"
    assert c["alternative_count"] == 0
    assert c["economics"]["available"] is True
    assert "no new facts" in c["method"]


def test_native_cockpit_format_is_available():
    n, p = _n(), _p()
    p.decision_passport = build_decision_passport(n, p)
    p.decision_cockpit = build_decision_cockpit(n, p)
    assert "decision_cockpit" in FORMATS
    out = render_decision(p, "decision_cockpit")
    assert out["title"] == "VENDOREDGE COMMERCIAL DECISION COCKPIT"
    assert "WHAT CHANGES IT" in out["body"]


def test_byof_exposes_cockpit_token_without_llm_call():
    p = _p()
    p.decision_cockpit = {"verdict": p.recommendation, "confidence": "medium"}
    out = render_custom(p, "Decision={{recommendation}}\\nCockpit={{decision_cockpit}}")
    assert out["format"] == "custom"
    assert "Cockpit=" in out["body"]
