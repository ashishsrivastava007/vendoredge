from pathlib import Path
import re

HTML = Path(__file__).resolve().parents[1].joinpath("app/static/index.html").read_text()
ROUTES = Path(__file__).resolve().parents[1].joinpath("app/routes/decisions.py").read_text()


def test_bootstrap_has_hard_timeout_and_bounded_retry():
    assert "BOOTSTRAP_REQUEST_TIMEOUT_MS = 15000" in HTML
    assert "BOOTSTRAP_MAX_ATTEMPTS = 2" in HTML
    assert "new AbortController()" in HTML
    assert "setTimeout(() => controller.abort(), timeoutMs)" in HTML
    assert "for (let attempt = 1; attempt <= BOOTSTRAP_MAX_ATTEMPTS; attempt++)" in HTML


def test_bootstrap_retry_is_cancelable_and_restarts_cleanly():
    start = HTML.index("async function ensureWorkspace")
    chunk = HTML[start:start + 3600]
    assert "workspaceBootstrapController.abort()" in chunk
    assert "const controller = new AbortController()" in chunk
    assert "HEADERS = null" in chunk
    assert "workspaceInitError = null" in chunk
    assert "const initRun = (async () =>" in chunk


def test_new_workspace_creation_is_idempotent_across_browser_retries():
    assert 'X-Workspace-Bootstrap-Key' in HTML
    assert 'getOrCreateWorkspaceBootstrapKey()' in HTML
    assert 'alias="X-Workspace-Bootstrap-Key"' in ROUTES
    assert 'uuid5(NAMESPACE_URL, f"vendoredge-workspace:{idempotency_key}")' in ROUTES
    assert 'uuid5(NAMESPACE_URL, f"vendoredge-user:{idempotency_key}")' in ROUTES
    assert 'ON CONFLICT (id) DO NOTHING' in ROUTES


def test_workspace_validation_is_part_of_bootstrap_before_app_unlocks():
    start = HTML.index("async function bootstrapWorkspaceOnce")
    chunk = HTML[start:start + 7000]
    assert 'fetchWithTimeout(`${API}/workspaces/me`' in chunk
    assert 'ageRes.status === 401 || ageRes.status === 403 || ageRes.status === 404' in chunk
    assert 'HEADERS = nextHeaders;' in chunk
    assert chunk.index('const ageRes = await fetchWithTimeout') < chunk.index('HEADERS = nextHeaders;')


def test_failed_bootstrap_has_real_retry_control_and_clear_states():
    assert 'setWorkspaceBootstrapMode("failed")' in HTML
    assert 'Could not start your private workspace.' in HTML
    assert 'onclick="retryWorkspaceBootstrap()"' in HTML
    assert 'workspace-bootstrap-failed' in HTML


def test_generic_authenticated_api_boundary_remains_in_place():
    script = HTML[HTML.index("<script>"):HTML.rindex("</script>")]
    raw_calls = [line.strip() for line in script.splitlines() if "fetchWithTimeout(`${API}/" in line]
    joined = "\n".join(raw_calls)
    assert "/workspaces/accept-invite" in joined
    assert "/workspaces/legacy-session" in joined
    assert "${API}/workspaces`" in joined
    assert "/workspaces/me" in joined
    assert "${API}/commercial-decisions" not in joined
    assert "${API}/ingest-file" not in joined
    assert "${API}/organisation-formats" not in joined


def test_start_fresh_workspace_clears_persistent_bootstrap_identity():
    start = HTML.index("function startFreshWorkspace")
    chunk = HTML[start:start + 700]
    assert "localStorage.removeItem(SESSION_STORAGE_KEY)" in chunk
    assert "localStorage.removeItem(WORKSPACE_BOOTSTRAP_KEY)" in chunk
    assert "workspaceBootstrapController.abort()" in chunk
    assert "workspaceInitPromise = null" in chunk
