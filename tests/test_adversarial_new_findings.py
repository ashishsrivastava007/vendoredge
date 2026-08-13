"""
Two genuinely NEW findings from Guarantee #6's adversarial pass, not
previously covered by any earlier guarantee's tests.
"""
from app.pipeline.incoterm_fallback import normalize_incoterm
from app.pipeline.normalize import normalize_evidence


def test_incoterm_full_name_is_normalized_not_silently_passed_through():
    """Real gap found during adversarial testing: 'Free On Board' (the
    full phrase) was previously accepted as-is with zero validation,
    silently causing freight_relevant to come back False even though the
    case genuinely described FOB terms."""
    ne, _ = normalize_evidence(
        "Terms are Free On Board Gdansk, 10% increase requested.", "price_increase",
        {"incoterm": "Free On Board"}, {},
    )
    assert ne.common.incoterm == "FOB"
    assert ne.derived.freight_relevant is True


def test_genuinely_malformed_incoterm_is_rejected_not_silently_accepted():
    """The other real boundary: a genuinely unrecognized value must
    become None, never silently pass through as if it were valid."""
    assert normalize_incoterm("garbage-value-123") is None
    ne, _ = normalize_evidence(
        "Terms are XYZ, 10% increase requested.", "price_increase",
        {"incoterm": "XYZ"}, {},
    )
    assert ne.common.incoterm is None


def test_per_supplier_incoterm_full_names_are_also_normalized():
    """The same fix applied to the separate per-supplier extraction path,
    not just the single-value common.incoterm path."""
    ne, _ = normalize_evidence(
        "Comparing suppliers.", "quote_comparison", {}, {},
        supplier_specific_evidence=[
            {"supplier_name": "Acme", "incoterm": "Delivered Duty Paid"},
        ],
    )
    assert ne.supplier_by_name("Acme").incoterm == "DDP"


def test_no_cross_attribution_across_similarly_named_suppliers():
    """Adversarial test: three deliberately similar-sounding supplier
    names, confirming each keeps its own real data with zero mixing."""
    supplier_data = [
        {"supplier_name": "Ferro Steel Ltd", "incoterm": "FOB", "price_display": "$1,420/tonne"},
        {"supplier_name": "Ferro Metals Inc", "incoterm": "CIF", "price_display": "$1,280/tonne"},
        {"supplier_name": "FerroTech Global", "incoterm": "DDP", "price_display": "$1,510/tonne"},
    ]
    ne, _ = normalize_evidence(
        "Comparing three similarly-named suppliers.", "quote_comparison", {}, {},
        supplier_specific_evidence=supplier_data,
    )
    assert ne.supplier_by_name("Ferro Steel Ltd").incoterm == "FOB"
    assert ne.supplier_by_name("Ferro Steel Ltd").price_display == "$1,420/tonne"
    assert ne.supplier_by_name("Ferro Metals Inc").incoterm == "CIF"
    assert ne.supplier_by_name("Ferro Metals Inc").price_display == "$1,280/tonne"
    assert ne.supplier_by_name("FerroTech Global").incoterm == "DDP"
    assert ne.supplier_by_name("FerroTech Global").price_display == "$1,510/tonne"
