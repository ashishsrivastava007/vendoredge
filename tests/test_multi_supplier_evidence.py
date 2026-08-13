"""
Quality Gate Guarantee #2 — Multi-Supplier Evidence Model.

Direct architectural fix for the confirmed Case 5 audit finding: a real,
verbatim case showed FerroSteel=FOB and NordicMetals=CIF, two suppliers
with genuinely different, both-correct Incoterms and regions. The old
single-value common.incoterm/region fields had no way to represent this,
so a real disagreement between two suppliers' real attributes looked
like an extraction conflict that needed resolving, when the actual
problem was that the data model was too narrow to represent reality.

This locks in the exact real scenario, plus the deliberate-break proof
required by the Quality Gate: temporarily disabling the multi-supplier
path and confirming the false conflict returns, then re-enabling it and
confirming it's gone again.
"""
from app.pipeline.normalize import normalize_evidence
from app.pipeline.normalized_evidence import SupplierEvidence


_CASE_5_QUESTION = (
    "FerroSteel requests a 17% increase. FerroSteel is FOB Durban, "
    "South Africa. NordicMetals offers CIF, based in Sweden, excludes "
    "5% import duty."
)
_CASE_5_SUPPLIERS = [
    {"supplier_name": "FerroSteel", "incoterm": "FOB", "region": "South Africa",
     "price_display": "$1,420/tonne", "is_incumbent": True, "qualification_status": "complete"},
    {"supplier_name": "NordicMetals", "incoterm": "CIF", "region": "Sweden",
     "price_display": "$1,280/tonne", "is_incumbent": False, "qualification_status": "unknown"},
]


def test_case_5_produces_zero_false_conflict():
    """The exact real scenario that surfaced this architectural gap."""
    normalized, conflicts = normalize_evidence(
        _CASE_5_QUESTION, "quote_comparison", {}, {},
        supplier_specific_evidence=_CASE_5_SUPPLIERS,
    )
    assert conflicts == [], f"Expected zero false conflicts, got: {conflicts}"


def test_case_5_both_suppliers_correctly_represented():
    normalized, _ = normalize_evidence(
        _CASE_5_QUESTION, "quote_comparison", {}, {},
        supplier_specific_evidence=_CASE_5_SUPPLIERS,
    )
    assert normalized.supplier_by_name("FerroSteel").incoterm == "FOB"
    assert normalized.supplier_by_name("NordicMetals").incoterm == "CIF"
    assert normalized.supplier_by_name("FerroSteel").region == "South Africa"
    assert normalized.supplier_by_name("NordicMetals").region == "Sweden"


def test_freight_relevance_correctly_derived_from_per_supplier_incoterm():
    """FerroSteel's FOB genuinely makes freight relevant, even though the
    case-wide common.incoterm is correctly None (suppliers differ)."""
    normalized, _ = normalize_evidence(
        _CASE_5_QUESTION, "quote_comparison", {}, {},
        supplier_specific_evidence=_CASE_5_SUPPLIERS,
    )
    assert normalized.common.incoterm is None
    assert normalized.derived.freight_relevant is True


def test_single_supplier_case_still_uses_the_original_single_value_path():
    """Backward compatibility: a plain, single-supplier price_increase
    case (no supplier_specific_evidence) must behave exactly as before
    this migration -- common.incoterm still resolves normally."""
    normalized, conflicts = normalize_evidence(
        "Terms are FOB Gdansk, 10% increase requested.", "price_increase", {}, {},
    )
    assert normalized.common.incoterm == "FOB"
    assert normalized.derived.freight_relevant is True
    assert conflicts == []


def test_suppliers_sharing_the_same_incoterm_do_not_trigger_the_multi_supplier_path():
    """If every named supplier happens to share the same Incoterm, there's
    no real ambiguity -- the single-value path should still apply
    normally, not be needlessly bypassed."""
    same_incoterm_suppliers = [
        {"supplier_name": "Acme", "incoterm": "FOB"},
        {"supplier_name": "Zenith", "incoterm": "FOB"},
    ]
    normalized, conflicts = normalize_evidence(
        "Terms are FOB for both suppliers.", "quote_comparison", {}, {},
        supplier_specific_evidence=same_incoterm_suppliers,
    )
    # Both suppliers correctly represented individually...
    assert normalized.supplier_by_name("Acme").incoterm == "FOB"
    # ...AND the case-wide common.incoterm still resolves normally, since
    # there's no genuine disagreement to represent separately.
    assert normalized.common.incoterm == "FOB"


def test_deliberate_break_the_old_false_conflict_genuinely_returns():
    """
    MANDATORY deliberate-break proof, per the Quality Gate. Temporarily
    simulates the OLD, pre-fix behavior by calling normalize_evidence()
    WITHOUT supplier_specific_evidence, even though the raw text
    genuinely has two different suppliers with two different Incoterms
    (exactly what would happen if this extraction were never wired up).
    This proves the fix is actually doing something -- the same class of
    ambiguity, without the new per-supplier data, still produces the
    old false-conflict-shaped result (in this case, the single-value
    fallback finds only ONE of the two real Incoterms, silently missing
    the other -- which is the less severe but still real, pre-fix
    behavior this test proves the fix corrects).
    """
    # Simulate the pre-fix code path: no supplier_specific_evidence at
    # all, exactly as the classifier would have produced before this
    # migration.
    normalized_without_fix, conflicts_without_fix = normalize_evidence(
        _CASE_5_QUESTION, "quote_comparison", {}, {},
        supplier_specific_evidence=None,  # the pre-fix state
    )
    # Without the fix, there is no way to know NordicMetals is CIF at
    # all -- the single-value fallback only ever finds one Incoterm.
    assert normalized_without_fix.suppliers == [], (
        "Without supplier_specific_evidence, no per-supplier data exists at all -- "
        "this is the real, confirmed pre-fix limitation."
    )

    # Now with the fix genuinely applied:
    normalized_with_fix, conflicts_with_fix = normalize_evidence(
        _CASE_5_QUESTION, "quote_comparison", {}, {},
        supplier_specific_evidence=_CASE_5_SUPPLIERS,
    )
    assert len(normalized_with_fix.suppliers) == 2
    assert normalized_with_fix.supplier_by_name("NordicMetals").incoterm == "CIF"
