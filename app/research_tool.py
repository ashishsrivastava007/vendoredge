"""
app/research_tool.py -- Provider-independent research/search tool
interface.

Companion to app/llm_client.py: that module abstracts which model
answers a completion; this one abstracts which mechanism performs a
live web search on VendorEdge's behalf. They are separate concerns --
a research tool call still needs an underlying LLM client to talk to a
provider, but the CALLER (market_verification.py, and any future
reasoning code that needs live research) should never need to know
whether the search itself is Anthropic's server-side web_search tool,
a client-orchestrated search-then-inject loop against a different
provider, or a fake test double.

Design, matching llm_client.py's approach: a Protocol with one method
-- `search(prompt, model, max_tokens) -> str | None`, returning the
provider's final synthesized text response (or None if the search
produced nothing usable) -- and a factory selecting the registered
adapter. Callers build their own prompt and parse the returned text
themselves (exactly as market_verification.py already did before this
abstraction existed); this interface only owns "how the search itself
gets executed," not prompt construction or response parsing, which
stay in the caller because they're specific to what's being verified,
not to the search mechanism.

Today's only adapter, AnthropicWebSearchTool, is a direct relocation of
the exact mechanics market_verification.py used to inline: the
`tools=[{"type": "web_search_20250305", ...}]` parameter, the
pause_turn continuation for long-running searches, and taking the LAST
text block (the model's synthesis after seeing search results, not an
intermediate block). Byte-for-byte the same behavior as before this
file existed -- confirmed by the test suite exercising both the old
inline path's logic and this adapter against a fake tool provider with
zero Anthropic dependency.

To add a future research-tool provider: implement a class exposing
`search(prompt, *, model, max_tokens) -> str | None`, register it in
_PROVIDERS below, and set VENDOREDGE_RESEARCH_TOOL_PROVIDER. No change
to market_verification.py or any other caller is required -- this is
the same "structural fix, not a new provider" scope as the LLM client
abstraction: still exactly one provider registered (Anthropic), no new
providers implemented in this pass.
"""
from __future__ import annotations
import os
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ResearchToolProvider(Protocol):
    def search(self, prompt: str, *, model: str, max_tokens: int) -> str | None: ...


class AnthropicWebSearchTool:
    """Adapter wrapping Anthropic's server-side web_search tool.
    Relocated, not rewritten, from market_verification.py's previous
    inline implementation -- same tools parameter, same pause_turn
    continuation, same last-text-block extraction."""

    def __init__(self, llm_client: Any):
        self._client = llm_client

    def search(self, prompt: str, *, model: str, max_tokens: int) -> str | None:
        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
        messages = [{"role": "user", "content": prompt}]
        response = self._client.messages.create(model=model, max_tokens=max_tokens, tools=tools, messages=messages)

        # Anthropic server-side tools can return pause_turn for a
        # long-running search. Continue the same turn once, preserving
        # the tool state, instead of silently treating a valid search
        # as a failure.
        if getattr(response, "stop_reason", None) == "pause_turn":
            continuation_messages = messages + [{"role": "assistant", "content": response.content}]
            response = self._client.messages.create(model=model, max_tokens=max_tokens, tools=tools, messages=continuation_messages)

        # Server-side tools (like web_search) can return multiple
        # content blocks (search results, then the model's final
        # text). We want the LAST text block -- the model's
        # synthesized answer after having seen the search results, not
        # an intermediate block.
        text_blocks = [b for b in response.content if getattr(b, "type", None) == "text"]
        if not text_blocks:
            return None
        return text_blocks[-1].text.strip()


def _build_anthropic_research_tool() -> ResearchToolProvider:
    from app.llm_client import get_llm_client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set.")
    timeout = 20 * 60
    client = get_llm_client(api_key, timeout)
    return AnthropicWebSearchTool(client)


# Registered research-tool providers. Only "anthropic" exists today --
# per explicit instruction, no new providers are implemented in this
# pass, only the seam for adding one later without touching any caller.
_PROVIDERS = {
    "anthropic": _build_anthropic_research_tool,
}

_tool_cache: dict[str, ResearchToolProvider] = {}


def get_research_tool() -> ResearchToolProvider:
    """Single factory every caller needing live research/search should
    use instead of constructing a provider-specific tool call
    directly. Defaults to "anthropic"; VENDOREDGE_RESEARCH_TOOL_PROVIDER
    selects a different registered provider without any change to
    calling code."""
    provider_name = os.environ.get("VENDOREDGE_RESEARCH_TOOL_PROVIDER", "anthropic")
    if provider_name not in _PROVIDERS:
        raise RuntimeError(
            f"Unknown VENDOREDGE_RESEARCH_TOOL_PROVIDER: {provider_name!r}. "
            f"Registered providers: {sorted(_PROVIDERS)}."
        )
    if provider_name not in _tool_cache:
        _tool_cache[provider_name] = _PROVIDERS[provider_name]()
    return _tool_cache[provider_name]
