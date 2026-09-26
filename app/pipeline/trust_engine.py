"""VendorEdge Trust Engine — Release 29.

Deterministic trust semantics exposed to the buyer.  This layer does not
re-score a recommendation and never asks an LLM for a confidence judgment.
It classifies the evidence actually present in NormalizedEvidence and the
validated decision outputs into five explicit states:
VERIFIED, CALCULATED, ASSUMED, INFERRED, UNKNOWN.
"""
from __future__ import annotations
from typing import Any

from app.pipeline.normalized_evidence import NormalizedEvidence
from app.models import CommercialPosition

# EXTERNAL_MARKET_EVIDENCE is already part of VendorEdge's evidence
# taxonomy; the ledger previously filed external market context under
# VERIFIED, counting it alongside the buyer's own verified facts --
# exactly the "market context presented as supplier evidence" conflation
# found in a live test. It is now its own state and its own count.
STATES = {"VERIFIED", "CALCULATED", "ASSUMED", "INFERRED", "UNKNOWN", "EXTERNAL_MARKET_EVIDENCE"}


def _value_present(v: Any) -> bool:
    return v is not None and v != "" and v != [] and v != {}


def _display(v: Any) -> str:
    if v is None:
        return "Unknown"
    if isinstance(v, (dict, list, tuple)):
        return str(v)
    return str(v)


def _provenance_state(source: str | None) -> str:
    if source in {"llm_extraction", "deterministic_fallback", "user_followup", "database_history", "both_agree"}:
        return "VERIFIED"
    if source == "derived_calculation":
        return "CALCULATED"
    return "UNKNOWN"


_ABSENCE_MARKERS = {
    "not stated", "not provided", "not specified", "not available", "not given",
    "unknown", "n/a", "na", "none", "none stated", "none provided", "not determined",
    "not determinable", "not disclosed", "not supplied", "not established", "unclear",
    "no information", "no data", "no information provided", "not mentioned",
}


def _is_absence_marker(v: Any) -> bool:
    """A value can be technically "present" (a non-empty string) while
    still being an explicit statement of absence -- "Not stated" is a
    string, not None, so _value_present alone would wrongly treat it
    as a real value. Both checks are needed: raw emptiness AND known
    absence phrasing, case-insensitive and punctuation-tolerant."""
    if not _value_present(v):
        return True
    if isinstance(v, str):
        normalized = v.strip().lower().rstrip(".")
        return normalized in _ABSENCE_MARKERS
    return False


def build_trust_engine(normalized: NormalizedEvidence, position: CommercialPosition) -> dict[str, Any]:
    """Build a buyer-readable, deterministic evidence ledger."""
    entries: list[dict[str, Any]] = []
    for field, prov in normalized.provenance.items():
        actual_value = _field_value(normalized, field, prov.supplier_name)
        # The bug this fixes: a field having a provenance record at
        # all (meaning the pipeline looked for it and recorded
        # something about the attempt) previously determined VERIFIED
        # vs CALCULATED purely from prov.source, without ever checking
        # whether the value the extraction actually landed on was a
        # real fact or an explicit statement of absence ("Not
        # stated"). Absence is checked FIRST and unconditionally wins
        # over source, since a "verified absence of information" is
        # still UNKNOWN, not VERIFIED -- VendorEdge did not verify a
        # fact, it verified that no fact was given.
        if _is_absence_marker(actual_value):
            state = "UNKNOWN"
        elif prov.conflicting:
            state = "UNKNOWN"
        else:
            state = "VERIFIED" if prov.source != "derived_calculation" else "CALCULATED"
        entries.append({
            "field": field,
            "value": _display(actual_value),
            "state": state,
            "source": prov.source,
            "supplier": prov.supplier_name,
            "conflicting": bool(prov.conflicting),
        })

    # Explicitly expose important decision-layer values that are not evidence
    # fields themselves. They are never relabelled as verified facts.
    if getattr(position, "market_verification", None):
        mv = position.market_verification
        entries.append({
            "field": "external_market_context",
            "value": _display(mv.get("verified_note") or mv.get("finding")),
            "state": "EXTERNAL_MARKET_EVIDENCE",
            "source": "external_market_search",
            "supplier": None,
            "conflicting": False,
        })

    if position.financial_impact is not None:
        entries.append({
            "field": "financial_impact.net_exposure_usd",
            "value": _display(position.financial_impact.net_exposure_usd),
            "state": "CALCULATED",
            "source": "derived_calculation",
            "supplier": None,
            "conflicting": False,
        })
    if position.recommendation:
        entries.append({
            "field": "recommendation",
            "value": position.recommendation,
            "state": "INFERRED",
            "source": "validated_reasoning",
            "supplier": None,
            "conflicting": False,
        })
    for i, assumption in enumerate(position.assumptions[:8], 1):
        entries.append({
            "field": f"assumption_{i}",
            "value": assumption,
            "state": "ASSUMED",
            "source": "decision_assumption",
            "supplier": None,
            "conflicting": False,
        })

    # Unknowns are deliberately first-class; they are not inferred from
    # silence elsewhere in the pipeline.
    unknowns: list[str] = []
    audit = position.decision_audit
    if audit:
        unknowns.extend(list(audit.uncertainties or []))
    passport = position.decision_passport or {}
    unknowns.extend(list(passport.get("unknowns") or []))
    for item in unknowns[:12]:
        if not any(e["field"] == f"unknown:{item}" for e in entries):
            entries.append({
                "field": f"unknown:{item}",
                "value": "Not established",
                "state": "UNKNOWN",
                "source": "insufficient_evidence",
                "supplier": None,
                "conflicting": False,
            })

    # Counts are computed over exactly the entries returned, so the
    # displayed counts always match the ledger the buyer can see
    # (previously counted over all entries, then truncated to 100).
    entries = entries[:100]
    counts = {s: sum(1 for e in entries if e["state"] == s) for s in STATES}
    unresolved = [e for e in entries if e["conflicting"] or e["state"] == "UNKNOWN"]
    return {
        "title": "VendorEdge Trust Engine",
        "version": "R29.1",
        "entries": entries,
        "entry_count": len(entries),
        "counts": counts,
        "unresolved_count": len(unresolved),
        "unresolved": unresolved[:12],
        "rules": [
            "VERIFIED means the value is supported by captured evidence, history, a user follow-up, or an agreeing extraction/fallback path.",
            "CALCULATED means VendorEdge derived the value deterministically from validated inputs.",
            "ASSUMED means the value is an explicit assumption and is not presented as fact.",
            "INFERRED means the recommendation or interpretation comes from reasoning and is not itself evidence.",
            "UNKNOWN means the evidence is missing or conflicting; silence is never converted into a negative fact.",
            "UNKNOWN also covers values recorded only as an explicit absence such as \"Not stated\" -- VendorEdge verified that no fact was given, not a fact.",
            "EXTERNAL_MARKET_EVIDENCE is contextual market information only; it does not establish a specific supplier's cost movement or entitlement.",
        ],
        "decision_integrity": "PASS" if not any(e["conflicting"] for e in entries) else "REVIEW_REQUIRED",
    }


def _field_value(normalized: NormalizedEvidence, field: str, supplier_name: str | None) -> Any:
    if supplier_name:
        supplier = next((s for s in normalized.suppliers if s.supplier_name == supplier_name), None)
        if supplier is not None and hasattr(supplier, field):
            return getattr(supplier, field)
    for obj in (normalized.common, normalized.case, normalized.derived, normalized.history):
        if hasattr(obj, field):
            return getattr(obj, field)
    return None
