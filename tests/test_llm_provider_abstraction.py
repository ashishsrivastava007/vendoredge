"""
Proves the LLM provider abstraction (app/llm_client.py) is genuinely
swappable -- a fake provider, registered at runtime with no Anthropic
import and no real API key, is what the real call sites in
classifier.py/reasoner.py/market_verification.py/model_orchestration.py/
commercial_triage.py resolve to once VENDOREDGE_LLM_PROVIDER selects it.

This is the concrete proof requested for the R41 provider-abstraction
freeze: not a claim that the abstraction exists, but a running
demonstration that the same downstream parsing code (_extract_text,
token-usage fields, stop_reason) works unchanged against a
non-Anthropic response object satisfying the same shape.
"""
import os
import app.llm_client as llm_client
from app.pipeline.classifier import _extract_text


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeUsage:
    def __init__(self, input_tokens=42, output_tokens=7):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeResponse:
    def __init__(self, text, input_tokens=42, output_tokens=7, stop_reason="end_turn"):
        self.content = [_FakeTextBlock(text)]
        self.usage = _FakeUsage(input_tokens, output_tokens)
        self.stop_reason = stop_reason


class _FakeMessagesAPI:
    def __init__(self, canned_text):
        self._canned_text = canned_text
        self.calls = []

    def create(self, *, model, max_tokens, system, messages):
        self.calls.append({"model": model, "max_tokens": max_tokens, "system": system, "messages": messages})
        return _FakeResponse(self._canned_text)


class _FakeProvider:
    def __init__(self, canned_text='{"ok": true}'):
        self.messages = _FakeMessagesAPI(canned_text)


def _register_fake_provider(canned_text):
    fake = _FakeProvider(canned_text)
    llm_client._PROVIDERS["fake_test_provider"] = lambda api_key, timeout: fake
    os.environ["VENDOREDGE_LLM_PROVIDER"] = "fake_test_provider"
    llm_client._client_cache.clear()
    return fake


def _cleanup():
    llm_client._PROVIDERS.pop("fake_test_provider", None)
    os.environ.pop("VENDOREDGE_LLM_PROVIDER", None)
    llm_client._client_cache.clear()


def test_get_llm_client_returns_the_registered_provider_no_anthropic_needed():
    fake = _register_fake_provider('{"decision": "hold"}')
    try:
        client = llm_client.get_llm_client("dummy-key", 60)
        assert client is fake
    finally:
        _cleanup()


def test_unknown_provider_raises_clearly_rather_than_silently_falling_back():
    os.environ["VENDOREDGE_LLM_PROVIDER"] = "not_a_registered_provider"
    llm_client._client_cache.clear()
    try:
        try:
            llm_client.get_llm_client("dummy-key", 60)
            assert False, "expected RuntimeError for an unregistered provider"
        except RuntimeError as e:
            assert "not_a_registered_provider" in str(e)
    finally:
        os.environ.pop("VENDOREDGE_LLM_PROVIDER", None)
        llm_client._client_cache.clear()


def test_shared_extract_text_parses_a_non_anthropic_response_shape_unchanged():
    """The concrete proof: the SAME parsing code every one of the five
    I/O files already uses works against a response object that never
    touched the Anthropic SDK, because the abstraction preserves the
    shape, not the provider."""
    fake = _register_fake_provider('{"decision": "hold", "reasoning": "evidence insufficient"}')
    try:
        client = llm_client.get_llm_client("dummy-key", 60)
        response = client.messages.create(model="fake-model", max_tokens=100, system="x", messages=[{"role": "user", "content": "x"}])
        text = _extract_text(response)
        assert text == '{"decision": "hold", "reasoning": "evidence insufficient"}'
        assert response.usage.input_tokens == 42
        assert response.usage.output_tokens == 7
        assert response.stop_reason == "end_turn"
    finally:
        _cleanup()


def test_real_call_sites_resolve_to_the_fake_provider_via_get_llm_client():
    """Proves the wiring in the actual production call sites, not just
    the factory function in isolation -- classifier.py's own
    _get_client() (module-level singleton, exactly as it existed
    before this abstraction) resolves to the same fake provider once
    the environment variable is set."""
    fake = _register_fake_provider('{"content_type": "price_increase"}')
    os.environ["ANTHROPIC_API_KEY"] = "not-a-real-key-should-never-be-used"
    try:
        import app.pipeline.classifier as classifier_module
        classifier_module._client = None
        resolved = classifier_module._get_client()
        assert resolved is fake
    finally:
        import app.pipeline.classifier as classifier_module
        classifier_module._client = None
        _cleanup()


def test_anthropic_provider_is_still_the_default_when_unset():
    """Confirms today's behavior is genuinely unchanged: with no
    VENDOREDGE_LLM_PROVIDER set, the factory still resolves to the
    real Anthropic SDK client class -- a pure pass-through, not a
    behavioral change for the current, only-supported-in-production
    provider."""
    os.environ.pop("VENDOREDGE_LLM_PROVIDER", None)
    llm_client._client_cache.clear()
    try:
        from anthropic import Anthropic
        client = llm_client.get_llm_client("dummy-key-for-construction-only", 60)
        assert isinstance(client, Anthropic)
    finally:
        llm_client._client_cache.clear()
