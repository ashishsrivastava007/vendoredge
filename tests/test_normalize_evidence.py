"""
Permanent regression tests for normalize_evidence() -- the single
evidence-normalization boundary. Covers all seven required scenarios
(A-G) from the migration spec, each proven against the real orchestrator
function, not a mock.
"""
from app.pipeline.normalize import normalize_evidence


def test_scenario_a_region():
    raw = "Our incumbent supplier based in Poland requests a 5% increase."
    ne, conflicts = normalize_evidence(raw, "price_increase", {}, {})
    assert ne.common.supplier_region_or_market == "Poland"
    assert conflicts == []


def test_scenario_b_incoterm_drives_freight_relevance():
    raw = "Terms are FOB Gdansk for this shipment, 10% increase requested."
    ne, conflicts = normalize_evidence(raw, "price_increase", {}, {})
    assert ne.common.incoterm == "FOB"
    assert ne.derived.freight_relevant is True


def test_scenario_c_duty_reaches_normalized_evidence_and_tco_relevance():
    """Duty relevance requires a cross-border signal alongside the rate --
    this preserves the exact, real, pre-existing methodology_consistency.py
    behavior, not a new stricter or looser rule."""
    raw = "Our supplier in Poland states the import duty is 4.5%, 8% increase requested."
    ne, conflicts = normalize_evidence(raw, "price_increase", {}, {})
    assert ne.common.duty_or_tax_rate_percent == 4.5
    assert ne.derived.duty_relevant is True


def test_scenario_d_currency_reaches_normalized_evidence():
    raw = "The supplier is billed in EUR, requesting a 6% increase."
    ne, conflicts = normalize_evidence(raw, "price_increase", {}, {})
    assert ne.common.supplier_currency == "EUR"
    assert ne.derived.currency_mismatch is True


def test_scenario_e_volume_participates_in_spend_derivation():
    raw = "Annual volume 3,500 units."
    ne, conflicts = normalize_evidence(raw, "price_increase", {}, {"unit_price_usd": 100.0})
    assert ne.common.annual_volume_units == 3500.0
    assert ne.derived.resolved_annual_spend_usd == 350_000.0
    assert ne.derived.annual_spend_resolution_method == "derived_from_price_and_volume"


def test_scenario_f_real_meridian_case_direct_spend_no_reask():
    raw = "Meridian Components requested a 9% increase. Current annual spend is $850,000."
    ne, conflicts = normalize_evidence(raw, "price_increase", {"supplier_name": "Meridian Components"}, {})
    assert ne.derived.resolved_annual_spend_usd == 850_000.0
    assert ne.derived.annual_spend_resolution_method == "direct"
    assert ne.case.requested_increase_percent == 9.0
    assert conflicts == []


def test_scenario_g_conflict_detected_and_both_values_retained():
    """The LLM says 2.0M, the deterministic fallback independently finds
    2.4M in the same text -- a genuine, deliberate conflict."""
    raw = "Annual spend is $2.4 million for this supplier."
    ne, conflicts = normalize_evidence(raw, "price_increase", {}, {"annual_spend_usd": 2_000_000.0})
    assert "annual_spend_usd" in conflicts
    prov = ne.provenance["annual_spend_usd"]
    assert prov.conflicting is True
    assert prov.conflicting_values == (2_000_000.0, 2_400_000.0)
    # LLM value used as primary, per the approved conflict-resolution rule
    assert ne.derived.resolved_annual_spend_usd == 2_000_000.0


def test_no_false_conflict_when_only_one_source_has_a_value():
    """The common, everyday case -- must never be flagged as a conflict."""
    raw = "Annual spend is $850,000."
    ne, conflicts = normalize_evidence(raw, "price_increase", {}, {})
    assert conflicts == []
    assert ne.provenance["annual_spend_usd"].source == "deterministic_fallback"


def test_agreement_marked_both_agree_not_a_conflict():
    """When LLM and fallback independently arrive at the same value, that
    should be marked as strengthened confidence, not a conflict."""
    raw = "Annual spend is $850,000 this year."
    ne, conflicts = normalize_evidence(raw, "price_increase", {}, {"annual_spend_usd": 850_000.0})
    assert conflicts == []
    assert ne.provenance["annual_spend_usd"].source == "both_agree"
