"""
Deterministic, code-level fallback for detecting a stated supplier
currency -- closes part of Critical Finding #2 from the reliability
audit. Detects real ISO currency codes and common symbols, since a
supplier billing in a non-USD currency is genuinely common in
cross-border procurement text.
"""
import re

# Deliberately the common, realistic set for procurement text -- not
# exhaustive of every ISO 4217 code, matching the same "genuinely common
# in real text" scoping used for region_fallback.py's country list.
_CURRENCY_CODES = ("EUR", "GBP", "JPY", "CNY", "INR", "CHF", "CAD", "AUD", "SGD", "MXN")
_SYMBOL_TO_CODE = {"€": "EUR", "£": "GBP", "¥": "JPY"}


def detect_currency_fallback(raw_text: str) -> str | None:
    """
    Real, deterministic detection. Handles: "billed in EUR", "invoiced in
    GBP", "supplier bills in JPY", and direct symbol usage like "€50,000".
    Returns the standard 3-letter code regardless of which form matched.
    """
    if not raw_text:
        return None

    for pattern in [r"billed\s+in\s+([A-Z]{3})", r"invoiced\s+in\s+([A-Z]{3})",
                     r"bills?\s+in\s+([A-Z]{3})", r"pric(?:ed|ing)\s+in\s+([A-Z]{3})"]:
        match = re.search(pattern, raw_text, re.IGNORECASE)
        if match:
            code = match.group(1).upper()
            if code in _CURRENCY_CODES:
                return code

    for symbol, code in _SYMBOL_TO_CODE.items():
        if symbol in raw_text:
            return code

    for code in _CURRENCY_CODES:
        if re.search(rf"\b{code}\b", raw_text):
            return code

    return None
