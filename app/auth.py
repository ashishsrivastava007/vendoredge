"""VendorEdge pilot authentication and tenant-bound session tokens.

This is intentionally small for the current private-link pilot.  The browser
receives a signed JWT whose org_id/user_id claims are created by the server.
Protected API requests must present that token; request-supplied org/user
headers are accepted only as compatibility metadata and must exactly match the
verified token claims.

This is a transitional authentication layer, not the final enterprise SSO
implementation.  It removes the critical trust-boundary flaw where a browser
could simply invent another organisation ID.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import HTTPException, Request


ALGORITHM = "HS256"
TOKEN_TYPE = "workspace_session"
DEFAULT_TTL_DAYS = 30


def _secret() -> str:
    secret = os.environ.get("VENDOREDGE_AUTH_SECRET")
    if not secret or len(secret) < 32:
        raise RuntimeError(
            "VENDOREDGE_AUTH_SECRET must be set to a random value of at least 32 characters."
        )
    return secret


def create_session_token(organisation_id: str, user_id: str, *, ttl_days: int = DEFAULT_TTL_DAYS) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "org_id": str(organisation_id),
        "typ": TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(days=ttl_days),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def verify_session_token(token: str) -> dict:
    try:
        claims = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Your workspace session has expired. Please reopen your workspace link.")
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(status_code=401, detail="Your workspace session is invalid. Please reopen your workspace link.")

    if claims.get("typ") != TOKEN_TYPE or not claims.get("sub") or not claims.get("org_id"):
        raise HTTPException(status_code=401, detail="Invalid VendorEdge session.")
    return claims


def bearer_token(request: Request) -> Optional[str]:
    value = request.headers.get("authorization", "")
    if not value.lower().startswith("bearer "):
        return None
    token = value[7:].strip()
    return token or None


def require_session(request: Request) -> dict:
    token = bearer_token(request)
    if not token:
        # Temporary migration/test compatibility only. Production must leave
        # this disabled. Even here, the user must genuinely belong to the
        # claimed organisation; the old headers are no longer blindly trusted.
        if os.environ.get("ALLOW_LEGACY_WORKSPACE_LINKS", "false").lower() == "true":
            org_id = request.headers.get("x-org-id")
            user_id = request.headers.get("x-user-id")
            if org_id and user_id:
                from app.database import get_org_scoped_connection
                with get_org_scoped_connection(org_id) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT 1 FROM users WHERE id = %s AND organisation_id = %s",
                            (user_id, org_id),
                        )
                        if cur.fetchone():
                            return {"org_id": org_id, "sub": user_id, "typ": "legacy_workspace_session"}
        raise HTTPException(status_code=401, detail="Authentication required.")
    claims = verify_session_token(token)

    # Compatibility headers are not trusted. If present, they must agree with
    # the signed claims. This prevents a caller from combining a valid token
    # for Org A with a forged x-org-id for Org B.
    supplied_org = request.headers.get("x-org-id")
    supplied_user = request.headers.get("x-user-id")
    if supplied_org and supplied_org != claims["org_id"]:
        raise HTTPException(status_code=403, detail="Workspace access denied.")
    if supplied_user and supplied_user != claims["sub"]:
        raise HTTPException(status_code=403, detail="User access denied.")

    return claims


def verify_membership(organisation_id: str, user_id: str) -> None:
    """Verify that the signed identity still exists inside its organisation.

    Tokens are bearer credentials, but organisation membership remains a live
    database fact. Checking it on protected requests means deleting or moving
    a user invalidates access without waiting for token expiry.
    """
    from app.database import get_org_scoped_connection
    with get_org_scoped_connection(organisation_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM users WHERE id = %s AND organisation_id = %s",
                (user_id, organisation_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=403, detail="Workspace access denied.")
