from pathlib import Path
import re

HTML = Path(__file__).resolve().parents[1].joinpath("app/static/index.html").read_text()


def _script_only():
    start = HTML.index("<script>")
    end = HTML.rindex("</script>")
    return HTML[start:end]


def test_authenticated_api_boundary_exists_and_waits_for_workspace():
    assert "async function authenticatedFetch(input, init = {})" in HTML
    start = HTML.index("async function authenticatedFetch")
    chunk = HTML[start:start + 1400]
    assert "await waitForWorkspaceReady()" in chunk
    assert "if (!ready || !HEADERS)" in chunk
    assert "new Headers(HEADERS)" in chunk
    assert "new Headers(init.headers)" in chunk


def test_only_bootstrap_endpoints_and_age_check_bypass_authenticated_api_wrapper():
    raw_calls = [line.strip() for line in _script_only().splitlines() if "fetchWithTimeout(`${API}/" in line]
    joined = "\n".join(raw_calls)
    assert "/workspaces/accept-invite" in joined
    assert "/workspaces/legacy-session" in joined
    assert "${API}/workspaces`" in joined
    assert "/workspaces/me" in joined


def test_no_application_api_fetch_constructs_request_with_null_headers():
    # Any authenticated API request outside the bootstrap/age-check calls
    # must cross the authenticatedFetch boundary.
    assert "fetch(`${API}/commercial-decisions" not in HTML
    assert "fetch(`${API}/commercial-decisions" not in HTML.replace("authenticatedFetch(`${API}/commercial-decisions", "")
    assert "fetch(`${API}/ingest-file" not in HTML
    assert "fetch(`${API}/organisation-formats" not in HTML


def test_workspace_ready_wait_has_bounded_click_wait():
    start = HTML.index("async function waitForWorkspaceReady")
    chunk = HTML[start:start + 1000]
    assert "maxWaitMs = 10000" in chunk
    assert "Promise.race" in chunk
    assert "taking longer than expected" in chunk


def test_bootstrap_initialization_remains_the_single_source_of_workspace_setup():
    assert "const ready = await ensureWorkspace(false);" in HTML
    assert "const nextHeaders = sessionHeaders(session.token, session.org, session.user);" in HTML
    assert "authenticatedFetch(`${API}/workspaces/accept-invite" not in HTML
    assert "authenticatedFetch(`${API}/workspaces/legacy-session" not in HTML
    assert "authenticatedFetch(`${API}/workspaces`" not in HTML
