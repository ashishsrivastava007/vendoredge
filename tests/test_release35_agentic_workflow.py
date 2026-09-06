from types import SimpleNamespace
from app.pipeline.agentic_workflow import build_agentic_workflow


def p(blocked=False):
    return SimpleNamespace(
        supplier_name="ABC Marine Supplies",
        recommendation="Hold the increase pending evidence",
        decision_audit=SimpleNamespace(evidence_integrity_status="CONDITIONAL"),
        control_tower=SimpleNamespace(critical_before_action=["cost evidence"] if blocked else []),
        negotiation_playbook=SimpleNamespace(objective="Protect effective cost", opening_position="Reject unsupported increase", target="Flat", walk_away="No unsupported increase"),
        negotiation_intelligence=None,
    )


def test_workflow_prepares_supplier_draft_without_side_effects():
    w = build_agentic_workflow(p())
    assert w["mode"] == "BOUNDED_AGENTIC_WORKFLOW"
    assert w["external_side_effects"] is False
    ids = [a["id"] for a in w["actions"]]
    assert "draft-supplier-message" in ids
    draft = next(a for a in w["actions"] if a["id"] == "draft-supplier-message")["prepared_output"]
    assert "ABC Marine Supplies" in draft
    assert "Reject unsupported increase" in draft


def test_blocked_case_cannot_become_ready_by_agent():
    w = build_agentic_workflow(p(blocked=True))
    approve = next(a for a in w["actions"] if a["id"] == "approve-commercial-position")
    assert approve["status"] == "blocked"
    assert any(a["id"] == "resolve-precommit-blockers" for a in w["actions"])


def test_agentic_output_never_claims_to_execute_external_action():
    w = build_agentic_workflow(p())
    assert w["external_side_effects"] is False
    assert "sending requires" in next(a for a in w["actions"] if a["id"] == "draft-supplier-message")["side_effect"]
