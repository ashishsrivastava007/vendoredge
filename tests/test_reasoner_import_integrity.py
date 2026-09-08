from pathlib import Path

ROOT = Path(__file__).parents[1]
REASONER = ROOT / "app/pipeline/reasoner.py"


def test_reasoner_imports_position_contract_used_by_runtime():
    text = REASONER.read_text()
    assert "from app.pipeline.position_contract import normalize_bounded_position_lists" in text
    assert text.count("normalize_bounded_position_lists(") >= 2
