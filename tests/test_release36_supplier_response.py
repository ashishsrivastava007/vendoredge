from types import SimpleNamespace
from app.pipeline.agentic_workflow import build_agentic_workflow


def p():
    # supplier_name deliberately not set on the stub -- see
    # test_release35_agentic_workflow.py for the full explanation of why.
    return SimpleNamespace(
        recommendation="Hold the increase pending evidence",
        decision_audit=SimpleNamespace(evidence_integrity_status="CONDITIONAL"),
        control_tower=SimpleNamespace(critical_before_action=[]),
        negotiation_playbook=SimpleNamespace(objective="Protect effective cost", opening_position="Reject unsupported increase", target="Flat", walk_away="No unsupported increase"),
        negotiation_intelligence=None,
    )


def test_phase9_keeps_supplier_message_as_editable_bounded_action():
    w = build_agentic_workflow(p(), supplier_name="ABC Marine Supplies")
    action = next(a for a in w["actions"] if a["id"] == "draft-supplier-message")
    assert action["approval_required"] is True
    assert "sending requires" in action["side_effect"]
    assert "ABC Marine Supplies" in action["prepared_output"]

