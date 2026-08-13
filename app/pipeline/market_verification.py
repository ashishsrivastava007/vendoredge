"""
Targeted live market-claim verification using Claude's web search tool.

Deliberate design, matching the "near-zero cash cost" constraint: this is
NOT a live data subscription and does not run on every question. It makes
one small, targeted search call ONLY when a supplier's stated justification
in a price_increase question names something genuinely checkable (a
commodity, a market trend) -- turning a per-use, cents-level API call into
an honest, current, citable verification, instead of a recurring paid feed.

HONESTY NOTE ON TEST COVERAGE, stated plainly rather than hidden: the
trigger logic (does this claim look checkable?) and the failure-handling
(what happens if the search call errors) are both tested below without a
live key. The actual live web_search tool call itself has NOT been proven
against the real Anthropic API in this environment -- that is the one
piece that genuinely needs to be tested with a real key before being
trusted in front of real pilot users. This is flagged here on purpose,
not discovered later.
"""
import json
import os
import re
from anthropic import Anthropic
from app.model_config import CLASSIFIER_MODEL

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set.")
        _client = Anthropic(api_key=api_key)
    return _client


# Deliberately narrow keyword list -- a supplier's justification only counts
# as "checkable" if it references something with a real, findable public
# market signal. This is intentionally conservative: better to skip a
# genuinely verifiable claim occasionally than to trigger a search call on
# vague text like "increased costs" that no search could meaningfully verify
# anyway, which would just spend money for no real benefit.
_CHECKABLE_MARKET_TERMS = [
    "steel", "nitrile", "aluminum", "aluminium", "copper", "resin", "plastic",
    "crude oil", "oil price", "freight", "shipping rate", "energy cost",
    "natural gas", "labour cost", "labor cost", "inflation", "wage",
    "raw material", "commodity", "commodities", "lumber", "timber",
]


def is_claim_checkable(stated_justification: str) -> bool:
    """
    Deterministic, free, zero-API-cost check: does this justification even
    mention something worth spending a real search call on? This is plain
    Python string matching, not an LLM call -- keeping the expensive step
    (the actual search) gated behind a free filter.
    """
    if not stated_justification:
        return False
    text = stated_justification.lower()
    return any(term in text for term in _CHECKABLE_MARKET_TERMS)


def verify_market_claim(stated_justification: str, region: str | None = None) -> dict | None:
    """
    Makes ONE targeted, real web search call to check a supplier's stated
    market justification against current, real information. Returns None
    (not an exception) on any failure -- this must NEVER block the main
    reasoning flow; a failed verification just means the answer proceeds
    without it, exactly like financial_impact being None when not
    computable.

    Returns a dict: {"claim_checked": str, "finding": str, "verified_note": str,
    "scope": str} or None if verification wasn't possible for any reason.

    Real, identified gap this `region` parameter fixes: without it, every
    verification checked the claim against GENERAL/GLOBAL data, even when
    a supplier's real cost base is genuinely regional -- meaning a claim
    that's actually accurate for their real region could look "overstated"
    against a global average, producing a confidently wrong verification.
    When `region` is given (captured passively from the user's own text,
    never asked for), the search itself is targeted at that region, not
    global figures. `scope` in the return value states plainly which one
    actually happened -- set deterministically in code below, not left to
    the model's own prose, so the frontend can always show the true answer.
    """
    if not is_claim_checkable(stated_justification):
        return None

    if region and region.strip():
        region_instruction = (
            f"Check this specifically against market data FOR {region.strip()} -- "
            f"not a global average. If genuine, reliable region-specific data isn't "
            f"available, say so explicitly in verified_note rather than silently "
            f"substituting a global figure."
        )
        scope_label = region.strip()
    else:
        region_instruction = (
            "No specific region was given for this case -- check against "
            "general/global market data."
        )
        scope_label = "global"

    try:
        client = _get_client()
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=600,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{
                "role": "user",
                "content": (
                    f"A supplier has justified a price increase by citing: \"{stated_justification}\". "
                    f"{region_instruction} "
                    f"Use web search to check current, real information about whether this specific market "
                    f"claim is accurate right now. Respond with ONLY a JSON object, no other text: "
                    f'{{"claim_checked": "the specific claim being checked", '
                    f'"finding": "supported | contradicted | inconclusive", '
                    f'"verified_note": "one or two sentences on what the search actually found, '
                    f'in plain language, citing roughly what the search showed, and explicitly noting '
                    f'if genuine regional data was unavailable and a global figure was used instead"}}'
                ),
            }],
        )

        # Server-side tools (like web_search) can return multiple content
        # blocks (search results, then the model's final text). We want the
        # LAST text block, which is the model's synthesized answer after
        # having seen the search results -- not an intermediate block.
        text_blocks = [b for b in response.content if getattr(b, "type", None) == "text"]
        if not text_blocks:
            return None
        raw_text = text_blocks[-1].text.strip()

        # Reuse the same robust JSON extraction already proven earlier today,
        # since a tool-use response is at least as likely to include
        # surrounding prose as the plain classification/reasoning calls were.
        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not json_match:
            return None
        result = json.loads(json_match.group(0))

        if not all(k in result for k in ("claim_checked", "finding", "verified_note")):
            return None
        # Deterministic, code-set -- not left to the model to self-report,
        # same "guarantee, don't just ask nicely" pattern used throughout.
        result["scope"] = scope_label
        return result

    except Exception as e:
        # Deliberately swallow every error here -- a failed live search must
        # never take down the main answer. Printed for our own visibility
        # (same pattern as every other error-logging in this codebase),
        # never surfaced to the end user as a failure.
        print(f"Market verification skipped (non-blocking): {type(e).__name__}: {e}")
        return None
