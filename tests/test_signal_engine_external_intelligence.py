"""
R48 Signal Engine -- external intelligence gating (Section 13).
Removes the "price_increase-only" conceptual gate as the SOLE trigger
and adds a second, additive condition specific to commercial_signal
cases: research fires only when the case's own stated text describes a
genuine market-price-divergence pattern (market moved, this supplier's
price didn't) -- the one signal shape where external verification can
materially change the conclusion. The original Supplier Request
vertical's gate condition is completely unchanged, proven by keeping
its exact original test passing unmodified.
"""
from app.pipeline.fresh_intelligence import should_research_fresh_intelligence


def test_market_divergence_signal_triggers_research():
    kernel = {
        "case": {"content_type": "price_increase", "subject": "Supplier X"},
        "facts": [{"metric": "stated_justification", "value": "The market price has fallen but the supplier's price has not moved."}],
    }
    assert should_research_fresh_intelligence(kernel) is True


def test_otif_signal_does_not_trigger_research():
    """Internal supplier performance has no external-market relevance --
    research must never fire merely because content_type happens to be
    price_increase."""
    kernel = {
        "case": {"content_type": "price_increase", "subject": "Supplier A"},
        "facts": [{"metric": "stated_justification", "value": "Supplier OTIF dropped from 96% to 81%."}],
    }
    assert should_research_fresh_intelligence(kernel) is False


def test_generic_spend_volume_signal_with_no_market_language_does_not_trigger_research():
    """Research must not fire merely because the signal mentions a
    market in passing or is spend-shaped -- only a genuine divergence
    pattern qualifies."""
    kernel = {
        "case": {"content_type": "price_increase", "subject": "Category X"},
        "facts": [{"metric": "stated_justification", "value": "Spend is growing faster than volume."}],
    }
    assert should_research_fresh_intelligence(kernel) is False


def test_original_supplier_request_vertical_shape_unchanged():
    """Regression proof: the original gate condition (Industrial
    Valves / Supplier A shape) is byte-for-byte unchanged by this
    addition."""
    kernel = {
        "case": {"content_type": "price_increase", "subject": "Supplier A"},
        "facts": [{"metric": "annual_spend", "value": 5_550_000}, {"metric": "requested_change_percent", "value": 11.0}],
    }
    assert should_research_fresh_intelligence(kernel) is True


def test_no_subject_still_correctly_blocks_the_original_vertical_path():
    kernel = {
        "case": {"content_type": "price_increase", "subject": None},
        "facts": [{"metric": "annual_spend", "value": 5_550_000}, {"metric": "requested_change_percent", "value": 11.0}],
    }
    assert should_research_fresh_intelligence(kernel) is False
