"""
Permanent regression test for the deterministic region-detection fallback,
built after a real, live case proved the model can miss a passively-stated
region on a very dense question, even when the text plainly says "based in
Poland." This locks in that exact real scenario, plus the broader pattern
set, so this class of miss can't silently regress.
"""
from app.pipeline.region_fallback import detect_supplier_region_fallback


def test_exact_real_case_that_failed_live():
    """The literal text from the real case where this was found -- the
    most important test in this file."""
    real_text = (
        "We are renewing a 3-year supply agreement for precision bearing "
        "assemblies with Kowalski Industrial Sp. z o.o., our incumbent "
        "supplier based in Poland."
    )
    assert detect_supplier_region_fallback(real_text) == "Poland"


def test_common_real_phrasings_are_all_caught():
    cases = {
        "Our supplier is located in Vietnam and ships monthly.": "Vietnam",
        "We work with a Germany-based manufacturer.": "Germany",
        "The component is manufactured in China.": "China",
        "Our Czech Republic supplier quotes DDP terms.": "Czech Republic",
    }
    for text, expected in cases.items():
        assert detect_supplier_region_fallback(text) == expected


def test_no_false_positives_when_nothing_is_genuinely_stated():
    assert detect_supplier_region_fallback("Steel prices are up 9 percent this year.") is None
    assert detect_supplier_region_fallback("") is None
    assert detect_supplier_region_fallback(None) is None
