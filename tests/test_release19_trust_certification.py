from app.models import CommercialPosition, Confidence, ConfidenceFactor, DecisionAudit
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, QuoteComparisonEvidence, DerivedEvidence, FieldProvenance, SupplierEvidence
from app.pipeline.trust_certification import build_trust_certification


def _n(conflicting=False):
    return NormalizedEvidence(
        content_type="quote_comparison",
        common=CommonEvidence(annual_volume_units=8000),
        case=QuoteComparisonEvidence(number_of_suppliers_being_compared="2", price_per_supplier="Atlas €52; EuroMotion €43"),
        derived=DerivedEvidence(currency_calculation_safe=True),
        provenance={
            "price_per_supplier": FieldProvenance(source="llm_extraction", stage_captured="test", conflicting=conflicting, supplier_name=None),
            "number_of_suppliers_being_compared": FieldProvenance(source="llm_extraction", stage_captured="test"),
            "atlas_price": FieldProvenance(source="llm_extraction", stage_captured="test", supplier_name="Atlas"),
            "euromotion_price": FieldProvenance(source="llm_extraction", stage_captured="test", supplier_name="EuroMotion"),
        },
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
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="evidence", value="mixed", weight="decreases confidence")], derivation_note="[System-owned confidence level: 'medium'. Deterministic evidence checks: none.]"),
        assumptions=["EuroMotion qualification must complete."],
        disconfirming_condition="If EuroMotion completes qualification and confirms capacity, revisit the award.",
        decision_type="optimization",
        decision_audit=DecisionAudit(material_evidence=[{"label":"Supplier pricing","status":"PROVEN","evidence":"Atlas €52; EuroMotion €43"}], evidence_integrity_status="PROVEN", evidence_counts={"PROVEN":1}),
        sensitivity_analysis={"available": True},
        stress_test={"status": "PASS"},
        alternative_analysis={"available": True, "status": "EVIDENCE_BACKED_PATHS", "summary": "Test paths", "alternatives": []},
    )


def test_r19_certifies_clean_decision_process():
    cert = build_trust_certification(_n(), _p())
    assert cert["status"] == "CERTIFIED"
    assert cert["checks_failed"] == 0
    assert cert["checks_warned"] == 0
    assert cert["version"] == "R19.1"
    assert any(c["name"] == "model_independence" and c["status"] == "PASS" for c in cert["checks"])


def test_r19_blocks_certification_on_load_bearing_conflict():
    cert = build_trust_certification(_n(conflicting=True), _p())
    assert cert["status"] == "NOT_CERTIFIED"
    assert cert["checks_failed"] >= 1
    assert "Load-bearing evidence contains unresolved conflicts." in cert["critical_failures"]


def test_r19_is_not_outcome_accuracy_claim():
    cert = build_trust_certification(_n(), _p())
    assert "commercial outcome accuracy" in cert["disclaimer"]
