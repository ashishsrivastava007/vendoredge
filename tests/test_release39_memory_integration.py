from pathlib import Path


def test_r39_memory_surface_is_present_once_and_primary_history_group_is_consolidated():
    html = Path('app/static/index.html').read_text()
    assert html.count('id="pos-commercial-memory"') == 1
    assert 'renderCommercialMemory(pos);' in html
    assert '["pos-commercial-memory", "pos-outcome-intelligence"]' in html


def test_r39_model_field_exists():
    source = Path('app/models.py').read_text()
    assert 'commercial_memory: Optional[dict[str, Any]] = None' in source


def test_r39_module_is_non_predictive():
    source = Path('app/pipeline/commercial_memory.py').read_text().lower()
    assert 'no prediction' in source
