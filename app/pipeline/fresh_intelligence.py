"""
Fresh Decision Intelligence -- first vertical slice (R45).

Scope, deliberately narrow per explicit instruction: proves the concept
for exactly one case shape -- a price_increase case with real category
and supplier concentration data (the "Industrial Valves / Supplier A"
vertical), not a general-purpose market-monitoring system. No new
evidence model, no new reasoning chain: this module's entire job is to
turn one targeted, gated research call into MarketDriverClaim-shaped
data and hand it to market_intelligence.py's already-proven fact/claim/
inference/unknown/implication chain -- the exact same pipeline that
already handles claims the case itself stated, now also handling a
claim VendorEdge found on its own.

Cost control, explicit: should_research_fresh_intelligence() is a free,
deterministic gate (no API call) that only returns True for a case
genuinely shaped like the target vertical. research_fresh_market_
intelligence() makes exactly one research-tool call when that gate
passes, exactly like market_verification.py's own one-call-per-case
discipline. Default tests never trigger a live call -- every test here
uses a fake research-tool provider, matching the pattern already
established for market_verification.py and the LLM/tool abstractions.

Evidence discipline, unchanged from every other module in this
codebase: market moved -> category relevance -> supplier exposure ->
commercial implication, and only the parts genuinely supported by
evidence are ever concluded. A live search finding that steel prices
rose does not, by itself, become "Supplier A's request is justified" --
that conclusion requires a stated cost-share weight this claim will
essentially never have (research finds public market data, not a
specific supplier's confidential cost structure), and market_
intelligence.py's existing _explainable_portion() logic already refuses
to estimate one.
"""
from __future__ import annotations
import json
import re
from typing import Any

from app.research_tool import get_research_tool
from app.model_config import MARKET_MODEL


def should_research_fresh_intelligence(kernel: dict[str, Any]) -> bool:
    """Free, deterministic gate -- no API call. Only fires for the
    target vertical's shape: a price_increase case where the category
    has an identifiable subject/product context AND there's a real
    supplier with meaningful spend concentration already established
    (matching "Industrial Valves / Supplier A" -- a named category, a
    named supplier, a real requested change). A case with no category
    context, or no supplier spend data at all, has nothing concrete
    enough to research -- firing a search anyway would just be "search
    for anything," the exact behavior item 5/7 rule out."""
    case = kernel.get("case") or {}
    if case.get("content_type") != "price_increase":
        return False
    subject = case.get("subject")
    if not subject:
        return False
    facts = kernel.get("facts") or []
    has_supplier_spend = any(f.get("metric") == "annual_spend" and f.get("value") for f in facts)
    has_requested_change = any(f.get("metric") == "requested_change_percent" for f in facts)
    return bool(has_supplier_spend and has_requested_change)


def _parse_research_response(raw_text: str) -> list[dict[str, Any]]:
    """Defensive parsing, matching market_verification.py's discipline:
    a malformed or empty response is treated as "nothing found," never
    as a parse error that propagates. Expects a JSON array of driver
    objects; anything else (prose, a JSON object instead of an array,
    an empty array) safely resolves to no claims."""
    if not raw_text:
        return []
    match = re.search(r"\[.*\]", raw_text, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    claims = []
    for item in parsed:
        if not isinstance(item, dict) or not item.get("driver"):
            continue
        claims.append({
            "driver": str(item["driver"])[:80],
            "direction": item.get("direction"),
            "magnitude": item.get("magnitude"),
            "geography": item.get("geography"),
            "period": item.get("period"),
            "source": item.get("source"),
            "attributed_to": "external_research",
            "publication_or_retrieval_date": item.get("publication_or_retrieval_date"),
            "unit_or_currency": item.get("unit_or_currency"),
        })
    return claims


def research_fresh_market_intelligence(kernel: dict[str, Any]) -> list[dict[str, Any]]:
    """Makes ONE targeted research call for the case's category context,
    asking what has genuinely changed recently among plausible cost
    drivers (steel/alloy, energy, freight, FX, relevant supply
    disruption -- named as examples, not a checklist the model must
    fill in; "no relevant driver found" is a valid, expected answer).
    Returns [] on any failure or when nothing relevant was found --
    never raises, matching verify_market_claim()'s must-never-block
    discipline."""
    case = kernel.get("case") or {}
    subject = case.get("subject") or "this category"

    prompt = (
        f"A procurement team is evaluating a supplier price request in the category: \"{subject}\". "
        f"Using web search, identify only genuinely relevant recent (last few months) external market "
        f"developments that could plausibly affect the cost of this category -- for example steel/alloy "
        f"prices, energy costs, freight rates, relevant currency movements, or a specific supply "
        f"disruption, but ONLY if there is real, current evidence of relevance. Do not force a finding -- "
        f"if nothing genuinely relevant and current exists, return an empty array. "
        f"Respond with ONLY a JSON array, no other text, each item shaped as: "
        f'{{"driver": "e.g. steel", "direction": "increased|decreased|stable", "magnitude": "e.g. 8% or null", '
        f'"geography": "e.g. Europe or null", "period": "e.g. last 3 months", '
        f'"source": "the specific source name", "publication_or_retrieval_date": "e.g. 2026-08", '
        f'"unit_or_currency": "e.g. EUR/tonne or null"}}. '
        f"Return [] if nothing relevant and current was found -- do not invent a driver to fill the array."
    )

    try:
        tool = get_research_tool()
        raw_text = tool.search(prompt, model=MARKET_MODEL, max_tokens=800)
        return _parse_research_response(raw_text) if raw_text else []
    except Exception as e:
        # Never blocks the main reasoning flow -- same discipline as
        # market_verification.py's own error handling.
        print(f"Fresh market intelligence research skipped (non-blocking): {type(e).__name__}: {e}")
        return []


def build_fresh_intelligence_answer(kernel: dict[str, Any]) -> dict[str, Any] | None:
    """Buyer-facing Fresh Decision Intelligence answer: WHAT CHANGED ->
    WHAT IT MEANS FOR YOU -> WHAT IS PROVEN -> WHAT IS NOT PROVEN -> MY
    VIEW -> NEXT MOVE -> WHAT COULD CHANGE THIS. Built entirely by
    filtering market_intelligence.py's already-proven per-claim
    reasoning to claims this module itself found (attributed_to ==
    "external_research") -- no new reasoning logic, only composition of
    output that already went through the real evidence chain.

    Returns a structured "nothing material found" result, never a
    silently-omitted section and never an invented finding, when no
    externally-researched claims exist for this case (including when
    should_research_fresh_intelligence's gate never fired at all)."""
    from app.pipeline.market_intelligence import build_market_reasoning

    reasoning = build_market_reasoning(kernel)
    fresh_drivers = [d for d in (reasoning["drivers"] if reasoning else []) if d.get("attributed_to") == "external_research"]

    if not fresh_drivers:
        return {
            "available": False,
            "message": "No current external development identified that materially changes this decision.",
        }

    what_changed = [d["market_evidence"] for d in fresh_drivers]
    what_it_means_for_you = [d["decision_implication"] for d in fresh_drivers]
    what_is_not_proven = [d["unknown"] for d in fresh_drivers]
    # MY VIEW: one synthesized line, never claiming more than the
    # weakest link in the chain supports -- if not one driver has an
    # established supplier scope (the normal case for research
    # findings, since a live search finds public market data, not a
    # specific supplier's confidential cost structure), the honest
    # view is that this context doesn't yet change the recommendation.
    if any(d.get("applies_to_supplier") for d in fresh_drivers):
        my_view = "This external development has an established connection to the supplier in this case -- weigh it directly in the decision."
    else:
        my_view = "This external context is real, but it hasn't been tied to this specific supplier's cost -- it doesn't change the recommendation on its own."
    next_move = "If this driver plausibly affects the supplier's real cost base, ask for evidence connecting it to their specific position before treating it as justification."

    return {
        "available": True,
        "what_changed": what_changed[:4],
        "what_it_means_for_you": what_it_means_for_you[:4],
        "what_is_proven": what_changed[:4],
        "what_is_not_proven": what_is_not_proven[:4],
        "my_view": my_view,
        "next_move": next_move,
        "what_could_change_this": [
            "A stated cost-share weight connecting this driver to the supplier's actual pricing.",
            "The supplier's own confirmation or denial that this driver affects their cost base.",
        ],
    }
