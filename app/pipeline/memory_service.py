"""
Category Memory service -- journey-neutral. Minimal first release:
CATEGORY and DECISION memory only, Category Strategy read/write only.

Architecture (per the approved design gate): extraction is entirely
deterministic in this release, not LLM-proposed. Category Strategy's
findings are already the output of a validated, evidence-safe
pipeline (dimension/finding/evidence_state/decision_impact); deriving
memory candidates from them directly is more testable and honest than
adding an LLM "propose candidates" call that cannot be exercised
against a live model in this environment. This is a deliberate,
reported design choice, not an oversight -- future memory types may
warrant LLM-assisted extraction, but this release doesn't need it and
shouldn't claim it.

Current evidence always outranks memory: this module is called ONLY
to (a) write memory after a Category Strategy answer is composed, and
(b) retrieve memory BEFORE composition, as separate, clearly-labelled
context. It never participates in computing the current answer itself
-- that remains entirely the kernel's job, unchanged.
"""
from __future__ import annotations
from typing import Any
from datetime import datetime, timezone
import json
import re

from app.database import get_org_scoped_connection

# ---------------------------------------------------------------------
# Closed fact_type vocabulary (hard guardrail 1). A finding that
# doesn't match one of these is REJECTED from durable memory, never
# force-classified into the nearest type.
# ---------------------------------------------------------------------

FACT_TYPES = {
    "spend_concentration",
    "supplier_strategy_classification",
    "price_movement_calculated",
    "specification_change_price_impact",
    "market_driver_price_correlation",
    "market_driver_no_internal_movement",
    "contract_adjustment_mechanism",
    "supplier_claim_price_history_contradiction",
    "spend_only_movement",
}


def classify_fact_type(finding: dict[str, Any]) -> str | None:
    """Maps one Category Strategy finding to a closed fact_type, or
    None when it cannot be safely classified. Ordered most-specific
    first so a finding matching multiple loose patterns still resolves
    to its most precise type."""
    text = str(finding.get("finding", "")).lower()
    dimension = finding.get("dimension", "")

    if "% of category spend" in text and "holds" in text:
        return "spend_concentration"
    if dimension == "supplier_landscape" and any(f": {s}" in text for s in ("challenge", "qualify", "develop", "monitor")):
        return "supplier_strategy_classification"
    if "stated justification claims costs have increased" in text:
        return "supplier_claim_price_history_contradiction"
    if "contractual adjustment mechanism" in text:
        return "contract_adjustment_mechanism"
    if "specification change was also reported" in text:
        return "specification_change_price_impact"
    if "market movement in" in text and "unit price has moved" in text:
        return "market_driver_price_correlation"
    if "no corresponding internal spend or price movement" in text:
        return "market_driver_no_internal_movement"
    if "spend has changed" in text and "volume data is unavailable" in text:
        return "spend_only_movement"
    if "unit price has moved" in text or "average unit price has moved" in text:
        return "price_movement_calculated"
    return None


def _entity_for(finding: dict[str, Any], kernel: dict[str, Any]) -> tuple[str | None, str | None]:
    """(category, supplier) this finding concerns. Supplier is parsed
    from the finding text when it names one (the finding templates all
    put the supplier name first, e.g. "Wrist holds 56%..."); category
    always comes from the kernel's own subject, never guessed.

    M1.4 fix: kernel.case.subject IS the incumbent supplier's own name
    (see kernel.py) -- for fact_types that are inherently about THIS
    case's own supplier (contract_adjustment_mechanism and supplier_
    claim_price_history_contradiction are both derived from stated_
    justification text, which is always the requesting supplier's own
    statement, never a category-wide claim), that subject is a
    genuinely correct supplier association, not a guess -- it was
    simply never assigned before, which is the root cause behind why
    RELATED_HISTORICAL_CONTEXT for these fact_types could never reach
    supplier-strategy reasoning in the live path (only a dimension==
    "supplier_landscape" finding ever got a supplier at all). Findings
    outside this narrow, explicitly-supplier-derived set (e.g. market_
    driver_no_internal_movement, which concerns the category as a
    whole, not one supplier) are deliberately left with supplier=None,
    unchanged."""
    category = kernel.get("case", {}).get("subject")
    supplier = None
    text = str(finding.get("finding", ""))
    m = re.match(r"^([A-Za-z0-9 .&'-]+?)(?:'s| holds| :|:)", text)
    if m and finding.get("dimension") == "supplier_landscape":
        supplier = m.group(1).strip()
    elif classify_fact_type(finding) in ("contract_adjustment_mechanism", "supplier_claim_price_history_contradiction"):
        supplier = category
    return category, supplier


def _proposition_key(memory_type: str, org_id: str, category: str | None, supplier: str | None, fact_type: str) -> str:
    """Hard guardrail 3: two items only ever compare as duplicate or
    contradictory when this key matches exactly. fact_type is already
    specific enough that genuinely different propositions (a raw-
    material cost claim vs. a quoted price fact) get different keys
    by construction -- they were classified into different fact_types
    above, not merged into one generic 'price' bucket."""
    return "|".join([memory_type, org_id, category or "", supplier or "", fact_type])


# ---------------------------------------------------------------------
# Extraction + validation (hard guardrail 2: decision-impact is a
# strong signal, not the sole gate)
# ---------------------------------------------------------------------

_LONG_TERM_VALUE_FACT_TYPES = {
    "spend_concentration", "supplier_strategy_classification", "contract_adjustment_mechanism",
    "supplier_claim_price_history_contradiction",
}


def extract_candidates(kernel: dict[str, Any], findings: list[dict[str, Any]], source_case_id: str, source_journey: str = "category_strategy") -> list[dict[str, Any]]:
    """Deterministic extraction: every finding is considered; each
    becomes a candidate or is rejected with a reason. Nothing here
    calls an LLM (see module docstring)."""
    candidates: list[dict[str, Any]] = []
    org_id = kernel.get("org_id") or kernel.get("organisation_id")
    for finding in findings:
        fact_type = classify_fact_type(finding)
        if fact_type is None:
            candidates.append({"rejected": True, "reason": "unrecognized_fact_type", "raw_finding": finding.get("finding")})
            continue
        # Hard guardrail 2: decision-impact is a strong signal, not the
        # sole gate. DECISION_CHANGING/MATERIAL_RISK/DECISION_CRITICAL_
        # UNKNOWN pass automatically (existing relevance test). A
        # BACKGROUND finding may still pass if its fact_type is one
        # with durable, cross-conversation value regardless of today's
        # immediate materiality (e.g. a supplier's strategy
        # classification stays useful context long after this specific
        # case closes).
        decision_impact = finding.get("decision_impact")
        memory_worthy = decision_impact in ("DECISION_CHANGING", "MATERIAL_RISK", "DECISION_CRITICAL_UNKNOWN") or fact_type in _LONG_TERM_VALUE_FACT_TYPES
        if not memory_worthy:
            candidates.append({"rejected": True, "reason": "not_memory_worthy", "raw_finding": finding.get("finding")})
            continue
        evidence_state = finding.get("evidence_state")
        if evidence_state not in ("VERIFIED", "CALCULATED", "SUPPLIER_CLAIM", "STAKEHOLDER_VIEW", "EXTERNAL_MARKET_EVIDENCE", "INFERRED", "ASSUMED", "UNKNOWN", "CONTRADICTED"):
            candidates.append({"rejected": True, "reason": "missing_or_invalid_evidence_state", "raw_finding": finding.get("finding")})
            continue
        category, supplier = _entity_for(finding, kernel)
        if not category and not supplier:
            candidates.append({"rejected": True, "reason": "missing_entity", "raw_finding": finding.get("finding")})
            continue
        provenance = {"source_case_id": source_case_id, "kernel_source": finding.get("source"), "evidence": finding.get("evidence")}
        if not provenance.get("kernel_source"):
            candidates.append({"rejected": True, "reason": "missing_provenance", "raw_finding": finding.get("finding")})
            continue
        candidates.append({
            "rejected": False,
            "memory_type": "CATEGORY",
            "organisation_id": org_id,
            "entity_category": category,
            "entity_supplier": supplier,
            "fact_type": fact_type,
            "proposition_key": _proposition_key("CATEGORY", str(org_id), category, supplier, fact_type),
            "value": {"finding": finding.get("finding"), "implication": finding.get("implication"), "possible_action": finding.get("possible_action")},
            "evidence_state": evidence_state,
            "source_case_id": source_case_id,
            "source_journey": source_journey,
            "provenance": provenance,
            # event_date: the BUSINESS-EVENT date this fact concerns --
            # e.g. when a supplier's concentration was genuinely at
            # this level, not when VendorEdge happened to run this
            # analysis. recorded_at (a separate column, set by the DB
            # itself) already captures analysis/write time; using it,
            # or "now()" here, for event_date would conflate two
            # different concepts and could manufacture a false
            # temporal-change or contradiction signal purely from
            # request timing. This evidence model has no field that
            # reliably establishes when the underlying business fact
            # occurred, so event_date is left unset (unknown) here --
            # correct per "do not invent dates" -- until a genuine
            # business-date source exists in the evidence model.
        })
    return candidates


# ---------------------------------------------------------------------
# Persistence: deduplication, versioning, contradiction handling
# ---------------------------------------------------------------------

def _values_conflict(old_value: dict, new_value: dict) -> bool:
    """Same proposition_key, but do the two VALUES actually disagree?
    Compared on the finding text's stated figures where present;
    otherwise treated as a duplicate (same proposition, same
    assertion), not a contradiction."""
    old_text = str(old_value.get("finding", ""))
    new_text = str(new_value.get("finding", ""))
    old_nums = re.findall(r"[+-]?\d+(?:\.\d+)?%", old_text)
    new_nums = re.findall(r"[+-]?\d+(?:\.\d+)?%", new_text)
    if old_nums and new_nums and old_nums != new_nums:
        return True
    return old_text.strip() != new_text.strip() and bool(old_nums) != bool(new_nums)


def store_candidates(organisation_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Writes accepted candidates, applying deduplication/versioning/
    contradiction rules per proposition_key. Never blocks the caller:
    any single candidate's failure is recorded, not raised, matching
    this codebase's established non-blocking pattern for secondary
    writes."""
    result = {"stored": [], "new_versions": [], "duplicates": [], "contradictions": [], "rejected": []}
    accepted = [c for c in candidates if not c.get("rejected")]
    for c in candidates:
        if c.get("rejected"):
            result["rejected"].append({"reason": c["reason"], "raw_finding": c.get("raw_finding")})
    if not accepted:
        return result
    try:
        with get_org_scoped_connection(organisation_id) as conn:
            with conn.cursor() as cur:
                for c in accepted:
                    cur.execute(
                        "SELECT id, value, evidence_state, version FROM memory_items "
                        "WHERE organisation_id = %s AND proposition_key = %s AND temporal_status = 'CURRENT' "
                        "ORDER BY version DESC LIMIT 1",
                        (organisation_id, c["proposition_key"]),
                    )
                    existing = cur.fetchone()
                    if existing is None:
                        cur.execute(
                            "INSERT INTO memory_items (organisation_id, memory_type, entity_category, entity_supplier, "
                            "fact_type, proposition_key, value, evidence_state, source_case_id, source_journey, provenance, event_date) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                            (organisation_id, c["memory_type"], c["entity_category"], c["entity_supplier"], c["fact_type"],
                             c["proposition_key"], json.dumps(c["value"]), c["evidence_state"], c["source_case_id"],
                             c["source_journey"], json.dumps(c["provenance"]), c.get("event_date")),
                        )
                        new_row = cur.fetchone()
                        result["stored"].append(str(new_row["id"]))
                        continue
                    old_value = existing["value"] if isinstance(existing["value"], dict) else json.loads(existing["value"])
                    if not _values_conflict(old_value, c["value"]):
                        result["duplicates"].append(c["proposition_key"])
                        continue
                    # Genuine conflict on the same proposition: new version,
                    # linked via supersedes_id. Only mark the OLD version
                    # SUPERSEDED (not deleted) when the new evidence is at
                    # least as strong; otherwise both stay CURRENT and are
                    # cross-linked via contradicts_ids -- neither silently
                    # wins.
                    strength_order = ["ASSUMED", "UNKNOWN", "INFERRED", "STAKEHOLDER_VIEW", "SUPPLIER_CLAIM", "EXTERNAL_MARKET_EVIDENCE", "CALCULATED", "VERIFIED"]
                    old_strength = strength_order.index(existing["evidence_state"]) if existing["evidence_state"] in strength_order else -1
                    new_strength = strength_order.index(c["evidence_state"]) if c["evidence_state"] in strength_order else -1
                    cur.execute(
                        "INSERT INTO memory_items (organisation_id, memory_type, entity_category, entity_supplier, "
                        "fact_type, proposition_key, value, evidence_state, source_case_id, source_journey, provenance, "
                        "version, supersedes_id, contradicts_ids, event_date) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid[], %s) RETURNING id",
                        (organisation_id, c["memory_type"], c["entity_category"], c["entity_supplier"], c["fact_type"],
                         c["proposition_key"], json.dumps(c["value"]), c["evidence_state"], c["source_case_id"],
                         c["source_journey"], json.dumps(c["provenance"]), existing["version"] + 1,
                         str(existing["id"]), [str(existing["id"])] if new_strength <= old_strength else [], c.get("event_date")),
                    )
                    new_id = cur.fetchone()["id"]
                    if new_strength > old_strength:
                        cur.execute("UPDATE memory_items SET temporal_status = 'SUPERSEDED' WHERE id = %s", (existing["id"],))
                        result["new_versions"].append(str(new_id))
                    else:
                        cur.execute("UPDATE memory_items SET contradicts_ids = contradicts_ids || %s::uuid[] WHERE id = %s", ([str(new_id)], existing["id"]))
                        result["contradictions"].append(str(new_id))
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result


# ---------------------------------------------------------------------
# Retrieval: entity-filtered, tier-ranked, never a full dump
# ---------------------------------------------------------------------

_STRENGTH_ORDER = {"VERIFIED": 0, "CALCULATED": 1, "EXTERNAL_MARKET_EVIDENCE": 2, "SUPPLIER_CLAIM": 3, "STAKEHOLDER_VIEW": 4, "INFERRED": 5, "CONTRADICTED": 6, "ASSUMED": 7, "UNKNOWN": 8}


def retrieve_memory(organisation_id: str, category: str | None = None, supplier: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Entity-filtered retrieval, ranked by: contradiction status
    surfaced first (never buried), then temporal status (CURRENT
    before HISTORICAL/SUPERSEDED), then evidence strength, then
    recency. No numeric weighted score -- see design gate Section K."""
    try:
        with get_org_scoped_connection(organisation_id) as conn:
            with conn.cursor() as cur:
                query = "SELECT * FROM memory_items WHERE organisation_id = %s"
                params: list[Any] = [organisation_id]
                if category:
                    query += " AND entity_category = %s"
                    params.append(category)
                if supplier:
                    query += " AND entity_supplier = %s"
                    params.append(supplier)
                query += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit * 4)  # over-fetch, then rank in Python -- table stays small in this release
                cur.execute(query, params)
                rows = [dict(r) for r in cur.fetchall()]
    except Exception:
        return []
    for r in rows:
        if isinstance(r.get("value"), str):
            r["value"] = json.loads(r["value"])
    rows.sort(key=lambda r: (
        0 if r.get("contradicts_ids") else 1,
        0 if r["temporal_status"] == "CURRENT" else 1,
        _STRENGTH_ORDER.get(r["evidence_state"], 9),
        -(r["created_at"].timestamp() if hasattr(r["created_at"], "timestamp") else 0),
    ))
    return rows[:limit]


# ---------------------------------------------------------------------
# Reconciliation: classifies each retrieved memory item's relationship
# to the CURRENT case's own findings, computed WITHIN the reasoning
# path (see category_strategy_intelligence.build_360_findings), never
# as a separate step bolted on after the answer exists. Current
# evidence always wins the comparison; memory is never promoted to a
# current fact regardless of the classified relationship.
# ---------------------------------------------------------------------

_RELATIONSHIP_TYPES = {"SUPPORTS", "CONTRADICTS", "TEMPORAL_CHANGE", "COMPLEMENTS", "HISTORICAL_PRECEDENT", "RELATED_HISTORICAL_CONTEXT", "SUPERSEDED", "STALE", "NOT_RELEVANT"}

# fact_types representing an inherently time-varying metric (concentration,
# price, spend) -- a numeric mismatch here defaults to TEMPORAL_CHANGE,
# since the metric itself is expected to evolve. This is the direct fix
# for the audit's finding that these were being mislabelled CONTRADICTS.
_TIME_VARYING_FACT_TYPES = {
    "spend_concentration", "price_movement_calculated", "spend_only_movement",
    "specification_change_price_impact", "market_driver_price_correlation",
}
# fact_types representing a claim-vs-documented-fact comparison, where a
# numeric mismatch genuinely means two incompatible propositions about
# the same thing -- not a metric evolving over time.
_CLAIM_CONSISTENCY_FACT_TYPES = {
    "supplier_claim_price_history_contradiction", "contract_adjustment_mechanism",
}


def _extract_numbers(text: str) -> list[str]:
    return re.findall(r"[+-]?\d+(?:\.\d+)?%", str(text))


def _extract_numbers_from_value(value: dict[str, Any]) -> list[str]:
    """Checks finding text first, falling back to implication -- a
    supplier-strategy finding's own asserted text ("X: challenge.")
    carries no number at all; the underlying percentage that drove the
    classification lives in its implication field instead (see
    build_360_findings' supplier_landscape block, where implication is
    the same reason text classify_supplier_strategy produced)."""
    nums = _extract_numbers(value.get("finding", ""))
    if nums:
        return nums
    return _extract_numbers(value.get("implication", ""))


def _same_calendar_day(a: str | None, b: str | None) -> bool:
    """Compares by date, not exact timestamp -- two cases run seconds
    apart on the same real day are genuinely the same period; two
    cases a year apart are not, even if both timestamps happen to be
    "now" relative to when each was extracted."""
    if not a or not b:
        return False
    try:
        da = datetime.fromisoformat(str(a).replace("Z", "+00:00")).date()
        db = datetime.fromisoformat(str(b).replace("Z", "+00:00")).date()
        return da == db
    except (ValueError, TypeError):
        return False


def reconcile_one(memory_item: dict[str, Any], current_finding: dict[str, Any] | None, current_event_date: str | None = None) -> dict[str, Any]:
    """current_finding is the CURRENT case's own finding sharing this
    memory item's (entity, fact_type) -- or None if no current finding
    covers that proposition at all. Same proposition-safety discipline
    as store_candidates: only compared when fact_type genuinely
    matches, never by loose text similarity.

    current_event_date is the KNOWN business-event date this case's
    own fact concerns -- NOT when this case was analyzed. Left as None
    unless a genuine business-event date is actually established;
    passing an analysis/request timestamp here would manufacture a
    false temporal signal purely from request timing, which this
    function must never do. Used only to decide CONTRADICTS vs
    TEMPORAL_CHANGE; never to alter the current_finding's own asserted
    value."""
    values_differ_unknown_period = False
    if memory_item.get("temporal_status") in ("SUPERSEDED", "EXPIRED"):
        relationship = "STALE"
    elif current_finding is None:
        # Nothing current to compare against -- this is background
        # precedent, not evidence about today's condition.
        relationship = "HISTORICAL_PRECEDENT"
    else:
        old_nums = _extract_numbers_from_value(memory_item["value"])
        new_nums = _extract_numbers_from_value(current_finding)
        if old_nums and new_nums and old_nums == new_nums:
            relationship = "SUPPORTS"
        elif old_nums and new_nums:
            fact_type = memory_item.get("fact_type")
            mem_event_date = memory_item.get("event_date")
            if fact_type in _CLAIM_CONSISTENCY_FACT_TYPES:
                # This fact_type IS a same-moment consistency check by
                # its own nature (a claim vs. documented history) --
                # never a time-series metric -- so a mismatch here is
                # always a genuine conflict, not evolution over time.
                # Safe without a separate business-event date, since
                # the comparison is inherently about "now" by
                # construction (the claim and the documented history
                # are both being evaluated against the current case).
                relationship = "CONTRADICTS"
            elif mem_event_date and current_event_date:
                # Both sides carry a genuinely KNOWN business-event
                # date (never populated from analysis/request timing --
                # see extract_candidates' own event_date comment).
                # Only here is a period comparison safe to make at all.
                if _same_calendar_day(mem_event_date, current_event_date):
                    relationship = "CONTRADICTS"  # same known period, genuine value mismatch
                else:
                    relationship = "TEMPORAL_CHANGE"  # different known periods, honest evolution
            else:
                # The business period is unknown on one or both sides
                # -- the current, honest default for this evidence
                # model, since nothing here yet extracts a genuine
                # business-event date. Do NOT confidently assert
                # either CONTRADICTS or TEMPORAL_CHANGE from unknown
                # timing; COMPLEMENTS is the safe "related, not
                # verified equal or conflicting" label instead. Marked
                # with values_differ=True below so downstream callers
                # render the honest "values differ, period unknown"
                # wording rather than the "recurs / not a one-off"
                # language that only fits a genuine categorical match
                # (M1.2 fix B -- the prior wording conflated these two
                # distinct situations under one COMPLEMENTS message).
                relationship = "COMPLEMENTS"
                values_differ_unknown_period = True
        else:
            # No numbers on one or both sides -- fall back to comparing
            # the raw finding text itself (e.g. "X: challenge." vs
            # "X: monitor." -- a genuine categorical difference with no
            # percentage in either string, most notably the "monitor"
            # default reason, which states no share figure at all).
            # M1.2 fix B follow-up: this same distinction applies here
            # too -- a categorical mismatch is a real difference, not a
            # "recurring" match, even without numbers to compare.
            relationship = "COMPLEMENTS"
            old_text = str(memory_item["value"].get("finding", "")).strip()
            new_text = str(current_finding.get("finding", "")).strip()
            if old_text and new_text and old_text != new_text:
                values_differ_unknown_period = True
    return {
        "relationship": relationship,
        "values_differ_unknown_period": values_differ_unknown_period,
        "memory_type": memory_item.get("memory_type"),
        "fact_type": memory_item.get("fact_type"),
        "evidence_state": memory_item.get("evidence_state"),
        "temporal_status": memory_item.get("temporal_status"),
        "event_date": str(memory_item.get("event_date")) if memory_item.get("event_date") else None,
        "evidence_date": str(memory_item.get("evidence_date")) if memory_item.get("evidence_date") else None,
        "source_case_id": str(memory_item.get("source_case_id")) if memory_item.get("source_case_id") else None,
        "provenance": memory_item.get("provenance"),
        "supersedes_id": str(memory_item.get("supersedes_id")) if memory_item.get("supersedes_id") else None,
        "contradicts_ids": [str(x) for x in (memory_item.get("contradicts_ids") or [])] if isinstance(memory_item.get("contradicts_ids"), (list, tuple)) else [],
        "finding_text": memory_item["value"].get("finding"),
        "implication_text": memory_item["value"].get("implication"),
        "recorded_at": str(memory_item.get("recorded_at")) if memory_item.get("recorded_at") else None,
    }


def as_related_historical_context(memory_item: dict[str, Any]) -> dict[str, Any]:
    """A memory item sharing this case's entity (supplier/category) but
    NOT its exact (fact_type) proposition. This category exists so
    genuinely related context (a past negotiation outcome, a
    differently-typed prior observation) isn't silently dropped just
    because the proposition differs -- but it must never be usable as
    SUPPORTS/CONTRADICTS/TEMPORAL_CHANGE, since those require true
    proposition identity this item doesn't have."""
    return {
        "relationship": "RELATED_HISTORICAL_CONTEXT",
        "memory_type": memory_item.get("memory_type"),
        "fact_type": memory_item.get("fact_type"),
        "entity_supplier": memory_item.get("entity_supplier"),
        "entity_category": memory_item.get("entity_category"),
        "evidence_state": memory_item.get("evidence_state"),
        "temporal_status": memory_item.get("temporal_status"),
        "event_date": str(memory_item.get("event_date")) if memory_item.get("event_date") else None,
        "source_case_id": str(memory_item.get("source_case_id")) if memory_item.get("source_case_id") else None,
        "provenance": memory_item.get("provenance"),
        "finding_text": memory_item["value"].get("finding"),
        # M1.4: see the identical comment in reconcile_one -- same
        # proposition/implication distinction, reused here.
        "implication_text": memory_item["value"].get("implication"),
        "recorded_at": str(memory_item.get("recorded_at")) if memory_item.get("recorded_at") else None,
    }


def reconcile_memory_for_category(diagnosis: dict[str, Any], retrieved_memory: list[dict[str, Any]] | None, current_event_date: str | None = None) -> tuple[dict[tuple[str, str | None], dict[str, Any]], list[dict[str, Any]]]:
    """Reconciles retrieved memory EARLY -- against diagnosis's own
    pure, current-evidence values -- so the result is available BEFORE
    supplier strategy classification and opportunity prioritization
    run (see category_strategy_profile.py's call site). diagnosis
    itself is never read from here in a way that could feed back into
    it; this only builds comparison text from values diagnosis already
    computed, purely for matching against memory.

    Returns (proposition_memory_by_key, related_historical_context):
      - proposition_memory_by_key: {(fact_type, entity_supplier): reconciliation}
        for items that share BOTH fact_type and entity with something
        diagnosis actually computed -- eligible for SUPPORTS/
        CONTRADICTS/TEMPORAL_CHANGE/HISTORICAL_PRECEDENT.
      - related_historical_context: items sharing only the entity
        (supplier), with a different fact_type -- NEVER eligible for
        those relationships, per as_related_historical_context's own
        contract.
    """
    proposition_memory_by_key: dict[tuple[str, str | None], dict[str, Any]] = {}
    related_historical_context: list[dict[str, Any]] = []
    if not retrieved_memory:
        return proposition_memory_by_key, related_historical_context

    # Pseudo "current findings" built purely from diagnosis's own
    # already-computed values -- text-only, used solely to reuse
    # reconcile_one's existing number-comparison logic, never fed back
    # into diagnosis itself. Keyed by supplier name alone (not
    # fact_type): the ACTUAL stored fact_type for a given supplier
    # depends on whether it received its own supplier_strategy_
    # classification finding when written (build_360_findings skips
    # the standalone spend_concentration finding for suppliers that
    # get one) -- something not yet known at this point in the
    # pipeline, since classify_supplier_strategy has not run yet.
    # Both fact_types represent the same underlying "what do we know
    # about this supplier's concentration/strategy" proposition.
    _CONCENTRATION_RELATED_FACT_TYPES = {"spend_concentration", "supplier_strategy_classification"}
    pseudo_finding_by_supplier: dict[str, dict[str, Any]] = {}
    for s in diagnosis.get("suppliers_by_spend", []):
        share = s.get("category_share_percent")
        supplier_name = s.get("supplier")
        if share is not None and supplier_name:
            pseudo_finding_by_supplier[supplier_name] = {"finding": f"{supplier_name} holds {share}% of category spend."}

    known_suppliers = set(pseudo_finding_by_supplier.keys())
    for m in retrieved_memory:
        supplier = m.get("entity_supplier")
        fact_type = m.get("fact_type")
        if supplier in pseudo_finding_by_supplier and fact_type in _CONCENTRATION_RELATED_FACT_TYPES:
            key = (fact_type, supplier)
            proposition_memory_by_key[("spend_concentration", supplier)] = reconcile_one(m, pseudo_finding_by_supplier[supplier], current_event_date)
        elif supplier and supplier in known_suppliers:
            # Same supplier, but no current pseudo-finding shares this
            # exact fact_type -- related context only, never SUPPORTS/
            # CONTRADICTS/TEMPORAL_CHANGE.
            related_historical_context.append(as_related_historical_context(m))
        elif m.get("temporal_status") not in ("SUPERSEDED", "EXPIRED") and supplier is None:
            # Category-level (no specific supplier) memory with no
            # matching pseudo-finding -- still related context for the
            # category as a whole.
            related_historical_context.append(as_related_historical_context(m))
    return proposition_memory_by_key, related_historical_context
