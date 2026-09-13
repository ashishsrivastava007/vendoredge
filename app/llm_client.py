"""
app/llm_client.py -- Provider-independent LLM client abstraction.

Context (confirmed by the R41 Foundation Freeze audit): VendorEdge's
actual procurement intelligence -- the Commercial Intelligence Kernel,
evidence-state model, financial/scenario calculations, decision-audit
contradiction detection, category diagnosis, supplier-strategy
classification, market/ESG reasoning chains, and dependency-aware
roadmap logic -- has ZERO references to any model provider's SDK or
response format anywhere. That was true before this module existed and
remains true after it; this module changes nothing about that layer.

What WAS genuinely coupled: four files (reasoner.py, classifier.py,
market_verification.py, model_orchestration.py) each directly
constructed `anthropic.Anthropic(...)` and called `.messages.create(
...)`. This module is the thin seam between them and whichever
provider actually answers the call.

Design choice, deliberately conservative: rather than inventing a new
call signature and rewriting every call site's request/response
handling, this defines a factory that returns an object matching the
EXACT shape those four files already code against --
`.messages.create(model=..., max_tokens=..., system=..., messages=
[...])` returning an object with `.content` (a list of blocks with
`.type`/`.text`), `.usage.input_tokens`/`.output_tokens`, and
`.stop_reason`. That shape is not Anthropic-specific Python -- it's
just a shape -- so a correctly-written adapter for any other provider
can return an object satisfying it, and every downstream line in the
four callers (response parsing via the already-shared _extract_text()
helper in classifier.py, token-usage tracking, stop_reason checks)
needs zero changes.

Proven today with the Anthropic provider: _build_anthropic_provider
returns the real anthropic.Anthropic client unmodified -- a pure
pass-through -- so today's behavior is byte-for-byte identical to
before this module existed, just routed through one factory function
instead of four separate direct constructions.

To add a future provider (OpenAI, Gemini, a local model):
1. Write an adapter class exposing `.messages.create(model, max_tokens,
   system, messages) -> response` where response has `.content` (list
   of objects with `.type == "text"` and `.text`), `.usage.
   input_tokens`/`.output_tokens`, and `.stop_reason`.
2. Register it in _PROVIDERS below.
3. Set VENDOREDGE_LLM_PROVIDER to select it.
No change to reasoner.py/classifier.py/market_verification.py/
model_orchestration.py's calling code, prompt construction, or
response parsing is required -- only the single client-construction
line in each (already isolated behind a `_get_client()` function in
every one of them) changes, and only to call get_llm_client() instead
of constructing a provider SDK client directly.
"""
from __future__ import annotations
import os
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMMessagesAPI(Protocol):
    def create(self, *, model: str, max_tokens: int, system: str, messages: list[dict]) -> Any: ...


class LLMProvider(Protocol):
    """A provider exposes a `.messages` object with a `.create(...)`
    method matching the shape above -- mirroring the Anthropic SDK's
    own client shape deliberately, since that is the interface every
    one of VendorEdge's four I/O files already codes against, not
    because VendorEdge depends on Anthropic specifically."""
    messages: LLMMessagesAPI


def _build_anthropic_provider(api_key: str, timeout: float) -> LLMProvider:
    from anthropic import Anthropic
    return Anthropic(api_key=api_key, timeout=timeout)


# Registered providers. Each entry must return an object satisfying
# LLMProvider -- a real SDK client (as Anthropic's does today) or a
# hand-written adapter wrapping a different provider's SDK so its
# response shape matches what the four calling files expect.
_PROVIDERS = {
    "anthropic": _build_anthropic_provider,
}

_client_cache: dict[str, LLMProvider] = {}


def get_llm_client(api_key: str, timeout: float) -> LLMProvider:
    """Single factory every I/O boundary file calls instead of
    constructing a provider SDK client directly. Defaults to
    "anthropic"; VENDOREDGE_LLM_PROVIDER selects a different
    registered provider without any change to calling code. Cached
    per (provider, api_key) pair, matching each caller's existing
    module-level singleton pattern."""
    provider_name = os.environ.get("VENDOREDGE_LLM_PROVIDER", "anthropic")
    if provider_name not in _PROVIDERS:
        raise RuntimeError(
            f"Unknown VENDOREDGE_LLM_PROVIDER: {provider_name!r}. "
            f"Registered providers: {sorted(_PROVIDERS)}."
        )
    cache_key = f"{provider_name}:{(api_key or '')[:12]}"
    if cache_key not in _client_cache:
        _client_cache[cache_key] = _PROVIDERS[provider_name](api_key, timeout)
    return _client_cache[cache_key]
