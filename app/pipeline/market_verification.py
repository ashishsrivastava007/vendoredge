"""
Targeted live market-claim verification using a provider-independent
research/search tool interface (app/research_tool.py).

Deliberate design, matching the "near-zero cash cost" constraint: this is
NOT a live data subscription and does not run on every question. It makes
one small, targeted search call ONLY when a supplier's stated justification
in a price_increase question names something genuinely checkable (a
commodity, a market trend) -- turning a per-use, cents-level API call into
an honest, current, citable verification, instead of a recurring paid feed.

Tool abstraction note: this module used to construct an Anthropic client
and call `.messages.create(..., tools=[{"type": "web_search_20250305",
...}])` directly -- the one genuinely provider-specific capability in the
whole I/O boundary, since a live web search has no generic cross-provider
call shape the way a plain text completion does. That mechanism (the
tools parameter, the pause_turn continuation for long-running searches,
taking the last text block) has been relocated, unchanged, into
AnthropicWebSearchTool in app/research_tool.py -- this file now only
builds the verification prompt and calls get_research_tool().search(...),
never touching Anthropic-specific mechanics directly. A future research-
tool provider registers there, not here; this file's behavior is
unaffected either way.

HONESTY NOTE ON TEST COVERAGE, stated plainly rather than hidden: the
trigger logic (does this claim look checkable?), the failure-handling
(what happens if the search call errors), and this file's correct use of
the generic tool interface (proven against a fake research-tool provider
with zero Anthropic dependency) are all tested below without a live key.
The actual live web_search tool call itself has NOT been proven against
the real Anthropic API in this environment -- that is the one piece that
genuinely needs to be tested with a real key before being trusted in
front of real pilot users. This is flagged here on purpose, not
discovered later.
"""
import json
import re
from app.research_tool import get_research_tool
from app.model_config import MARKET_MODEL


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
        tool = get_research_tool()
        prompt = (
            f"A supplier has justified a price increase by citing: \"{stated_justification}\". "
            f"{region_instruction} "
            f"Use web search to check current, real information about whether this specific market "
            f"claim is accurate right now. Respond with ONLY a JSON object, no other text: "
            f'{{"claim_checked": "the specific claim being checked", '
            f'"finding": "supported | contradicted | inconclusive", '
            f'"verified_note": "one or two sentences on what the search actually found, '
            f'in plain language, citing roughly what the search showed, and explicitly noting '
            f'if genuine regional data was unavailable and a global figure was used instead", '
            f'"sources": [{{"title": "source name", "url": "https://..."}}]}}'
        )
        raw_text = tool.search(prompt, model=MARKET_MODEL, max_tokens=600)
        if raw_text is None:
            return None

        # Reuse the same robust JSON extraction already proven earlier today,
        # since a tool-use response is at least as likely to include
        # surrounding prose as the plain classification/reasoning calls were.
        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not json_match:
            return None
        result = json.loads(json_match.group(0))

        if not all(k in result for k in ("claim_checked", "finding", "verified_note")):
            return None
        if result.get("finding") not in {"supported", "contradicted", "inconclusive"}:
            return None
        # Sources are audit metadata, not a reason to trust the model's claim.
        # Keep only well-formed absolute URLs and source titles; if none were
        # returned, the market check still remains usable as contextual evidence
        # but the UI will explicitly show that source metadata was unavailable.
        cleaned_sources = []
        for src in result.get("sources") or []:
            if not isinstance(src, dict):
                continue
            title = str(src.get("title") or "").strip()
            url = str(src.get("url") or "").strip()
            if title and re.match(r"^https?://", url):
                cleaned_sources.append({"title": title[:180], "url": url[:500]})
        result["sources"] = cleaned_sources[:5]
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
