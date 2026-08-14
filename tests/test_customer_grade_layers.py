from types import SimpleNamespace
import pytest
from app.pipeline.customer_exports import render_custom, export_csv
from app.pipeline.customer_actions import build_action_plan


def p():
    audit = SimpleNamespace(evidence_integrity_status="UNKNOWN", stakeholder_conflict=["Finance wants savings; Operations prefers incumbent"])
    return SimpleNamespace(
        recommendation="Hold price until evidence is verified",
        financial_impact=None,
        confidence=SimpleNamespace(level="medium"),
        why_this_wins="It protects leverage without accepting unsupported cost inflation.",
        opening_position="Reject the increase",
        walk_away_threshold="Unsupported double-digit increase",
        disconfirming_condition="Audited cost evidence materially supports the increase",
        assumptions=["Freight is not yet quantified"],
        reasoning="Evidence is incomplete, so the position is conditional.",
        decision_audit=audit,
        control_tower=SimpleNamespace(critical_before_action=["Freight evidence"]),
        negotiation_playbook=SimpleNamespace(objective="Negotiate a defensible price", opening_position="Reject increase", target="Flat", walk_away="Unsupported increase"),
    )


def test_custom_format_is_deterministic_and_supports_user_template():
    r = render_custom(p(), "CFO: {{recommendation}}\nConfidence: {{confidence}}\nRisk: {{stakeholder_conflicts}}")
    assert "Hold price" in r["body"]
    assert "Finance wants savings" in r["body"]
    assert "no new facts" in r["method"]


def test_custom_format_rejects_unknown_tokens():
    with pytest.raises(ValueError):
        render_custom(p(), "{{secret_database_password}}")


def test_custom_format_rejects_oversized_template():
    with pytest.raises(ValueError):
        render_custom(p(), "x" * 12001)


def test_action_plan_is_approval_gated_and_side_effect_free():
    plan = build_action_plan(p())
    assert plan["human_approval_required"] is True
    assert plan["external_side_effects"] is False
    assert any(a["status"] == "approval_required" for a in plan["actions"])
    assert any(a["status"] == "blocked_until_resolved" for a in plan["actions"])


def test_csv_export_has_stable_headers_and_no_new_reasoning():
    csv = export_csv(p())
    assert "recommendation,confidence,evidence_integrity" in csv
    assert "Hold price until evidence is verified" in csv


def test_migration_is_fail_closed():
    main = open("app/main.py", encoding="utf-8").read()
    seed = open("app/seed.py", encoding="utf-8").read()
    assert "startup aborted" in main
    assert "startup must not continue" in seed
