from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "app" / "static" / "index.html"


def test_r40_has_daily_commercial_workbench_front_door():
    s = HTML.read_text()
    assert 'id="home-screen"' in s
    assert "COMMERCIAL WORKBENCH" in s
    assert "Supplier request" in s
    assert "Something I noticed" in s
    assert "Category / strategy question" in s


def test_r40_has_single_workspace_loader_and_authenticated_case_fetch():
    s = HTML.read_text()
    assert "async function loadCommercialWorkspace()" in s
    start = s.index("async function loadCommercialWorkspace()")
    end = s.index("async function goToCases()", start)
    block = s[start:end]
    assert "authenticatedFetch(`${API}/commercial-decisions`" in block
    assert "renderCommercialWorkspace(cases)" in block
    assert "show(\"home-screen\")" in block


def test_r40_bootstrap_opens_workbench_after_resume_check():
    s = HTML.read_text()
    start = s.rindex("(async function initializeApp()")
    block = s[start:s.index("</script>", start)]
    assert "const resumed = await tryResumeLastCase();" in block
    assert "if (!resumed) await loadCommercialWorkspace();" in block
    assert "renderNudgeBanner();" not in block


def test_r40_proactive_entrypoints_are_real_case_prompts_not_fake_predictions():
    s = HTML.read_text()
    assert "I noticed a commercial pattern or change in our business." in s
    assert "I am reviewing a category or commercial strategy." in s
    assert "decisions I should investigate next" in s
    assert "This is activity you captured, not a forecast." in s


def test_r40_attention_panel_only_uses_actionable_open_statuses():
    s = HTML.read_text()
    start = s.index("function renderCommercialWorkspace(cases)")
    end = s.index("async function loadCommercialWorkspace()", start)
    block = s[start:end]
    assert '["awaiting_user_input","provider_unavailable","reasoning","classifying"]' in block
    assert 'c.status !== "completed" && c.status !== "cancelled"' in block
    assert 'completed cases as "needing attention"' in block
