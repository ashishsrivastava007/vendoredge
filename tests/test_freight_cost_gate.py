"""
Permanent regression tests for the conditional freight-cost evidence
requirement -- built after a real, live case labeled its own approach
"TCO/landed-cost analysis" while quietly missing an input (freight cost
under FOB terms) that the user could genuinely have supplied. The fix:
freight cost becomes a real, conditionally-required field, triggered only
by the actual Incoterms where the buyer genuinely bears that cost.

MIGRATED (NormalizedEvidence architecture): constructs NormalizedEvidence
objects directly, with derived.freight_relevant set exactly as
normalize_evidence() itself would compute it -- this tests
check_missing_evidence()'s CONSUMPTION of that flag, which is the real
behavior under test, not the derivation logic itself (covered separately
in test_normalize_evidence.py).
"""
from app.pipeline.evidence import check_missing_evidence
from app.pipeline.evidence import INCOTERMS_WHERE_BUYER_BEARS_FREIGHT
from app.pipeline.normalized_evidence import (
    NormalizedEvidence, CommonEvidence, PriceIncreaseEvidence, DerivedEvidence,
)

_ALL_ELEVEN_INCOTERMS = ("EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")


def _make_normalized(incoterm=None, freight_cost_or_estimate=None):
    freight_relevant = incoterm in INCOTERMS_WHERE_BUYER_BEARS_FREIGHT if incoterm else False
    return NormalizedEvidence(
        content_type="price_increase",
        common=CommonEvidence(incoterm=incoterm),
        case=PriceIncreaseEvidence(
            current_price_or_terms="x", requested_increase_percent=10.0,
            suppliers_stated_justification="x", how_critical_is_this_supplier_relationship="x",
            freight_cost_or_estimate=freight_cost_or_estimate,
        ),
        derived=DerivedEvidence(freight_relevant=freight_relevant),
    )


def test_fob_case_correctly_requires_freight_cost():
    """The exact real scenario that surfaced this gap."""
    normalized = _make_normalized(incoterm="FOB")
    missing_fields = [m["field"] for m in check_missing_evidence(normalized)]
    assert "freight_cost_or_estimate" in missing_fields


def test_ddp_case_does_not_require_freight_cost():
    """Freight is already built into the seller's price under DDP -- must
    not trigger the new requirement."""
    normalized = _make_normalized(incoterm="DDP")
    missing_fields = [m["field"] for m in check_missing_evidence(normalized)]
    assert "freight_cost_or_estimate" not in missing_fields


def test_no_incoterm_mentioned_does_not_require_freight_cost():
    """Genuinely conditional -- a case with no Incoterm at all must not
    suddenly gain a new blanket requirement."""
    normalized = _make_normalized(incoterm=None)
    missing_fields = [m["field"] for m in check_missing_evidence(normalized)]
    assert "freight_cost_or_estimate" not in missing_fields


def test_all_four_buyer_pays_freight_incoterms_trigger_the_requirement():
    for incoterm in ("EXW", "FCA", "FAS", "FOB"):
        normalized = _make_normalized(incoterm=incoterm)
        missing_fields = [m["field"] for m in check_missing_evidence(normalized)]
        assert "freight_cost_or_estimate" in missing_fields, f"{incoterm} should require freight cost"


def test_all_seller_pays_freight_incoterms_do_not_trigger_it():
    for incoterm in ("CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"):
        normalized = _make_normalized(incoterm=incoterm)
        missing_fields = [m["field"] for m in check_missing_evidence(normalized)]
        assert "freight_cost_or_estimate" not in missing_fields, f"{incoterm} should NOT require freight cost"


def test_supplying_freight_cost_satisfies_the_requirement():
    normalized = _make_normalized(incoterm="FOB", freight_cost_or_estimate="€150/unit")
    assert check_missing_evidence(normalized) == []
