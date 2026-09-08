from pathlib import Path

ROUTES = Path(__file__).parents[1] / "app" / "routes" / "decisions.py"
MEMORY = Path(__file__).parents[1] / "app" / "pipeline" / "commercial_memory.py"


def test_general_workflow_has_explicit_private_routing_metadata():
    text = ROUTES.read_text()
    assert '"__workflow_mode__": "general_commercial_triage"' in text
    assert '"__decision_category__": category' in text


def test_all_recovery_paths_use_general_case_boundary():
    text = ROUTES.read_text()
    assert "def _is_general_case(row: dict) -> bool" in text
    assert "specialist_case = not _is_general_case(row)" in text
    assert 'if _is_general_case(row):' in text
    assert "return _queue_generic_retry" in text
    assert 'job_queue.requeue(org_id, decision_id, job_kind="generic_triage")' in text


def test_generic_continuation_never_enters_specialist_normalizer():
    text = ROUTES.read_text()
    start = text.index("def continue_case(")
    block = text[start:]
    assert "if _is_general_case(parent):" in block
    branch = block[block.index("if _is_general_case(parent):"):block.index("# A continuation is new evidence", block.index("if _is_general_case(parent):"))]
    assert 'job_queue.enqueue(x_org_id, new_decision_id, "generic_triage")' in branch
    assert "normalize_evidence(" not in branch


def test_generic_memory_keeps_category_and_workflow_mode():
    text = MEMORY.read_text()
    assert '"decision_category"' in text
    assert '"workflow_mode"' in text
    assert "decision_category" in text[text.index("activity_keys"):text.index("pattern_level")]
