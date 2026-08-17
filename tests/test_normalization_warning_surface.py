from app.models import CommercialPosition, Confidence, ConfidenceFactor, DecisionAudit
from app.pipeline.decision_audit import build_decision_audit
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence
from app.pipeline.trust_certification import build_trust_certification


def _position():
    return CommercialPosition(
        recommendation="Hold and negotiate",
        commercial_insights=["Evidence supports negotiation"],
        reasoning="Reasoning",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="evidence", value="mixed", weight="decreases confidence")], derivation_note="System-owned confidence level from deterministic evidence checks."),
        assumptions=["Some evidence is incomplete"],
        disconfirming_condition="Reassess if verified evidence changes the economics.",
        decision_type="optimization",
    )


def _normalized(warnings=None):
    n = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Atlas"),
        case=PriceIncreaseEvidence(current_price_or_terms="EUR 52", requested_increase_percent=6.4, suppliers_stated_justification="cost inflation"),
        derived=DerivedEvidence(),
        normalization_warnings=warnings or [],
    )
    return n


def test_normalization_warnings_are_user_visible_in_decision_audit():
    n = _normalized(["case:annual_spend_usd:invalid_numeric_shape"])
    p = _position()
    audit = build_decision_audit(n, p)
    assert audit["normalization_warnings"] == ["case:annual_spend_usd:invalid_numeric_shape"]
    assert audit["evidence_integrity_status"] == "UNKNOWN"
    assert not any("Evidence extraction warning" in x for x in audit["uncertainties"])
    DecisionAudit(**audit)


def test_clean_normalization_does_not_create_warning_signal():
    n = _normalized()
    audit = build_decision_audit(n, _position())
    assert audit["normalization_warnings"] == []
    assert audit["evidence_integrity_status"] == "PROVEN"


def test_trust_certificate_surfaces_normalization_quality_warning():
    n = _normalized(["case:annual_spend_usd:invalid_numeric_shape"])
    p = _position()
    p.decision_audit = DecisionAudit(**build_decision_audit(n, p))
    cert = build_trust_certification(n, p)
    check = next(c for c in cert["checks"] if c["name"] == "normalization_quality")
    assert check["status"] == "WARN"
    assert "1 evidence extraction warning" in check["summary"]
