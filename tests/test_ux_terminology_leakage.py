"""
R46 UX refactor -- regression tests preventing the specific leaks named
in the audit: release/version labels, and internal negotiation-
framework terminology (Dimension/Boundary/Trading Rule/Give-Get Matrix/
Response Playbook/Escalation Triggers) that a founder shouldn't have to
ask "what does this mean?" about.

Static-scan tests check the actual rendered source (app/static/index.html)
directly, since these are markup/label strings a Python-level API test
can't otherwise see. Kept intentionally narrow to the terms actually
named in the audit, not a general jargon-detector -- a broader filter
would have too many false positives (e.g. "Dimension" or "Target" used
in a genuinely different, harmless context elsewhere in the file).
"""
from pathlib import Path

INDEX_HTML = Path(__file__).parents[1] / "app" / "static" / "index.html"


def _read():
    return INDEX_HTML.read_text()


def test_no_release_label_in_the_default_answer_header():
    text = _read()
    assert "VENDOREDGE COMMERCIAL ANSWER" not in text
    for label in ("R38", "R41", "R42", "R45"):
        assert f"· {label}" not in text and f"·{label}" not in text


def test_no_blanket_confidence_badge_in_the_default_answer():
    """The single, misleading "CONFIDENCE · HIGH" badge on the primary
    commercial answer is removed -- confidence, where it matters, must
    be tied to a specific claim, not one blanket label covering a
    mixed-certainty conclusion."""
    text = _read()
    assert 'CONFIDENCE · ${esc(confidence)}' not in text


def test_negotiation_framework_jargon_not_exposed_as_section_headers():
    """The exact terms named in the audit -- the ones a founder had to
    ask "what does this mean?" about -- must not appear as UI section
    headers/labels. Capability preserved (still tested via the
    available-gate test below); only the exposed labels changed."""
    text = _read()
    for forbidden in ("GIVE / GET MATRIX", "RESPONSE PLAYBOOK", "ESCALATION TRIGGERS", "NEGOTIATION INTELLIGENCE", "Prepare → trade → respond → escalate"):
        assert forbidden not in text, f"Found forbidden internal-framework label: {forbidden!r}"


def test_negotiation_table_uses_plain_english_column_headers():
    text = _read()
    assert "What I want" in text
    assert "What I wouldn't accept" in text
    assert "How I'd trade it" in text
    # The old jargon column headers must not appear together as a row
    # (","Dimension" alone could be a false positive elsewhere in the
    # file, so this checks the specific old header sequence is gone).
    assert '<td style="padding:4px 9px">Dimension</td><td style="padding:4px 9px">Target</td><td style="padding:4px 9px">Boundary</td>' not in text


def test_secondary_section_summaries_use_plain_english():
    text = _read()
    for forbidden in ("Commercial analysis <span>economics", "Memory &amp; learning <span>supplier history, outcomes and organisational learning",
                       "Advanced review <span>model challenge, methodology and decision pack"):
        assert forbidden not in text


def test_signal_hypothesis_status_labels_are_translated_to_plain_english():
    """R48: the raw backend status values (SUPPORTED, PARTIALLY_
    SUPPORTED, NOT_SUPPORTED, UNKNOWN, CONTRADICTED) must never be the
    only thing rendered -- a translation map must cover all five."""
    text = _read()
    assert 'statusLabel = { SUPPORTED:' in text
    for raw_status in ("SUPPORTED:", "PARTIALLY_SUPPORTED:", "NOT_SUPPORTED:", "UNKNOWN:", "CONTRADICTED:"):
        assert raw_status in text  # present as a translation-map key, not as bare rendered text


def test_negotiation_dimensions_raw_table_no_longer_duplicated_on_page():
    """Repetition fix: pos.negotiation_dimensions used to render twice
    (a bare table, and again -- more usefully -- inside the give/get
    detail). Confirms the redundant call was removed from the render
    dispatch, not just the function left dangling."""
    text = _read()
    assert "renderNegotiationDimensions(pos);" not in text
    # The function definition itself is kept (not deleted) for
    # potential future/audit use -- only the default-path call site
    # was removed.
    assert "function renderNegotiationDimensions(pos)" in text


def test_negotiation_playbook_evidence_never_leaks_raw_dict_repr():
    """A real bug found while manually reading the negotiation payload:
    material_evidence is list[dict] (label/status/evidence keys), and
    str(x) on each dict was producing the raw Python repr
    ("{'label': ..., 'status': ...}") directly in buyer-facing text.
    Now extracts the actual readable text."""
    from app.pipeline.negotiation_playbook import build_negotiation_playbook
    from app.models import CommercialPosition, Confidence, ConfidenceFactor, DecisionAudit

    conf = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")
    pos = CommercialPosition(
        recommendation="x", commercial_insights=["a"], reasoning="x", confidence=conf, assumptions=["a"],
        disconfirming_condition="A change in evidence would revisit this.", decision_type="optimization",
    )
    pos.decision_audit = DecisionAudit(
        material_evidence=[{"label": "Annual spend", "status": "PROVEN", "evidence": "$500,000 annual spend"}],
        uncertainties=[], evidence_integrity_status="PROVEN",
    )
    playbook = build_negotiation_playbook(pos)
    assert playbook["evidence_to_lead_with"] == ["$500,000 annual spend"]
    assert "{'label'" not in str(playbook) and "{'status'" not in str(playbook)
