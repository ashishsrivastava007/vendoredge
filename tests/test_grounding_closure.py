"""
Grounding Closure -- the two remaining material gaps from the Evidence
Grounding Rebuild's own implementation report:

1. Implication-side temporal grounding. Timeframe grounding existed
   for evidence but was never consulted for the procurement
   translation itself. _classify_temporal_status is one general
   mechanism (not a historical-specific patch) reused for both
   evidence and implication text; validate_procurement_implication
   now rejects a translation whose own temporal framing asserts
   "current" when the evidence it's based on is grounded as
   "historical" or "forecast".

2. Strengthened scope/geography grounding. The prior exact-equality
   geography check is replaced by ground_geography_claim, a general
   narrower-only subset mechanism over a small, fixed, genuinely
   generic region-name lexicon (continents/major regions, not an
   industry taxonomy) -- a claim may narrow what the source supports
   but must never broaden it.
"""
from app.pipeline.market_signal_intelligence import (
    validate_procurement_implication, _parse_implication_proposition, _parse_evidence_proposition,
    _classify_temporal_status, ground_geography_claim, _extract_regions,
)


def _ev(**kw):
    base = {"subject": "", "predicate": "", "quantitative_value": None, "scope": "global_market",
            "geography": None, "timeframe": None, "negated": False, "attribution": "third_party_report"}
    base.update(kw)
    return _parse_evidence_proposition(base)


def _im(**kw):
    base = {"subject": "", "scope": "market", "quantitative_value": None, "causal_claim": False,
            "entitlement_claim": False, "geography": None}
    base.update(kw)
    return _parse_implication_proposition(base)


# ---------------------------------------------------------------------
# Gap 1: temporal classifier -- direct
# ---------------------------------------------------------------------

def test_temporal_classifier_historical():
    assert _classify_temporal_status("European steel prices increased 8% in 2024.") == "historical"


def test_temporal_classifier_current():
    assert _classify_temporal_status("Steel prices are currently increasing.") == "current"


def test_temporal_classifier_forecast():
    assert _classify_temporal_status("Steel prices are forecast to increase 8% next quarter.") == "forecast"


def test_temporal_classifier_announced():
    assert _classify_temporal_status("The company announced a planned 8% increase.") == "forecast"


def test_temporal_classifier_unspecified():
    assert _classify_temporal_status("Steel prices increased 8%.") == "unspecified"


# ---------------------------------------------------------------------
# Gap 1: wired into validate_procurement_implication
# ---------------------------------------------------------------------

def test_historical_to_current_rejected():
    evidence = _ev(subject="European steel market", predicate="price increased", quantitative_value="8%", scope="regional_market", geography="Europe")
    finding = "European steel prices increased 8% in 2024."
    implication = _im(subject="European steel market", scope="market", quantitative_value="8%", geography="Europe")
    allowed = validate_procurement_implication(implication, evidence, finding, translation_text="European steel prices are currently 8% higher.")
    assert allowed is False


def test_forecast_to_actual_rejected():
    evidence = _ev(quantitative_value="8%")
    finding = "Steel prices are forecast to increase 8% next quarter."
    allowed = validate_procurement_implication(_im(scope="market", quantitative_value="8%"), evidence, finding, translation_text="Steel prices are currently 8% higher.")
    assert allowed is False


def test_target_to_achieved_rejected():
    evidence = _ev(quantitative_value="8%")
    finding = "The company targeted an 8% price increase for the year."
    allowed = validate_procurement_implication(_im(scope="market", quantitative_value="8%"), evidence, finding, translation_text="Prices are currently 8% higher.")
    assert allowed is False


def test_announcement_to_actual_rejected():
    evidence = _ev(quantitative_value="8%")
    finding = "The company announced a planned 8% price increase."
    allowed = validate_procurement_implication(_im(scope="market", quantitative_value="8%"), evidence, finding, translation_text="Prices are currently 8% higher.")
    assert allowed is False


def test_planned_to_completed_rejected():
    evidence = _ev(quantitative_value="8%")
    finding = "An 8% increase is planned for next quarter."
    allowed = validate_procurement_implication(_im(scope="market", quantitative_value="8%"), evidence, finding, translation_text="The 8% increase is now in effect.")
    assert allowed is False


def test_past_increase_to_current_entitlement_rejected():
    """Caught by BOTH the entitlement check and the temporal check --
    confirms the temporal check doesn't need to be the only guard."""
    evidence = _ev(subject="the supplier", predicate="price increased", quantitative_value="8%", scope="supplier_specific")
    finding = "The supplier's price increased 8% in 2024."
    allowed = validate_procurement_implication(_im(subject="the supplier", scope="supplier", quantitative_value="8%", entitlement_claim=True), evidence, finding, translation_text="The supplier should currently increase prices 8%.")
    assert allowed is False


def test_legitimate_historical_translation_allowed():
    """The fix must not become overly aggressive: a translation that
    correctly preserves historical framing is still allowed."""
    evidence = _ev(subject="European steel market", predicate="price increased", quantitative_value="8%", scope="regional_market", geography="Europe")
    finding = "European steel prices increased 8% in 2024."
    implication = _im(subject="European steel market", scope="market", quantitative_value="8%", geography="Europe")
    allowed = validate_procurement_implication(implication, evidence, finding, translation_text="European steel prices increased 8% in 2024.")
    assert allowed is True


def test_legitimate_current_evidence_current_translation_allowed():
    evidence = _ev(subject="steel market", predicate="price increasing", scope="global_market")
    finding = "Steel prices are currently increasing."
    allowed = validate_procurement_implication(_im(subject="steel market", scope="market"), evidence, finding, translation_text="Steel prices are currently increasing.")
    assert allowed is True


# ---------------------------------------------------------------------
# Gap 2: region extraction and subset grounding -- direct
# ---------------------------------------------------------------------

def test_region_extraction_normalizes_adjective_and_noun_forms():
    """The confirmed bug found during implementation: "Europe" and
    "European" must resolve to the same canonical region."""
    assert _extract_regions("Europe") == _extract_regions("European markets")


def test_geography_europe_to_europe_grounded():
    status, _ = ground_geography_claim("Europe", "European steel prices increased 8%.")
    assert status == "GROUNDED"


def test_geography_europe_to_global_ungrounded():
    status, _ = ground_geography_claim("Global", "European steel prices increased 8%.")
    assert status in ("UNGROUNDED", "CONTRADICTED")


def test_geography_multi_region_source_narrower_claim_grounded():
    status, _ = ground_geography_claim("Europe", "Steel prices increased 8% across Europe and Asia.")
    assert status == "GROUNDED"


def test_geography_europe_to_asia_contradicted():
    status, _ = ground_geography_claim("Asia", "European steel prices increased 8%.")
    assert status == "CONTRADICTED"


def test_geography_no_region_in_source_ungrounded():
    status, _ = ground_geography_claim("Europe", "Steel prices increased 8%.")
    assert status == "UNGROUNDED"


# ---------------------------------------------------------------------
# Gap 2: wired into validate_procurement_implication
# ---------------------------------------------------------------------

def test_multi_region_subset_implication_allowed():
    evidence = _ev(quantitative_value="8%", geography="Europe and Asia")
    finding = "Steel prices increased 8% across Europe and Asia."
    implication = _im(scope="market", quantitative_value="8%", geography="Europe")
    allowed = validate_procurement_implication(implication, evidence, finding, translation_text="European steel prices increased 8%.")
    assert allowed is True


def test_market_to_asia_when_only_europe_established_rejected():
    evidence = _ev(quantitative_value="8%", geography="Europe")
    finding = "European steel prices increased 8%."
    implication = _im(scope="market", quantitative_value="8%", geography="Asia")
    allowed = validate_procurement_implication(implication, evidence, finding, translation_text="Asian steel prices increased 8%.")
    assert allowed is False


def test_market_to_category_geography_expansion_rejected():
    """market -> category/customer scope expansion combined with an
    unsupported geography broadening, together."""
    evidence = _ev(quantitative_value="8%", geography="Europe", scope="regional_market")
    finding = "European steel prices increased 8%."
    implication = _im(scope="category", quantitative_value="8%", geography="Global")
    allowed = validate_procurement_implication(implication, evidence, finding, translation_text="Global category costs increased 8%.")
    assert allowed is False
