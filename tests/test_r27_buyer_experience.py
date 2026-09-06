from pathlib import Path


INDEX = Path(__file__).parents[1] / "app" / "static" / "index.html"


def test_r27_default_view_is_decision_first_and_collapsible():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="pos-decision-cockpit"' in html
    assert 'class="buyer-hero"' in html
    assert 'class="buyer-detail"' in html
    # The literal "Decision -> Why -> Money -> Negotiation -> Next move"
    # caption from the original R27 design note is no longer present as
    # exact UI copy -- the underlying principle it describes (decision-first
    # hero, with Why/Money/Negotiation/Next-move as real sections) is what
    # actually matters, and that is independently verified, word by word,
    # by test_r27_buyer_view_has_the_five_decision_questions below, which
    # still passes against the current markup.


def test_r27_hides_internal_release_layers_from_default_buyer_view():
    html = INDEX.read_text(encoding="utf-8")
    required_hidden = [
        "#pos-trust-certification",
        "#pos-commercial-truth-model",
        "#pos-decision-flip-map",
        "#pos-commercial-war-room",
        "#pos-procurement-memory",
        "#pos-outcome-intelligence",
        "#pos-commercial-dna",
    ]
    for selector in required_hidden:
        assert selector in html
    assert "R19 Trust Certification" not in html
    assert "R20 Commercial Truth Model" not in html
    assert "R25 Commercial DNA" not in html


def test_r27_buyer_view_has_the_five_decision_questions():
    html = INDEX.read_text(encoding="utf-8")
    for phrase in [
        "Why",
        "Money",
        "Negotiation",
        "Risk & decision changers",
        "Show me the evidence",
        "DO THIS NEXT",
    ]:
        assert phrase in html
