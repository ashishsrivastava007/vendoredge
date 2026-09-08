from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / 'app' / 'static' / 'index.html'


def _block(text):
    start = text.index('function renderCommercialWorkspace(cases)')
    end = text.index('async function loadCommercialWorkspace()', start)
    return text[start:end]


def test_r403_does_not_show_zero_stats_for_a_brand_new_workspace():
    s = HTML.read_text()
    block = _block(s)
    assert 'if (!all.length)' in block
    assert 'Start with a real commercial question' in block
    assert 'CASES THIS YEAR' in block
    assert 'Your real activity will appear here after your first case.' in block


def test_r403_keeps_real_stats_when_activity_exists():
    s = HTML.read_text()
    block = _block(s)
    assert '${thisYear.length}' in block
    assert '${completed.length}' in block
    assert '${open.length}' in block


def test_r403_empty_state_uses_real_entrypoints_not_fake_activity():
    s = HTML.read_text()
    block = _block(s)
    assert "startPrompt('Supplier request')" in block
    assert "startPrompt('Something I noticed')" in block
    assert "startPrompt('Category / strategy question')" in block
    assert 'real activity will appear here' in block
