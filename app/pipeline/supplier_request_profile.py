"""
Phase 3 / R41 -- Supplier Request reasoning profile.

The first of three reasoning profiles over the shared Commercial
Intelligence Kernel. This module does two things, and only two:

1. Formats the kernel into an explicit, structured context block Claude
   receives BEFORE it reasons -- so the model answers questions 2-5 of
   the reasoning sequence (what do we know / what's only claimed / what
   can we calculate / what can't yet be proven) by reading the kernel's
   own evidence_state tags, not by re-deriving them from raw prose.
2. Assembles the supplier_request answer contract (DECISION, WHY, MONEY,
   LEVERAGE, TRADE-OFF, NEXT MOVE, WHAT COULD CHANGE THIS, DRAFT
   RESPONSE) deterministically from the kernel and the position's
   already-computed fields -- never a second computation path.

Neither function makes a model call. This module supplies what the
model reads and formats what the model plus the kernel together
produce; it does not decide reasoning quality, which depends on the
live model call this environment cannot exercise.
"""
from __future__ import annotations
from typing import Any


SUPPLIER_REQUEST_REASONING_SEQUENCE = """You are reasoning through a supplier request. Work through these questions in order, using ONLY the kernel facts below for anything the kernel already states -- do not re-derive a fact from the raw case text if the kernel already has it, and never state a figure that disagrees with the kernel.

1. What exactly is the supplier asking for?
2. What do we know (kernel facts marked VERIFIED or CALCULATED)?
3. What is only the supplier's claim (kernel facts marked SUPPLIER_CLAIM) -- never treat these as proven?
4. What can we calculate (kernel facts marked CALCULATED) -- use the kernel's own numbers, never recompute them yourself?
5. What cannot yet be proven (kernel facts marked UNKNOWN or CONTRADICTED)?
6. What leverage is real (backed by VERIFIED or CALCULATED facts)?
7. What leverage is only theoretical (would need evidence we don't have yet)?
8. What is the supplier asking us to give up in return, if anything?
9. What would we receive if we agreed?
10. What would we give up if we agreed?
11. What is the best commercial position given everything above?
12. What evidence should we request before deciding further?
13. What should we be willing to trade?
14. What should we never give away unconditionally?
15. What could change this decision (an unresolved unknown or contradiction that, if resolved, would change the recommendation)?
16. What should Procurement do next?
17. What should Procurement say to the supplier?

Hard rules, never break these:
- Never state a numeric target or walk-away unless the kernel already has one marked ESTABLISHED. If none exists, say so plainly and explain what would establish one.
- Never state a benchmark or market comparison figure that isn't in the kernel.
- Never claim savings that aren't a kernel CALCULATED fact.
- Never turn a SUPPLIER_CLAIM into a stated fact.
- Never turn an UNKNOWN into a stated fact.
- Never state a number that disagrees with a kernel CALCULATED fact -- if the kernel says €610,500, your answer must say €610,500, not a rounded or re-derived version.
- If a kernel fact is CONTRADICTED, say so -- never silently pick one side.
"""


def build_kernel_context_block(kernel: dict[str, Any]) -> str:
    """Formats the kernel into explicit text, grouped by evidence state,
    so the model can answer "what do we know vs what's only claimed"
    directly from this block rather than re-parsing raw prose. Every
    fact keeps its entity, metric, value, currency, and evidence state
    exactly as the kernel states them -- never summarized in a way that
    could blur two different entities into one."""
    lines = ["KERNEL -- THE VERIFIED COMMERCIAL TRUTH FOR THIS CASE:", ""]
    case = kernel.get("case", {})
    if case.get("suppliers"):
        lines.append(f"Suppliers in this case: {', '.join(case['suppliers'])}")
    if case.get("subject"):
        lines.append(f"Subject supplier (the one whose request this is): {case['subject']}")
    lines.append("")

    by_state: dict[str, list[str]] = {}
    for f in kernel.get("facts", []):
        cur = f" {f['currency']}" if f.get("currency") else ""
        period = f" ({f['period']})" if f.get("period") else ""
        line = f"  {f['entity']}.{f['metric']}{period} = {f['value']}{cur}"
        by_state.setdefault(f["evidence_state"], []).append(line)

    state_order = ["VERIFIED", "CALCULATED", "SUPPLIER_CLAIM", "STAKEHOLDER_VIEW", "ASSUMED", "INFERRED", "CONTRADICTED", "UNKNOWN"]
    state_labels = {
        "VERIFIED": "VERIFIED (stated directly in the case)",
        "CALCULATED": "CALCULATED (computed deterministically, never recompute these yourself)",
        "SUPPLIER_CLAIM": "SUPPLIER CLAIM (never treat as proven)",
        "STAKEHOLDER_VIEW": "STAKEHOLDER VIEW (an opinion, not a fact)",
        "ASSUMED": "ASSUMED",
        "INFERRED": "INFERRED",
        "CONTRADICTED": "CONTRADICTED (the case states two disagreeing things -- do not silently pick one)",
        "UNKNOWN": "UNKNOWN (not stated anywhere in the case)",
    }
    for state in state_order:
        if state in by_state:
            lines.append(f"{state_labels[state]}:")
            lines.extend(by_state[state])
            lines.append("")

    if kernel.get("suppliers"):
        lines.append("SUPPLIER PROFILES:")
        for s in kernel["suppliers"]:
            parts = [s["supplier_name"]]
            if s.get("is_incumbent"):
                parts.append("(incumbent)")
            if s.get("qualification"):
                parts.append(f"qualification: {s['qualification']['value']}")
            if s.get("capacity"):
                parts.append(f"capacity: {s['capacity']['value']}")
            lines.append("  " + " -- ".join(parts))
        lines.append("")

    if kernel.get("stakeholders"):
        lines.append("STAKEHOLDER VIEWS:")
        for st in kernel["stakeholders"]:
            flag = " [unresolved disagreement]" if st.get("unresolved_disagreement") else ""
            lines.append(f"  {st['stakeholder']}: {st['view']}{flag}")
        lines.append("")

    if kernel.get("unknowns"):
        lines.append("DECISION-CRITICAL UNKNOWNS:")
        for u in kernel["unknowns"]:
            lines.append(f"  {u['unknown']} -- why it matters: {u['why_it_matters']} -- resolves by: {u['resolution_action']}")
        lines.append("")

    return "\n".join(lines)


def build_supplier_request_prompt_addition(kernel: dict[str, Any]) -> str:
    """The full addition to the existing prompt for supplier_request
    mode: the reasoning sequence, then the kernel context. This is
    ADDED to the existing, already-correct evidence-firewall prompt --
    it does not replace it -- so every existing guarantee (no fabricated
    numbers, no invented thresholds) still applies; this only adds the
    mode-specific reasoning order and makes the kernel the explicit,
    primary source rather than something to re-derive."""
    return "\n\n" + SUPPLIER_REQUEST_REASONING_SEQUENCE + "\n" + build_kernel_context_block(kernel)


def build_supplier_request_answer(kernel: dict[str, Any], commercial_answer: dict[str, Any]) -> dict[str, Any]:
    """Assembles the supplier_request answer contract -- DECISION, WHY,
    MONEY, LEVERAGE, TRADE-OFF, NEXT MOVE, WHAT COULD CHANGE THIS, DRAFT
    RESPONSE -- deterministically. Reuses commercial_answer's already-
    correct decision/why/money/decision_changers/draft fields rather
    than recomputing them; LEVERAGE and TRADE-OFF are genuinely new
    here, built directly from kernel facts (VERIFIED/CALCULATED facts
    are real leverage; SUPPLIER_CLAIM/UNKNOWN facts are not)."""
    facts = kernel.get("facts", [])
    case = kernel.get("case", {})
    real_leverage = [
        f"{f['entity']}: {f['metric'].replace('_', ' ')} = {f['value']}" + (f" {f['currency']}" if f.get("currency") else "")
        for f in facts if f["evidence_state"] in ("VERIFIED", "CALCULATED")
    ]
    theoretical_leverage = [
        f"{f['entity']}: {f['metric'].replace('_', ' ')} is only claimed by the supplier, not verified"
        for f in facts if f["evidence_state"] == "SUPPLIER_CLAIM"
    ]
    contradictions = [f for f in facts if f["evidence_state"] == "CONTRADICTED"]
    trade_offs = []
    for c in contradictions:
        # Simple-English rule: the underlying decision_audit text is
        # accurate but long and technical. This restates the same fact
        # in one short, direct sentence for the buyer-facing trade-off
        # list -- the full text stays available in decision_audit for
        # anyone who wants the detail. Two known contradiction shapes
        # exist today; a genuinely unrecognized one still gets a safe,
        # honest, generic sentence rather than a wrong specific one.
        text = str(c.get("value", ""))
        if "UNRESOLVED VALUE CONFLICT" in text:
            trade_offs.append(f"The case has two different numbers for {c['entity']}'s {c['metric'].replace('_', ' ')}. Do not use either until this is resolved.")
        elif "no price adjustment" in text.lower() or "reconciliation" in text.lower():
            trade_offs.append(f"{case.get('subject') or 'The supplier'} says no price change for years, but the case's own history shows real increases. Do not accept the justification until this is explained.")
        else:
            trade_offs.append(f"{c['entity']} has a fact in dispute ({c['metric'].replace('_', ' ')}). Resolve it before relying on it.")
    for u in kernel.get("unknowns", []):
        trade_offs.append(f"Do not trade value on {u['unknown'].split(':')[0]} until this is resolved.")

    money = commercial_answer.get("money", {})
    negotiation = commercial_answer.get("negotiation", {})

    return {
        "decision": commercial_answer.get("decision"),
        "why": commercial_answer.get("why", []),
        "money": money,
        "leverage": {
            "real": real_leverage[:6],
            "theoretical": theoretical_leverage[:4],
        },
        "trade_off": trade_offs[:5],
        "next_move": (commercial_answer.get("what_to_do") or [])[:3],
        "what_could_change_this": commercial_answer.get("decision_changers", []),
        "draft_response": commercial_answer.get("supplier_response"),
        "target": negotiation.get("target"),
        "walk_away": negotiation.get("walk_away"),
    }
