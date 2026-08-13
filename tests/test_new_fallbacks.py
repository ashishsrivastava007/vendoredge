"""
Permanent regression tests for the four deterministic fallbacks built to
close Critical Findings #1, #2, and #3 from the reliability audit:
Incoterm, duty rate, currency, and annual volume had zero fallback
protection before this migration.
"""
from app.pipeline.incoterm_fallback import detect_incoterm_fallback
from app.pipeline.duty_fallback import detect_duty_rate_fallback
from app.pipeline.currency_fallback import detect_currency_fallback
from app.pipeline.volume_fallback import detect_annual_volume_fallback


def test_incoterm_fallback_real_scenarios():
    assert detect_incoterm_fallback("FOB Gdansk") == "FOB"
    assert detect_incoterm_fallback("Terms are DDP.") == "DDP"
    assert detect_incoterm_fallback("No incoterm mentioned here at all.") is None


def test_incoterm_fallback_all_eleven_real_terms_detected():
    for term in ("EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"):
        assert detect_incoterm_fallback(f"Terms are {term} for this shipment.") == term


def test_duty_fallback_real_scenarios():
    assert detect_duty_rate_fallback("The import duty is 4.5%.") == 4.5
    assert detect_duty_rate_fallback("A duty of 6% applies.") == 6.0
    assert detect_duty_rate_fallback("No duty mentioned here.") is None


def test_currency_fallback_real_scenarios():
    assert detect_currency_fallback("The supplier is billed in EUR.") == "EUR"
    assert detect_currency_fallback("The price is €50,000.") == "EUR"
    assert detect_currency_fallback("No currency mentioned, just USD implied.") is None


def test_volume_fallback_real_scenarios():
    assert detect_annual_volume_fallback("Annual volume 3,500 units.") == 3500.0
    assert detect_annual_volume_fallback("Annual demand: 6,500 units") == 6500.0
    assert detect_annual_volume_fallback("No volume mentioned.") is None
