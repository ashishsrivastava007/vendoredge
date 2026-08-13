"""
Permanent regression tests for the financial-figure extraction fallback.
Built after a real, live case where "Current annual spend is $2 million"
was clearly stated in the question, but the model's own numeric_facts
extraction came back empty -- the exact same class of miss already found
and fixed for supplier region (see region_fallback.py), now applied to
financial figures.
"""
from app.pipeline.financial_fallback import (
    extract_annual_spend_fallback, extract_requested_change_percent_fallback,
)

_REAL_QUESTION = (
    "Our supplier for aluminum extrusion components has requested a 15% "
    "price increase, citing rising aluminum prices as the driver. Current "
    "annual spend is $2 million under a 3-year agreement. Should we accept "
    "this increase, and what should our negotiation position be?"
)


def test_exact_real_case_that_failed_live():
    """The literal question from the real case where this was found."""
    assert extract_annual_spend_fallback(_REAL_QUESTION) == 2_000_000.0
    assert extract_requested_change_percent_fallback(_REAL_QUESTION) == 15.0


def test_common_real_spend_phrasings_are_all_caught():
    cases = {
        "Annual spend is $1.8 million.": 1_800_000.0,
        "We spend $500,000 per year with this supplier.": 500_000.0,
        "Current spend of $2M annually.": 2_000_000.0,
        "$250k in annual spend.": 250_000.0,
    }
    for text, expected in cases.items():
        assert extract_annual_spend_fallback(text) == expected


def test_common_real_percent_phrasings_are_all_caught():
    cases = {
        "The supplier requested a 12% price increase.": 12.0,
        "This is a 9.5% increase.": 9.5,
        "an increase of 20% has been proposed": 20.0,
    }
    for text, expected in cases.items():
        assert extract_requested_change_percent_fallback(text) == expected


def test_no_false_positives_when_nothing_is_genuinely_stated():
    assert extract_annual_spend_fallback("No numbers mentioned at all.") is None
    assert extract_requested_change_percent_fallback("No numbers mentioned at all.") is None
    assert extract_annual_spend_fallback("") is None
    assert extract_annual_spend_fallback(None) is None
