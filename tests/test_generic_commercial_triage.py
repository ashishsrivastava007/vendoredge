import json
from types import SimpleNamespace

from app.models import CommercialPosition
from app.pipeline import commercial_triage


def _fake_position_json(confidence="medium"):
    return json.dumps({
        "recommendation": "Protect continuity while resolving responsibility and commercial exposure before accepting any additional cost.",
        "commercial_insights": [
            "Operational urgency and commercial acceptance are separate decisions; protecting continuity does not require accepting the supplier's cost position.",
            "The most valuable missing fact is the evidence that establishes who owns the specification or failure and what remedy is actually required."
        ],
        "commercial_hypothesis": None,
        "methodology_applied": "General commercial decision triage; specialist analysis not claimed.",
        "why_this_wins": "It protects the immediate business need without converting an unresolved commercial question into an irreversible commitment.",
        "reasoning": "Known: the buyer is facing a supplier-related commercial decision. Unknown: the evidence needed to establish cost responsibility and the full commercial exposure. The safest current action is to protect continuity while keeping the commercial position open.",
        "confidence": {
            "level": confidence,
            "factors": [
                {"factor": "The user's question clearly identifies the commercial problem.", "value": "problem is clear", "weight": "increases confidence"},
                {"factor": "Material supporting evidence is missing.", "value": "limited evidence", "weight": "decreases confidence"}
            ],
            "derivation_note": "Medium confidence because the direction of the protective action is defensible, but specialist evidence is incomplete."
        },
        "decision_under_uncertainty": {
            "mode": "PROTECT",
            "label": "PROTECT — ACT WITH A GUARDRAIL",
            "recommendation": "Protect continuity while resolving responsibility and commercial exposure before accepting any additional cost.",
            "confidence": confidence,
            "known": ["The user is facing a supplier-related commercial decision."],
            "unknowns": ["Responsibility for the issue", "Full commercial exposure"],
            "question": "What documented evidence establishes responsibility for the issue and the required remedy?",
            "question_why": "That evidence can materially change the commercial position.",
            "safe_now": True,
            "reversibility": "Keep any immediate commitment limited and reversible.",
            "review_trigger": "Reassess when responsibility and remedy evidence is established."
        },
        "assumptions": ["No contract or technical evidence was supplied beyond the user's question.", "No independent market or legal verification was performed."],
        "opening_position": "We will protect continuity, but we are not accepting additional commercial cost until the technical and commercial basis is established.",
        "walk_away_threshold": None,
        "disconfirming_condition": "Documented evidence materially changes responsibility, remedy, or the operational risk of the available options.",
        "decision_type": "optimization"
    })


def test_generic_triage_accepts_real_out_of_scope_case(monkeypatch):
    class FakeClient:
        class Messages:
            @staticmethod
            def create(**kwargs):
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=_fake_position_json())])
        messages = Messages()

    monkeypatch.setattr(commercial_triage, "_client", FakeClient())
    pos = commercial_triage.build_generic_commercial_position(
        "Valve supplier says the failed item must be replaced at our cost after the vessel sailed.",
        "supplier_exit",
    )
    assert isinstance(pos, CommercialPosition)
    assert pos.recommendation.startswith("Protect continuity")
    assert pos.financial_impact is None
    assert pos.decision_under_uncertainty["mode"] == "PROTECT"
    assert pos.confidence.level == "low"


def test_generic_triage_never_allows_high_confidence(monkeypatch):
    class FakeClient:
        class Messages:
            @staticmethod
            def create(**kwargs):
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=_fake_position_json("high"))])
        messages = Messages()

    monkeypatch.setattr(commercial_triage, "_client", FakeClient())
    pos = commercial_triage.build_generic_commercial_position("Supplier is threatening to stop supply.", "supplier_exit")
    # generic_integrity.py's apply_generic_integrity_contract deterministically
    # overwrites confidence to a fixed, conservative "low" for every generic
    # triage case, regardless of what level the model itself claimed -- "no
    # model-owned confidence... is allowed in this route" (see its own
    # comment). This test's real purpose -- prove a model-claimed "high"
    # confidence can never survive this route -- holds; "low" is the actual,
    # deliberately stricter enforced value, not "medium".
    assert pos.confidence.level == "low"
    assert "System-set low confidence" in pos.confidence.derivation_note
