"""
Step B — Evidence Check. Deterministic, no LLM call.
This is the actual mechanism behind "ask before guessing" (Hard Rule 1, PIPE-01).
The required-fields list is fixed in code, not left to model judgment at runtime —
that's the whole point: a model deciding for itself what evidence it needs is exactly
what let a failing tool skip straight to a guessed answer in live testing.

MIGRATED (NormalizedEvidence architecture): this no longer independently
re-derives whether freight is relevant from raw Incoterm text -- that
derivation happens exactly once, in normalize_evidence(), and is read
here as normalized.derived.freight_relevant. This is the direct fix for
the audit's Critical Finding #1: the evidence-gate now sees the SAME
Incoterm value (LLM extraction or deterministic fallback, whichever
found it) that every other stage sees, not a second, independent read.
"""
from app.pipeline.normalized_evidence import NormalizedEvidence

EVIDENCE_REQUIREMENTS: dict[str, list[str]] = {
    "price_increase": [
        "current_price_or_terms",
        "requested_increase_percent",
        "suppliers_stated_justification",
        "how_critical_is_this_supplier_relationship",
    ],
    "quote_comparison": [
        "number_of_suppliers_being_compared",
        "price_per_supplier",
        "payment_terms_per_supplier",
        "lead_time_per_supplier",
        "quality_or_defect_history_per_supplier",
        "is_this_a_new_or_incumbent_relationship",
    ],
}

# Real, conditional requirement -- found after a genuine live case labeled
# its own approach "TCO/landed-cost analysis" while quietly missing an
# input that was actually knowable. Under these specific Incoterms (the
# real, published Incoterms 2020 standard), the BUYER bears freight cost
# from a certain point onward -- meaning it's genuinely something the user
# could supply, not a gap to just note afterward. Under the other terms
# (CFR, CIF, CPT, CIP, DAP, DPU, DDP), freight is already built into the
# seller's quoted price, so asking for it separately would be redundant,
# not more thorough.
#
# Still the single source of truth for this list -- normalize.py imports
# it from here, rather than duplicating it, to compute freight_relevant.
INCOTERMS_WHERE_BUYER_BEARS_FREIGHT = {"EXW", "FCA", "FAS", "FOB"}

# Human-readable question text shown to the user for each field — kept separate
# from the machine field name so the UI copy can be tuned without touching pipeline logic.
FIELD_PROMPTS: dict[str, str] = {
    "current_price_or_terms": "What are the current price or terms with this supplier?",
    "requested_increase_percent": "What increase percentage is being requested?",
    "suppliers_stated_justification": "What reason did the supplier give for the increase (e.g. raw material cost, energy, labor)?",
    "how_critical_is_this_supplier_relationship": "Is this currently a sole-source supplier, or do you have qualified alternative suppliers? If yes, please provide any known price, lead time, quality, or switching cost.",
    "number_of_suppliers_being_compared": "How many supplier quotes are you comparing?",
    "price_per_supplier": "What's the price from each supplier?",
    "payment_terms_per_supplier": "What are the payment terms from each supplier?",
    "lead_time_per_supplier": "What's the lead time from each supplier?",
    "quality_or_defect_history_per_supplier": "Any known quality, defect rate, or delivery reliability history for each supplier?",
    "is_this_a_new_or_incumbent_relationship": "Is any of these an existing/incumbent supplier, or are they all new to you?",
    "freight_cost_or_estimate": "Under this Incoterm, freight/transport cost from the seller's handoff point is yours to bear -- what's the known or estimated freight cost, per unit (e.g. \"€35/unit\")?",
}


FIELD_WHY: dict[str, str] = {
    "current_price_or_terms": "Needed to calculate whether the requested increase is commercially reasonable.",
    "requested_increase_percent": "The actual number being asked for — everything else is measured against this.",
    "suppliers_stated_justification": "Needed to check the increase against a real cost driver, not just accept it on faith.",
    "how_critical_is_this_supplier_relationship": "Needed to assess your real negotiating leverage.",
    "number_of_suppliers_being_compared": "Sets how many quotes need to be weighed against each other.",
    "price_per_supplier": "The starting point for any fair comparison — but never the whole story on its own.",
    "payment_terms_per_supplier": "A lower price with worse payment terms can cost more in practice.",
    "lead_time_per_supplier": "Longer lead times mean more inventory risk, which has a real cost.",
    "quality_or_defect_history_per_supplier": "A cheaper supplier with a worse track record can cost more overall.",
    "is_this_a_new_or_incumbent_relationship": "Switching to an unproven supplier carries its own risk, separate from price.",
    "freight_cost_or_estimate": "Under this Incoterm, the quoted price doesn't include getting the goods to you -- without this, any landed-cost comparison is genuinely incomplete, not just approximate.",
}


def check_missing_evidence(normalized: NormalizedEvidence) -> list[dict]:
    """
    Returns a list of {field, prompt, why} dicts for any required field not
    yet present (and non-empty) in the normalized evidence. Empty list
    means evidence is complete.

    Reads normalized.derived.freight_relevant directly -- computed once,
    upstream, in normalize_evidence() -- rather than re-deriving it from
    raw Incoterm text here. This is the structural fix: the evidence-gate
    can no longer see a DIFFERENT Incoterm value than what the guaranteed
    calculation and the methodology contracts see, because there is only
    one place that value is ever decided.

    Fix for the confirmed master-case bug: the single-value
    freight_cost_or_estimate check below is UNCHANGED and applies only to
    price_increase (where it always has -- a single supplier, a single
    freight fact). For quote_comparison, freight is checked PER SUPPLIER
    instead, using each supplier's OWN Incoterm and OWN
    freight_cost_or_estimate field -- never the case-wide derived flag,
    and never one supplier's value able to satisfy another's requirement.
    This is what makes explicitly-supplied per-supplier freight
    recognized, while genuinely missing per-supplier freight is still
    correctly requested.
    """
    required = list(EVIDENCE_REQUIREMENTS.get(normalized.content_type, []))

    if normalized.content_type == "price_increase" and normalized.derived.freight_relevant:
        required = required + ["freight_cost_or_estimate"]

    supplied = normalized.as_flat_evidence_dict()

    missing = [
        {"field": f, "prompt": FIELD_PROMPTS[f], "why": FIELD_WHY[f]}
        for f in required
        if f not in supplied or supplied.get(f) in (None, "", [])
    ]

    if normalized.content_type == "quote_comparison":
        for supplier in normalized.suppliers:
            supplier_incoterm = (supplier.incoterm or "").strip().upper()
            if supplier_incoterm not in INCOTERMS_WHERE_BUYER_BEARS_FREIGHT:
                continue
            if supplier.freight_cost_or_estimate:
                continue  # this specific supplier's own freight is genuinely present
            field_key = f"freight_cost_or_estimate__{supplier.supplier_name}"
            missing.append({
                "field": field_key,
                "prompt": f"Under this Incoterm, freight/transport cost from {supplier.supplier_name}'s "
                          f"handoff point is yours to bear -- what's the known or estimated freight cost "
                          f"for {supplier.supplier_name}, per unit (e.g. \"€35/unit\")?",
                "why": f"Under this Incoterm, {supplier.supplier_name}'s quoted price doesn't include "
                       f"getting the goods to you -- without this, any landed-cost comparison involving "
                       f"{supplier.supplier_name} is genuinely incomplete, not just approximate.",
            })

    return missing
