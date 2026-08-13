"""
Deterministic, code-level fallback for detecting a supplier's stated
region/country -- built after a real, live case proved the model can miss
this on an extremely dense question, even when the text plainly says
"based in Poland." The classifier's own passive extraction is the primary
path; this is the safety net, matching the same "guarantee, don't just ask
nicely" philosophy used everywhere else in this codebase, applied to this
specific gap.

Deliberately simple: real regex pattern matching against a real list of
countries, not another AI call. Cheap, fast, and either finds an exact,
genuine match or finds nothing -- never a fuzzy guess.
"""
import re

# Not exhaustive -- genuinely common countries/regions that appear in real
# procurement text. Extending this list is safe and cheap; it's plain data,
# not logic.
_KNOWN_COUNTRIES_AND_REGIONS = [
    "Poland", "Germany", "France", "Italy", "Spain", "United Kingdom", "UK",
    "Netherlands", "Belgium", "Czech Republic", "Slovakia", "Hungary",
    "Romania", "Portugal", "Sweden", "Norway", "Denmark", "Finland",
    "Austria", "Switzerland", "Ireland", "Greece", "Turkey",
    "China", "Japan", "South Korea", "Taiwan", "India", "Vietnam",
    "Thailand", "Indonesia", "Malaysia", "Singapore", "Philippines",
    "United States", "USA", "Canada", "Mexico", "Brazil", "Argentina",
    "South Africa", "Egypt", "Morocco",
    "Southeast Asia", "Eastern Europe", "Western Europe", "Middle East",
    "North America", "South America", "Central Europe",
]

# Real, common phrasings for how a supplier's region genuinely gets stated
# in procurement text -- built directly from the exact phrasing that was
# missed live ("based in Poland").
_REGION_PATTERNS = [
    r"based in ({country})",
    r"located in ({country})",
    r"manufactured in ({country})",
    r"supplier (?:in|from) ({country})",
    r"({country})[\s\-]based",
    r"our ({country}) supplier",
]


def detect_supplier_region_fallback(raw_text: str) -> str | None:
    """
    Real, deterministic detection -- returns the exact country/region name
    if a genuine, common pattern is found in the raw text, else None. This
    is a fallback, not a replacement: it's only consulted when the
    classifier's own passive extraction didn't already capture a region,
    so it never overrides a genuine, more nuanced extraction the model
    already made.
    """
    if not raw_text:
        return None

    country_alternation = "|".join(re.escape(c) for c in _KNOWN_COUNTRIES_AND_REGIONS)
    for pattern_template in _REGION_PATTERNS:
        pattern = pattern_template.format(country=country_alternation)
        match = re.search(pattern, raw_text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None
