"""
Shared pytest fixture for the market_signal_intelligence test files.

M1.5.1 added an independent verification call (verify_proposition_
claims) inside classify_evidence() and synthesize_and_translate(),
using the same _get_client() as the main extraction calls. Tests that
call classify_evidence()/synthesize_and_translate() directly, without
mocking _get_client() themselves (because before M1.5.1 those
functions never made any LLM call at all), would otherwise hit a real
401 against the placeholder API key and fail closed to UNKNOWN/
rejected -- not a bug in the fix itself, but a fixture gap this
autouse fixture closes globally for this test module only.

Individual tests that DO mock _get_client() themselves (typically the
full-pipeline HTTP tests, which mock call-sequencing precisely) are
unaffected: their own `with patch(...)` block takes precedence over
this outer, module-scoped one for its duration.
"""
import json
from unittest.mock import patch, MagicMock
import pytest


def _mk_verifier_response(text):
    resp = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp.content = [block]
    return resp


_SAFE_VERIFIER_JSON = json.dumps({"negates_claim": False, "asserts_causation": False, "asserts_entitlement": False, "is_self_report": False})


@pytest.fixture(autouse=True)
def _default_safe_verifier():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mk_verifier_response(_SAFE_VERIFIER_JSON)
    with patch("app.pipeline.market_signal_intelligence._get_client", return_value=fake_client):
        yield
