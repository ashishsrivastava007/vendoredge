"""
Entity-aware calculation selection.

Root cause, confirmed by direct tracing, not assumed: the classifier's
numeric_facts.annual_spend_usd field had no entity/subject scoping --
one generic field, meant to serve as the baseline for a supplier-
specific price-increase calculation, with no structured way to
distinguish it from a case's separate category/portfolio-level total
when a case states both. Reproduced: a case stating "category spend
EUR 8.40M; Supplier A spend EUR 5.55M, requesting 11%" could have its
scenario calculation silently baselined on the category total (EUR
924,000) instead of the correct, requested entity (EUR 610,500) --
correct arithmetic, wrong commercial object.

Fixed additively: category_annual_spend_usd is a new, separate field.
annual_spend_usd's meaning is now explicit in the classifier prompt
(the SPECIFIC SUPPLIER's own spend), and resolved_annual_spend_usd
(what actually feeds every scenario/financial calculation) is still
derived from annual_spend_usd alone -- category_annual_spend_usd is
never read by financial.py, by construction, not merely by convention.
"""
from app.pipeline.normalize import normalize_evidence
from app.pipeline.financial import compute_financial_impact
from app.pipeline.normalized_evidence import NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence


def test_adversarial_category_vs_supplier_entity_separation():
    """The exact adversarial case: category EUR 10M, Supplier A EUR 2M,
    5% increase. Correct: EUR 100,000. Wrong (category baseline):
    EUR 500,000. Proves the engine is genuinely entity-aware, not
    merely coincidentally passing one specific golden case."""
    extracted_evidence = {"supplier_currency": "EUR"}
    numeric_facts = {
        "annual_spend_usd": 2_000_000,
        "category_annual_spend_usd": 10_000_000,
        "requested_change_percent": 5.0,
    }
    raw = "Category spend is EUR 10,000,000. Supplier A's own annual spend is EUR 2,000,000 and has requested a 5% increase."
    ne, _ = normalize_evidence(raw, "price_increase", extracted_evidence, numeric_facts)

    assert ne.case.annual_spend_usd == 2_000_000.0
    assert ne.case.category_annual_spend_usd == 10_000_000.0
    assert ne.derived.resolved_annual_spend_usd == 2_000_000.0, \
        "resolved spend must be the supplier's own figure, never the category total"

    result = compute_financial_impact(ne)
    assert result.potential_annual_impact == 100_000.0
    assert result.potential_annual_impact != 500_000.0, \
        "must never silently use the category baseline for a supplier-specific scenario"


def test_golden_case_shape_category_8_4m_supplier_5_55m_11_percent():
    """The real, reported defect's exact shape: category EUR 8.40M,
    Supplier A EUR 5.55M, 11% request. Correct: EUR 610,500.
    Previously-observed wrong answer: EUR 924,000 (category baseline)."""
    extracted_evidence = {"supplier_currency": "EUR"}
    numeric_facts = {
        "annual_spend_usd": 5_550_000,
        "category_annual_spend_usd": 8_400_000,
        "requested_change_percent": 11.0,
    }
    raw = "Category spend is EUR 8.40M. Supplier A's own spend is EUR 5.55M, requesting an 11% increase."
    ne, _ = normalize_evidence(raw, "price_increase", extracted_evidence, numeric_facts)
    result = compute_financial_impact(ne)
    assert result.potential_annual_impact == 610_500.0
    assert result.potential_annual_impact != 924_000.0


def test_case_with_no_category_figure_at_all_is_entirely_unaffected():
    """Regression guard: the overwhelming majority of price_increase
    cases have exactly one spend figure and no category/portfolio
    distinction at all -- this fix must not change their behavior."""
    extracted_evidence = {}
    numeric_facts = {"annual_spend_usd": 1_000_000, "requested_change_percent": 10.0}
    ne, _ = normalize_evidence("Supplier requests a 10% increase on our USD 1,000,000 annual spend.", "price_increase", extracted_evidence, numeric_facts)
    assert ne.case.category_annual_spend_usd is None
    assert ne.derived.resolved_annual_spend_usd == 1_000_000.0
    result = compute_financial_impact(ne)
    assert result.potential_annual_impact == 100_000.0


def test_category_annual_spend_usd_is_never_read_by_financial_py():
    """Direct proof, not inference: construct a NormalizedEvidence where
    category_annual_spend_usd is deliberately huge and annual_spend_usd
    is deliberately small, confirming financial.py's calculation is
    structurally incapable of picking up the category figure -- it
    simply never looks at that field at all."""
    n = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(supplier_currency="EUR"),
        case=PriceIncreaseEvidence(requested_increase_percent=10.0, annual_spend_usd=1.0, category_annual_spend_usd=999_999_999.0),
        derived=DerivedEvidence(resolved_annual_spend_usd=1.0, currency_calculation_safe=True, spend_currency="EUR"),
    )
    result = compute_financial_impact(n)
    assert result.potential_annual_impact == 0.1
