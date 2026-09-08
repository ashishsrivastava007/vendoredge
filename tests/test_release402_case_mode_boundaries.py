from pathlib import Path

ROUTES = Path(__file__).parents[1] / "app" / "routes" / "decisions.py"
NORMALIZED = Path(__file__).parents[1] / "app" / "pipeline" / "normalized_evidence.py"


def test_specialist_normalization_boundary_is_explicit():
    text = ROUTES.read_text()
    assert "def _is_specialist_content_type" in text
    assert 'return content_type in {"price_increase", "quote_comparison"}' in text
    assert "Never route them through normalize_evidence()" in text


def test_restart_and_queue_paths_guard_specialist_normalization():
    text = ROUTES.read_text()
    assert "def _restart_reasoning_from_stored_evidence" in text
    restart_start = text.index("def _restart_reasoning_from_stored_evidence")
    restart_end = text.index("def _run_generic_reasoning_safe", restart_start)
    restart_block = text[restart_start:restart_end]
    assert "if _is_general_case(row):" in restart_block
    assert "return _queue_generic_retry" in restart_block

    job_start = text.index("def _run_queued_job")
    job_end = text.index("def _run_reasoning_safe", job_start)
    job_block = text[job_start:job_end]
    assert "if _is_general_case(row):" in job_block
    assert "_run_generic_reasoning_safe" in job_block


def test_respond_and_continue_paths_do_not_force_generic_cases_into_specialist_normalizer():
    text = ROUTES.read_text()
    respond_start = text.index("def respond(")
    continue_start = text.index("def continue_case(")
    respond_block = text[respond_start:continue_start]
    assert "specialist_case = not _is_general_case(row)" in respond_block
    assert "if not specialist_case" in respond_block

    continue_block = text[continue_start:]
    assert "if _is_general_case(parent):" in continue_block
    assert 'job_queue.enqueue(x_org_id, new_decision_id, "generic_triage")' in continue_block


def test_specialist_normalized_evidence_contract_remains_narrow():
    text = NORMALIZED.read_text()
    assert 'content_type: Literal["price_increase", "quote_comparison"]' in text
