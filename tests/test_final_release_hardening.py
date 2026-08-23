from pathlib import Path
import io
import zipfile
import pytest

from app.pipeline.file_extraction import extract_text_from_zip, FileExtractionError

ROOT = Path(__file__).resolve().parents[1]


def _zip_with_entries(count=51, payload=b"x"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for i in range(count):
            z.writestr(f"f{i}.txt", payload)
    return buf.getvalue()


def test_zip_member_count_limit_is_enforced():
    try:
        extract_text_from_zip(_zip_with_entries())
    except FileExtractionError as exc:
        assert "too many files" in str(exc)
    else:
        raise AssertionError("ZIP member-count limit was not enforced")


def test_final_package_contains_r20_structural_layer():
    assert (ROOT / "app/pipeline/commercial_model.py").exists()
    assert (ROOT / "tests/test_release20_commercial_model.py").exists()
    source = (ROOT / "app/routes/decisions.py").read_text()
    model = (ROOT / "app/models.py").read_text()
    assert "build_commercial_truth_model" in source
    assert "commercial_truth_model" in model


def test_frontend_escapes_model_controlled_fields():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    for token in ["d.dimension", "d.opening_ask", "d.target_outcome", "d.walk_away", "m.trigger", "m.line"]:
        assert f"escapeHtml(String({token}" in html
    assert "<p class=\"q\">${escapeHtml(c.raw_question)}</p>" in html


def test_render_blueprint_is_present_and_keeps_legacy_links_disabled():
    yaml = (ROOT / "render.yaml").read_text()
    assert "runtime: docker" in yaml
    assert "healthCheckPath: /health" in yaml
    assert 'key: ANTHROPIC_API_KEY' in yaml
    assert 'sync: false' in yaml
    assert 'key: ALLOW_LEGACY_WORKSPACE_LINKS' in yaml
    assert 'value: "false"' in yaml


def test_market_verification_resumes_server_tool_pause(monkeypatch):
    pytest.importorskip("anthropic")
    from types import SimpleNamespace
    import app.pipeline.market_verification as mv

    class FakeMessages:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(stop_reason="pause_turn", content=[SimpleNamespace(type="text", text="working")])
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text='{"claim_checked":"steel","finding":"supported","verified_note":"Current market evidence supports the claim."}')],
            )

    fake = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(mv, "_client", fake)
    result = mv.verify_market_claim("steel prices increased", "Europe")
    assert result["finding"] == "supported"
    assert result["scope"] == "Europe"
    assert fake.messages.calls == 2


def test_xlsx_nested_zip_expansion_limit_is_enforced():
    from app.pipeline.file_extraction import _validate_zip_container, FileExtractionError
    import io
    import zipfile
    import pytest
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("xl/oversized.bin", b"x" * 10_000_001)
    with pytest.raises(FileExtractionError):
        _validate_zip_container(buf.getvalue())
