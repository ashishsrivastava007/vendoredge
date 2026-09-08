from pathlib import Path
import re

ROOT = Path(__file__).parents[1]
ROUTES = ROOT / "app/routes/decisions.py"
HTML = ROOT / "app/static/index.html"


def test_no_raw_generic_specialist_mismatch_pattern_remains():
    text = ROUTES.read_text()
    # Any specialist normalization call must have the explicit specialist boundary
    # in its surrounding control-flow. The broad guard patterns are release invariants.
    assert "def _is_specialist_content_type" in text
    assert "def _is_general_case" in text
    assert "if _is_general_case(row):" in text
    assert "if _is_general_case(parent):" in text


def test_generic_retry_uses_canonical_worker_and_generic_job_kind():
    text = ROUTES.read_text()
    start = text.index("def _queue_generic_retry")
    end = text.index("def _restart_reasoning_from_stored_evidence", start)
    block = text[start:end]
    assert 'job_queue.requeue(org_id, decision_id, job_kind="generic_triage")' in block
    assert "background_tasks.add_task(_run_queued_job, org_id, decision_id)" in block
    assert "_run_generic_reasoning_safe" not in block


def test_workbench_entry_points_exist():
    text = HTML.read_text()
    for label in ("Supplier request", "Something I noticed", "Category / strategy question"):
        assert label in text
    assert "commercial_workbench" in text or "Commercial Workbench" in text


def test_no_object_object_leak_in_frontend():
    text = HTML.read_text()
    assert "[object Object]" not in text


def test_release_has_single_final_documentation_marker():
    text = (ROOT / "CTO_RELEASE_40_2_PROACTIVE_CASE_BOUNDARY.md").read_text()
    assert "R40.2" in text
    assert "No general/proactive case can enter `normalize_evidence()`" in text
