from app.pipeline.sensitivity import build_sensitivity_analysis
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, QuoteComparisonEvidence,
    DerivedEvidence, SupplierEvidence,
)


def test_price_increase_sensitivity_is_deterministic():
    n = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(annual_volume_units=1000, unit_price_usd=100),
        case=PriceIncreaseEvidence(requested_increase_percent=12),
        derived=DerivedEvidence(resolved_annual_spend_usd=100000, currency_calculation_safe=True),
    )
    a = build_sensitivity_analysis(n)
    assert a["available"] is True
    assert any(x["scenario"] == "Price change of 12%" and x["annual_impact_usd"] == 12000 for x in a["scenarios"])
    assert all("assumed" not in x["basis"].lower() for x in a["scenarios"])


def test_price_sensitivity_refuses_unsafe_currency():
    n = NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(),
        case=PriceIncreaseEvidence(requested_increase_percent=12),
        derived=DerivedEvidence(resolved_annual_spend_usd=100000, currency_calculation_safe=False),
    )
    assert build_sensitivity_analysis(n)["available"] is False


def test_two_supplier_allocation_sensitivity_uses_only_explicit_usd_prices():
    n = NormalizedEvidence(
        content_type="quote_comparison",
        common=CommonEvidence(annual_volume_units=1000),
        case=QuoteComparisonEvidence(number_of_suppliers_being_compared="2"),
        derived=DerivedEvidence(),
        suppliers=[
            SupplierEvidence(supplier_name="A", currency="USD", price_usd=80),
            SupplierEvidence(supplier_name="B", currency="USD", price_usd=100),
        ],
    )
    a = build_sensitivity_analysis(n)
    assert a["available"] is True
    assert a["scenarios"][0]["annual_spend_usd"] == 100000
    assert a["scenarios"][-1]["annual_spend_usd"] == 80000


def test_allocation_sensitivity_refuses_fx_assumption():
    n = NormalizedEvidence(
        content_type="quote_comparison",
        common=CommonEvidence(annual_volume_units=1000),
        case=QuoteComparisonEvidence(),
        derived=DerivedEvidence(),
        suppliers=[
            SupplierEvidence(supplier_name="A", currency="EUR", price_usd=80),
            SupplierEvidence(supplier_name="B", currency="USD", price_usd=100),
        ],
    )
    assert build_sensitivity_analysis(n)["available"] is False
