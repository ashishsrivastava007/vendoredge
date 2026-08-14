"""Release 11: customer-ready decision brief integrity.

The Decision Pack is deliberately a pure rendering layer. These tests make
sure it remains deterministic, includes the load-bearing decision controls,
and does not introduce a second reasoning/calculation path.
"""
from pathlib import Path


HTML = Path(__file__).parents[1] / "app" / "static" / "index.html"
TEXT = HTML.read_text()


def test_decision_pack_ui_exists_and_is_actionable():
    assert 'id="pos-decision-pack"' in TEXT
    assert "Decision Pack — ready to take into your meeting" in TEXT
    assert "copyDecisionPack()" in TEXT
    assert "downloadDecisionPack()" in TEXT


def test_decision_pack_contains_the_load_bearing_controls():
    required = [
        '"VENDOREDGE — COMMERCIAL DECISION BRIEF"',
        '"DECISION"',
        '"CONFIDENCE"',
        '"FINANCIAL IMPACT"',
        '"WHY THIS WINS"',
        '"WHAT I AM ASSUMING"',
        '"WHAT WOULD CHANGE THE DECISION"',
        '"MATERIAL EVIDENCE"',
        '"UNCERTAINTIES"',
        '"STAKEHOLDER CONFLICTS"',
        '"REVERSAL CONDITIONS"',
        '"DECISION READINESS"',
        '"COMMERCIAL ALTERNATIVES"',
        '"STRESS TEST"',
    ]
    for marker in required:
        assert marker in TEXT, marker


def test_decision_pack_is_rendered_from_existing_position_only():
    start = TEXT.index("function buildDecisionBriefText(pos)")
    end = TEXT.index("function renderDecisionPack(pos)")
    block = TEXT[start:end]
    assert "fetch(" not in block
    assert "generate_commercial_position" not in block
    assert "Math.random" not in block
    assert "financial_impact" in block
    assert "decision_audit" in block
    assert "control_tower" in block


def test_decision_pack_is_wired_into_completed_position_render():
    assert "renderDecisionPack(pos);" in TEXT
    render_pos = TEXT.index("function renderPosition(pos)")
    render_pack = TEXT.index("renderDecisionPack(pos);", render_pos)
    assert render_pack > render_pos


def test_decision_pack_has_no_new_llm_or_server_endpoint():
    start = TEXT.index("function buildDecisionBriefText(pos)")
    end = TEXT.index("function renderDecisionPack(pos)")
    block = TEXT[start:end]
    assert "/api/" not in block
    assert "anthropic" not in block.lower()
    assert "XMLHttpRequest" not in block
