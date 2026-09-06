from pathlib import Path

HTML = Path(__file__).resolve().parents[1].joinpath("app/static/index.html").read_text()


def test_workspace_bootstrap_blocks_ui_race():
    assert '<body class="workspace-initializing">' in HTML
    assert 'id="workspace-bootstrap"' in HTML
    assert "pointer-events: none" in HTML
    assert "let workspaceInitPromise = null;" in HTML


def test_primary_actions_wait_for_workspace_before_authenticated_fetch():
    for fn in ("askQuestion", "goToCases", "openCase", "retryCase", "submitEvidence", "handleFileUpload"):
        marker = f"async function {fn}"
        start = HTML.index(marker)
        chunk = HTML[start:start + 800]
        assert "waitForWorkspaceReady()" in chunk, fn


def test_workspace_failure_is_user_visible_not_requestinit_typeerror():
    assert "Could not start your private workspace." in HTML
    assert "workspaceInitError = e;" in HTML
    assert "workspaceInitPromise = ensureWorkspace();" in HTML
