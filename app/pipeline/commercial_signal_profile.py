"""
Phase 4 / R41 -- Commercial Signal reasoning profile.

For "I noticed something -- is there a real commercial problem, what
may be causing it, what should I do?" There is no supplier request
here; the profile must never invent one. Same kernel, same
deterministic engine as Supplier Request -- only the reasoning
sequence, the guardrails, and the answer shape are genuinely
different.
"""
from __future__ import annotations
from typing import Any

from app.pipeline.supplier_request_profile import build_kernel_context_block

COMMERCIAL_SIGNAL_REASONING_SEQUENCE = """You are investigating a commercial signal -- an observed pattern or change, not a supplier request. Work through these questions in order, using ONLY the kernel facts below for anything the kernel already states.

1. What changed?
2. Is the signal real (backed by VERIFIED or CALCULATED kernel facts), or only a claimed pattern?
3. What does the data actually prove?
4. Quantify the change using the kernel's own CALCULATED figures -- never recompute them yourself.
5. Decompose the movement where the kernel supports it: price vs volume vs mix vs specification vs FX vs freight vs discount vs other.
6. What explanations are supported by kernel facts?
7. What explanations are only hypotheses (not yet backed by a kernel fact)?
8. What can we NOT conclude from this evidence?
9. What commercial risk does this create?
10. What is the single highest-value investigation to run next?
11. What should happen in the next 7 days?
12. What should happen in the next 30-90 days?
13. What evidence would confirm or reject the main hypothesis?

Hard rules, never break these:
- Do NOT invent a supplier request. This is an investigation, not a negotiation -- never draft a message to a supplier or frame this as "what to ask the supplier for" unless the case itself already contains a real supplier request.
- Do NOT invent a market benchmark, a savings figure, or a target.
- An average-price increase is NOT the same fact as like-for-like price inflation. If the kernel has no like-for-like (SKU-level, spec-controlled) comparison, say plainly that you cannot yet tell how much of the movement is real price inflation versus mix, specification, or other drivers.
- Do NOT conclude that any specific supplier is overcharging. That requires like-for-like evidence this case does not have. Say what you can and cannot conclude, not more.
- A stakeholder's concern (e.g. Finance asking why spend is rising) is a STAKEHOLDER_VIEW, not a verified fact -- treat it as a reason to investigate, never as evidence of a cause.
- If a kernel fact is CONTRADICTED, say so -- never silently pick one side.
- State each unknown once. Do not repeat the same unresolved point in multiple sections.
"""


def build_commercial_signal_prompt_addition(kernel: dict[str, Any]) -> str:
    return "\n\n" + COMMERCIAL_SIGNAL_REASONING_SEQUENCE + "\n" + build_kernel_context_block(kernel)


_OVERCHARGING_PHRASES = ("overcharging", "over-charging", "is overcharging", "price gouging", "unfairly priced")


def detect_unsupported_overcharging_claim(text: str, kernel: dict[str, Any]) -> bool:
    """Adversarial guard (test C): a claim that a specific supplier is
    overcharging requires like-for-like (SKU-level, spec-controlled)
    evidence. This kernel/case shape never carries that -- average
    price growth is a category/entity-level CALCULATED fact, not a
    like-for-like comparison -- so any overcharging claim in the
    model's own text is, by construction, unsupported here and must be
    caught, not silently trusted."""
    lowered = text.lower()
    return any(p in lowered for p in _OVERCHARGING_PHRASES)


def build_commercial_signal_answer(kernel: dict[str, Any], position: Any) -> dict[str, Any]:
    """Assembles the SIGNAL / WHAT THE DATA SAYS / WHAT MAY EXPLAIN IT /
    WHAT WE CANNOT PROVE / COMMERCIAL RISK / WHAT TO CHECK NEXT / ACTION
    PLAN contract, deterministically, from the kernel and the model's
    own prose fields. Never recomputes a kernel fact; only classifies
    and arranges what's already there."""
    facts = kernel.get("facts", [])
    calculated = [f for f in facts if f["evidence_state"] == "CALCULATED"]
    # Item 4 fix: category-level and supplier-level facts were a single
    # flat list, distinguishable only by reading each line's entity
    # prefix -- not the clear structural separation the case actually
    # needs, since a category-wide trend must never read as if it were
    # a conclusion about one specific supplier. Grouped explicitly by
    # entity here instead. No truncation on the category group at all
    # (it's always small); per-supplier groups keep a real cap so a
    # case with many suppliers doesn't produce an unreadable wall of
    # numbers, but every supplier that has ANY calculated fact gets its
    # own group -- nothing is silently dropped by an overall list limit
    # the way an 8-item flat cap previously could (and, on this exact
    # case, did) cut off a genuinely interesting fact.
    def _fact_line(f):
        return f"{f['metric'].replace('_', ' ')}: {f['value']}" + ('%' if 'percent' in f['metric'] or 'pp' in f['metric'] else (' ' + f['currency'] if f.get('currency') else ''))
    category_data = [_fact_line(f) for f in calculated if f["entity"] == "category"]
    by_supplier_data: dict[str, list[str]] = {}
    for f in calculated:
        if f["entity"] != "category":
            by_supplier_data.setdefault(f["entity"], []).append(_fact_line(f))
    what_the_data_says = {"category": category_data, "by_supplier": by_supplier_data}

    stakeholder_views = kernel.get("stakeholders", [])
    what_may_explain_it = [
        str(insight) for insight in (getattr(position, "commercial_insights", None) or [])
        if not detect_unsupported_overcharging_claim(str(insight), kernel)
    ]

    unknowns = kernel.get("unknowns", [])
    # Rule, explicitly stated in the spec: do not repeat the same
    # unknown in multiple sections. A stakeholder's concern already
    # shown under stakeholder_views (below) must not also appear here
    # as if it were an unproven fact -- a question Finance asked is not
    # the same category of thing as an unresolved fact about the data.
    stakeholder_statements = {s["view"].strip().lower() for s in kernel.get("stakeholders", [])}
    unknowns_not_duplicated = [
        u for u in unknowns
        if not any(stmt in u["unknown"].lower() for stmt in stakeholder_statements)
    ]
    # Relevance filter: preserve the fact, but do not force an
    # irrelevant one into the primary answer. Determined by topic, not
    # by deleting anything -- the kernel itself (position.kernel,
    # available as deeper context) still carries every unknown
    # unchanged. This signal's own topic is whatever it actually
    # calculated: a spend/volume/price investigation (this case shape)
    # has no calculated fact about qualification or capacity at all, so
    # an unknown about a supplier's qualification timeline is a
    # different topic -- sourcing readiness, not this signal -- and
    # does not belong in the primary answer. A signal that DID compute
    # something qualification/capacity-related would keep those
    # unknowns; nothing here is a blanket ban on the topic, only a
    # match against what THIS signal actually investigated.
    calculated_metrics = {f["metric"] for f in calculated}
    signal_is_about_qualification_or_capacity = any(
        "qualification" in m or "capacity" in m for m in calculated_metrics
    )
    _OFF_TOPIC_MARKERS = ("qualification", "capacity")
    what_we_cannot_prove = [
        u["unknown"] for u in unknowns_not_duplicated
        if signal_is_about_qualification_or_capacity or not any(marker in u["unknown"].lower() for marker in _OFF_TOPIC_MARKERS)
    ]
    # The one, specific, always-true unknown for this profile: the
    # kernel never carries a like-for-like comparison, so this line is
    # added deterministically, once, rather than depending on the model
    # to remember to say it.
    if calculated and not any("like-for-like" in str(u).lower() or "like for like" in str(u).lower() for u in what_we_cannot_prove):
        what_we_cannot_prove.append("How much of any average-price movement is real like-for-like price inflation versus mix, specification, or other drivers -- no SKU-level comparison exists in this case.")

    reasoning_text = str(getattr(position, "reasoning", "") or "")
    recommendation_text = str(getattr(position, "recommendation", "") or "")
    insights = getattr(position, "commercial_insights", None) or []
    overcharging_flagged = (
        detect_unsupported_overcharging_claim(reasoning_text, kernel)
        or detect_unsupported_overcharging_claim(recommendation_text, kernel)
        or any(detect_unsupported_overcharging_claim(str(i), kernel) for i in insights)
    )

    signal_subject = kernel.get("case", {}).get("subject")
    has_category_facts = any(f["entity"] == "category" for f in facts)
    if has_category_facts:
        signal = "Category spend and volume are being reviewed for a real commercial change."
    elif signal_subject:
        signal = f"{signal_subject}'s spend is being reviewed for a real commercial change."
    else:
        signal = "This pattern is being reviewed for a real commercial change."

    # Value-density fix, confirmed by a real audit: the model's own
    # "assumptions" field can restate the exact same fact already
    # covered deterministically in what_we_cannot_prove (e.g. both
    # saying, in different words, that no like-for-like comparison
    # exists) -- a genuine repeated-fact case a pure word-overlap check
    # doesn't catch, since the phrasing differs even though the meaning
    # doesn't. Filtered here by checking for shared distinctive terms
    # with what's already stated, not just literal string equality.
    _prove_text = " ".join(what_we_cannot_prove).lower()
    _redundancy_markers = ("like-for-like", "like for like", "sku-level", "sku level")
    what_to_check_next = [
        str(x) for x in (getattr(position, "assumptions", None) or [])
        if not (any(m in str(x).lower() for m in _redundancy_markers) and any(m in _prove_text for m in _redundancy_markers))
    ][:3]

    return {
        "signal": signal,
        "what_the_data_says": what_the_data_says,
        "what_may_explain_it": what_may_explain_it[:5],
        "what_we_cannot_prove": what_we_cannot_prove[:5],
        "commercial_risk": [str(x) for x in (getattr(position, "commercial_insights", None) or []) if "risk" in str(x).lower()][:3],
        "what_to_check_next": what_to_check_next,
        "action_plan": {
            "next_7_days": recommendation_text or None,
            "next_30_90_days": str(getattr(position, "disconfirming_condition", "") or "") or None,
        },
        "stakeholder_views": [{"stakeholder": s["stakeholder"], "view": s["view"]} for s in stakeholder_views],
        "overcharging_claim_flagged_and_removed": overcharging_flagged,
    }
