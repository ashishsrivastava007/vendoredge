import time
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

from app.routes.decisions import router as decisions_router
from app.seed import ensure_demo_org_exists, run_migrations
from app.auth import require_session, verify_membership, _secret
from app.database import close_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Authentication is mandatory for protected API routes. Fail fast rather
    # than creating workspaces that cannot receive a signed session.
    _secret()

    # Applies any small, safe schema catch-up changes first, so an existing
    # database (from an earlier build, before some column existed) stays in
    # sync automatically -- no manual "docker compose down -v" reset needed
    # every time the code changes going forward.
    try:
        run_migrations()
    except Exception as e:
        # A database schema failure is not a recoverable application state.
        # Starting anyway creates the most dangerous failure mode: a healthy-
        # looking API backed by an unknown/outdated schema. Fail fast so the
        # hosting platform restarts/reports the service instead.
        print(f"FATAL: migrations failed; refusing to start against an unknown schema ({e})")
        raise RuntimeError("Database migration failed; application startup aborted.") from e

    # Creates a default demo org/user automatically, so the frontend works
    # the moment you run it, with no manual database setup.
    # Retries with backoff -- a real defense-in-depth layer alongside the
    # docker-compose healthcheck, since even a "ready" database can briefly
    # refuse a connection during its own final startup moment. Without this,
    # a single failed attempt here used to mean the demo account silently
    # never got created, and every single request afterward would crash.
    for attempt in range(1, 6):
        try:
            ensure_demo_org_exists()
            break
        except Exception as e:
            print(f"Demo org setup attempt {attempt}/5 failed ({e}); retrying...")
            time.sleep(2)
    else:
        print(
            "WARNING: could not set up the demo organisation after 5 attempts. "
            "The app will start, but every request will fail until this is resolved -- "
            "check that the database is reachable at the configured DATABASE_URL."
        )
    try:
        yield
    finally:
        close_pool()


app = FastAPI(title="VendorEdge MVP", version="0.1.0", lifespan=lifespan)
app.include_router(decisions_router)


@app.middleware("http")
async def tenant_auth_middleware(request: Request, call_next):
    """Enforce the signed workspace session at the API trust boundary.

    The browser may still send x-org-id/x-user-id for backwards-compatible
    frontend plumbing, but those values are never authoritative: require_session
    validates the signed bearer token and rejects any mismatch. Workspace creation
    is the only unauthenticated API operation because it creates the identity.
    """
    path = request.url.path
    if path.startswith("/api/v1/") and not (
        path == "/api/v1/workspaces" and request.method.upper() == "POST"
        or path == "/api/v1/workspaces/legacy-session" and request.method.upper() == "POST"
        or path == "/api/v1/workspaces/accept-invite" and request.method.upper() == "POST"
    ):
        try:
            claims = require_session(request)
            verify_membership(claims["org_id"], claims["sub"])
            request.state.organisation_id = claims["org_id"]
            request.state.user_id = claims["sub"]
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Apply baseline browser security headers to every response.

    VendorEdge currently uses inline UI JavaScript/styles, so the CSP keeps
    those narrowly scoped to the same document while still blocking remote
    script injection, framing, plugin content and unexpected form targets.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return response


@app.middleware("http")
async def no_cache_html_middleware(request: Request, call_next):
    """
    Real, permanent fix for a genuine production incident: with no
    cache-control headers at all, a visitor's browser was free to cache the
    main page indefinitely using its own default heuristics -- meaning a
    real redeploy on the server could still leave real users stuck on an
    old, buggy version of the page, since their browser might never even
    ask the server for a newer one. This forces every HTML page load to
    always fetch fresh from the server, every time -- static assets like
    images could still cache safely, but the page itself never should,
    given how frequently this project is actively being updated.
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/v1/"):
        # Commercial cases can contain confidential pricing, supplier terms
        # and stakeholder information. Never allow an intermediary/browser
        # cache to retain an API response.
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    if path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


@app.exception_handler(Exception)
async def catch_all_exception_handler(request: Request, exc: Exception):
    """
    The systemic safety net: without this, ANY unhandled error anywhere in
    the app falls through to a generic plain-text 'Internal Server Error'
    page that breaks the frontend's JSON parsing. Full detail is always
    logged here, privately, for real debugging -- but what's RETURNED to
    the caller is now a calm, generic message, not the raw exception text.
    This was a genuine pre-pilot finding: showing a real external user a raw
    Python exception string mid-demo is unprofessional and was fine only
    during our own internal debugging, never for a real pilot user.
    """
    full_trace = traceback.format_exc()
    print(f"\n===== UNHANDLED ERROR on {request.url.path} =====\n{full_trace}=====\n")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Something went wrong on our end. Please try again in a moment. "
                      "If this keeps happening, let us know what you asked."
        },
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/validation")
def validation_page():
    """
    The simple, non-technical validation page -- explicit route so the
    exact URL the user is told to visit always works, rather than relying
    on StaticFiles' html-mode extension-guessing behavior.
    """
    from fastapi.responses import FileResponse
    return FileResponse("app/static/validation.html")


# Serves the actual clickable screen at http://localhost:8000/
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
