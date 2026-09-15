"""
Proves the research/search tool abstraction (app/research_tool.py) is
genuinely swappable -- market_verification.py's verify_market_claim()
runs correctly against a fake research-tool provider with no Anthropic
import and no real API key, and source/provenance/freshness/evidence
handling (the sources list, the finding classification, the region
scope label) all survive unchanged when the underlying tool mechanism
is swapped out.
"""
import os
import app.research_tool as research_tool
from app.pipeline import market_verification as mv


class _FakeResearchTool:
    """A research-tool provider satisfying ResearchToolProvider's
    interface with zero Anthropic dependency -- proves the interface
    itself, not just the default Anthropic adapter, is what
    verify_market_claim() actually depends on."""
    def __init__(self, canned_text):
        self._canned_text = canned_text
        self.calls = []

    def search(self, prompt, *, model, max_tokens):
        self.calls.append({"prompt": prompt, "model": model, "max_tokens": max_tokens})
        return self._canned_text


def test_get_research_tool_returns_the_registered_provider_no_anthropic_needed():
    fake = _FakeResearchTool('{"ok": true}')
    research_tool._PROVIDERS["fake_test_research_provider"] = lambda: fake
    os.environ["VENDOREDGE_RESEARCH_TOOL_PROVIDER"] = "fake_test_research_provider"
    research_tool._tool_cache.clear()
    try:
        tool = research_tool.get_research_tool()
        assert tool is fake
    finally:
        research_tool._PROVIDERS.pop("fake_test_research_provider", None)
        os.environ.pop("VENDOREDGE_RESEARCH_TOOL_PROVIDER", None)
        research_tool._tool_cache.clear()


def test_unknown_research_provider_raises_clearly():
    os.environ["VENDOREDGE_RESEARCH_TOOL_PROVIDER"] = "not_a_registered_research_provider"
    research_tool._tool_cache.clear()
    try:
        try:
            research_tool.get_research_tool()
            assert False, "expected RuntimeError for an unregistered provider"
        except RuntimeError as e:
            assert "not_a_registered_research_provider" in str(e)
    finally:
        os.environ.pop("VENDOREDGE_RESEARCH_TOOL_PROVIDER", None)
        research_tool._tool_cache.clear()


def test_verify_market_claim_works_against_a_fake_tool_zero_anthropic_dependency(monkeypatch):
    """The concrete proof requested: the real, unmodified
    verify_market_claim() -- prompt construction, JSON parsing, source
    cleaning, scope labeling -- runs correctly against a fake tool
    provider that never imports or touches the Anthropic SDK."""
    fake = _FakeResearchTool(
        '{"claim_checked": "steel prices", "finding": "supported", '
        '"verified_note": "Current data supports this claim for the stated region.", '
        '"sources": [{"title": "Steel Price Index", "url": "https://example.com/steel"}]}'
    )
    monkeypatch.setattr(mv, "get_research_tool", lambda: fake)
    result = mv.verify_market_claim("steel prices have increased significantly", region="Germany")

    assert result is not None
    assert result["finding"] == "supported"
    # Source/provenance handling preserved: well-formed sources kept, capped, cleaned.
    assert result["sources"] == [{"title": "Steel Price Index", "url": "https://example.com/steel"}]
    # Freshness/scope handling preserved: region passed through to the
    # deterministic scope label, not left to the model to self-report.
    assert result["scope"] == "Germany"
    assert len(fake.calls) == 1
    assert "Germany" in fake.calls[0]["prompt"]
    assert "steel prices have increased significantly" in fake.calls[0]["prompt"]


def test_verify_market_claim_evidence_gate_unaffected_by_tool_swap(monkeypatch):
    """The is_claim_checkable() gate -- deterministic, zero-API-cost --
    must still block a non-checkable claim before any tool is called
    at all, regardless of which research-tool provider is registered."""
    fake = _FakeResearchTool('{"claim_checked": "x", "finding": "supported", "verified_note": "y"}')
    monkeypatch.setattr(mv, "get_research_tool", lambda: fake)
    result = mv.verify_market_claim("we just decided to raise prices", region=None)
    assert result is None
    assert fake.calls == []


def test_malformed_tool_response_still_fails_safe():
    """Source/evidence integrity: a research-tool response that isn't
    valid JSON, or is missing required fields, must still return None
    rather than a partially-trusted result -- unchanged by the
    abstraction."""
    import app.pipeline.market_verification as mv2
    fake_bad = _FakeResearchTool("not json at all")
    import unittest.mock
    with unittest.mock.patch.object(mv2, "get_research_tool", return_value=fake_bad):
        assert mv2.verify_market_claim("steel prices increased") is None

    fake_incomplete = _FakeResearchTool('{"claim_checked": "steel"}')
    with unittest.mock.patch.object(mv2, "get_research_tool", return_value=fake_incomplete):
        assert mv2.verify_market_claim("steel prices increased") is None
