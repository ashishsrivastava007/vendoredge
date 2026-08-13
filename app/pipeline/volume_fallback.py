"""
Deterministic, code-level fallback for detecting a stated annual volume
figure -- closes Critical Finding #3 from the reliability audit: without
this, the freight calculation silently fails to combine with a correctly
captured per-unit freight figure whenever spend was stated as one lump
sum rather than unit price times volume.
"""
import re


def detect_annual_volume_fallback(raw_text: str) -> float | None:
    """
    Real, deterministic detection of a stated annual volume in units.
    Handles: "annual volume 3,500 units", "volume of 1,800 units",
    "3,500 units annually", "annual demand: 6,500 units".
    """
    if not raw_text:
        return None

    patterns = [
        r"annual\s+(?:volume|demand)\s*(?:is|of|:)?\s*([\d,]+)\s*units",
        r"volume\s+of\s+([\d,]+)\s*units",
        r"([\d,]+)\s*units\s+(?:annually|per\s+year|a\s+year)",
        r"annual\s+volume\s*[:=]?\s*([\d,]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, raw_text, re.IGNORECASE)
        if match:
            number_str = match.group(1).replace(",", "")
            try:
                return float(number_str)
            except ValueError:
                continue

    return None
