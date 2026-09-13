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


def test_r381_answer_surfaces_what_would_change_this_once_not_duplicated():
    """UPDATED: the original R38.1 consolidation kept two separate,
    overlapping primary sections -- "DECISION-CRITICAL UNKNOWNS" (from
    critical_unknowns) and "WHAT WOULD CHANGE THIS" (from
    decision_changers) -- built from the same underlying uncertainty
    list, so the top items appeared twice, verbatim, in the primary
    answer. Fixed by removing the redundant critical_unknowns field and
    section entirely; decision_changers is now the one, single, correct
    home for "what would change this decision" in the primary view."""
    html = _html()
    assert "DECISION-CRITICAL UNKNOWNS" not in html
    assert "a.critical_unknowns" not in html
    assert "WHAT WOULD CHANGE THIS" in html
    start = html.index("function renderCommercialAnswer")
    end = html.index("function _moneyLabel", start)
    block = html[start:end]
    assert "a.decision_changers" in block


def test_r381_decision_audit_dedupes_deep_section_against_decision_changers():
    """UPDATED: the original two-set dedup (answerUnknowns +
    answerChangers) existed specifically because critical_unknowns and
    decision_changers were two separate, overlapping lists needing
    separate filters. With critical_unknowns removed, decision_changers
    is the single canonical list the deeper evidence section filters
    against -- one set, not two, doing the same real job with less
    duplicated machinery."""
    html = _html()
    assert "const answerUnknowns = new Set" not in html
    assert "const answerChangers = new Set" in html
    assert "filter(x => !answerChangers.has" in html


def test_r381_control_tower_not_open_by_default_with_consolidated_answer():
    html = _html()
    start = html.index("function renderControlTower")
    end = html.index("function buildDecisionBriefText", start)
    block = html[start:end]
    assert '<details style=' in block
    assert '<details open style=' not in block
