import os
import pytest
from fastapi import HTTPException
from starlette.requests import Request

os.environ["VENDOREDGE_AUTH_SECRET"] = "unit-test-secret-that-is-longer-than-32-chars"

from app.auth import create_session_token, verify_session_token, require_session


def make_request(headers):
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {"type": "http", "method": "GET", "path": "/api/v1/test", "headers": raw}
    return Request(scope)


def test_signed_token_contains_server_issued_identity():
    token = create_session_token("org-a", "user-a")
    claims = verify_session_token(token)
    assert claims["org_id"] == "org-a"
    assert claims["sub"] == "user-a"
    assert claims["typ"] == "workspace_session"


def test_tampered_token_is_rejected():
    token = create_session_token("org-a", "user-a")
    with pytest.raises(HTTPException) as exc:
        verify_session_token(token + "x")
    assert exc.value.status_code == 401


def test_bearer_token_is_authoritative_over_headers(monkeypatch):
    token = create_session_token("org-a", "user-a")
    request = make_request({
        "authorization": f"Bearer {token}",
        "x-org-id": "org-b",
        "x-user-id": "user-a",
    })
    with pytest.raises(HTTPException) as exc:
        require_session(request)
    assert exc.value.status_code == 403


def test_matching_compatibility_headers_are_allowed():
    token = create_session_token("org-a", "user-a")
    request = make_request({
        "authorization": f"Bearer {token}",
        "x-org-id": "org-a",
        "x-user-id": "user-a",
    })
    claims = require_session(request)
    assert claims["org_id"] == "org-a"
    assert claims["sub"] == "user-a"
