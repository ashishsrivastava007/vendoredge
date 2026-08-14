from app.pipeline.alternatives import build_alternative_paths
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, DerivedEvidence,
    PriceIncreaseEvidence, QuoteComparisonEvidence, SupplierEvidence,
    StakeholderView,
)


def _price_case():
    atlas = SupplierEvidence(
        supplier_name="Atlas Motors", is_incumbent=True, price_usd=100,
        otif_percent=99.2, qualification_status="complete",
    )
    nova = SupplierEvidence(
        supplier_name="NovaDrive", price_usd=82, capacity_percent=30,
        qualification_status="unknown", production_history_status="unknown",
    )
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(annual_volume_units=1000),
        case=PriceIncreaseEvidence(requested_increase_percent=12),
        derived=DerivedEvidence(resolved_annual_spend_usd=100000, currency_calculation_safe=True),
        suppliers=[atlas, nova],
        stakeholder_views=[StakeholderView(stakeholder_name="Operations", view_type="preference", statement="Operations prefers Atlas Motors")],
    )


def test_price_increase_builds_three_distinct_paths():
    result = build_alternative_paths(_price_case())
    assert result["available"] is True
    assert len(result["alternatives"]) == 3
    names = [x["name"] for x in result["alternatives"]]
    assert "Continuity — accept the requested change" in names
    assert "Negotiate — protect the current baseline" in names
    assert "Leverage — develop an alternative source" in names


def test_no_blended_allocation_is_invented():
    result = build_alternative_paths(_price_case())
    dual = result["alternatives"][2]
    assert dual["annual_spend_usd"] is None
    assert "no allocation is assumed" in dual["financial_basis"].lower()


def test_alternative_supplier_open_items_are_exposed():
    result = build_alternative_paths(_price_case())
    dual = result["alternatives"][2]
    assert any("Qualification" in x for x in dual["requires_new_evidence"])
    assert any("capacity" in x.lower() for x in dual["requires_new_evidence"])


def test_stakeholder_view_is_attributed_to_supplier():
    result = build_alternative_paths(_price_case())
    continuity = result["alternatives"][0]
    assert any(x.startswith("Operations:") for x in continuity["stakeholder_impacts"])


def test_quote_comparison_requires_two_prices():
    n = NormalizedEvidence(
        content_type="quote_comparison",
        common=CommonEvidence(annual_volume_units=1000),
        case=QuoteComparisonEvidence(),
        derived=DerivedEvidence(currency_calculation_safe=True),
        suppliers=[SupplierEvidence(supplier_name="A", price_usd=10)],
    )
    result = build_alternative_paths(n)
    assert result["available"] is False
    assert result["status"] == "NOT_TESTABLE"


def test_quote_comparison_creates_cost_continuity_and_dual_paths():
    a = SupplierEvidence(supplier_name="A Supplier", price_usd=80, qualification_status="complete")
    b = SupplierEvidence(supplier_name="B Supplier", price_usd=100, is_incumbent=True, qualification_status="complete")
    n = NormalizedEvidence(
        content_type="quote_comparison",
        common=CommonEvidence(annual_volume_units=1000),
        case=QuoteComparisonEvidence(),
        derived=DerivedEvidence(currency_calculation_safe=True),
        suppliers=[a, b],
    )
    result = build_alternative_paths(n)
    assert result["available"] is True
    assert len(result["alternatives"]) == 3
    assert result["alternatives"][0]["supplier"] == "A Supplier"
    assert result["alternatives"][1]["supplier"] == "B Supplier"
    assert result["alternatives"][2]["type"] == "dual_source"


def test_no_qualification_silence_is_not_treated_as_negative_fact():
    n = _price_case()
    result = build_alternative_paths(n)
    dual = result["alternatives"][2]
    assert any("Qualification is not recorded as complete" in x for x in dual["requires_new_evidence"])
