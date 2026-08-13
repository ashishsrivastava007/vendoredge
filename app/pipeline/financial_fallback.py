"""
Deterministic, code-level fallback for extracting key financial figures
(annual spend, requested percentage change) directly from the raw
question text -- built after a real, live case proved the model's
numeric_facts extraction can miss a clearly-stated figure ("Current
annual spend is $2 million") even when the same information was
correctly captured in extracted_evidence's free text. Same class of gap,
same fix philosophy, as region_fallback.py: never trust a single AI
extraction pass alone for something a simple, reliable pattern match can
also catch.

Deliberately conservative: only fires when the classifier's own
numeric_facts extraction already came back empty for that specific
figure, and only returns a value when a genuinely unambiguous pattern is
found -- never a fuzzy guess dressed up as a real number.
"""
import re


def extract_annual_spend_fallback(raw_text: str) -> float | None:
    """
    Real, deterministic detection of an annual spend figure genuinely
    stated in the text -- handles the common real phrasings: "annual
    spend is $2 million", "$2 million in annual spend", "spend of $2M
    annually", "$2,000,000 per year".
    """
    if not raw_text:
        return None

    patterns = [
        r"annual\s+spend\s+(?:is|of)?\s*\$?([\d,]+(?:\.\d+)?)\s*(million|m\b|k\b|thousand)?",
        r"\$?([\d,]+(?:\.\d+)?)\s*(million|m\b|k\b|thousand)?\s+(?:in\s+)?annual\s+spend",
        r"spend\s+of\s+\$?([\d,]+(?:\.\d+)?)\s*(million|m\b|k\b|thousand)?\s+annually",
        r"\$?([\d,]+(?:\.\d+)?)\s*(million|m\b|k\b|thousand)?\s+per\s+year",
    ]

    for pattern in patterns:
        match = re.search(pattern, raw_text, re.IGNORECASE)
        if match:
            number_str = match.group(1).replace(",", "")
            try:
                value = float(number_str)
            except ValueError:
                continue
            multiplier_word = (match.group(2) or "").lower()
            if multiplier_word in ("million", "m"):
                value *= 1_000_000
            elif multiplier_word in ("k", "thousand"):
                value *= 1_000
            return value

    return None


def extract_requested_change_percent_fallback(raw_text: str) -> float | None:
    """
    Real, deterministic detection of a requested percentage change --
    handles "requested a 15% price increase", "15% increase", "increase
    of 15%".
    """
    if not raw_text:
        return None

    patterns = [
        r"requested?\s+a\s+(\d+(?:\.\d+)?)\s*%\s+(?:price\s+)?increase",
        r"(\d+(?:\.\d+)?)\s*%\s+(?:price\s+)?increase",
        r"increase\s+of\s+(\d+(?:\.\d+)?)\s*%",
    ]

    for pattern in patterns:
        match = re.search(pattern, raw_text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue

    return None
