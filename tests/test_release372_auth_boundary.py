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


def test_only_bootstrap_endpoints_and_age_check_use_raw_api_fetch():
    raw_api_fetches = re.findall(r"(?<!authenticated)fetch\(`\\?\$\{API\}([^`]+)", _script_only())
    assert set(raw_api_fetches) == {
        "/workspaces/accept-invite",
        "/workspaces/legacy-session",
        "/workspaces",
        "/workspaces/me",
    }


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
    assert "workspaceInitPromise = ensureWorkspace();" in HTML
    assert "HEADERS = sessionHeaders(session.token, session.org, session.user);" in HTML
    assert "authenticatedFetch(`${API}/workspaces/accept-invite" not in HTML
    assert "authenticatedFetch(`${API}/workspaces/legacy-session" not in HTML
    assert "authenticatedFetch(`${API}/workspaces`" not in HTML
