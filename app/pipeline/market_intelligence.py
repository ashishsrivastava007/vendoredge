"""
Phase 5B / R41 -- Market Intelligence.

No live external market-data source exists anywhere in this
environment. This module never looks up, estimates, or fabricates a
market figure -- it only reasons over MarketDriverClaim evidence the
case itself already stated (see normalized_evidence.py's module
docstring on that model). If a case mentions no market driver at all --
the overwhelming majority, including the actual Industrial Valves
golden case as currently specified -- this module correctly produces
nothing, not a placeholder.

The reasoning chain, kept as five explicitly separate categories, never
blurred into one paragraph:

MARKET EVIDENCE  -- what the case states a driver did (a fact, as
                     stated -- never independently verified, since
                     there is no live source to verify against)
SUPPLIER CLAIM    -- what the supplier says that driver means for
                     THEIR cost (never treated as proven)
INFERENCE          -- a plausible, explicitly-labelled connection
                     between the two (never treated as proven)
UNKNOWN            -- what would need to be established to move from
                     inference to proof
DECISION IMPLICATION -- what this means for the actual decision, always
                     including the explicit line that a market
                     direction matching a supplier's request does not,
                     by itself, justify the number requested

Never converts a generic market movement into a specific dollar
entitlement unless the case itself states the exact weight (e.g. "steel
is 30% of our cost") -- see _explainable_portion()'s explicit refusal
to estimate an unstated weight.
"""
from __future__ import annotations
from typing import Any


def build_market_reasoning(kernel: dict[str, Any]) -> dict[str, Any] | None:
    """Returns None when the case states no market driver claim at all
    -- the correct, honest, overwhelming-majority case. Never returns a
    placeholder structure with empty-but-present fields pretending
    analysis happened when it didn't."""
    claims = kernel.get("case", {}).get("market_driver_claims") if isinstance(kernel.get("case"), dict) else None
    if not claims:
        return None

    subject = kernel.get("case", {}).get("subject")
    # The case's own currency, read from any kernel fact that carries
    # one -- never guessed, never defaulted; if no fact has a currency,
    # currency-mismatch detection simply doesn't fire, which is the
    # correct, honest behavior rather than a false positive.
    case_currency = next((f.get("currency") for f in kernel.get("facts", []) if f.get("currency")), None)
    entries = []
    for c in claims:
        entries.append(_reason_about_one_claim(c, subject, claims, case_currency))
    return {"drivers": entries}


def _fmt_pct(v: float) -> str:
    """Plain number formatting for buyer-facing text -- 30 not 30.0."""
    return f"{v:g}"


_STALE_LANGUAGE_MARKERS = ("year ago", "years ago", "outdated", "no longer current", "old data", "stale")


def _establish_supplier_scope(claim: dict[str, Any], subject: str | None) -> tuple[str | None, bool]:
    """Item 4's core distinction, made explicit and code-enforced:
    'market driver exists' is never the same thing as 'market driver
    exposure is established for THIS supplier'. Returns
    (supplier_name_or_None, is_established) -- established is True only
    when the case itself ties the claim to a specific supplier, either
    via an explicit applies_to_supplier field or because the claim IS
    that supplier's own stated claim (attributed_to == "supplier", in
    which case the case's own subject supplier is who made it). A
    buyer-cited or unspecified claim with no explicit
    applies_to_supplier is scoped to NO supplier -- it must never be
    silently narrowed onto the case's subject supplier just because
    that's the only supplier in view."""
    explicit = claim.get("applies_to_supplier")
    if explicit:
        return explicit, True
    if claim.get("attributed_to") == "supplier" and subject:
        return subject, True
    return None, False


def _detect_stale_claim(claim: dict[str, Any]) -> str | None:
    """Conservative by design: only flags staleness the CASE ITSELF
    states (e.g. "three years ago", "outdated") -- there is no reliable
    "today" reference for a case's own text, so this never guesses
    staleness from a bare year number, which would risk false positives
    on a case written at a different time than this pass runs."""
    date_text = str(claim.get("publication_or_retrieval_date") or "").lower()
    period_text = str(claim.get("period") or "").lower()
    combined = f"{date_text} {period_text}"
    for marker in _STALE_LANGUAGE_MARKERS:
        if marker in combined:
            return claim.get("publication_or_retrieval_date") or claim.get("period")
    return None


def _detect_currency_mismatch(claim: dict[str, Any], case_currency: str | None) -> str | None:
    """Reliable, narrow check: only fires when the claim states its own
    unit/currency AND the case has its own known currency AND they
    genuinely differ -- never guesses a conversion, never assumes they
    match when one side is simply unstated."""
    claim_unit = claim.get("unit_or_currency")
    if not claim_unit or not case_currency:
        return None
    if case_currency.upper() not in claim_unit.upper():
        return claim_unit
    return None


def _reason_about_one_claim(claim: dict[str, Any], subject: str | None, all_claims: list[dict[str, Any]], case_currency: str | None) -> dict[str, Any]:
    driver = claim.get("driver", "unknown driver")
    attributed_to = claim.get("attributed_to", "unspecified")
    scoped_supplier, supplier_established = _establish_supplier_scope(claim, subject)

    # MARKET EVIDENCE: the claim exactly as stated, never rephrased into
    # something more certain than the case actually said.
    parts = [driver]
    if claim.get("direction"):
        parts.append(claim["direction"])
    if claim.get("magnitude"):
        parts.append(f"by {claim['magnitude']}")
    period = claim.get("period")
    if period:
        # Avoid "over year over year" when the stated period text
        # already reads naturally without a leading "over" (e.g. the
        # period itself is phrased as a duration like "year over
        # year"); only prepend "over" for a plain date/range value.
        parts.append(period if period.lower().startswith(("year over year", "quarter over quarter", "month over month")) else f"over {period}")
    if claim.get("geography"):
        parts.append(f"in {claim['geography']}")
    market_evidence = " ".join(parts) + ("." if not parts[-1].endswith(".") else "")
    market_evidence = market_evidence[0].upper() + market_evidence[1:]
    if claim.get("source"):
        market_evidence += f" (source: {claim['source']})"

    # Category-context transparency: surfaced, never used to silently
    # judge relevance -- the reader sees exactly what context the case
    # itself framed this claim in, and can judge fit themselves.
    if claim.get("stated_category_context"):
        market_evidence += f" [stated in the context of: {claim['stated_category_context']}]"

    # Stale-data flag: only when the case's own language says so.
    stale = _detect_stale_claim(claim)
    if stale:
        market_evidence += f" -- flagged as dated by the case itself ({stale})."

    # Currency/unit mismatch: never silently assumed to match.
    currency_mismatch = _detect_currency_mismatch(claim, case_currency)
    if currency_mismatch:
        market_evidence += f" -- stated in {currency_mismatch}, not the case's own currency ({case_currency}); do not treat as directly comparable without conversion evidence."

    # Conflicting-source detection: another claim for the SAME driver
    # with a DIFFERENT stated direction is a genuine, credible conflict
    # -- never silently pick one side.
    conflicting = [
        c for c in all_claims
        if c is not claim and c.get("driver", "").strip().lower() == driver.strip().lower()
        and c.get("direction") and claim.get("direction") and c.get("direction") != claim.get("direction")
    ]
    if conflicting:
        market_evidence += f" -- CONTRADICTED: another claim in this case states {driver} {conflicting[0].get('direction')} instead; do not silently choose one side."

    # SUPPLIER CLAIM vs buyer-cited: kept explicitly distinct, never
    # collapsed into one undifferentiated "the market says" statement --
    # a supplier's own claim about a driver affecting their cost carries
    # different weight than the buyer's own citation of an index.
    supplier_claim = None
    if attributed_to == "supplier":
        supplier_claim = f"{scoped_supplier or 'The supplier'} cites {driver} as a factor in the requested change."

    # INFERENCE: an explicit, labelled, non-committal connection --
    # never stated as proven, always paired with what remains unknown.
    # Item 4 fix: never names a specific supplier here unless the
    # case's own evidence actually established that scope.
    if supplier_established:
        inference = f"If {driver} genuinely moved as stated, it could plausibly contribute to cost pressure somewhere in this market -- this does not establish how much, or whether it applies to {scoped_supplier} specifically."
    else:
        inference = f"If {driver} genuinely moved as stated, it could plausibly contribute to cost pressure somewhere in this market -- this does not establish how much, or whether it applies to any specific supplier."

    # UNKNOWN: what's actually missing to move from inference to proof.
    share = claim.get("stated_cost_share_percent")
    if not supplier_established:
        unknown = f"No specific supplier's exposure to {driver} is established in this case -- this is a general market observation, not yet tied to any named supplier."
    elif share is None:
        unknown = f"{scoped_supplier or 'The supplier'}'s actual product-level exposure to {driver} is not established -- no stated cost share exists in this case."
    else:
        unknown = f"Whether the stated {_fmt_pct(share)}% cost share for {driver} is itself accurate has not been independently confirmed -- there is no live source to check it against."

    # DECISION IMPLICATION: the one line that must always appear,
    # regardless of direction -- a market movement in the same
    # direction as a request never by itself justifies the request.
    # Item 4 fix: if supplier exposure was never established, the
    # implication says so plainly rather than defaulting to whichever
    # supplier happens to be the case's subject.
    if not supplier_established:
        decision_implication = (
            f"{driver.capitalize()} moving in the claimed direction is a general market observation -- it has not been tied to any specific "
            f"supplier's cost in this case, so it cannot by itself justify or explain any particular supplier's request."
        )
    else:
        explainable = _explainable_portion(claim)
        if explainable is not None:
            decision_implication = (
                f"Based on the stated {_fmt_pct(share)}% cost share, {driver} moving as claimed could explain up to "
                f"approximately {_fmt_pct(explainable)}% of {scoped_supplier}'s cost change -- this is a ceiling drawn from the case's own "
                f"stated numbers, not a confirmed amount, and it does not by itself validate the specific increase requested."
            )
        else:
            decision_implication = (
                f"{driver.capitalize()} moving in the claimed direction does not, by itself, justify the size of {scoped_supplier}'s request -- "
                f"no stated cost-share weight exists in this case to calculate what portion, if any, it could explain."
            )

    return {
        "market_evidence": market_evidence,
        "supplier_claim": supplier_claim,
        "inference": inference,
        "unknown": unknown,
        "decision_implication": decision_implication,
        "attributed_to": attributed_to,
        "applies_to_supplier": scoped_supplier if supplier_established else None,
    }


def _explainable_portion(claim: dict[str, Any]) -> float | None:
    """Returns the stated cost-share percent directly -- NEVER an
    estimated or assumed weight. If the case doesn't state one, this
    returns None and the caller must say so plainly, never substitute a
    guessed number. This is the single most important guard in this
    module: turning a generic market movement into a specific dollar or
    percentage entitlement without the case's own explicit weight is
    exactly the fabrication this whole phase exists to prevent."""
    share = claim.get("stated_cost_share_percent")
    if share is None:
        return None
    return share


def build_market_prompt_addition(kernel: dict[str, Any]) -> str:
    """Added to a reasoning profile's prompt only when market driver
    claims genuinely exist in the kernel -- silently omitted otherwise,
    never a placeholder instruction about market conditions that don't
    exist in this case."""
    reasoning = build_market_reasoning(kernel)
    if reasoning is None:
        return ""
    lines = ["MARKET DRIVER CLAIMS STATED IN THIS CASE (never independently verified -- no live market-data source exists; reason about these exactly as separated below, never blur fact/claim/inference together):", ""]
    for d in reasoning["drivers"]:
        lines.append(f"- Market evidence: {d['market_evidence']}")
        if d["supplier_claim"]:
            lines.append(f"  Supplier claim: {d['supplier_claim']}")
        lines.append(f"  Inference (not proof): {d['inference']}")
        lines.append(f"  Unknown: {d['unknown']}")
        lines.append(f"  Decision implication: {d['decision_implication']}")
    lines.append("")
    lines.append("Hard rule: do not imply causation merely because a market driver moved in the same direction as the request. Do not convert a generic market movement into a specific dollar or percentage entitlement unless the case itself states the exact cost-share weight.")
    return "\n\n" + "\n".join(lines)


def build_market_answer_section(kernel: dict[str, Any]) -> dict[str, Any] | None:
    """The buyer-facing MARKET section -- plain language, no internal
    key/object names in any prose value. Returns None (the section is
    simply absent) when the case states no market driver claim, which
    is the honest, correct state for the current Industrial Valves
    golden case.

    Certification-gate fix, confirmed by inspecting the actual answer
    through the real HTTP path: supplier_claim and inference were
    already computed by build_market_reasoning() but never reached this
    section -- a supplier's own claim was indistinguishable from market
    data, and the explicit "this is inference, not proof" language
    never surfaced. Both are real reasoning outputs already produced
    upstream; this only presents them, it computes nothing new."""
    reasoning = build_market_reasoning(kernel)
    if reasoning is None:
        return None
    what_the_market_says = [d["market_evidence"] for d in reasoning["drivers"]]
    what_the_supplier_says = [d["supplier_claim"] for d in reasoning["drivers"] if d["supplier_claim"]]
    inference = [d["inference"] for d in reasoning["drivers"]]
    what_this_means = [d["decision_implication"] for d in reasoning["drivers"]]
    still_unknown = [d["unknown"] for d in reasoning["drivers"]]
    return {
        "what_the_market_says": what_the_market_says,
        "what_the_supplier_says": what_the_supplier_says,
        "inference_not_proof": inference,
        "what_this_means": what_this_means,
        "still_unknown": still_unknown,
    }
