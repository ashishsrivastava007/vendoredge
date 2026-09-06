from types import SimpleNamespace

from app.pipeline.commercial_decision_engine import build_commercial_decision_engine


def _normalized():
    return SimpleNamespace(content_type="price_increase")


def _position(mode="DECIDE", integrity="CERTIFIED"):
    return SimpleNamespace(
        recommendation="Reject unsupported increase; negotiate with safeguards.",
        decision_type="optimization",
        confidence=SimpleNamespace(level="high"),
        decision_under_uncertainty={"mode": mode, "unknowns": [], "review_trigger": "Reassess if market evidence changes."},
        control_tower={"critical_before_action": [], "action_items": [{"action": "Open negotiation", "owner": "buyer", "timing": "now"}]},
        decision_audit={"reversal_conditions": []},
        trust_engine={"decision_integrity": "REVIEW_REQUIRED" if integrity == "REVIEW_REQUIRED" else "CERTIFIED", "counts": {"VERIFIED": 4}},
        financial_impact={"annual_spend_usd": 1000000, "potential_annual_impact_usd": 85000, "net_exposure_usd": 85000, "note": "$85,000"},
        decision_cockpit={"economics": {"available": True, "headline": "$85,000 potential annual impact"}},
        alternative_analysis={"available": True, "summary": "Two paths", "alternatives": [{"name": "Compete", "type": "alternative"}]},
        negotiation_playbook={"objective": "Protect economics", "target": "0%", "walk_away": "Unsupported increase"},
        decision_passport={"next_move": "Request cost support and negotiate terms.", "decision_changers": []},
        opening_position="Request support",
        walk_away_threshold="Unsupported increase",
    )


def test_engine_is_single_operational_spine():
    e = build_commercial_decision_engine(_normalized(), _position())
    assert e["version"] == "R31.1"
    assert e["decision"]["mode"] == "DECIDE"
    assert e["execution"]["next_move"]
    assert e["economics"]["potential_annual_impact_usd"] == 85000


def test_conflict_forces_conditional_status():
    e = build_commercial_decision_engine(_normalized(), _position(integrity="REVIEW_REQUIRED"))
    assert e["evidence"]["status"] == "CONFLICT"
    assert e["status"] == "CONDITIONAL"


def test_ask_mode_survives_without_becoming_decide():
    e = build_commercial_decision_engine(_normalized(), _position(mode="ASK"))
    assert e["decision"]["mode"] == "ASK"
    assert e["status"] == "CONDITIONAL"
