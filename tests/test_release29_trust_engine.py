from types import SimpleNamespace
from app.pipeline.trust_engine import build_trust_engine


def _normalized():
    prov = {
        "requested_increase_percent": SimpleNamespace(source="user_followup", conflicting=False, supplier_name=None),
        "annual_spend_usd": SimpleNamespace(source="llm_extraction", conflicting=False, supplier_name=None),
        "derived_value": SimpleNamespace(source="derived_calculation", conflicting=False, supplier_name=None),
        "conflict": SimpleNamespace(source="user_followup", conflicting=True, supplier_name=None),
    }
    common = SimpleNamespace(requested_increase_percent=None, annual_spend_usd=1000)
    case = SimpleNamespace(requested_increase_percent=8.5, annual_spend_usd=1000)
    derived = SimpleNamespace(derived_value=123)
    history = SimpleNamespace()
    return SimpleNamespace(provenance=prov, suppliers=[], common=common, case=case, derived=derived, history=history)


def _position():
    return SimpleNamespace(
        financial_impact=SimpleNamespace(net_exposure_usd=85),
        recommendation="Challenge the unsupported increase.",
        assumptions=["Freight estimate is comparison-only."],
        decision_audit=SimpleNamespace(uncertainties=["Actual supplier cost movement is unknown."]),
        decision_passport={"unknowns": ["Detailed supplier cost breakdown is unavailable."]},
    )


def test_trust_engine_classifies_all_five_states():
    result = build_trust_engine(_normalized(), _position())
    states = {e["state"] for e in result["entries"]}
    assert {"VERIFIED", "CALCULATED", "ASSUMED", "INFERRED", "UNKNOWN"} <= states


def test_conflict_is_never_verified():
    result = build_trust_engine(_normalized(), _position())
    entry = next(e for e in result["entries"] if e["field"] == "conflict")
    assert entry["state"] == "UNKNOWN"
    assert entry["conflicting"] is True
    assert result["decision_integrity"] == "REVIEW_REQUIRED"


def test_recommendation_is_inference_not_fact():
    result = build_trust_engine(_normalized(), _position())
    entry = next(e for e in result["entries"] if e["field"] == "recommendation")
    assert entry["state"] == "INFERRED"
