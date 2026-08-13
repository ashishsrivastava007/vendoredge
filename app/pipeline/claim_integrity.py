"""
Quality Gate Guarantee #4 — Evidence → Claim Integrity Gate.
Generalized beyond qualification status, per the explicit follow-up
request: "Don't stop at 'qualified.'"

VendorEdge must never make a stronger claim than the evidence supports.
Each check below targets a genuinely different evidence type -- these
are deliberately separate, narrow, pattern-based functions, not one
vague "does this sound too confident" judgment call. A second AI call to
police the first AI call's confidence would just add a new, equally
fallible judgment, not a real guarantee. Each check compares a specific
word pattern against a specific, real piece of structured evidence.
"""
import re
from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _supplier_referenced_in(supplier_name: str, text: str) -> bool:
    """
    Real-world prose almost never repeats a full, multi-word supplier
    name every time -- "EuroMotion Poland" becomes "EuroMotion" after
    the first mention, exactly as it did in the real case that exposed
    this gap. Checking only the exact full name would silently miss
    every claim-integrity check for any supplier referred to by a short
    form, which in practice is most references after the first. Matches
    on the full name OR the first significant word of it (4+ characters,
    to avoid false positives on short, generic first words).
    """
    if supplier_name in text:
        return True
    first_word = supplier_name.split()[0] if supplier_name else ""
    if len(first_word) >= 4 and first_word in text:
        return True
    return False


_PROXIMITY_WINDOW_WORDS = 5


def _words_near(sentence: str, match_start: int, window_words: int = _PROXIMITY_WINDOW_WORDS) -> str:
    """Shared word-based windowing, used both for supplier attribution
    and for Tier A metric-anchoring -- one consistent notion of "nearby"
    throughout this module."""
    words = sentence.split()
    prefix = sentence[:match_start]
    match_word_index = len(prefix.split())
    window_word_start = max(0, match_word_index - window_words)
    window_word_end = min(len(words), match_word_index + window_words + 1)
    return " ".join(words[window_word_start:window_word_end])


def _claim_attributed_to_supplier(supplier_name: str, sentence: str, match_start: int, match_end: int) -> bool:
    """
    Real, critical finding from testing against the actual deployed
    response: a sentence can genuinely mention two suppliers while a
    strength claim belongs to only one of them -- "EuroMotion is a
    qualified DDP alternative... against Atlas" names Atlas too, but
    "qualified" was never a claim ABOUT Atlas. Sentence-level
    co-occurrence alone would have flagged both, silently borrowing
    EuroMotion's (lack of) evidence onto Atlas -- exactly the
    cross-supplier bleed this firewall must never produce.

    Word-based proximity, not character-based: an initial character-count
    window was calibrated against a shorter test sentence and proved too
    generous once tested against the full, real, longer sentence -- a
    genuine miscalibration found by testing, not assumed correct. Word
    count is more linguistically stable across sentence lengths than a
    fixed character count.
    """
    nearby = _words_near(sentence, match_start)
    return _supplier_referenced_in(supplier_name, nearby)


# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", text or "")


_HEDGE_WORDS = [
    "partial", "partially", "progress", "underway", "pending", "incomplete",
    "in-progress", "not yet", "still being", "%", "percent", "may be",
    "believed to be", "reportedly", "unconfirmed",
    # Targeted negation phrases -- precise, not a broad "not" catch-all
    # (which would over-hedge unrelated sentence content). These exist
    # specifically so a CORRECT negative statement ("EuroMotion is not
    # qualified") is never mistaken for the unhedged overstatement this
    # firewall exists to catch.
    "not qualified", "not certified", "not approved", "not preferred",
    "not a qualified", "not a certified", "not a preferred", "not a verified",
    "isn't qualified", "isn't certified", "isn't approved", "isn't preferred",
]


def _has_hedge(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(hedge in lowered for hedge in _HEDGE_WORDS)


# ---------------------------------------------------------------------------
# Check 1: Qualification / approval strength (original, unchanged)
# ---------------------------------------------------------------------------

_UNQUALIFIED_STRENGTH_PATTERNS = [
    r"\bqualified\b", r"\bapproved\b", r"\bis a verified\b", r"\bverified supplier\b",
]
_CERTIFICATION_STRENGTH_PATTERNS = [
    r"\bcertified\b", r"\bis compliant\b", r"\bmeets compliance\b",
    r"\b[\w]+-certified\b",  # a NAMED certification, e.g. "ISO-certified", "IATF-certified"
]
_PREFERRED_STRENGTH_PATTERNS = [
    r"\bpreferred supplier\b", r"\bpreferred vendor\b", r"\bour preferred\b",
]
_PERFORMANCE_CHARACTERIZATION_PATTERNS = [
    r"\bproven supplier\b", r"\ba proven\b", r"\bestablished, reliable\b", r"\breliable partner\b",
    r"\bhas a reliable track record\b", r"\bhas a proven track record\b",
]


def check_qualification_overstatement(
    position: CommercialPosition, normalized: NormalizedEvidence
) -> list[str]:
    """
    For every supplier whose real, structured qualification_status is
    genuinely NOT "complete," checks whether the response's own prose
    describes them with unhedged "qualified"/"approved"/"certified"/
    "compliant" language -- all real synonyms for the same overstatement,
    now checked together.
    """
    issues = []
    text = position.reasoning or ""

    for supplier in normalized.suppliers:
        if supplier.qualification_status == "complete":
            continue
        if not _supplier_referenced_in(supplier.supplier_name, text):
            continue

        for sentence in _split_sentences(text):
            if not _supplier_referenced_in(supplier.supplier_name, sentence):
                continue
            lowered = sentence.lower()
            for pattern in _UNQUALIFIED_STRENGTH_PATTERNS:
                match = re.search(pattern, lowered)
                if not match or _has_hedge(sentence):
                    continue
                if not _claim_attributed_to_supplier(supplier.supplier_name, sentence, match.start(), match.end()):
                    continue  # this supplier merely co-occurs in the sentence; the claim belongs to someone else
                issues.append(
                    f"'{supplier.supplier_name}' is described with unhedged qualification/"
                    f"approval/certification language (\"{sentence.strip()}\"), but the real "
                    f"evidence shows qualification_status='{supplier.qualification_status}'"
                    + (f" ({supplier.qualification_percent}% complete)" if supplier.qualification_percent else "")
                    + " -- this overstates supplier readiness beyond what the evidence supports."
                )

    return issues


def check_certification_overstatement(position: CommercialPosition, normalized: NormalizedEvidence) -> list[str]:
    """
    Separate from qualification deliberately: a supplier can be
    qualification_status='complete' while never having stated any
    certification at all -- these are different facts, and a generic
    qualification pass must never silently license a certification
    claim. Also catches an OVER-SPECIFIC claim: a named certification
    ("ISO-certified") that doesn't match what was actually evidenced.
    """
    issues = []
    text = position.reasoning or ""

    for supplier in normalized.suppliers:
        if not _supplier_referenced_in(supplier.supplier_name, text):
            continue
        for sentence in _split_sentences(text):
            if not _supplier_referenced_in(supplier.supplier_name, sentence):
                continue
            lowered = sentence.lower()
            for pattern in _CERTIFICATION_STRENGTH_PATTERNS:
                match = re.search(pattern, lowered)
                if not match or _has_hedge(sentence):
                    continue
                if not _claim_attributed_to_supplier(supplier.supplier_name, sentence, match.start(), match.end()):
                    continue
                if supplier.certification_status != "certified":
                    issues.append(
                        f"'{supplier.supplier_name}' is described as certified/compliant "
                        f"(\"{sentence.strip()}\"), but the real evidence shows "
                        f"certification_status='{supplier.certification_status}' -- this asserts "
                        f"a certification fact the evidence does not support."
                    )
                    continue
                # Certified, but is the SPECIFIC certification named the one
                # actually evidenced? A named cert not matching the real one
                # is still an unsupported claim, even though certification
                # generally is real.
                named_cert = match.group(0)
                if "-certified" in named_cert and supplier.certification_detail:
                    claimed = named_cert.split("-certified")[0].strip().lower()
                    real = supplier.certification_detail.lower()
                    if claimed not in real and real not in claimed:
                        issues.append(
                            f"'{supplier.supplier_name}' is described as \"{named_cert}\", but the "
                            f"evidence states the certification as '{supplier.certification_detail}' -- "
                            f"this names a specific certification the evidence does not support."
                        )

    return issues


def check_preferred_supplier_overstatement(position: CommercialPosition, normalized: NormalizedEvidence) -> list[str]:
    """Same pattern, third field: 'preferred supplier' is a real, distinct
    status claim, not implied by price, OTIF, or qualification alone."""
    issues = []
    text = position.reasoning or ""

    for supplier in normalized.suppliers:
        if supplier.preferred_supplier_status == "preferred":
            continue
        if not _supplier_referenced_in(supplier.supplier_name, text):
            continue
        for sentence in _split_sentences(text):
            if not _supplier_referenced_in(supplier.supplier_name, sentence):
                continue
            lowered = sentence.lower()
            for pattern in _PREFERRED_STRENGTH_PATTERNS:
                match = re.search(pattern, lowered)
                if not match or _has_hedge(sentence):
                    continue
                if not _claim_attributed_to_supplier(supplier.supplier_name, sentence, match.start(), match.end()):
                    continue
                issues.append(
                    f"'{supplier.supplier_name}' is described as a preferred supplier/vendor "
                    f"(\"{sentence.strip()}\"), but the real evidence shows "
                    f"preferred_supplier_status='{supplier.preferred_supplier_status}' -- this "
                    f"asserts a status the evidence does not support."
                )

    return issues


def check_performance_characterization_overstatement(position: CommercialPosition, normalized: NormalizedEvidence) -> list[str]:
    """
    Two-tier, deliberately not a single rule. Tier A (metric-anchored):
    a real OTIF/defect figure for THIS supplier cited in the same
    sentence always justifies a performance observation -- numbers speak
    for themselves. Tier B (status characterization): a general trait
    claim standing alone, with no cited figure nearby, requires
    production_history_status support -- real numbers existing
    ELSEWHERE in the response do not get silently borrowed to unlock a
    broad claim here.
    """
    issues = []
    text = position.reasoning or ""

    for supplier in normalized.suppliers:
        if not _supplier_referenced_in(supplier.supplier_name, text):
            continue
        for sentence in _split_sentences(text):
            if not _supplier_referenced_in(supplier.supplier_name, sentence):
                continue
            lowered = sentence.lower()
            for pattern in _PERFORMANCE_CHARACTERIZATION_PATTERNS:
                match = re.search(pattern, lowered)
                if not match or _has_hedge(sentence):
                    continue
                if not _claim_attributed_to_supplier(supplier.supplier_name, sentence, match.start(), match.end()):
                    continue
                # Tier A: this supplier's OWN real OTIF/defect figure is
                # cited NEAR the claim -- always allowed. Scoped to the
                # same proximity window as the claim attribution itself,
                # not "anywhere in the sentence" -- a sentence naming two
                # suppliers could cite ONE supplier's real percentage
                # while characterizing the OTHER as "reliable" with no
                # real basis; a sentence-wide metric search would have
                # silently let the second supplier borrow the first's
                # number. Only a percentage genuinely near THIS claim
                # counts as THIS supplier's own metric.
                nearby_text = _words_near(sentence, match.start())
                cites_own_metric = bool(re.search(r"\d+(\.\d+)?\s*%", nearby_text))
                if cites_own_metric:
                    continue
                # Tier B: requires real track-record support -- not
                # satisfied by numbers existing elsewhere in the response.
                if supplier.production_history_status not in ("established", "limited"):
                    issues.append(
                        f"'{supplier.supplier_name}' is characterized as proven/reliable/established "
                        f"(\"{sentence.strip()}\") without a cited figure in the same sentence, and "
                        f"production_history_status='{supplier.production_history_status}' -- this is a "
                        f"broad status claim the evidence does not support on its own."
                    )

    return issues


# ---------------------------------------------------------------------------
# Check 2: Verification / confirmation strength
# ---------------------------------------------------------------------------

_VERIFICATION_PATTERNS = [r"\bverified\b", r"\bconfirmed\b"]

# The only provenance sources that genuinely justify "verified"/"confirmed"
# language -- a fact independently agreed by two methods, or explicitly
# confirmed by the user. A single, unconfirmed extraction (LLM alone, or
# fallback alone) does not meet this bar.
_GENUINELY_VERIFIED_SOURCES = {"both_agree", "user_followup"}


def check_verification_overstatement(
    position: CommercialPosition, normalized: NormalizedEvidence
) -> list[str]:
    """
    "Verified" and "confirmed" are real, specific claims about HOW a fact
    was established, not just that it's true. A fact resolved by a
    single, unconfirmed extraction method (the model alone, or a regex
    fallback alone) was never actually verified or confirmed by anything
    -- calling it that overstates the actual provenance.
    """
    issues = []
    text = position.reasoning or ""

    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if not any(re.search(p, lowered) for p in _VERIFICATION_PATTERNS):
            continue
        if _has_hedge(sentence):
            continue
        # Market claims specifically may be genuinely verified via a real,
        # live search -- check that path separately (Check 3) rather than
        # flagging it here as unsupported.
        if "market" in lowered or "index" in lowered:
            continue

        # Does this sentence reference a specific field whose provenance
        # we can check? We check ALL load-bearing-shaped provenance
        # entries for a genuinely unverified source, since the sentence
        # itself doesn't cleanly map to one field name in free text.
        unverified_fields = [
            name for name, prov in normalized.provenance.items()
            if prov.source not in _GENUINELY_VERIFIED_SOURCES
        ]
        if unverified_fields:
            sources_seen = sorted(set(normalized.provenance[f].source for f in unverified_fields))
            issues.append(
                f"The response uses verification language (\"{sentence.strip()}\"), but at least "
                f"one relevant fact was resolved only by {', '.join(sources_seen)} "
                f"-- never independently confirmed by the model's own understanding or the user."
            )
            break  # one finding per response is enough signal; avoid noisy duplicates

    return issues


# ---------------------------------------------------------------------------
# Check 3: Market-support claims
# ---------------------------------------------------------------------------

_MARKET_SUPPORT_PATTERNS = [
    r"\bmarket[- ]supported\b", r"\bmarket data confirms\b",
    r"\bmarket index (?:confirms|supports|verifies)\b",
]


def check_market_support_overstatement(position: CommercialPosition) -> list[str]:
    """
    "Market-supported" or "market data confirms" is a specific claim that
    a real, live market check actually happened and actually backed up
    the number -- not that the model believes a market movement is
    plausible. If no real market verification ran at all for this case
    (market_verification_scope is None), this claim is unsupported.
    """
    issues = []
    text = position.reasoning or ""
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if any(re.search(p, lowered) for p in _MARKET_SUPPORT_PATTERNS):
            if position.market_verification_scope is None:
                issues.append(
                    f"The response claims market support (\"{sentence.strip()}\"), but no real "
                    f"market verification search was ever performed for this case "
                    f"(market_verification_scope is None) -- this claim is unsupported."
                )
    return issues


# ---------------------------------------------------------------------------
# Check 4: Comparative / superlative price claims
# ---------------------------------------------------------------------------

_SUPERLATIVE_PRICE_PATTERNS = [r"\bbest price\b", r"\blowest price\b", r"\bcheapest\b"]


def check_comparative_price_overstatement(
    position: CommercialPosition, normalized: NormalizedEvidence
) -> list[str]:
    """
    "Best price" or "lowest price" is inherently a comparison -- it
    requires at least two real suppliers with real, comparable price data
    to mean anything. Claiming it with only one supplier's price known is
    not a comparison, it's an assertion with nothing to compare against.
    """
    issues = []
    text = position.reasoning or ""
    suppliers_with_price = [s for s in normalized.suppliers if s.price_display or s.price_usd]

    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if any(re.search(p, lowered) for p in _SUPERLATIVE_PRICE_PATTERNS):
            if len(suppliers_with_price) < 2:
                issues.append(
                    f"The response claims a superlative price (\"{sentence.strip()}\"), but only "
                    f"{len(suppliers_with_price)} supplier(s) with real price data exist in evidence "
                    f"-- a genuine 'best' or 'lowest' claim requires at least two to compare."
                )
    return issues


# ---------------------------------------------------------------------------
# Check 5: Certainty / guarantee claims
# ---------------------------------------------------------------------------

# Deliberately targets a real FUTURE-OUTCOME certainty claim, not
# VendorEdge's own, already-established, legitimate use of "guaranteed"
# to mean "code-computed and verified" (e.g. "the guaranteed calculation
# shows...", used throughout this codebase's own prompt text). A real,
# found false-positive during testing: "guaranteed calculation" is not
# an overstatement, it's this product's own correct terminology.
_GUARANTEE_PATTERNS = [
    r"\bguaranteed to (?:save|deliver|achieve|result|reduce|increase)\b",
    r"\bguarantee(?:s)? (?:that|a) (?:saving|reduction|outcome|result)\b",
    r"\bguaranteed saving\b", r"\bguaranteed outcome\b", r"\bguaranteed result\b",
]


def check_certainty_overstatement(position: CommercialPosition) -> list[str]:
    """
    A prospective commercial recommendation is inherently a forecast, not
    a certainty -- nothing about a future negotiation outcome, future
    savings, or future supplier performance can genuinely be
    "guaranteed" by an analysis performed today. This is one of the very
    few checks that doesn't need a specific counter-fact to compare
    against: the claim type itself is structurally incompatible with what
    VendorEdge can actually know about the future.
    """
    issues = []
    text = position.reasoning or ""
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if any(re.search(p, lowered) for p in _GUARANTEE_PATTERNS):
            issues.append(
                f"The response uses certainty language (\"{sentence.strip()}\") about a prospective "
                f"commercial outcome -- no future negotiation result, saving, or supplier "
                f"performance can genuinely be guaranteed by an analysis performed today."
            )
    return issues


# ---------------------------------------------------------------------------
# Check 6: Achievement claims (past-tense savings)
# ---------------------------------------------------------------------------

_ACHIEVEMENT_PATTERNS = [
    r"\bsavings? achieved\b", r"\bcost saving achieved\b", r"\bhas saved\b", r"\balready saved\b",
]


def check_achievement_overstatement(position: CommercialPosition, is_continuation: bool = False) -> list[str]:
    """
    "Savings achieved" is a past-tense, retrospective claim -- it asserts
    something actually happened, not that it's projected or recommended.
    A fresh, prospective recommendation has no access to real outcome
    data and can only speak to POTENTIAL savings. Only a genuine
    continuation case, referencing real recorded history, could honestly
    use achievement language -- and even then, only about the past case,
    not the current recommendation.
    """
    issues = []
    if is_continuation:
        return issues  # a continuation case may legitimately reference real past outcomes
    text = position.reasoning or ""
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if any(re.search(p, lowered) for p in _ACHIEVEMENT_PATTERNS):
            issues.append(
                f"The response uses past-tense achievement language (\"{sentence.strip()}\") for a "
                f"fresh, prospective recommendation -- this case has no real outcome data yet, "
                f"only a projection; 'achieved' claims a result that hasn't actually happened."
            )
    return issues


# ---------------------------------------------------------------------------
# Check 7: Contract-status claims
# ---------------------------------------------------------------------------

_CONTRACT_STATUS_PATTERNS = [r"\bunder contract\b", r"\bcontracted supplier\b", r"\bis contracted\b"]


def check_contract_status_overstatement(position: CommercialPosition, raw_question: str) -> list[str]:
    """
    "Under contract" is a specific legal-status claim VendorEdge has no
    independent way to verify -- it can only be honest if the user's own
    original text actually stated it. If the phrase never appeared in
    the raw input at all, the response inventing contract status is a
    real overstatement, not a reasonable inference.
    """
    issues = []
    text = position.reasoning or ""
    raw_lower = (raw_question or "").lower()
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if any(re.search(p, lowered) for p in _CONTRACT_STATUS_PATTERNS):
            if "contract" not in raw_lower:
                issues.append(
                    f"The response asserts a contract status (\"{sentence.strip()}\"), but the "
                    f"original question never mentioned any contract at all -- this is an "
                    f"invented legal-status claim, not a reasonable inference from evidence."
                )
    return issues


# ---------------------------------------------------------------------------
# Check 8: Lead-time plausibility
# ---------------------------------------------------------------------------

_CROSS_BORDER_LEAD_TIME_FLOOR_WEEKS = 1.0


def check_lead_time_plausibility(position: CommercialPosition, normalized: NormalizedEvidence) -> list[str]:
    """
    Production Hardening fix for the confirmed red-team finding: a
    supplier claiming near-instant delivery from overseas ("China-based,
    FOB terms, 3-day delivery") passed through with zero validation.

    Deliberately narrow, to avoid false positives per instruction: only
    fires when a supplier's OWN region is genuinely stated (real
    cross-border signal, the same pattern already used for
    duty_relevant) AND their stated lead time is below a conservative
    1-week floor. A domestic case, or a supplier with no stated region
    at all, is never touched by this check -- real ocean/air freight
    plus customs clearance has a hard physical floor that doesn't apply
    to genuinely domestic logistics.

    Consistent with every other check here: if the model's OWN reasoning
    already flags the implausibility (e.g. "verify this lead time" or
    "unrealistic given customs"), there's nothing to correct -- only
    silence about a real, checkable red flag is worth a retry.
    """
    issues = []
    text = (position.reasoning or "").lower()
    for supplier in normalized.suppliers:
        if not supplier.region:
            continue  # no cross-border signal at all -- never flagged
        if supplier.lead_time_weeks is None:
            continue
        if supplier.lead_time_weeks < _CROSS_BORDER_LEAD_TIME_FLOOR_WEEKS:
            if _has_hedge(text) or "verify" in text or "unrealistic" in text or "implausible" in text:
                continue  # the model already caught and flagged this -- nothing to correct
            issues.append(
                f"'{supplier.supplier_name}' claims a {supplier.lead_time_weeks} week lead time "
                f"from {supplier.region} -- physically implausible for real cross-border logistics "
                f"(ocean/air freight plus customs clearance has a real floor this doesn't account for), "
                f"and the response doesn't flag this as a concern."
            )
    return issues


# ---------------------------------------------------------------------------
# Check 9: Material Caveat Ledger - claim + caveat integrity
# ---------------------------------------------------------------------------

_QUALIFICATION_STRENGTH_PATTERNS = [
    r"\bqualified\b", r"\btechnically qualified\b", r"\bapproved\b",
]
_PRODUCTION_HISTORY_CAVEAT_PATTERNS = [
    "no production history", "not production-proven", "unproven in production",
    "limited production history", "no historical performance", "no track record",
    "not yet production", "no production track record",
]


def check_material_caveat_omission(position: CommercialPosition, normalized: NormalizedEvidence) -> list[str]:
    """
    Not a keyword filter -- a structured rule over real evidence fields.
    A supplier can be genuinely, technically qualified while having zero
    real production track record; the response's own text must pair the
    two facts, not state the positive claim alone. This is deliberately
    different from check_qualification_overstatement: that check catches
    a claim CONTRADICTING known evidence; this one catches a claim
    OMITTING a known, material, structurally-registered caveat.

    Fires ONLY when production_history_status is a genuinely KNOWN
    absence ("none" or "limited") -- never on "unknown". Asserting a
    caveat the system doesn't actually have evidence for would itself be
    a fabrication in the other direction; silence must never be treated
    as a confirmed negative.
    """
    issues = []
    text = position.reasoning or ""

    for supplier in normalized.suppliers:
        if supplier.qualification_status != "complete":
            continue  # the OTHER check (overstatement) already covers incomplete qualification
        if supplier.production_history_status not in ("none", "limited"):
            continue  # "unknown" or "established" -- nothing to pair here
        if not _supplier_referenced_in(supplier.supplier_name, text):
            continue

        for sentence in _split_sentences(text):
            if not _supplier_referenced_in(supplier.supplier_name, sentence):
                continue
            lowered = sentence.lower()
            qualification_match = None
            for p in _QUALIFICATION_STRENGTH_PATTERNS:
                m = re.search(p, lowered)
                if m:
                    qualification_match = m
                    break
            if not qualification_match:
                continue
            if not _claim_attributed_to_supplier(
                supplier.supplier_name, sentence, qualification_match.start(), qualification_match.end()
            ):
                continue  # this supplier co-occurs in the sentence; the qualification claim is about someone else
            has_caveat = any(phrase in lowered for phrase in _PRODUCTION_HISTORY_CAVEAT_PATTERNS)
            if has_caveat:
                continue
            issues.append(
                f"'{supplier.supplier_name}' is described as qualified (\"{sentence.strip()}\") without "
                f"pairing the known, material caveat that production_history_status="
                f"'{supplier.production_history_status}' -- a qualification claim standing alone here "
                f"is materially incomplete, not simply unhedged."
            )

    return issues


# ---------------------------------------------------------------------------
# Aggregate entry point
# ---------------------------------------------------------------------------

def check_all_claim_overstatements(
    position: CommercialPosition,
    normalized: NormalizedEvidence,
    raw_question: str = "",
    is_continuation: bool = False,
) -> list[str]:
    """The single entry point _run_reasoning actually calls -- runs every
    registered claim-strength check and returns the combined list."""
    return (
        check_qualification_overstatement(position, normalized)
        + check_verification_overstatement(position, normalized)
        + check_market_support_overstatement(position)
        + check_comparative_price_overstatement(position, normalized)
        + check_certainty_overstatement(position)
        + check_achievement_overstatement(position, is_continuation)
        + check_contract_status_overstatement(position, raw_question)
        + check_lead_time_plausibility(position, normalized)
        + check_material_caveat_omission(position, normalized)
        + check_certification_overstatement(position, normalized)
        + check_preferred_supplier_overstatement(position, normalized)
        + check_performance_characterization_overstatement(position, normalized)
    )
