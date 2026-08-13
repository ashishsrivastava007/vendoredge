"""
Deterministic, code-level fallback for detecting a stated Incoterm --
built to close Critical Finding #1 from the reliability audit: Incoterm
had zero fallback anywhere, and its absence causes a SILENT skip (the
conditional freight requirement simply never triggers), not a visible
error. Same philosophy as region_fallback.py: real pattern matching
against the real, published Incoterms 2020 list, never a guess.
"""
import re

# The real, complete, published Incoterms 2020 list. Order matters for the
# regex alternation below -- longer/more-specific codes are not a concern
# here since all 11 are exactly 3 letters, but kept as an explicit tuple
# (not a set) so the source list is readable and auditable at a glance.
INCOTERMS_2020 = (
    "EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP",
)

# Common full names the LLM might reasonably use instead of the code --
# genuine, real terminology, not a guess. Maps to the real code.
_INCOTERM_FULL_NAMES = {
    "ex works": "EXW",
    "free carrier": "FCA",
    "free alongside ship": "FAS",
    "free on board": "FOB",
    "cost and freight": "CFR",
    "cost insurance and freight": "CIF",
    "cost, insurance and freight": "CIF",
    "carriage paid to": "CPT",
    "carriage and insurance paid to": "CIP",
    "carriage and insurance paid": "CIP",
    "delivered at place": "DAP",
    "delivered at place unloaded": "DPU",
    "delivered duty paid": "DDP",
}


def normalize_incoterm(raw_value: str | None) -> str | None:
    """
    Real validation, not a pass-through. A raw LLM extraction might say
    "Free On Board" instead of "FOB" -- or, adversarially, could contain
    a genuinely malformed or hallucinated value that isn't a real
    Incoterm at all. Silently accepting either would mean
    derived.freight_relevant silently comes back False even when the
    case genuinely describes a buyer-pays-freight term -- a real, found
    gap during adversarial testing. This normalizes real full names to
    their code, and returns None for anything that doesn't genuinely
    match the real standard, rather than passing through garbage.
    """
    if not raw_value:
        return None
    cleaned = raw_value.strip()
    upper = cleaned.upper()
    if upper in INCOTERMS_2020:
        return upper
    lowered = cleaned.lower()
    if lowered in _INCOTERM_FULL_NAMES:
        return _INCOTERM_FULL_NAMES[lowered]
    return None


def detect_incoterm_fallback(raw_text: str) -> str | None:
    """
    Real, deterministic detection -- returns the exact Incoterm code if a
    genuine, whole-word match is found in the raw text, else None. Word
    boundaries are essential here: without them, "FOB" would false-match
    inside unrelated text; Incoterms are always written as standalone
    3-letter codes in real procurement text (e.g. "FOB Gdansk", "under
    DDP terms"), never embedded inside another word.
    """
    if not raw_text:
        return None

    for term in INCOTERMS_2020:
        if re.search(rf"\b{term}\b", raw_text, re.IGNORECASE):
            return term

    return None
