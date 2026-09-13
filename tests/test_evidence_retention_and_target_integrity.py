"""
Evidence retention (qualification timeframe, capacity validation status)
and target/walk-away integrity, fixed as part of the R41 hardening
continuation.
"""
from types import SimpleNamespace

from app.pipeline.normalize import normalize_evidence
from app.pipeline.decision_audit import build_decision_audit
from app.pipeline.negotiation_intelligence import build_negotiation_intelligence, _is_established
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence, SupplierEvidence
from app.models import CommercialPosition, Confidence, ConfidenceFactor, NegotiationDimension


# ---------------------------------------------------------------------
# Evidence retention: qualification timeframe and capacity validation
# ---------------------------------------------------------------------

def test_qualification_timeframe_survives_real_extraction():
    """Full real pipeline, not a hand-built object: a stated timeframe
    must reach normalized evidence, not be silently dropped because the
    categorical status defaults to 'unknown'."""
    extracted = {"supplier_currency": "EUR"}
    suppliers = [
        {"supplier_name": "Supplier A", "is_incumbent": True},
        {"supplier_name": "Supplier B", "qualification_time_estimate": "4-6 months"},
        {"supplier_name": "Supplier C", "qualification_time_estimate": "approximately 6 months"},
        {"supplier_name": "Supplier D", "capacity_percent": 15, "capacity_status": "unvalidated"},
    ]
    ne, _ = normalize_evidence("case text", "price_increase", extracted, {"requested_change_percent": 11.0}, supplier_specific_evidence=suppliers)
    by_name = {s.supplier_name: s for s in ne.suppliers}
    assert by_name["Supplier B"].qualification_time_estimate == "4-6 months"
    assert by_name["Supplier C"].qualification_time_estimate == "approximately 6 months"
    assert by_name["Supplier D"].capacity_status == "unvalidated"
    assert by_name["Supplier D"].capacity_percent == 15.0


def test_decision_audit_surfaces_real_timeframe_not_false_not_provided():
    """The confirmed root-cause bug, reproduced against the real
    function: a supplier with an explicitly stated timeframe must never
    be described as having no qualification information at all."""
    ne = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Supplier A"),
        case=PriceIncreaseEvidence(requested_increase_percent=11.0),
        derived=DerivedEvidence(),
        suppliers=[
            SupplierEvidence(supplier_name="Supplier A", is_incumbent=True),
            SupplierEvidence(supplier_name="Supplier B", qualification_time_estimate="4-6 months"),
        ],
    )
    audit = build_decision_audit(ne, _position())
    uncertainties_text = " ".join(audit["uncertainties"])
    assert "4-6 months" in uncertainties_text
    assert "was not provided" not in uncertainties_text


def test_decision_audit_still_says_not_provided_when_genuinely_nothing_stated():
    """Regression guard: a supplier with genuinely no timeframe at all
    must still correctly show as not provided -- this fix must not
    invent information that was never given."""
    ne = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Supplier A"),
        case=PriceIncreaseEvidence(requested_increase_percent=11.0),
        derived=DerivedEvidence(),
        suppliers=[
            SupplierEvidence(supplier_name="Supplier A", is_incumbent=True),
            SupplierEvidence(supplier_name="Supplier B"),
        ],
    )
    audit = build_decision_audit(ne, _position())
    assert any("was not provided" in u for u in audit["uncertainties"])


def test_capacity_unvalidated_status_surfaced_in_material_evidence():
    ne = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Supplier A"),
        case=PriceIncreaseEvidence(requested_increase_percent=11.0),
        derived=DerivedEvidence(),
        suppliers=[
            SupplierEvidence(supplier_name="Supplier A", is_incumbent=True),
            SupplierEvidence(supplier_name="Supplier D", capacity_percent=15.0, capacity_status="unvalidated"),
        ],
    )
    audit = build_decision_audit(ne, _position())
    d_entry = next(i for i in audit["material_evidence"] if i["label"] == "Supplier D")
    assert "not yet validated" in d_entry["evidence"]


# ---------------------------------------------------------------------
# Target/walk-away integrity
# ---------------------------------------------------------------------

def _position():
    return CommercialPosition(
        recommendation="test", commercial_insights=["a"], reasoning="r",
        confidence=Confidence(level="medium", factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")], derivation_note="n"),
        assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
    )


def test_is_established_correctly_classifies_hedge_vs_real_value():
    assert _is_established("Not safely quantified from the supplied evidence") is False
    assert _is_established("No supported numeric target established from current evidence.") is False
    assert _is_established("") is False
    assert _is_established(None) is False
    assert _is_established("Increase justified line-by-line, not blanket") is True
    assert _is_established("12% maximum") is True


def test_negotiation_intelligence_never_says_hold_target_when_not_established():
    """The confirmed root-cause bug: a hedge string like 'Not safely
    quantified' must never produce 'Hold the stated target' -- the
    exact contradiction the case's own TARGET section and its
    negotiation-scenario section previously disagreed on."""
    pos = _position()
    pos.negotiation_dimensions = [
        NegotiationDimension(
            dimension="Price base rate",
            opening_ask="Line-by-line evidence before any adjustment",
            target_outcome="Not safely quantified from the supplied evidence",
            walk_away="Not safely quantified from the supplied evidence",
        )
    ]
    result = build_negotiation_intelligence(pos)
    for scenario in result["response_scenarios"]:
        assert "Hold the stated target" not in scenario["buyer_move"]
        assert scenario["target_state"] == "NOT_ESTABLISHED"
    for row in result["give_get_matrix"]:
        assert row["target_state"] == "NOT_ESTABLISHED"
        assert row["walk_away_state"] == "NOT_ESTABLISHED"


def test_negotiation_intelligence_correctly_holds_a_genuinely_established_target():
    """Regression guard: a real, evidence-backed target must still
    produce the normal 'hold the target' language -- this fix must not
    make every negotiation scenario say 'not established'."""
    pos = _position()
    pos.negotiation_dimensions = [
        NegotiationDimension(
            dimension="Payment terms", opening_ask="Net 60", target_outcome="Net 45", walk_away="Net 30",
        )
    ]
    result = build_negotiation_intelligence(pos)
    scenarios = result["response_scenarios"]
    assert any("Hold the stated target" in s["buyer_move"] for s in scenarios)
    assert all(s["target_state"] == "ESTABLISHED" for s in scenarios if s["trigger"] != "Supplier challenges the opening position")


# ---------------------------------------------------------------------
# Contradiction / reconciliation: claim vs documented history
# ---------------------------------------------------------------------

def test_no_adjustment_claim_contradicted_by_documented_history():
    """The exact golden-case pattern: 'no adjustment for three years'
    directly contradicted by a stated non-zero history. Must surface
    both real non-zero entries, exclude the genuine zero-change entry,
    and never resolve which side is correct."""
    from app.pipeline.decision_audit import build_decision_audit
    n = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Supplier A"),
        case=PriceIncreaseEvidence(
            requested_increase_percent=11.0,
            suppliers_stated_justification="We have had no price adjustment for three years.",
            stated_price_history=["Year -3: +2.5%", "Year -2: +3.0%", "Year -1: 0%"],
        ),
        derived=DerivedEvidence(),
    )
    audit = build_decision_audit(n, _position())
    assert audit["evidence_integrity_status"] == "CONTRADICTED"
    assert len(audit["contradictions"]) == 1
    text = audit["contradictions"][0]
    assert "Year -3: +2.5%" in text
    assert "Year -2: +3.0%" in text
    assert "Year -1: 0%" not in text
    assert "CLAIM REQUIRES RECONCILIATION" in text


def test_no_contradiction_when_history_is_genuinely_consistent_with_claim():
    """Regression guard: a claim of 'no adjustment' with a history that's
    genuinely all zero-change must NOT be flagged as a contradiction --
    this fix must not manufacture disagreement where none exists."""
    from app.pipeline.decision_audit import build_decision_audit
    n = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Supplier A"),
        case=PriceIncreaseEvidence(
            requested_increase_percent=11.0,
            suppliers_stated_justification="We have had no price adjustment for three years.",
            stated_price_history=["Year -3: 0%", "Year -2: 0%", "Year -1: 0%"],
        ),
        derived=DerivedEvidence(),
    )
    audit = build_decision_audit(n, _position())
    assert audit["contradictions"] == []
    assert audit["evidence_integrity_status"] != "CONTRADICTED"


def test_no_contradiction_when_no_claim_or_no_history_present():
    """Regression guard: the overwhelming majority of cases have neither
    a 'no adjustment' claim nor a stated history at all -- entirely
    unaffected."""
    from app.pipeline.decision_audit import build_decision_audit
    n = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_name="Supplier A"),
        case=PriceIncreaseEvidence(requested_increase_percent=11.0),
        derived=DerivedEvidence(),
    )
    audit = build_decision_audit(n, _position())
    assert audit["contradictions"] == []


def test_stated_price_history_survives_real_extraction_pipeline():
    """Full real pipeline: the history itself must actually reach
    normalized evidence, not just work in a hand-built object."""
    extracted = {"suppliers_stated_justification": "No price adjustment for three years."}
    history = ["Year -3: +2.5%", "Year -2: +3.0%", "Year -1: 0%"]
    ne, _ = normalize_evidence("case text", "price_increase", extracted, {"requested_change_percent": 11.0}, stated_price_history=history)
    assert ne.case.stated_price_history == history
