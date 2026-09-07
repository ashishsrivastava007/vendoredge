import json
from types import SimpleNamespace

from app.models import CommercialPosition
from app.pipeline import commercial_triage


def _position_with_four_insights():
    data = {
        "recommendation": "Investigate the observed spend pattern before changing supplier allocation.",
        "commercial_insights": [
            "Spend has risen materially faster than volume.",
            "Average unit price is also higher year over year.",
            "Supplier A's share of spend has increased.",
            "The data does not yet establish a like-for-like supplier price increase.",
        ],
        "commercial_hypothesis": "The first priority is to isolate price versus mix effects.",
        "methodology_applied": "General commercial decision triage; specialist analysis not claimed.",
        "why_this_wins": "It resolves the highest-value uncertainty without making an unsupported accusation.",
        "reasoning": "The case contains enough evidence for an investigative action but not for a supplier overcharging conclusion.",
        "confidence": {
            "level": "medium",
            "factors": [
                {"factor": "The observed spend pattern is clear.", "value": "clear pattern", "weight": "increases confidence"}
            ],
            "derivation_note": "Medium confidence in the investigative direction.",
        },
        "decision_under_uncertainty": {
            "mode": "PROTECT",
            "label": "PROTECT — INVESTIGATE BEFORE COMMITTING",
            "recommendation": "Perform a like-for-like price and mix analysis before changing supplier allocation.",
            "confidence": "medium",
            "known": ["Spend is up faster than volume."],
            "unknowns": ["Like-for-like price movement"],
            "question": "What explains the spend increase after controlling for mix and specification changes?",
            "question_why": "It determines whether there is a supplier-specific pricing issue.",
            "safe_now": True,
            "reversibility": "Investigation is reversible and creates no supplier commitment.",
            "review_trigger": "Reassess after the like-for-like analysis.",
        },
        "assumptions": ["No independent market verification was performed."],
        "opening_position": "We are reviewing the observed pricing pattern before making any allocation decision.",
        "walk_away_threshold": None,
        "disconfirming_condition": "Like-for-like analysis shows the increase is fully explained by mix or specification changes.",
        "decision_type": "optimization",
    }
    return data


def test_generic_triage_recovers_from_one_overflowed_bounded_list(monkeypatch):
    class FakeClient:
        class Messages:
            @staticmethod
            def create(**kwargs):
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(_position_with_four_insights()))])
        messages = Messages()

    monkeypatch.setattr(commercial_triage, "_client", FakeClient())
    pos = commercial_triage.build_generic_commercial_position(
        "I noticed category spend is rising faster than volume.",
        "other",
    )
    assert isinstance(pos, CommercialPosition)
    assert len(pos.commercial_insights) == 3
    assert pos.commercial_insights[0].startswith("Spend has risen")
