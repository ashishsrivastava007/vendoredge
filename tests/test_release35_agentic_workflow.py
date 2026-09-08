from types import SimpleNamespace
from app.pipeline.agentic_workflow import build_agentic_workflow


def p(blocked=False):
    # supplier_name is deliberately NOT set here -- CommercialPosition
    # never had this field (that was the actual root cause of the real
    # 'CommercialPosition' object has no attribute 'supplier_name' bug;
    # a SimpleNamespace stub with the attribute set directly was masking
    # it, since an unconstrained stub allows any attribute the real
    # Pydantic model never would). The real supplier name is now passed
    # to build_agentic_workflow explicitly, sourced from evidence, not
    # read off the position -- see test_hardening_pass_currency_and_
    # supplier_name.py for the fix against the real model and real call
    # chain, not a stub.
    return SimpleNamespace(
        recommendation="Hold the increase pending evidence",
        decision_audit=SimpleNamespace(evidence_integrity_status="CONDITIONAL"),
        control_tower=SimpleNamespace(critical_before_action=["cost evidence"] if blocked else []),
        negotiation_playbook=SimpleNamespace(objective="Protect effective cost", opening_position="Reject unsupported increase", target="Flat", walk_away="No unsupported increase"),
        negotiation_intelligence=None,
    )


def test_workflow_prepares_supplier_draft_without_side_effects():
    w = build_agentic_workflow(p(), supplier_name="ABC Marine Supplies")
    assert w["mode"] == "BOUNDED_AGENTIC_WORKFLOW"
    assert w["external_side_effects"] is False
    ids = [a["id"] for a in w["actions"]]
    assert "draft-supplier-message" in ids
    draft = next(a for a in w["actions"] if a["id"] == "draft-supplier-message")["prepared_output"]
    assert "ABC Marine Supplies" in draft
    assert "Reject unsupported increase" in draft


def test_blocked_case_cannot_become_ready_by_agent():
    w = build_agentic_workflow(p(blocked=True), supplier_name="ABC Marine Supplies")
    approve = next(a for a in w["actions"] if a["id"] == "approve-commercial-position")
    assert approve["status"] == "blocked"
    assert any(a["id"] == "resolve-precommit-blockers" for a in w["actions"])


def test_agentic_output_never_claims_to_execute_external_action():
    w = build_agentic_workflow(p(), supplier_name="ABC Marine Supplies")
    assert w["external_side_effects"] is False
    assert "sending requires" in next(a for a in w["actions"] if a["id"] == "draft-supplier-message")["side_effect"]


def test_workflow_still_works_with_no_supplier_name_available():
    """A genuinely missing supplier name (e.g. a general commercial-signal
    case with no single named supplier) must fall back gracefully, not
    crash -- this is the actual behavior the original bug's symptom
    (an unhandled AttributeError, silently swallowed by the outer
    non-blocking except in decisions.py) should never have reached."""
    w = build_agentic_workflow(p(), supplier_name=None)
    draft = next(a for a in w["actions"] if a["id"] == "draft-supplier-message")["prepared_output"]
    assert "the supplier" in draft
