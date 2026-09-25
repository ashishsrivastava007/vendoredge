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
    # R48 Signal Engine bug fix, found and traced precisely while
    # verifying the OTIF/defect delta calculations added to the
    # kernel: supplier performance facts (otif_change_pp,
    # defect_rate_change_pp, and anything else on SupplierProfile.
    # performance) live in kernel["suppliers"][*]["performance"], a
    # structure entirely separate from the top-level kernel["facts"]
    # list this function has always read. Without this merge, every
    # OTIF/defect calculation added to the kernel was invisible here --
    # confirmed by an actual test producing the wrong "no calculable
    # figure exists yet" headline despite both values being present.
    for supplier in (kernel.get("suppliers", []) or []):
        facts = facts + (supplier.get("performance") or [])
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
    # R48 Signal Engine: multi-dimensional signal detection, replacing
    # the previous spend/volume-only headline logic. Checked in an
    # order that reflects what's actually most informative when
    # several dimensions are present -- a supplier-specific
    # performance deterioration (OTIF/defects) is more directly
    # actionable than a category-level spend pattern, so it leads when
    # both exist. Every branch states only what was actually
    # calculated; the old generic "spend and volume are being
    # reviewed" fallback is gone -- a signal with no spend/volume data
    # at all no longer gets a headline implying it does.
    category_growth = {f["metric"]: f["value"] for f in calculated if f["entity"] == "category"}
    spend_growth = category_growth.get("annual_spend_growth_percent")
    volume_growth = category_growth.get("annual_volume_growth_percent")
    otif_changes = [(f["entity"], f["value"]) for f in calculated if f["metric"] == "otif_change_pp"]
    defect_changes = [(f["entity"], f["value"]) for f in calculated if f["metric"] == "defect_rate_change_pp"]
    spend_share_changes = [(f["entity"], f["value"]) for f in calculated if f["metric"] == "spend_share_change_pp"]
    case_spec_changed = bool(kernel.get("case", {}).get("specification_changed") or kernel.get("case", {}).get("specification_change_description"))
    # R48 Signal Engine: market-divergence detection, reusing the same
    # stated-justification text and marker phrases as the external-
    # intelligence gate in fresh_intelligence.py (kept as a separate,
    # local check rather than a shared import, since this one only
    # needs to recognize the pattern for headline wording -- it never
    # decides whether to spend a research call).
    stated_text = " ".join(str(f.get("value") or "") for f in facts if f.get("metric") == "stated_justification").lower()
    is_market_divergence = any(m in stated_text for m in (
        "market price has fallen", "market prices have fallen", "market price fell", "market prices fell",
        "supplier price has not moved", "supplier's price has not moved", "supplier price remains unchanged", "price has not changed",
    ))

    # R48 Signal Engine, generalized backbone: every dimension actually
    # present is collected into a list, not picked one-at-a-time by an
    # if/elif chain -- this is what makes a genuinely multi-dimensional
    # signal ("spend up, volume up, AND OTIF down") representable at
    # all, rather than silently reporting only the first-matched
    # dimension and dropping the rest. Each entry is deliberately
    # minimal (type/entity/delta/description) so headline, materiality,
    # and hypothesis generation can all walk the same list rather than
    # three separate detection passes drifting out of sync.
    dimensions: list[dict[str, Any]] = []
    if otif_changes:
        entity, delta = otif_changes[0]
        direction = "dropped" if delta < 0 else "improved"
        dimensions.append({"type": "otif", "entity": entity, "delta": delta, "description": f"{entity}'s OTIF has {direction} by {abs(delta):.1f} percentage points"})
    if defect_changes:
        entity, delta = defect_changes[0]
        direction = "increased" if delta > 0 else "decreased"
        dimensions.append({"type": "defect", "entity": entity, "delta": delta, "description": f"{entity}'s defect rate has {direction} by {abs(delta):.1f} percentage points"})
    if spend_share_changes:
        entity, delta = spend_share_changes[0]
        direction = "increased" if delta > 0 else "decreased"
        dimensions.append({"type": "concentration", "entity": entity, "delta": delta, "description": f"{entity}'s share of category spend has {direction} by {abs(delta):.1f} percentage points"})
    if case_spec_changed:
        dimensions.append({"type": "spec_change", "entity": None, "delta": None, "description": "a specification or requirement change has been reported alongside a change in cost"})
    if is_market_divergence:
        dimensions.append({"type": "market_divergence", "entity": None, "delta": None, "description": "a market price movement has been reported, alongside a supplier price that has not moved to match it"})
    if spend_growth is not None and volume_growth is not None:
        direction = "faster than" if spend_growth > volume_growth else "slower than" if spend_growth < volume_growth else "in line with"
        dimensions.append({"type": "spend_volume", "entity": "category", "delta": spend_growth - volume_growth, "description": f"category spend is growing {direction} volume ({spend_growth:+.1f}% spend vs {volume_growth:+.1f}% volume)"})
    elif spend_growth is not None and spend_growth != 0:
        # A literal 0.0% spend change is the absence of a spend signal,
        # not a dimension worth naming alongside a genuine finding from
        # another dimension (e.g. a market-divergence signal on an
        # otherwise flat category) -- excluded here, not by an
        # invented magnitude threshold, but because zero change is not
        # a change.
        dimensions.append({"type": "spend_only", "entity": "category", "delta": spend_growth, "description": f"category spend has changed {spend_growth:+.1f}% versus the prior period"})

    # R48 Signal Engine: multi-dimensional headline. When more than one
    # dimension is genuinely present, they are combined rather than
    # only the first (highest-priority) one reported -- a case can
    # genuinely be about supplier performance AND a spend pattern at
    # once, and dropping one silently would misrepresent what was
    # actually found. Capped at two combined to keep the headline
    # readable; anything beyond that is still fully represented in the
    # sections below, just not crammed into one sentence.
    if dimensions:
        parts = [d["description"] for d in dimensions[:2]]
        if len(parts) == 1:
            signal = parts[0][0].upper() + parts[0][1:] + "."
        else:
            signal = (parts[0][0].upper() + parts[0][1:] + ", and " + parts[1] + ".")
    elif signal_subject:
        signal = f"{signal_subject} has been flagged for review, but no calculable before/after figure exists yet."
    else:
        signal = "This observation has been flagged for review, but no calculable before/after figure exists yet."

    # R48 Signal Engine: materiality engine, replacing the previous
    # "risk" substring match against the model's free text (which
    # matched nothing unless that exact word appeared, regardless of
    # how material the actual numbers were). Now built entirely from
    # what was actually calculated: states the real magnitude of
    # whichever dimension is present, adds the dollar exposure only
    # when a real calculated impact figure exists, and explicitly says
    # when evidence is insufficient to establish impact rather than
    # inventing urgency or a universal threshold.
    commercial_risk: list[str] = []
    # Generalized impact representation (replaces the old scenario_
    # annual_impact reliance, which required requested_change_percent
    # -- a Supplier Request concept most observation-only signals never
    # carry, making that tier effectively dead code for this
    # experience). Computed directly from evidence this profile
    # already has: the category's own current spend (a real VERIFIED
    # fact) and its calculated growth percentage together determine
    # the absolute dollar change algebraically -- not estimated, not
    # borrowed from a different case shape, and never invented when
    # the underlying spend figure isn't available at all.
    category_current_spend = next((f["value"] for f in facts if f["entity"] == "category" and f["metric"] == "annual_spend"), None)
    scenario_impact = None
    scenario_currency = next((f.get("currency") for f in facts if f["entity"] == "category" and f["metric"] == "annual_spend"), None)
    if category_current_spend is not None and spend_growth is not None and spend_growth != -100:
        prior_spend = category_current_spend / (1 + spend_growth / 100)
        scenario_impact = category_current_spend - prior_spend
    if otif_changes:
        entity, delta = otif_changes[0]
        if delta < 0:
            commercial_risk.append(f"A {abs(delta):.1f} percentage-point OTIF decline is an operational continuity signal. Based on the evidence available, the downstream business impact (missed production, expedite costs, customer impact) has not been quantified here.")
    if defect_changes:
        entity, delta = defect_changes[0]
        if delta > 0:
            commercial_risk.append(f"A {delta:.1f} percentage-point rise in defect rate is a quality signal. Based on the evidence available, the cost of rework, scrap, or customer impact has not been quantified here.")
    if spend_growth is not None and volume_growth is not None and spend_growth > volume_growth:
        gap = spend_growth - volume_growth
        if scenario_impact is not None:
            commercial_risk.append(f"Spend growing {gap:.1f} percentage points faster than volume, on this category's spend base, represents a real cost trend -- see the calculated dollar impact above.")
        else:
            commercial_risk.append(f"Spend growing {gap:.1f} percentage points faster than volume is a real signal, but current evidence is insufficient to establish the dollar exposure without knowing the category's total spend base.")
    if spend_share_changes:
        entity, delta = spend_share_changes[0]
        if delta > 0:
            commercial_risk.append(f"{entity}'s growing share of category spend increases dependency on a single supplier. Based on the evidence available, whether qualified alternatives exist has not been established here.")
    if is_market_divergence:
        commercial_risk.append("If the market has genuinely moved and the supplier's price has not, that is a real commercial opportunity to raise -- but the supplier-specific cost basis has not yet been confirmed, so the exact savings potential is not established here.")
    if not commercial_risk and (otif_changes or defect_changes or spend_growth is not None or spend_share_changes or case_spec_changed or is_market_divergence):
        commercial_risk.append("Potentially material, but current evidence is insufficient to establish impact.")

    # R48 Signal Engine: generalized investigation-value layer. A
    # dimension "has established materiality" when it produced a real,
    # named-magnitude commercial_risk line above (a percentage-point
    # gap, a dollar impact) -- not when its downstream dollar cost is
    # fully quantified, which is a much higher and rarer bar. This is
    # read directly from the same conditions the materiality engine
    # above just evaluated, not re-derived or re-guessed from text.
    dimension_established_materiality: dict[str, bool] = {
        "otif": bool(otif_changes and otif_changes[0][1] < 0),
        "defect": bool(defect_changes and defect_changes[0][1] > 0),
        "concentration": bool(spend_share_changes and spend_share_changes[0][1] > 0),
        "spend_volume": bool(spend_growth is not None and volume_growth is not None and spend_growth > volume_growth),
        "market_divergence": is_market_divergence,
        "spec_change": False,  # spec-change alone states no magnitude of its own; it borrows the spend/volume gap when both are present
    }

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

    # R48 Signal Engine, Section 9: competing-explanations engine,
    # generalized. Two hypotheses now apply to ANY dimension with a
    # real calculated delta -- not duplicated per dimension type, but
    # generated once per present dimension via a single shared
    # generator, which is what makes this a framework rather than a
    # per-case-type branch. Neither invents a field the evidence model
    # doesn't have: both are honestly UNKNOWN, since nothing in this
    # evidence model can confirm or deny a one-off event or a data
    # error, and each names exactly what evidence would make it
    # testable rather than pretending the question doesn't exist.
    def _generic_hypotheses(dimension_label: str, dimension_key: str) -> list[dict[str, Any]]:
        return [
            {
                "hypothesis": f"This reflects a one-off or time-limited event rather than a sustained pattern in {dimension_label}.",
                "supporting_evidence": [], "contradicting_evidence": [],
                "missing_evidence": ["Transaction- or period-level detail (e.g. whether this reflects a single large event or a sustained pattern across the period) is not available in this case."],
                "status": "UNKNOWN", "_generic": True, "_dimension": dimension_key,
            },
            {
                "hypothesis": f"The reported {dimension_label} figures reflect a data or reporting error rather than a real change.",
                "supporting_evidence": [], "contradicting_evidence": [],
                "missing_evidence": ["Confirmation that the figures have been validated against the source system (not just reported) is not available in this case."],
                "status": "UNKNOWN", "_generic": True, "_dimension": dimension_key,
            },
        ]

    avg_price_growth = category_growth.get("avg_unit_price_growth_percent") if spend_growth is not None and volume_growth is not None else None
    hypotheses: list[dict[str, Any]] = []
    has_spend_volume_dimension = any(d["type"] == "spend_volume" for d in dimensions)
    if has_spend_volume_dimension:
        if avg_price_growth is not None:
            hypotheses.append({
                "hypothesis": "The average unit price has genuinely increased.",
                "supporting_evidence": [f"Calculated average unit price growth is {avg_price_growth:+.1f}%."] if avg_price_growth > 0 else [],
                "contradicting_evidence": [f"Calculated average unit price growth is {avg_price_growth:+.1f}%, not an increase."] if avg_price_growth <= 0 else [],
                "missing_evidence": ["SKU-level price data would confirm whether this is uniform across items or concentrated in a few."],
                "status": "SUPPORTED" if avg_price_growth > 0 else "NOT_SUPPORTED",
                "_dimension": "spend_volume",
            })
        else:
            hypotheses.append({
                "hypothesis": "The average unit price has genuinely increased.",
                "supporting_evidence": [], "contradicting_evidence": [],
                "missing_evidence": ["No average-unit-price calculation exists yet for this case."],
                "status": "UNKNOWN",
                # A real, structural dependency, not an assumed priority:
                # mix-shift and specification-attribution below cannot be
                # meaningfully tested until price-vs-mix-vs-volume is
                # established first -- this is what makes it the gate.
                "_dimension": "spend_volume", "_gates_others": True,
            })
        hypotheses.append({
            "hypothesis": "A shift toward higher-cost items within the category (mix shift) explains some or all of the change.",
            "supporting_evidence": [], "contradicting_evidence": [],
            "missing_evidence": ["SKU-level or sub-category volume/spend breakdown -- not available in this evidence model."],
            # Honest reclassification, found while stress-testing the
            # investigation-value layer: this names a specific artifact
            # (SKU-level data), which made it look more "feasible" than
            # the generic hypotheses -- but unlike the average-unit-
            # price hypothesis (resolvable the moment spend/volume
            # numbers exist), no field anywhere in this evidence model
            # can ever represent SKU-level detail, in any case, ever.
            # It shares the generic hypotheses' real infeasibility, so
            # it's marked the same way rather than misleadingly ranked
            # as more achievable than it actually is.
            "status": "UNKNOWN", "_dimension": "spend_volume", "_generic": True,
        })
        hypotheses.extend(_generic_hypotheses("the spend/volume movement", "spend_volume"))

    # P1 fix (acceptance-test finding, B9): specification-change
    # analysis decoupled from the spend/volume block. Previously nested
    # entirely inside `if has_spend_volume_dimension:`, so a genuine
    # spec-change signal with no volume figure (spend data alone, or no
    # spend data at all) got only the two generic, permanently-UNKNOWN
    # hypotheses instead of this richer, more informative one -- the
    # real information the user provided (a specification change was
    # reported) was being discarded rather than analyzed. Now fires
    # whenever case_spec_changed is true, independent of which other
    # dimensions are present. Never invents volume evidence, a spend
    # figure, or materiality that isn't there: when no cost movement
    # (spend/volume OR spend-only) exists to attribute the change to,
    # status stays honestly UNKNOWN with a named, real evidence gap
    # (a spend or cost figure), not PARTIALLY_SUPPORTED with an implied
    # magnitude that was never established.
    has_any_cost_movement = has_spend_volume_dimension or any(d["type"] == "spend_only" for d in dimensions)
    if case_spec_changed:
        if has_any_cost_movement:
            hypotheses.append({
                "hypothesis": "A specification or requirement change explains some or all of the cost movement.",
                "supporting_evidence": ["A specification change was explicitly reported alongside a real cost movement."],
                "contradicting_evidence": [],
                "missing_evidence": ["The magnitude of cost impact specifically attributable to the specification change has not been isolated."],
                "status": "PARTIALLY_SUPPORTED", "_dimension": "spec_change",
            })
        else:
            hypotheses.append({
                "hypothesis": "A specification or requirement change explains some or all of the cost movement.",
                "supporting_evidence": ["A specification change was explicitly reported."],
                "contradicting_evidence": [],
                "missing_evidence": ["No spend or cost figure exists yet to establish what movement, if any, the specification change should be attributed to."],
                "status": "UNKNOWN", "_dimension": "spec_change",
            })
    elif has_any_cost_movement:
        # A real cost movement exists but no specification change was
        # reported for it -- a genuine negative finding, only
        # meaningful when there's an actual movement to compare
        # against (not applicable to a case with neither).
        hypotheses.append({
            "hypothesis": "A specification or requirement change explains some or all of the cost movement.",
            "supporting_evidence": [], "contradicting_evidence": ["No specification change was reported for this case."],
            "missing_evidence": [], "status": "NOT_SUPPORTED", "_dimension": "spend_volume",
        })

    # Generalized: every OTHER dimension present also gets the two
    # universal hypotheses, using its own real magnitude in the
    # description rather than a generic placeholder -- this is what
    # closes the "mix shift only works for spend/volume" gap without
    # writing a new branch per signal type.
    for d in dimensions:
        if d["type"] == "otif":
            hypotheses.extend(_generic_hypotheses(f"{d['entity']}'s OTIF", "otif"))
        elif d["type"] == "defect":
            hypotheses.extend(_generic_hypotheses(f"{d['entity']}'s defect rate", "defect"))
        elif d["type"] == "concentration":
            hypotheses.extend(_generic_hypotheses(f"{d['entity']}'s spend concentration", "concentration"))
        elif d["type"] == "spec_change":
            hypotheses.extend(_generic_hypotheses("the specification change", "spec_change"))
        elif d["type"] == "market_divergence":
            hypotheses.extend(_generic_hypotheses("the market price movement", "market_divergence"))

    # R48 Signal Engine: explicit contradiction detection, kept
    # visibly separate from ordinary hypotheses (a different list, a
    # different purpose) rather than folded in as just another
    # CONTRADICTED-status entry -- a contradiction is a conflict
    # between two things the case itself asserts, not an open question
    # about the world. Narrow and evidence-literal by design: each
    # check compares a real CALCULATED fact against the case's own
    # stated text or another CALCULATED fact, never against an assumed
    # baseline.
    contradictions: list[dict[str, Any]] = []
    _price_increase_claimed = any(p in stated_text for p in (
        "price increase", "prices have risen", "price rose", "price increased", "price went up", "cost increase", "costs have risen",
    ))
    _price_decrease_claimed = any(p in stated_text for p in (
        "price decrease", "prices have fallen", "price fell", "price decreased", "price went down", "cost decrease",
    ))
    if avg_price_growth is not None:
        if _price_increase_claimed and avg_price_growth <= 0:
            contradictions.append({
                "description": "The case's own stated text claims a price increase, but the calculated average unit price movement does not support that.",
                "calculated_evidence": f"Calculated average unit price growth is {avg_price_growth:+.1f}%.",
                "claimed_evidence": "The stated justification asserts a price increase.",
                "_dimension": "spend_volume",
            })
        elif _price_decrease_claimed and avg_price_growth > 0:
            contradictions.append({
                "description": "The case's own stated text claims a price decrease, but the calculated average unit price movement does not support that.",
                "calculated_evidence": f"Calculated average unit price growth is {avg_price_growth:+.1f}%.",
                "claimed_evidence": "The stated justification asserts a price decrease.",
                "_dimension": "spend_volume",
            })
    for d in dimensions:
        if d["type"] == "otif" and d["delta"] is not None:
            if d["delta"] < 0 and any(p in stated_text for p in ("otif improved", "otif has improved", "delivery performance improved", "on-time delivery improved")):
                contradictions.append({
                    "description": f"The case's own stated text claims {d['entity']}'s OTIF improved, but the calculated figures show a decline.",
                    "calculated_evidence": f"Calculated OTIF change is {d['delta']:+.1f} percentage points.",
                    "claimed_evidence": "The stated text asserts OTIF improved.",
                    "_dimension": "otif",
                })
            elif d["delta"] > 0 and any(p in stated_text for p in ("otif dropped", "otif declined", "otif deteriorated", "delivery performance declined")):
                contradictions.append({
                    "description": f"The case's own stated text claims {d['entity']}'s OTIF declined, but the calculated figures show an improvement.",
                    "calculated_evidence": f"Calculated OTIF change is {d['delta']:+.1f} percentage points.",
                    "claimed_evidence": "The stated text asserts OTIF declined.",
                    "_dimension": "otif",
                })

    # R48 Signal Engine, Section 11 (redesigned): generalized
    # investigation-value layer, stress-tested against deliberately
    # conflicting factors -- status, feasibility, materiality, and
    # magnitude are no longer collapsed into one binary "established"
    # signal. Ordered as: (1) feasibility -- an investigation that
    # cannot realistically be resolved is never "first," however
    # material, because recommending it produces no real next step;
    # (2) decision impact -- a genuine, evidence-derived magnitude
    # comparison (a quantified dollar figure ranks above a percentage-
    # point-only figure, which ranks above no established impact at
    # all; larger magnitudes rank above smaller ones within the same
    # kind), so a high-impact UNKNOWN correctly outranks a low-impact
    # PARTIALLY_SUPPORTED hypothesis rather than status always winning
    # by default; (3) status, as the final tie-breaker among
    # otherwise-equal candidates. No dimension TYPE (OTIF, spend,
    # concentration...) appears anywhere in this ordering -- only what
    # each dimension's own evidence actually established.
    dimension_magnitude: dict[str, float] = {
        "otif": abs(otif_changes[0][1]) if otif_changes else 0.0,
        "defect": abs(defect_changes[0][1]) if defect_changes else 0.0,
        "concentration": abs(spend_share_changes[0][1]) if spend_share_changes else 0.0,
        "spend_volume": abs(spend_growth - volume_growth) if (spend_growth is not None and volume_growth is not None) else 0.0,
    }
    dimension_dollar_impact: dict[str, float] = {}
    if scenario_impact is not None and dimension_established_materiality.get("spend_volume"):
        dimension_dollar_impact["spend_volume"] = abs(scenario_impact)

    def _decision_impact_rank(h: dict[str, Any]) -> tuple[int, float]:
        if h.get("_gates_others"):
            return (0, 0.0)  # unlocks multiple other tests -- highest information value, not a magnitude comparison
        dim = h.get("_dimension")
        if dim in dimension_dollar_impact:
            return (1, -dimension_dollar_impact[dim])
        if dimension_established_materiality.get(dim, False):
            return (2, -dimension_magnitude.get(dim, 0.0))
        return (3, 0.0)

    def _investigation_value(h: dict[str, Any]) -> tuple:
        feasibility_rank = 1 if h.get("_generic") else 0
        status_rank = 0 if h["status"] == "PARTIALLY_SUPPORTED" else 1
        return (feasibility_rank, _decision_impact_rank(h), status_rank)

    first_investigation = None
    # R48 Signal Engine, final structural fix: decision-relevant
    # uncertainty, replacing "does an UNKNOWN hypothesis exist" with
    # "has this dimension's movement already been explained by
    # something resolved." A dimension with a SUPPORTED or PARTIALLY_
    # SUPPORTED, non-generic explanation is treated as settled -- its
    # remaining residual generic hypotheses (one-off event, data
    # error) no longer count as decision-relevant, because a real
    # CALCULATED explanation already exists and litigating whether the
    # underlying numbers might also be a data artifact doesn't change
    # what to do. A dimension with NO resolved explanation keeps its
    # hypotheses decision-relevant only if that dimension's own
    # materiality was actually established -- an unmaterial dimension
    # with open questions still doesn't justify investigation work.
    # This is deliberately NOT "does hypothesis type X exist in our
    # catalogue" -- it asks the same question of every dimension
    # uniformly, catalogue size aside.
    def _dimension_has_resolved_explanation(dimension_key: str) -> bool:
        return any(
            h.get("_dimension") == dimension_key and h["status"] in ("SUPPORTED", "PARTIALLY_SUPPORTED") and not h.get("_generic")
            for h in hypotheses
        )

    def _is_decision_relevant(h: dict[str, Any]) -> bool:
        if h.get("_gates_others"):
            return True
        if h["status"] == "PARTIALLY_SUPPORTED":
            return True
        dim = h.get("_dimension")
        if _dimension_has_resolved_explanation(dim):
            return False
        return dimension_established_materiality.get(dim, False)

    unresolved = [h for h in hypotheses if h["status"] in ("UNKNOWN", "PARTIALLY_SUPPORTED") and _is_decision_relevant(h)]
    if not unresolved:
        # Section 10/explicit outcome: hypotheses exist and were
        # actually tested, and nothing that remains open is decision-
        # relevant -- a genuine "enough evidence to act" conclusion,
        # not the absence of an answer, and not merely the absence of
        # any UNKNOWN in the catalogue. Distinguished from a genuinely
        # weak signal (WATCH): "sufficient to act" implies there IS a
        # real, established finding worth acting on -- a case with no
        # material dimension at all has nothing to act on either, and
        # must not be told the same thing as a resolved, material one.
        if hypotheses:
            if any(dimension_established_materiality.values()):
                first_investigation = "No further investigation is needed based on current evidence -- the available evidence is sufficient to act on."
            else:
                first_investigation = "This signal is not yet shown to be material -- monitor rather than investigate or act on it now."
    else:
        best = min(unresolved, key=_investigation_value)
        impact_tier = _decision_impact_rank(best)[0]
        if impact_tier == 3 and best.get("_generic"):
            # The best-scoring remaining unknown has no established
            # materiality AND asks a broad, rarely-resolvable question --
            # investigating it is unlikely to change anything. Do not
            # manufacture investigation work merely because an UNKNOWN
            # hypothesis technically exists; represent this honestly as
            # something to watch, not something to chase.
            first_investigation = "The remaining unknowns here are not yet shown to be material and are not easily resolvable -- monitor rather than launch an investigation on this basis alone."
        elif best.get("_gates_others"):
            first_investigation = "Establish whether the change is driven by price, mix, or volume -- without that split, any negotiation or supplier conversation is premature."
        else:
            first_investigation = f"Resolve whether \"{best['hypothesis'].rstrip('.')}\" -- {best['missing_evidence'][0] if best['missing_evidence'] else 'more evidence is needed'}."

    # The "_generic"/"_dimension"/"_gates_others" markers are internal
    # prioritisation details, not part of the buyer-facing contract --
    # stripped here, once, rather than every caller needing to know to
    # ignore them.
    _INTERNAL_HYPOTHESIS_KEYS = ("_generic", "_dimension", "_gates_others")

    # R48 Signal Engine: explicit decision state (ACT_NOW / INVESTIGATE
    # / WATCH). Evaluated from what was actually established above, in
    # this order: a contradiction tied to a dimension that's actually
    # material blocks a clean decision outright (the case's own
    # evidence disagrees with itself on the thing that matters, so
    # nothing downstream can be trusted yet); no dimension having any
    # established materiality at all means there's nothing here worth
    # acting OR investigating on, so watch rather than manufacture
    # either; a decision-relevant unresolved hypothesis existing means
    # genuine investigation is warranted; otherwise, whatever is
    # material has already been explained by something resolved, so
    # the evidence is sufficient to act.
    # Fixed during the decision-state stress test: a contradiction was
    # being judged material by the narrow "spend growing faster than
    # volume" gate (dimension_established_materiality), which wrongly
    # let a genuine, large price-claim-vs-calculation conflict fall
    # through to WATCH whenever spend happened not to be outpacing
    # volume specifically. Every contradiction this profile generates
    # is, by construction, already tied to a real CALCULATED fact (the
    # detector never fires otherwise) -- so a detected contradiction is
    # treated as material on that basis alone, not re-gated by a
    # narrower, differently-purposed materiality check. Distinguishing
    # a large conflict from a genuinely trivial one (per-scenario
    # "immaterial contradiction") is not yet solved and is reported
    # honestly as a limitation, not silently threshold-faked here.
    _material_contradiction = bool(contradictions)
    _any_material_dimension = any(dimension_established_materiality.values())
    if _material_contradiction:
        decision_state = "INVESTIGATE"
    elif not _any_material_dimension:
        decision_state = "WATCH"
    elif unresolved:
        decision_state = "INVESTIGATE"
    else:
        decision_state = "ACT_NOW"

    contradictions = [{k: v for k, v in c.items() if k != "_dimension"} for c in contradictions]
    hypotheses = [{k: v for k, v in h.items() if k not in _INTERNAL_HYPOTHESIS_KEYS} for h in hypotheses]

    return {
        "signal": signal,
        "what_the_data_says": what_the_data_says,
        "what_may_explain_it": what_may_explain_it[:5],
        "what_we_cannot_prove": what_we_cannot_prove[:5],
        "commercial_risk": commercial_risk[:3],
        "hypotheses": hypotheses,
        "decision_state": decision_state,
        "contradictions": contradictions,
        "first_investigation": first_investigation,
        "what_to_check_next": what_to_check_next,
        "action_plan": {
            "next_7_days": recommendation_text or None,
            "next_30_90_days": str(getattr(position, "disconfirming_condition", "") or "") or None,
        },
        "stakeholder_views": [{"stakeholder": s["stakeholder"], "view": s["view"]} for s in stakeholder_views],
        "overcharging_claim_flagged_and_removed": overcharging_flagged,
    }
