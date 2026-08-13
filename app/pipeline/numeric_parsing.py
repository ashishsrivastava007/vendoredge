"""
Deterministic parsing of a numeric value out of a free-text evidence
answer -- built specifically to close a real, found gap: freight cost was
being collected from the user as typed text (e.g. "€35/unit"), but nothing
ever turned that text back into a real number the deterministic financial
calculation could actually use. No AI call here -- this is pure, fast,
testable pattern matching, the same philosophy as region_fallback.py.
"""
import re


def parse_numeric_value(text: str) -> float | None:
    """
    Extracts the first clear numeric value from free text, stripping
    common currency symbols and thousands separators. Returns None if no
    genuine number is found -- never guesses, never returns 0 as a
    fallback, since a genuinely unparseable answer should be treated as
    missing data, not silently zero.

    Handles real, realistic formats: "€35/unit", "$35", "35", "about 35
    euros", "35.50", "1,250".
    """
    if not text or not text.strip():
        return None

    # Strip common currency symbols and the word "per unit"/"unit" so the
    # regex below only has to find a plain number.
    cleaned = re.sub(r"[€$£¥]", "", text)
    cleaned = re.sub(r"per\s*unit|/\s*unit|each", "", cleaned, flags=re.IGNORECASE)

    match = re.search(r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)", cleaned)
    if not match:
        return None

    raw_number = match.group(1).replace(",", "")
    try:
        return float(raw_number)
    except ValueError:
        return None
