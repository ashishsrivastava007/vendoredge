"""
Supplier-Claim Taxonomy — Complete Adversarial Suite.

Covers the full approved design: qualification/approval, certification,
preferred-supplier status, and performance characterization (metric-
anchored vs unanchored), all evidence-driven and supplier-specific --
never a keyword blacklist, never cross-supplier bleed, never UNKNOWN
silently becoming NO.

The exact real Atlas/EuroMotion case (the bug that triggered this whole
redesign) is used directly, not paraphrased, as the primary proof point.
"""
from app.pipeline.claim_integrity import check_all_claim_overstatements
from app.pipeline.normalize import normalize_evidence
from app.models import CommercialPosition, Confidence, ConfidenceFactor

_CONF = Confidence(
    level="medium",
    factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
    derivation_note="n",
)


def _pos(reasoning):
    return CommercialPosition(
        recommendation="x", commercial_insights=["a"], reasoning=reasoning,
        confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
    )


def _price_increase_case(suppliers):
    return normalize_evidence(
        "Incumbent requests an increase; alternative supplier exists.", "price_increase",
        {"current_price_or_terms": "x", "suppliers_stated_justification": "x",
         "how_critical_is_this_supplier_relationship": "x"},
        {"requested_change_percent": 10.0}, supplier_specific_evidence=suppliers,
    )


def _supplier_flagged(issues, name):
    return any(i.split("'")[1] == name for i in issues)


# ============================================================
# 1. The exact real Atlas/EuroMotion case
# ============================================================

def test_exact_real_atlas_euromotion_case_next_action_sentence():
    """The first real sentence from the actual deployed response."""
    suppliers = [
        {"supplier_name": "Atlas Bearings", "otif_percent": 99.2, "defect_rate_percent": 0.5, "is_incumbent": True},
        {"supplier_name": "EuroMotion Poland", "otif_percent": 97.0, "defect_rate_percent": 1.1, "capacity_percent": 30},
    ]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos(
        "Your 12% increase moves in the opposite direction of our current baseline, and we have "
        "a qualified DDP alternative at €43/unit -- before we discuss any adjustment, we need an "
        "audited, index-linked breakdown showing steel, energy and labour genuinely justify a "
        "double-digit move."
    )
    issues = check_all_claim_overstatements(pos, ne, "x")
    # This specific sentence never names EuroMotion at all -- a real,
    # honest limitation of name-based attribution, not a false negative
    # this suite should hide. Documented explicitly, not silently passed.
    assert issues == [], (
        "Known, documented limitation: a claim with no supplier name in the sentence at all "
        "cannot be attributed by this mechanism. See the second real sentence test below, which "
        "IS the one that genuinely triggers detection in the real deployed response."
    )


def test_exact_real_atlas_euromotion_case_approach_used_sentence():
    """The second real sentence -- the one that genuinely names EuroMotion
    and is the actual, provable catch."""
    suppliers = [
        {"supplier_name": "Atlas Bearings", "otif_percent": 99.2, "defect_rate_percent": 0.5, "is_incumbent": True},
        {"supplier_name": "EuroMotion Poland", "otif_percent": 97.0, "defect_rate_percent": 1.1, "capacity_percent": 30},
    ]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos(
        "Approach used: This is a BATNA-strengthening negotiation: EuroMotion's qualified quote "
        "gives credible leverage against Atlas's unverified increase even though full substitution "
        "isn't currently operationally viable."
    )
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert _supplier_flagged(issues, "EuroMotion Poland"), "PASS/FAIL: FAIL -- the real bug must be caught"
    assert not _supplier_flagged(issues, "Atlas Bearings"), "Atlas must never be flagged for EuroMotion's claim"


# ============================================================
# 2. UNKNOWN vs NEGATIVE evidence -- qualification and certification
# ============================================================

def test_unknown_qualification_never_manufactured_as_negative():
    """Core principle: silence must produce 'unknown', and a response
    correctly describing it as such (or simply not claiming qualified)
    must never be blocked for saying something TRUE."""
    suppliers = [{"supplier_name": "NewSupplier Inc"}]  # zero attributes stated
    ne, _ = _price_increase_case(suppliers)
    assert ne.supplier_by_name("NewSupplier Inc").qualification_status == "unknown"
    # A genuinely correct, hedged statement must be ALLOWED.
    pos = _pos("NewSupplier Inc's qualification status has not yet been confirmed.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert not _supplier_flagged(issues, "NewSupplier Inc")


def test_explicit_negative_qualification_correctly_stated_is_allowed():
    """The reverse case: evidence explicitly says NOT qualified, and the
    response correctly, honestly says so -- must be allowed, not
    mistaken for the unhedged positive claim."""
    suppliers = [{"supplier_name": "NewSupplier Inc", "qualification_status": "not_started"}]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("NewSupplier Inc is not qualified yet and would need vetting before consideration.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert not _supplier_flagged(issues, "NewSupplier Inc"), "A correct negative statement must never be blocked"


def test_unknown_certification_never_manufactured_as_negative():
    suppliers = [{"supplier_name": "NewSupplier Inc"}]
    ne, _ = _price_increase_case(suppliers)
    assert ne.supplier_by_name("NewSupplier Inc").certification_status == "unknown"


def test_explicit_negative_certification_correctly_stated_is_allowed():
    suppliers = [{"supplier_name": "NewSupplier Inc", "certification_status": "not_certified"}]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("NewSupplier Inc is not certified and would need to pursue certification.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert not _supplier_flagged(issues, "NewSupplier Inc")


# ============================================================
# 3. Certified vs unknown certification
# ============================================================

def test_certification_explicitly_supported_is_allowed():
    suppliers = [{"supplier_name": "Acme Corp", "certification_status": "certified", "certification_detail": "ISO 9001"}]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("Acme Corp is ISO-certified and meets our quality baseline.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert not _supplier_flagged(issues, "Acme Corp")


def test_certification_unsupported_is_blocked():
    suppliers = [{"supplier_name": "Acme Corp"}]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("Acme Corp is a certified supplier ready for immediate onboarding.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert _supplier_flagged(issues, "Acme Corp")


def test_wrong_specific_certification_named_is_blocked():
    """Certified, but the WRONG certification is claimed -- must still block."""
    suppliers = [{"supplier_name": "Acme Corp", "certification_status": "certified", "certification_detail": "ISO 9001"}]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("Acme Corp is IATF-certified for automotive quality standards.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert _supplier_flagged(issues, "Acme Corp"), "A named certification that doesn't match the real one must be blocked"


# ============================================================
# 4. Preferred vs unknown
# ============================================================

def test_preferred_status_unsupported_is_blocked():
    suppliers = [{"supplier_name": "Acme Corp"}]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("Acme Corp is our preferred supplier for this category.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert _supplier_flagged(issues, "Acme Corp")


def test_preferred_status_supported_is_allowed():
    suppliers = [{"supplier_name": "Acme Corp", "preferred_supplier_status": "preferred"}]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("Acme Corp is our preferred supplier for this category.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert not _supplier_flagged(issues, "Acme Corp")


# ============================================================
# 5. Metric-anchored vs unanchored performance claims
# ============================================================

def test_metric_anchored_reliable_claim_is_allowed():
    """Tier A: a real, cited OTIF figure for THIS supplier justifies the
    observation -- the exact real Atlas sentence from the deployed case."""
    suppliers = [{"supplier_name": "Atlas Bearings", "otif_percent": 99.2, "defect_rate_percent": 0.5, "is_incumbent": True}]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("Atlas's 99.2% OTIF and 0.5% defect rate materially outperform the alternative.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert not _supplier_flagged(issues, "Atlas Bearings"), "A real, cited metric must never be blocked"


def test_unanchored_status_claim_is_blocked():
    """Tier B: no track record, no cited figure nearby -- must block."""
    suppliers = [{"supplier_name": "EuroMotion Poland"}]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("EuroMotion is an established, reliable partner for this category.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert _supplier_flagged(issues, "EuroMotion Poland")


def test_unanchored_claim_not_rescued_by_metrics_elsewhere_in_response():
    """Critical proof: a real metric existing elsewhere in the SAME
    response must not silently unlock a status claim made without a
    cited figure nearby."""
    suppliers = [{"supplier_name": "EuroMotion Poland", "otif_percent": 97.0}]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos(
        "EuroMotion reports 97% OTIF on recent shipments. "
        "Overall, EuroMotion has a proven track record in this category."
    )
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert _supplier_flagged(issues, "EuroMotion Poland"), (
        "The 97% figure is in a DIFFERENT sentence from the 'proven track record' claim -- "
        "must still block, proving numbers aren't borrowed across sentences"
    )


def test_track_record_support_allows_unanchored_claim():
    suppliers = [{"supplier_name": "Atlas Bearings", "production_history_status": "established", "is_incumbent": True}]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("Atlas has a proven track record as our long-standing incumbent.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert not _supplier_flagged(issues, "Atlas Bearings")


# ============================================================
# 6. Cross-supplier contamination -- the critical proof
# ============================================================

def test_supplier_a_qualified_b_unknown_only_b_blocked():
    suppliers = [
        {"supplier_name": "Atlas Bearings", "qualification_status": "complete", "is_incumbent": True},
        {"supplier_name": "EuroMotion Poland"},
    ]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("Atlas is a qualified, long-standing partner. EuroMotion is also a qualified alternative.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert not _supplier_flagged(issues, "Atlas Bearings"), "Atlas's claim IS supported -- must not block"
    assert _supplier_flagged(issues, "EuroMotion Poland"), "EuroMotion's claim is NOT supported -- must block"


def test_reverse_supplier_a_unknown_b_qualified_only_a_blocked():
    suppliers = [
        {"supplier_name": "Atlas Bearings", "is_incumbent": True},
        {"supplier_name": "EuroMotion Poland", "qualification_status": "complete"},
    ]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("Atlas is a qualified partner. EuroMotion is also a qualified alternative.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert _supplier_flagged(issues, "Atlas Bearings")
    assert not _supplier_flagged(issues, "EuroMotion Poland")


def test_same_sentence_two_suppliers_different_status_no_bleed():
    """The hardest real version, taken directly from the actual deployed
    response's structure: both suppliers in ONE sentence, only one has
    a genuine claim made about them."""
    suppliers = [
        {"supplier_name": "Atlas Bearings", "is_incumbent": True},
        {"supplier_name": "EuroMotion Poland"},
    ]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("EuroMotion is a qualified DDP alternative and its quote gives credible leverage against Atlas.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert _supplier_flagged(issues, "EuroMotion Poland")
    assert not _supplier_flagged(issues, "Atlas Bearings"), (
        "PASS/FAIL: FAIL if Atlas is flagged -- Atlas merely co-occurs in the sentence; "
        "the qualification claim was never about Atlas"
    )


def test_same_sentence_both_suppliers_explicitly_claimed_both_evaluated_independently():
    """A harder variant still: BOTH suppliers explicitly claimed qualified
    in ONE sentence, opposite real statuses -- each must be judged purely
    on their own evidence."""
    suppliers = [
        {"supplier_name": "Atlas Bearings", "qualification_status": "complete", "is_incumbent": True},
        {"supplier_name": "EuroMotion Poland"},
    ]
    ne, _ = _price_increase_case(suppliers)
    pos = _pos("Both Atlas and EuroMotion are qualified suppliers for this category.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert not _supplier_flagged(issues, "Atlas Bearings")
    assert _supplier_flagged(issues, "EuroMotion Poland")


# ============================================================
# 7. No-evidence supplier
# ============================================================

def test_supplier_with_zero_attributes_still_gets_checked():
    suppliers = [{"supplier_name": "Mystery Supplier Co"}]
    ne, _ = _price_increase_case(suppliers)
    s = ne.supplier_by_name("Mystery Supplier Co")
    assert s.qualification_status == "unknown"
    assert s.certification_status == "unknown"
    assert s.preferred_supplier_status == "unknown"
    pos = _pos("Mystery Supplier Co is a qualified, certified, preferred alternative.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert _supplier_flagged(issues, "Mystery Supplier Co")


# ============================================================
# 8. Deliberate break
# ============================================================

def test_deliberate_break_withholding_supplier_entry_reproduces_original_bug():
    """
    MANDATORY deliberate-break proof. Simulates the ORIGINAL bug directly:
    EuroMotion never captured as a SupplierEvidence entry at all (the
    actual root cause), and confirms the exact real claim genuinely goes
    uncaught in that state -- proving the fix, not luck, is what closes it.
    """
    suppliers_missing_euromotion = [
        {"supplier_name": "Atlas Bearings", "otif_percent": 99.2, "is_incumbent": True},
    ]
    ne, _ = _price_increase_case(suppliers_missing_euromotion)
    assert ne.supplier_by_name("EuroMotion Poland") is None, "Confirms EuroMotion genuinely has no entry -- the original bug state"

    pos = _pos("EuroMotion's qualified quote gives credible leverage against Atlas's unverified increase.")
    issues = check_all_claim_overstatements(pos, ne, "x")
    assert not _supplier_flagged(issues, "EuroMotion Poland"), (
        "Confirms the original bug reproduces exactly when the supplier entry is withheld -- "
        "the fix is genuinely about extraction reachability, not the check logic itself"
    )


# ============================================================
# Incumbent safety net
# ============================================================

def test_incumbent_always_gets_entry_even_if_model_omits_it():
    """The deterministic safety net -- proven at the normalize_evidence
    level, not dependent on prompt-following alone."""
    ne, _ = normalize_evidence(
        "Atlas requests an increase.", "price_increase",
        {"current_price_or_terms": "x", "supplier_name": "Atlas Bearings",
         "suppliers_stated_justification": "x", "how_critical_is_this_supplier_relationship": "x"},
        {"requested_change_percent": 10.0}, supplier_specific_evidence=None,
    )
    atlas = ne.supplier_by_name("Atlas Bearings")
    assert atlas is not None
    assert atlas.is_incumbent is True
    assert atlas.qualification_status == "unknown"
