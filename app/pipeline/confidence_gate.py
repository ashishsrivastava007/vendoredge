"""
Quality Gate Guarantee #5 — Decision Integrity / Confidence Gate.

Confidence must never be an LLM-generated feeling. This module computes a
real, deterministic CEILING on confidence from structural evidence
quality, and the final, guaranteed confidence level is:

    min(model's own stated level, the deterministic ceiling)

The ceiling can only ever LOWER confidence, never raise it -- this is
what prevents "lots of evidence present" from being mistaken for "this
recommendation is certain." One genuine structural problem caps
confidence regardless of how much else is correct, exactly per the
instruction that this must reflect decision-criticality, not a raw
completeness percentage.

Five real, deterministic checks, each targeting a specific, real failure
mode:
  A. Financial completeness   -- Case #1 (excellent evidence, one number missing)
  B. Unresolved conflict      -- Case #2 (two load-bearing facts disagree)
  C. Alternative-supplier reliance on incomplete qualification -- Case #3
  D. Internal contradiction (Guarantee #3) still present on the final response
  E. Sole-fallback reliance on load-bearing evidence -- Case #4
"""
from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence
from app.pipeline.contradiction_check import check_all_contradictions
from app.pipeline.decision_integrity import compute_pre_reasoning_confidence as _compute_pre_reasoning_confidence

_LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}


def _min_level(a: str, b: str) -> str:
    return a if _LEVEL_RANK[a] <= _LEVEL_RANK[b] else b


# Which fields genuinely count as "load-bearing" per content type -- not
# every optional field, only the ones a real recommendation actually
# depends on. Deliberately a named, auditable list, not a computed
# percentage of "how many fields exist."
_LOAD_BEARING_FIELDS = {
    "price_increase": {
        "current_price_or_terms", "requested_increase_percent",
        "suppliers_stated_justification", "annual_spend_usd",
    },
    "quote_comparison": {
        "price_per_supplier", "number_of_suppliers_being_compared",
    },
}


def compute_confidence_ceiling(position: CommercialPosition, normalized: NormalizedEvidence) -> tuple[str, list[str]]:
    """
    Returns (ceiling_level, reasons) -- the real, structural cap on
    confidence for this specific response, and a plain-language
    explanation of exactly which checks triggered it, per Guarantee #1's
    same "no black-box number" discipline.
    """
    ceiling = "high"
    reasons: list[str] = []
    load_bearing = _LOAD_BEARING_FIELDS.get(normalized.content_type, set())

    # Check A -- financial completeness. A price_increase recommendation
    # without a real, guaranteed dollar figure behind it should never be
    # presented as HIGH confidence, no matter how much qualitative
    # evidence surrounds it.
    if normalized.content_type == "price_increase" and position.financial_impact is None:
        ceiling = _min_level(ceiling, "medium")
        reasons.append("no guaranteed financial impact could be calculated for a price_increase case")

    # Check B -- unresolved conflict on a load-bearing field. A genuine,
    # unresolved factual disagreement about something the recommendation
    # actually depends on must never be papered over with high confidence.
    conflicting_load_bearing = [
        name for name, prov in normalized.provenance.items()
        if prov.conflicting and name in load_bearing
    ]
    if conflicting_load_bearing:
        ceiling = _min_level(ceiling, "medium")
        reasons.append(f"unresolved extraction conflict on load-bearing field(s): {', '.join(conflicting_load_bearing)}")

    # Check C -- reliance on an alternative supplier whose qualification
    # is genuinely incomplete. Recommending real commercial action on an
    # unready alternative is inherently less certain, even if every other
    # fact in the case is perfectly verified.
    reasoning_text = (position.reasoning or "") + " " + (position.recommendation or "")
    for supplier in normalized.suppliers:
        if supplier.is_incumbent:
            continue
        if supplier.qualification_status == "complete":
            continue
        if supplier.supplier_name and supplier.supplier_name in reasoning_text:
            ceiling = _min_level(ceiling, "medium")
            reasons.append(
                f"recommendation relies on '{supplier.supplier_name}', whose qualification is "
                f"'{supplier.qualification_status}', not complete"
            )

    # Check D -- the single most severe signal: the final response still
    # contradicts its own guaranteed data. This is worse than a missing
    # or conflicting input -- it means the response disagrees with
    # itself, so it gets the hardest cap.
    if check_all_contradictions(position):
        ceiling = _min_level(ceiling, "low")
        reasons.append("the final response contains an unresolved internal contradiction")

    # Check E -- sole-fallback reliance. If a majority of load-bearing
    # fields were resolved ONLY by a deterministic regex fallback -- never
    # independently understood by the model, never confirmed by the user
    # -- the underlying facts are structurally less certain, even if the
    # arithmetic built on top of them is entirely correct.
    if load_bearing:
        fallback_only = [
            name for name in load_bearing
            if name in normalized.provenance and normalized.provenance[name].source == "deterministic_fallback"
        ]
        present_load_bearing = [name for name in load_bearing if name in normalized.provenance]
        if present_load_bearing and len(fallback_only) / len(present_load_bearing) > 0.5:
            ceiling = _min_level(ceiling, "medium")
            reasons.append(
                f"a majority of load-bearing evidence ({', '.join(fallback_only)}) was resolved only "
                f"by deterministic fallback, never independently confirmed by the model or the user"
            )

    return ceiling, reasons


def apply_confidence_ceiling(position: CommercialPosition, normalized: NormalizedEvidence) -> CommercialPosition:
    """
    The actual enforcement point. Mutates position.confidence.level to
    min(model's stated level, the real ceiling) -- never raises it, only
    ever lowers it. Also appends the real, specific reasons to
    derivation_note, so the "why" is visible, not just the final number.
    """
    ceiling, reasons = compute_confidence_ceiling(position, normalized)
    original_level = position.confidence.level
    final_level = ceiling

    if final_level != original_level:
        position.confidence.derivation_note = (
            position.confidence.derivation_note
            + f" [System-owned confidence level: '{final_level}'. Model-stated '{original_level}' "
            f"was not authoritative. Deterministic evidence checks: {'; '.join(reasons) if reasons else 'none'}.]"
        )
    else:
        position.confidence.derivation_note = (
            position.confidence.derivation_note
            + f" [System-owned confidence level: '{final_level}'. Deterministic evidence checks: "
            f"{'none' if not reasons else '; '.join(reasons)}.]"
        )
    position.confidence.level = final_level
    return position


def compute_pre_reasoning_confidence(normalized: NormalizedEvidence) -> tuple[str, list[str]]:
    """Compatibility export for the evidence-only, pre-LLM confidence decision."""
    return _compute_pre_reasoning_confidence(normalized)
