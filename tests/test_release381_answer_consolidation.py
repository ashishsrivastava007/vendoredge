from pathlib import Path


def _html() -> str:
    return Path(__file__).resolve().parents[1].joinpath("app/static/index.html").read_text()


def test_r381_legacy_decision_cockpit_is_suppressed_when_commercial_answer_exists():
    html = _html()
    assert 'if (pos.commercial_answer && pos.commercial_answer.decision) { el.innerHTML = ""; return; }' in html


def test_r381_reasoning_loop_owns_only_trace_and_counter_case():
    html = _html()
    start = html.index("function renderCommercialReasoningLoop")
    end = html.index("function renderDecisionCockpit", start)
    block = html[start:end]
    assert 'r.strongest_counterargument' in block
    assert 'r.decision_changers' not in block
    assert 'r.strongest_evidence' not in block
    assert 'r.commercial_tension' not in block


def test_r381_answer_surfaces_critical_unknowns_once():
    html = _html()
    assert 'DECISION-CRITICAL UNKNOWNS' in html
    start = html.index("function renderCommercialAnswer")
    end = html.index("function _moneyLabel", start)
    block = html[start:end]
    assert 'a.critical_unknowns' in block


def test_r381_decision_audit_dedupes_answer_owned_unknowns_and_changers():
    html = _html()
    assert 'const answerUnknowns = new Set' in html
    assert 'const answerChangers = new Set' in html
    assert 'filter(x => !answerUnknowns.has' in html
    assert 'filter(x => !answerChangers.has' in html


def test_r381_control_tower_not_open_by_default_with_consolidated_answer():
    html = _html()
    start = html.index("function renderControlTower")
    end = html.index("function buildDecisionBriefText", start)
    block = html[start:end]
    assert '<details style=' in block
    assert '<details open style=' not in block
