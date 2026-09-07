from app.pipeline.position_contract import normalize_bounded_position_lists
from app import caps


def test_overflowed_commercial_insights_are_trimmed_deterministically():
    raw = {"commercial_insights": ["a", "b", "c", "d"]}
    out = normalize_bounded_position_lists(raw)
    assert out["commercial_insights"] == ["a", "b", "c"]
    assert raw["commercial_insights"] == ["a", "b", "c", "d"]


def test_every_explicit_cap_is_enforced():
    values = {
        "commercial_insights": caps.MAX_COMMERCIAL_INSIGHTS + 1,
        "cost_driver_comparison": caps.MAX_COST_DRIVERS + 1,
        "key_figures": caps.MAX_KEY_FIGURES + 1,
        "supplier_comparison": caps.MAX_SUPPLIERS + 1,
        "negotiation_dimensions": caps.MAX_NEGOTIATION_DIMENSIONS + 1,
        "negotiation_talk_track": caps.MAX_TALK_TRACK_MOVES + 1,
        "financial_scenarios": caps.MAX_FINANCIAL_SCENARIOS + 1,
        "assumptions": caps.MAX_ASSUMPTIONS + 1,
    }
    raw = {k: list(range(v)) for k, v in values.items()}
    out = normalize_bounded_position_lists(raw)
    for field, maximum in [
        ("commercial_insights", caps.MAX_COMMERCIAL_INSIGHTS),
        ("cost_driver_comparison", caps.MAX_COST_DRIVERS),
        ("key_figures", caps.MAX_KEY_FIGURES),
        ("supplier_comparison", caps.MAX_SUPPLIERS),
        ("negotiation_dimensions", caps.MAX_NEGOTIATION_DIMENSIONS),
        ("negotiation_talk_track", caps.MAX_TALK_TRACK_MOVES),
        ("financial_scenarios", caps.MAX_FINANCIAL_SCENARIOS),
        ("assumptions", caps.MAX_ASSUMPTIONS),
    ]:
        assert len(out[field]) == maximum


def test_uncapped_fields_are_not_modified():
    raw = {"confidence": {"factors": list(range(20))}, "other": list(range(20))}
    out = normalize_bounded_position_lists(raw)
    assert out == raw
