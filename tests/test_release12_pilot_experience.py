from pathlib import Path
from app.models import PilotExperienceRequest

ROOT = Path(__file__).resolve().parents[1]


def test_pilot_experience_model_accepts_valid_structured_signal():
    item = PilotExperienceRequest(
        ease_of_use="easy",
        trust_level="high",
        time_saved="significant",
        would_use_again=True,
        most_valuable="The landed-cost comparison made the negotiation position clearer.",
        missing_or_frustrating=None,
    )
    assert item.would_use_again is True
    assert item.time_saved == "significant"


def test_pilot_experience_model_rejects_invalid_controlled_values():
    try:
        PilotExperienceRequest(
            ease_of_use="great", trust_level="high", time_saved="some",
            would_use_again=True, most_valuable="Useful"
        )
    except Exception:
        return
    raise AssertionError("invalid ease_of_use should be rejected")


def test_schema_is_idempotent_and_tenant_scoped():
    schema = (ROOT / "db" / "schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS pilot_experience_feedback" in schema
    assert "UNIQUE (commercial_decision_id, submitted_by_user_id)" in schema
    assert "ALTER TABLE pilot_experience_feedback ADD COLUMN IF NOT EXISTS" in schema
    assert "ALTER TABLE pilot_experience_feedback ENABLE ROW LEVEL SECURITY" in schema
    assert "org_isolation_pef" in schema


def test_pilot_feedback_is_not_part_of_reasoning_or_decision_mutation():
    routes = (ROOT / "app" / "routes" / "decisions.py").read_text()
    start = routes.index('def submit_pilot_experience')
    end = routes.index('@router.post("/commercial-decisions/{decision_id}/feedback"', start)
    block = routes[start:end]
    assert "generate_commercial_position" not in block
    # Reading/returning the existing position is allowed elsewhere in the
    # router (e.g. customer-format export). This endpoint must not mutate it.
    assert "UPDATE commercial_decisions" not in block
    assert "pilot_experience_feedback" in block


def test_frontend_collects_value_signals_without_claiming_they_change_decision():
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    assert "pilot-experience-card" in html
    assert "would_use_again" in html
    assert "time_saved" in html
    assert "does not change this decision" in html
