"""
Deterministic, code-level fallback for detecting a stated duty/import tax
rate -- closes part of Critical Finding #2 from the reliability audit.
"""
import re


def detect_duty_rate_fallback(raw_text: str) -> float | None:
    """
    Real, deterministic detection of a stated duty/import tax rate.
    Handles common real phrasings: "import duty is 4.5%", "duty of 6%",
    "6% duty", "tariff of 10%", "customs duty of 4.5%".
    """
    if not raw_text:
        return None

    patterns = [
        r"(?:import\s+)?duty\s+(?:is|of)\s+(\d+(?:\.\d+)?)\s*%",
        r"(\d+(?:\.\d+)?)\s*%\s+(?:import\s+)?duty",
        r"tariff\s+(?:is|of)\s+(\d+(?:\.\d+)?)\s*%",
        r"(\d+(?:\.\d+)?)\s*%\s+tariff",
        r"customs\s+duty\s+(?:is|of)\s+(\d+(?:\.\d+)?)\s*%",
    ]

    for pattern in patterns:
        match = re.search(pattern, raw_text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue

    return None
