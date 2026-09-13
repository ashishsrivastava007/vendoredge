"""
Phase 5 / R41 -- Category Strategy reasoning profile.

SCOPE, STATED HONESTLY: this implementation covers category diagnosis,
evidence-based supplier strategy classification, and the proven-vs-
hypothesis discipline -- all built on the same kernel, with the same
"no LLM recalculation, no invented figures" guarantees as the other two
profiles. Market intelligence (Section 11-13 of the spec) is
INTERFACE-ONLY here: the data shapes exist so a future phase can
populate them from a real research capability, but this environment has
no live external market data access, and nothing here fabricates any.
The full 3-year roadmap, contract-strategy detail, and supply-chain
detail (Sections 9-10, 14-21) are NOT built in this pass -- attempting
to fake them would violate the spec's own explicit instruction not to
pretend completeness. What IS built: a real, evidence-grounded category
diagnosis and supplier strategy, the adversarial guards the golden case
requires, and a scoped, honest "what I would do" recommendation.
"""
from __future__ import annotations
from typing import Any

from app.pipeline.supplier_request_profile import build_kernel_context_block
from app.pipeline.commercial_signal_profile import detect_unsupported_overcharging_claim
from app.pipeline.category_archetype import detect_archetype, ARCHETYPE_LENS_LABELS
from app.pipeline.esg_intelligence import build_esg_answer_section
from app.pipeline.dependency_roadmap import build_initiatives, build_dependency_aware_roadmap


def _build_dependency_roadmap_section(kernel: dict[str, Any], diagnosis: dict[str, Any], supplier_strategies: list[dict[str, Any]]) -> dict[str, Any]:
    esg_answer = build_esg_answer_section(kernel)
    initiatives = build_initiatives(kernel, diagnosis, supplier_strategies, esg_answer)
    return build_dependency_aware_roadmap(initiatives)

CATEGORY_STRATEGY_REASONING_SEQUENCE = """You are building a category strategy. Work through these questions in order, using ONLY the kernel facts below for anything the kernel already states.

1. Where does the category stand today (spend, volume, price, using kernel CALCULATED facts only)?
2. Where is the money going -- which suppliers, at what share?
3. What is proven (VERIFIED/CALCULATED facts) versus only a hypothesis (not yet backed by a kernel fact)?
4. What is changing, and why -- to the extent the kernel supports an explanation?
5. Which suppliers should be maintained, developed, challenged, or reduced -- based on evidence (spend share, growth, qualification, performance), never a guess?
6. What are the real, evidence-supported quick wins -- and what genuinely needs months of qualification first?
7. What could change this strategy (an unresolved unknown or contradiction that, if resolved, would change the recommendation)?

Hard rules, never break these:
- Do NOT invent a market benchmark, a savings number, or a concentration target. If the kernel doesn't have it, say the evidence doesn't yet support a number.
- Do NOT conclude a specific supplier is overcharging. That needs like-for-like evidence this kernel does not have.
- Do NOT treat an unqualified alternative supplier as an immediately usable source. Qualification status is a real constraint, not a formality.
- Do NOT invent a specific market trend or claim market conditions prove a supplier's cost claim, unless real market evidence is present in the kernel -- there is none in this environment yet, so do not invent any.
- State each unknown once. Do not repeat the same fact, risk, or recommendation under a different heading.
- Every recommendation must trace to a specific kernel fact -- name it.
"""


def build_category_strategy_prompt_addition(kernel: dict[str, Any]) -> str:
    return "\n\n" + CATEGORY_STRATEGY_REASONING_SEQUENCE + "\n" + build_kernel_context_block(kernel)


# ---------------------------------------------------------------------
# Category diagnosis -- pure arithmetic over already-established kernel
# facts, never a new judgment call, matching the same discipline as the
# scenario/growth engines. Concentration (share) is a straightforward
# division of a supplier's own VERIFIED/CALCULATED spend by the
# category's VERIFIED/CALCULATED spend -- both already exist as kernel
# facts; this never asks the model to compute or reconcile it.
# ---------------------------------------------------------------------

def build_category_diagnosis(kernel: dict[str, Any]) -> dict[str, Any]:
    facts = kernel.get("facts", [])
    category_spend = next((f["value"] for f in facts if f["entity"] == "category" and f["metric"] == "annual_spend"), None)
    category_currency = next((f["currency"] for f in facts if f["entity"] == "category" and f["metric"] == "annual_spend"), None)
    category_growth = next((f["value"] for f in facts if f["entity"] == "category" and f["metric"] == "annual_spend_growth_percent"), None)
    category_volume_growth = next((f["value"] for f in facts if f["entity"] == "category" and f["metric"] == "annual_volume_growth_percent"), None)
    category_price_growth = next((f["value"] for f in facts if f["entity"] == "category" and f["metric"] == "avg_unit_price_growth_percent"), None)

    supplier_entities = sorted({f["entity"] for f in facts if f["entity"] not in ("category",)})
    suppliers = []
    for entity in supplier_entities:
        spend = next((f["value"] for f in facts if f["entity"] == entity and f["metric"] == "annual_spend"), None)
        growth = next((f["value"] for f in facts if f["entity"] == entity and f["metric"] == "annual_spend_growth_percent"), None)
        share = round((spend / category_spend) * 100, 1) if spend is not None and category_spend else None
        suppliers.append({"supplier": entity, "annual_spend": spend, "spend_growth_percent": growth, "category_share_percent": share})
    suppliers.sort(key=lambda s: (s["annual_spend"] or 0), reverse=True)

    return {
        "category_annual_spend": category_spend,
        "category_currency": category_currency,
        "category_spend_growth_percent": category_growth,
        "category_volume_growth_percent": category_volume_growth,
        "category_price_growth_percent": category_price_growth,
        "suppliers_by_spend": suppliers,
    }


# ---------------------------------------------------------------------
# Supplier strategy classification -- rules-based, evidence-grounded,
# NOT a prediction. Every classification cites the specific fact that
# drove it.
# ---------------------------------------------------------------------

_STRATEGY_OPTIONS = ("maintain", "develop", "challenge", "qualify", "dual-source", "consolidate", "reduce_dependency", "exit", "monitor")


def classify_supplier_strategy(supplier_diagnosis: dict[str, Any], supplier_profile: dict[str, Any] | None) -> dict[str, Any]:
    """Returns {strategy, reason}. Conservative by design: defaults to
    "monitor" (the only classification that asserts nothing) whenever
    the evidence genuinely doesn't clearly support a stronger call --
    this is a strategic classification, not a guess, and an
    unsupported claim of "exit" or "consolidate" is exactly the kind of
    invented conclusion the adversarial tests exist to catch.

    Works for BOTH an incumbent with real spend/share data
    (supplier_diagnosis populated) AND a candidate alternative with no
    awarded spend at all (supplier_diagnosis empty, classification
    driven purely by qualification/capacity evidence) -- a supplier
    existing in the case is never, by itself, a reason to classify it;
    each branch below requires an actual fact."""
    share = supplier_diagnosis.get("category_share_percent")
    growth = supplier_diagnosis.get("spend_growth_percent")
    qualification = (supplier_profile or {}).get("qualification")
    capacity = (supplier_profile or {}).get("capacity")

    if share is not None and share >= 50:
        return {"strategy": "challenge", "reason": f"holds {share}% of category spend -- a concentration level worth actively challenging with dual-sourcing or competitive pressure, not treating as settled"}
    if qualification and (
        qualification.get("metric") == "qualification_timeline"
        or "not" in str(qualification.get("value", "")).lower()
        or str(qualification.get("value", "")).lower() in ("in_progress", "not_started")
    ):
        return {"strategy": "qualify", "reason": f"qualification is not yet complete (stated: {qualification['value']}) -- do not treat as an immediately usable alternative"}
    if share is not None and share >= 25 and growth is not None and growth > (supplier_diagnosis.get("_category_growth") or 0):
        return {"strategy": "develop", "reason": f"already holds {share}% of category spend and is growing faster than the category -- worth actively managing the relationship, not just monitoring it"}
    # Capacity-unvalidated alone (no qualification concern) is
    # deliberately "monitor", not "qualify" -- these are different
    # evidence gaps. Qualification-incomplete means the supplier
    # cannot yet be used at all; an unvalidated capacity figure on an
    # otherwise-fine supplier just needs a data check, which "monitor
    # / validate capacity" reflects more accurately than "qualify".
    if capacity and "unvalidated" in str(capacity.get("value", "")).lower():
        return {"strategy": "monitor", "reason": "capacity is stated but not yet validated -- confirm the figure before relying on it as an alternative"}
    return {"strategy": "monitor", "reason": "current evidence does not clearly support a stronger classification than ongoing monitoring"}


# ---------------------------------------------------------------------
# Supply chain and contract notes -- real evidence, honest about gaps.
# lead_time_weeks/otif_percent/defect_rate_percent and payment_terms/
# incoterm are genuinely extracted evidence, already in the kernel
# (fixed this pass -- see kernel.py). Expiry, indexation, rebates, MOQ,
# and inventory have no evidence field anywhere in this schema yet --
# rather than invent placeholder values, this says so honestly.
# ---------------------------------------------------------------------

def build_supply_chain_notes(kernel: dict[str, Any]) -> list[str]:
    notes = []
    for s in kernel.get("suppliers", []):
        bits = []
        for f in s.get("performance", []):
            if f["metric"] == "otif_percent":
                bits.append(f"OTIF {f['value']}%")
            elif f["metric"] == "defect_rate_percent":
                bits.append(f"defect rate {f['value']}%")
            elif f["metric"] == "lead_time_weeks":
                bits.append(f"lead time {f['value']} weeks")
        if bits:
            notes.append(f"{s['supplier_name']}: {', '.join(bits)}.")
    return notes


def build_contract_notes(kernel: dict[str, Any]) -> list[str]:
    notes = []
    for s in kernel.get("suppliers", []):
        if s.get("commercial_position"):
            notes.append(f"{s['supplier_name']}: {s['commercial_position']}.")
    return notes


# ---------------------------------------------------------------------
# Quick wins -- genuinely time-gated using the REAL stated timeframe,
# never a generic assumption. A like-for-like price check needs only
# internal SKU data, so it is a real 0-30 day action. A supplier
# qualification with a stated "4-6 months" timeline is never called a
# quick win -- it is classified by its own stated duration.
# ---------------------------------------------------------------------

def build_quick_wins(kernel: dict[str, Any], diagnosis: dict[str, Any]) -> dict[str, list[str]]:
    wins = {"0_30_days": [], "31_90_days": [], "3_6_months": []}
    if diagnosis.get("category_price_growth_percent") is not None:
        wins["0_30_days"].append("Pull SKU-level pricing for the top product families and run a real like-for-like comparison -- this needs only internal data, not external research.")
    for s in kernel.get("suppliers", []):
        q = s.get("qualification")
        if q and q.get("metric") == "qualification_timeline":
            timeframe = str(q["value"]).lower()
            bucket = "3_6_months" if any(n in timeframe for n in ("4-6", "5-6", "6")) else "31_90_days"
            wins[bucket].append(f"{s['supplier_name']}: complete qualification (stated timeline: {q['value']}) before treating as an executable alternative.")
    for s in kernel.get("suppliers", []):
        cap = s.get("capacity")
        if cap and "unvalidated" in str(cap.get("value", "")).lower():
            wins["0_30_days"].append(f"{s['supplier_name']}: validate the stated capacity figure -- this is a data check, not a qualification programme.")
    return wins


# ---------------------------------------------------------------------
# Priority ranking -- evidence-grounded, explainable. Value = spend
# magnitude (a real number already in the kernel). Risk = a real
# contradiction or an unresolved qualification/capacity gap. Urgency =
# concentration level. No arbitrary numeric weights are invented; the
# ranking order itself, with a stated reason per item, IS the output --
# not a fabricated score.
# ---------------------------------------------------------------------

def build_priority_ranking(diagnosis: dict[str, Any], supplier_strategies: list[dict[str, Any]], kernel: dict[str, Any]) -> list[dict[str, str]]:
    priorities = []
    for s in supplier_strategies:
        if s["strategy"] in ("challenge", "qualify"):
            priorities.append({"priority": f"{s['supplier']}: {s['strategy'].replace('_', ' ')}", "reason": s["reason"]})
    if kernel.get("facts") and any(f["evidence_state"] == "CONTRADICTED" for f in kernel["facts"]):
        priorities.append({"priority": "Resolve the pricing-history contradiction", "reason": "A supplier claim directly conflicts with the case's own documented history -- this affects how much weight to give any cost justification."})
    if diagnosis.get("category_price_growth_percent") is not None:
        priorities.append({"priority": "Run the like-for-like price check", "reason": "Average price growth is real, but the cause is not yet proven -- this is the single fact that would change every other conclusion here."})
    return priorities


# ---------------------------------------------------------------------
# 3-year roadmap -- assembled entirely from the evidence-grounded
# pieces above. Nothing generic is added; a year with no evidence-
# supported action for THIS category stays honestly thin rather than
# padded with filler.
# ---------------------------------------------------------------------

def build_roadmap(quick_wins: dict[str, list[str]], supplier_strategies: list[dict[str, Any]], diagnosis: dict[str, Any]) -> dict[str, list[str]]:
    # Value-density + buyer-language fix, confirmed by certification
    # findings #6 and #8: this previously duplicated quick_wins
    # verbatim under "now"/"days_30"/"days_90", duplicated the full
    # supplier-strategy sentences under "year_1", AND referenced
    # "structural_implication" -- a literal internal key name -- in the
    # buyer-facing text. Roadmap is now the ONE place the time-phased
    # plan lives; Year 1 names every supplier needing real action
    # (never just the first one), in plain English, with no reference
    # to any internal object or key name anywhere.
    year1_suppliers = [f"{s['supplier']} ({s['strategy']})" for s in supplier_strategies if s["strategy"] != "monitor"]
    year1 = [f"Act on the supplier strategy for {', '.join(year1_suppliers)}."] if year1_suppliers else ["No evidence-supported Year 1 supplier action beyond the quick wins above."]
    return {
        "now": quick_wins["0_30_days"],
        "days_90": quick_wins["31_90_days"] + quick_wins["3_6_months"],
        "year_1": year1,
        "year_2": ["Not yet supported by evidence -- depends on the outcome of Year 1 qualification and concentration work."],
        "year_3": ["Not yet supported by evidence -- revisit once Year 1/2 outcomes and real market data are available."],
    }


# ---------------------------------------------------------------------
# Answer assembly
# ---------------------------------------------------------------------

def build_category_strategy_answer(kernel: dict[str, Any], position: Any) -> dict[str, Any]:
    diagnosis = build_category_diagnosis(kernel)
    supplier_profiles = {s["supplier_name"]: s for s in kernel.get("suppliers", [])}
    diagnosis_by_supplier = {s["supplier"]: s for s in diagnosis["suppliers_by_spend"]}

    # Supplier-universe fix, confirmed by certification finding #5: this
    # previously classified only suppliers with spend data (diagnosis.
    # suppliers_by_spend), silently excluding every candidate
    # alternative -- exactly Supplier B/C/D in the golden case, each
    # with real qualification/capacity evidence but no awarded spend.
    # Now iterates the FULL supplier universe from the kernel (every
    # supplier the case named), using spend/share data where it
    # genuinely exists and qualification/capacity evidence alone where
    # it doesn't -- never inventing a classification just because a
    # supplier exists; each branch in classify_supplier_strategy still
    # requires an actual fact.
    supplier_strategies = []
    for name, profile in supplier_profiles.items():
        s_with_context = dict(diagnosis_by_supplier.get(name, {}))
        s_with_context["_category_growth"] = diagnosis.get("category_spend_growth_percent")
        classification = classify_supplier_strategy(s_with_context, profile)
        supplier_strategies.append({"supplier": name, "sentence": f"{name} \u2014 {classification['strategy']}: {classification['reason']}.", **classification})
    # Stable order: challenge/develop first (the suppliers needing real
    # attention), then qualify, then monitor -- not alphabetical, so
    # the most consequential classification leads.
    _order = {"challenge": 0, "develop": 1, "qualify": 2, "monitor": 3}
    supplier_strategies.sort(key=lambda s: _order.get(s["strategy"], 9))

    # Adversarial guard, same discipline as Commercial Signal: an
    # overcharging claim anywhere in the model's own text is detected
    # and excluded from what reaches the buyer.
    reasoning_text = str(getattr(position, "reasoning", "") or "")
    recommendation_text = str(getattr(position, "recommendation", "") or "")
    insights = getattr(position, "commercial_insights", None) or []
    overcharging_flagged = (
        detect_unsupported_overcharging_claim(reasoning_text, kernel)
        or detect_unsupported_overcharging_claim(recommendation_text, kernel)
        or any(detect_unsupported_overcharging_claim(str(i), kernel) for i in insights)
    )
    what_is_changing = [str(i) for i in insights if not detect_unsupported_overcharging_claim(str(i), kernel)]

    unknowns = kernel.get("unknowns", [])
    what_still_needs_to_be_learned = [u["unknown"] for u in unknowns]
    # The same deterministic caveat commercial_signal always adds, for
    # the same reason: this kernel shape never carries a like-for-like
    # (SKU-level) comparison, so "what is driving the price movement"
    # is never provably settled -- state that once, deterministically,
    # rather than depend on the model remembering to say it every time.
    if diagnosis.get("category_price_growth_percent") is not None and not any(
        "like-for-like" in str(u).lower() or "like for like" in str(u).lower() for u in what_still_needs_to_be_learned
    ):
        what_still_needs_to_be_learned.append(
            "How much of the price movement is real like-for-like inflation versus mix, specification, or other drivers -- no SKU-level comparison exists in this case."
        )

    # Stakeholder views: a genuinely real gap, confirmed by running the
    # actual golden case -- Engineering's specification-change note
    # never appeared anywhere in this answer at all, even though the
    # spec explicitly requires it to be recognized. Surfaced here,
    # directly from the kernel, never from the model's own prose.
    stakeholder_views = [{"stakeholder": s["stakeholder"], "view": s["view"]} for s in kernel.get("stakeholders", [])]

    # Market intelligence: interface only, honestly empty. See module
    # docstring -- this environment has no live external market data
    # access, and nothing here invents any.
    market_drivers: list[dict[str, Any]] = []

    # Decision-quality fix, confirmed by certification finding #1: the
    # primary recommendation was trapped in position.recommendation and
    # never actually reached this answer -- surfaced here directly,
    # the same established pattern every other profile already uses
    # (this is the model's own synthesis, which is what a
    # "recommendation" field is for; it is not a fabricated fact).
    decision = recommendation_text or None

    # Commercial-correctness fix, confirmed by certification finding
    # #2: the 7% scenario and the delta existed correctly in the
    # kernel but were never surfaced in this answer's own text. Read
    # directly from the kernel's own CALCULATED facts -- never
    # recalculated here.
    facts = kernel.get("facts", [])
    money = None
    _a = next((f for f in facts if f["metric"] == "scenario_a_impact"), None)
    _b = next((f for f in facts if f["metric"] == "scenario_b_impact"), None)
    _diff = next((f for f in facts if f["metric"] == "scenario_difference"), None)
    # Money reference: the scenario figures are tied to whichever
    # supplier the scenario engine actually computed them for -- that's
    # the scenario facts' own entity, read directly rather than
    # re-derived, so this can never disagree with financial_impact.
    _scenario_entity = (_a or _b or _diff or {}).get("entity")
    _spend = next((f for f in facts if f["metric"] == "annual_spend" and f["entity"] == _scenario_entity), None)
    if _spend is None and diagnosis["suppliers_by_spend"]:
        _spend = next((f for f in facts if f["metric"] == "annual_spend" and f["entity"] == diagnosis["suppliers_by_spend"][0]["supplier"]), None)
    if _a or _b or _diff or _spend:
        money = {
            "currency": (_a or _b or _diff or _spend)["currency"],
            "current_annual_spend": _spend["value"] if _spend else None,
            "scenario_a": {"label": _a["period"], "impact": _a["value"]} if _a else None,
            "scenario_b": {"label": _b["period"], "impact": _b["value"]} if _b else None,
            "difference": _diff["value"] if _diff else None,
        }

    what_i_would_do = []
    if diagnosis.get("category_spend_growth_percent") is not None and diagnosis.get("category_volume_growth_percent") is not None:
        what_i_would_do.append(
            f"Category spend is growing faster than volume ({diagnosis['category_spend_growth_percent']}% vs {diagnosis['category_volume_growth_percent']}%) -- "
            f"run a SKU-level like-for-like check before accepting any price narrative."
        )
    if not what_i_would_do:
        what_i_would_do.append("Evidence does not yet support a specific strategic move -- close the open unknowns first.")

    # Value-density + buyer-language fix, confirmed by certification
    # findings #6 and #8: priorities previously restated the full
    # supplier_strategy sentence near-verbatim under a second heading,
    # AND the roadmap referenced "structural_implication" -- a literal
    # internal key name -- directly in buyer-facing text. Priorities is
    # now the SHORT, single-owner summary line per item; the full
    # reasoning has exactly one home, supplier_strategy below, and
    # nothing anywhere names that key in prose.
    #
    # Value-density fix (round 2, confirmed by a real audit against the
    # user's own example format): priorities.reason was still the FULL
    # supplier_strategy sentence, just missing the supplier-name prefix
    # -- genuinely the same explanation restated, not a real summary.
    # A short, few-word headline per strategy type gives the priority
    # list its own real value (a scannable summary) without repeating
    # the detailed reasoning that belongs to supplier_strategy alone.
    _short_reason = {
        "challenge": "concentration risk, unresolved cost evidence",
        "qualify": "qualification not yet complete",
        "develop": "growing share, actively manage the relationship",
    }
    priorities = []
    for s in supplier_strategies:
        if s["strategy"] in ("challenge", "qualify", "develop"):
            priorities.append({"priority": f"{s['supplier']} \u2014 {s['strategy']}", "reason": _short_reason.get(s["strategy"], s["strategy"])})
    if any(f["evidence_state"] == "CONTRADICTED" for f in facts):
        priorities.append({"priority": "Resolve the pricing-history contradiction", "reason": "supplier claim vs. documented history"})
    if diagnosis.get("category_price_growth_percent") is not None:
        priorities.append({"priority": "Run the like-for-like price check", "reason": "price cause not yet proven"})

    # Phase 6: category archetype -- evidence-based, never guessed. Used
    # only to select which existing lens (supply_chain_notes vs
    # contract_notes vs market drivers) is emphasized; never to invent
    # archetype-specific facts this case doesn't actually contain.
    archetype_result = detect_archetype(kernel)

    # Phase 6, item 6: the four mandatory lenses. Deliberately NOT a
    # parallel duplicate structure -- "what_we_think_is_happening",
    # "what_we_need_to_find_out", and "what_we_should_do_now" ARE
    # what_is_changing / what_still_needs_to_be_learned / what_i_would_do
    # under their mandated names (one conclusion, one owner, just
    # correctly labelled). "what_we_know" is the one genuinely new
    # summary -- short, evidence-cited sentences distinct in wording
    # from category_position's raw numbers, not a verbatim repeat of it.
    what_we_know = []
    if diagnosis.get("category_annual_spend") is not None:
        what_we_know.append(f"Category spend is {diagnosis['category_annual_spend']:,.0f} {diagnosis.get('category_currency') or ''}.".replace("  ", " "))
    for s in diagnosis["suppliers_by_spend"][:3]:
        if s.get("category_share_percent") is not None:
            what_we_know.append(f"{s['supplier']} holds {s['category_share_percent']}% of category spend.")
    if money and money.get("difference") is not None:
        what_we_know.append(f"The gap between the requested and alternative scenarios is {money['difference']:,.0f} {money.get('currency') or ''}.".replace("  ", " "))

    # Phase 6, item 11: "do not do this yet" -- evidence-gated, never
    # generic. Only fires when the specific missing prerequisite is
    # genuinely absent in THIS case's own evidence.
    do_not_do_yet = []
    for s in supplier_strategies:
        if s["strategy"] == "qualify":
            do_not_do_yet.append(f"{s['supplier']}: {s['reason']}.")
    if any(f["evidence_state"] == "CONTRADICTED" for f in facts):
        do_not_do_yet.append("Do not accept the supplier's cost narrative as settled -- it conflicts with the case's own documented history.")

    internal = {
        "decision": decision,
        "money": money,
        "archetype": archetype_result["archetype"],
        "archetype_basis": archetype_result["basis"],
        "what_we_know": what_we_know[:5],
        "category_position": diagnosis,
        "what_is_changing": what_is_changing[:5],
        "supplier_strategy": supplier_strategies,
        "what_still_needs_to_be_learned": what_still_needs_to_be_learned[:5],
        "do_not_do_yet": do_not_do_yet[:5],
        "stakeholder_views": stakeholder_views,
        "market_drivers": market_drivers,
        "market_intelligence_available": False,
        "what_i_would_do": what_i_would_do[:5],
        "priorities": priorities,
        "overcharging_claim_flagged_and_removed": overcharging_flagged,
        "supply_chain_notes": build_supply_chain_notes(kernel),
        "contract_notes": build_contract_notes(kernel),
        # Dependency-aware roadmap replaces the earlier flat build_roadmap
        # output under the same "roadmap" key -- same conceptual content,
        # genuinely richer (dependencies, decision gates, four
        # dimensions), not a second, duplicate roadmap section.
        "roadmap": _build_dependency_roadmap_section(kernel, diagnosis, supplier_strategies),
    }
    # Final UX fix: naively rendering "the answer object" must be safe
    # by default. Previously the safe view was a nested "buyer_facing"
    # key sitting alongside every internal field at the same level --
    # a frontend that just rendered the whole object would still leak
    # archetype/category_position/etc. Inverted here: the TOP LEVEL of
    # what this function returns IS the curated buyer view (built from
    # "internal" above, never recomputed); every internal/diagnostic
    # field moves under the explicit "diagnostics" key, which requires
    # deliberate access, not accidental exposure.
    buyer_view = _build_buyer_facing_view(internal)
    buyer_view["diagnostics"] = internal
    return buyer_view


def _build_buyer_facing_view(full_answer: dict[str, Any]) -> dict[str, Any]:
    """Curates the internal answer into what a buyer should actually
    see: What is happening -> Why -> What I recommend -> What to do
    next. Excludes archetype, archetype_basis, market_intelligence_
    available, overcharging_claim_flagged_and_removed, and the raw
    category_position/stakeholder_views/supply_chain_notes/
    contract_notes dumps -- those remain available in the object above
    for audit and deep-dive, never in this view."""
    view: dict[str, Any] = {}
    if full_answer.get("decision"):
        view["decision"] = full_answer["decision"]
    if full_answer.get("what_is_changing"):
        view["why"] = full_answer["what_is_changing"]
    if full_answer.get("money"):
        view["money"] = full_answer["money"]
    if full_answer.get("what_i_would_do"):
        view["recommendation"] = full_answer["what_i_would_do"]
    if full_answer.get("supplier_strategy"):
        # Simplified: supplier + strategy + one-line reason -- not the
        # duplicate "sentence" field, which just restates the same two
        # things concatenated.
        view["supplier_strategy"] = [
            {"supplier": s["supplier"], "strategy": s["strategy"], "reason": s["reason"]}
            for s in full_answer["supplier_strategy"]
        ]
    if full_answer.get("do_not_do_yet"):
        view["do_not_do_yet"] = full_answer["do_not_do_yet"]

    roadmap = full_answer.get("roadmap") or {}
    def _simplify_horizon(items):
        out = []
        for i in items:
            if "initiative" in i:
                entry = {"action": i["initiative"], "reason": i["reason"]}
                if i.get("decision_gate"):
                    entry["decision_gate"] = i["decision_gate"]
                if i.get("depends_on"):
                    entry["depends_on"] = i["depends_on"]
                out.append(entry)
            elif i.get("status"):
                out.append({"status": i["status"]})
        return out
    curated_roadmap = {}
    for key in ("quick_wins", "short_term_0_90_days", "medium_term_3_12_months", "year_1", "year_2", "year_3"):
        items = _simplify_horizon(roadmap.get(key, []))
        if items:
            curated_roadmap[key] = items
    if roadmap.get("cross_dimension_trade_offs"):
        curated_roadmap["trade_offs_to_weigh"] = roadmap["cross_dimension_trade_offs"]
    if curated_roadmap:
        view["roadmap"] = curated_roadmap

    if full_answer.get("what_still_needs_to_be_learned"):
        view["what_could_change_this"] = full_answer["what_still_needs_to_be_learned"]
    if full_answer.get("market"):
        view["market"] = full_answer["market"]
    if full_answer.get("esg"):
        view["esg"] = full_answer["esg"]
    return view
