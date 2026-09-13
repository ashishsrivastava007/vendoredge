"""
Category Strategy / Dependency-Aware Roadmap.

Architectural note, recorded per instruction, not implemented here:
VendorEdge's long-term target includes a Complex Procurement Problem
Solving capability (Problem -> Evidence -> Diagnosis -> Problem Tree ->
Gemba -> Root Cause -> 5 Whys -> Options -> Commercial/Operational/
Risk/ESG Assessment -> Countermeasure -> Business Case -> Execution
Roadmap -> Change Management -> Outcome), including the discipline of
exhausting process/specification/governance/existing-resource options
before proposing headcount, new systems, or infrastructure. This
module's Initiative object (dimension, horizon, dependency, decision
gate, owner, KPI, expected-vs-actual outcome) is intentionally shaped
so that future A3/problem-solving cases can plug into the same
structure without a redesign -- but no A3 workflow, root-cause engine,
or countermeasure-evaluation logic is built in this pass.

This module itself: an Initiative is the canonical unit of the
roadmap -- one action, one dimension (commercial / operational / risk
/ esg), one horizon, and explicit dependency references to other
initiatives, so the roadmap can explain "why this comes first" rather
than presenting a flat, unordered list. Every field not established by
real evidence stays None -- owner, KPI, target, and actual_outcome are
almost always None for a case at this stage, and that is the honest,
correct state, not a gap to fill.
"""
from __future__ import annotations
from typing import Any

from app.pipeline.esg_intelligence import tag_objective_type, identify_objective_trade_offs

_HORIZONS = ("quick_win", "short_term", "medium_term", "year_1", "year_2", "year_3")


def _make_initiative(
    initiative: str, dimension: str, horizon: str, reason: str, evidence: str,
    depends_on: list[str] | None = None, decision_gate: str | None = None,
) -> dict[str, Any]:
    """Every field not passed explicitly stays None -- owner, KPI,
    target, expected_impact, and actual_outcome are not invented just
    to fill the shape; a case that doesn't state them leaves them
    genuinely unknown."""
    return {
        "initiative": initiative,
        "dimension": dimension,
        "horizon": horizon,
        "reason": reason,
        "evidence": evidence,
        "depends_on": depends_on or [],
        "decision_gate": decision_gate,
        "owner": None,
        "expected_impact": None,
        "risk": None,
        "status": "not_started",
        "kpi": None,
        "target": None,
        "actual_outcome": None,
    }


def build_investigation_initiatives(kernel: dict[str, Any], supplier_strategies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Converts a material evidence gap into an evidence-gathering
    initiative -- never an attempt to manufacture the missing answer.
    Gated deliberately narrow: only when resolving the gap could
    materially change an ACTIVE strategic decision, not every unknown
    the kernel happens to carry. Two sources today: a market-driver
    claim whose exposure isn't established for a supplier who is
    actually being challenged (the fuel-cost example this was built
    for), and an ESG claim with a stated requirement whose current
    position isn't confirmed. Qualification and capacity unknowns
    already become investigation-shaped initiatives elsewhere (Complete
    qualification for X / Validate X's capacity) -- not duplicated here."""
    from app.pipeline.market_intelligence import build_market_reasoning
    from app.pipeline.esg_intelligence import build_esg_reasoning

    challenged_suppliers = {s["supplier"] for s in supplier_strategies if s["strategy"] == "challenge"}
    initiatives: list[dict[str, Any]] = []

    market = build_market_reasoning(kernel)
    if market:
        for d in market["drivers"]:
            # Materiality gate: only when the claim is tied to a
            # supplier under active strategic consideration (being
            # challenged) -- a general market observation with no
            # bearing on a live decision doesn't get an investigation
            # manufactured for it.
            if d["applies_to_supplier"] and d["applies_to_supplier"] in challenged_suppliers:
                initiatives.append(_make_initiative(
                    f"Obtain {_driver_investigation_title(d)}", "commercial", "quick_win",
                    reason=f"Purpose: determine whether the claimed market movement materially supports {d['applies_to_supplier']}'s pricing position. Currently: {d['unknown']}",
                    evidence=d["market_evidence"],
                    decision_gate=f"Update the category strategy once {d['applies_to_supplier']}'s exposure is established -- not before.",
                ))

    esg = build_esg_reasoning(kernel)
    if esg:
        for c in esg["claims"]:
            if c["applies_to_supplier"] and "stated requirement exists" in c["implication"].lower():
                initiatives.append(_make_initiative(
                    f"Confirm {c['applies_to_supplier']}'s current position on {c['topic']}", "esg", "short_term",
                    reason=f"Purpose: establish whether {c['applies_to_supplier']} currently meets the stated requirement before relying on it in strategy or contract. Currently: {c['supplier_exposure']}",
                    evidence=c["esg_fact"],
                    decision_gate=f"Update the category/supplier strategy once {c['applies_to_supplier']}'s {c['topic']} position is confirmed -- not before.",
                ))

    return initiatives


def _driver_investigation_title(d: dict[str, Any]) -> str:
    """Builds a short, natural action title from a market driver's own
    evidence -- e.g. "the steel cost basis and validate against LME"
    -- never inventing a reference source the claim didn't name."""
    driver = d.get("market_evidence", "").split(" ")[0].lower() if d.get("market_evidence") else "the relevant"
    return f"the {driver} cost basis and validate against an appropriate reference"


def build_initiatives(kernel: dict[str, Any], diagnosis: dict[str, Any], supplier_strategies: list[dict[str, Any]], esg_answer: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Builds the initiative set from evidence already established
    elsewhere (diagnosis, supplier strategy, ESG reasoning) -- this
    function assembles and sequences, it does not independently decide
    what's true. Returns initiatives with real names as dependency
    keys, so the roadmap layer can explain sequencing without a
    separate ID scheme leaking into buyer-facing text."""
    facts = kernel.get("facts", [])
    initiatives: list[dict[str, Any]] = []

    # Commercial: the cost-evidence baseline. This is the natural first
    # step in the dependency chain (item 3's own example starts here)
    # -- everything downstream that needs a real cost picture depends
    # on this existing first.
    cost_baseline_name = None
    if diagnosis.get("category_price_growth_percent") is not None:
        cost_baseline_name = "Run a SKU-level like-for-like price check"
        initiatives.append(_make_initiative(
            cost_baseline_name, "commercial", "quick_win",
            reason="Average price growth is real, but the cause is not yet proven -- this is the evidence baseline everything else about pricing depends on.",
            evidence=f"Category average price growth: {diagnosis['category_price_growth_percent']}%.",
        ))

    if any(f["evidence_state"] == "CONTRADICTED" for f in facts):
        initiatives.append(_make_initiative(
            "Resolve the supplier's pricing-history contradiction", "commercial", "quick_win",
            reason="A supplier claim directly conflicts with the case's own documented history -- this must be resolved before weighing the supplier's justification.",
            evidence="A CONTRADICTED fact exists in the case evidence.",
        ))

    # Risk/operational: supplier qualification and capacity validation.
    # These do NOT depend on the cost baseline -- they can run in
    # parallel, which the roadmap should make explicit rather than
    # implying a false sequential dependency.
    qualify_names = []
    qualify_suppliers = []
    for s in supplier_strategies:
        if s["strategy"] == "qualify":
            name = f"Complete qualification for {s['supplier']}"
            qualify_names.append(name)
            qualify_suppliers.append(s["supplier"])
            initiatives.append(_make_initiative(
                name, "operational", "medium_term",
                reason=s["reason"],
                evidence=f"{s['supplier']} strategy classification: qualify.",
                decision_gate=f"{s['supplier']} must pass qualification before being treated as an executable alternative.",
            ))
        elif s["strategy"] == "monitor" and "capacity" in s["reason"].lower():
            initiatives.append(_make_initiative(
                f"Validate {s['supplier']}'s stated capacity figure", "operational", "quick_win",
                reason=s["reason"],
                evidence=f"{s['supplier']} strategy classification: monitor (capacity unvalidated).",
            ))

    # Commercial, downstream: competitive leverage. This DOES genuinely
    # depend on qualification completing -- you cannot run a real
    # competitive event against alternatives that aren't qualified yet.
    # Only created when there IS a supplier being challenged AND at
    # least one alternative is in the qualification pipeline -- never
    # invented as a generic "run an RFQ" step. Names the specific
    # qualifying suppliers explicitly -- a genuine content fix, caught
    # by comparing against the prior, more explicit roadmap wording:
    # "using qualified alternatives" alone was less useful than naming
    # exactly which suppliers the leverage depends on.
    challenged = [s for s in supplier_strategies if s["strategy"] == "challenge"]
    leverage_name = f"Build competitive leverage against {challenged[0]['supplier'] if challenged else ''} using {', '.join(qualify_suppliers)}"
    if challenged and qualify_names:
        initiatives.append(_make_initiative(
            leverage_name, "commercial", "year_1",
            reason=f"{challenged[0]['supplier']}'s concentration is the core issue -- real leverage requires {', '.join(qualify_suppliers)} to be qualified alternatives, not just requested.",
            evidence=f"{challenged[0]['supplier']} strategy classification: challenge; {', '.join(qualify_suppliers)} in the qualification pipeline.",
            depends_on=list(qualify_names),
            decision_gate=f"Requires {' and '.join(qualify_suppliers)} to have completed qualification.",
        ))
        initiatives.append(_make_initiative(
            f"Restructure the contract with {challenged[0]['supplier']}", "commercial", "year_1",
            reason="A renegotiated contract is only credible once both the cost evidence and competitive leverage exist -- not before.",
            evidence="Depends on the cost-evidence baseline and competitive leverage initiatives above.",
            depends_on=([cost_baseline_name] if cost_baseline_name else []) + [leverage_name],
            decision_gate="Requires the cost-evidence baseline and competitive leverage to both be established first.",
        ))

    # Unknown -> investigation initiatives: material market-exposure and
    # ESG-requirement gaps tied to a supplier under active strategic
    # consideration. Replaces the earlier, cruder ESG-follow-up loop --
    # same underlying evidence, now structured with an explicit
    # Purpose/Currently/decision-gate shape, and extended to market
    # exposure (the fuel-cost example this was built for). Never
    # manufactures the missing answer -- the initiative IS "go get the
    # evidence", nothing more.
    initiatives.extend(build_investigation_initiatives(kernel, supplier_strategies))

    return initiatives


def build_dependency_aware_roadmap(initiatives: list[dict[str, Any]]) -> dict[str, Any]:
    """Organizes initiatives by horizon and, for each, states what it
    depends on and what depends on it -- the "why this comes first /
    what can't start until this is done" explanation item 3 requires.
    Also runs the objective-trade-off check across the full initiative
    set, not just ESG-vs-one-other-item, so a genuine cross-dimension
    conflict in the roadmap itself is surfaced."""
    by_horizon: dict[str, list[dict[str, Any]]] = {h: [] for h in _HORIZONS}
    name_to_dimension = {i["initiative"]: i["dimension"] for i in initiatives}

    for init in initiatives:
        blocks = [other["initiative"] for other in initiatives if init["initiative"] in other.get("depends_on", [])]
        by_horizon[init["horizon"]].append({
            "initiative": init["initiative"],
            "dimension": init["dimension"],
            "reason": init["reason"],
            "depends_on": init["depends_on"],
            "blocks": blocks,
            "decision_gate": init["decision_gate"],
            "owner": init["owner"],
            "status": init["status"],
            "kpi": init["kpi"],
            "target": init["target"],
            "actual_outcome": init["actual_outcome"],
        })

    tagged = [{"text": i["initiative"] + " -- " + i["reason"], "objective_type": i["dimension"]} for i in initiatives]
    trade_offs = identify_objective_trade_offs(tagged)

    return {
        "quick_wins": by_horizon["quick_win"],
        "short_term_0_90_days": by_horizon["short_term"],
        "medium_term_3_12_months": by_horizon["medium_term"],
        "year_1": by_horizon["year_1"],
        "year_2": by_horizon["year_2"] or [{"status": "Not yet supported by evidence -- depends on the outcome of Year 1 initiatives."}],
        "year_3": by_horizon["year_3"] or [{"status": "Not yet supported by evidence -- revisit once Year 1/2 outcomes and, if applicable, real market data are available."}],
        "cross_dimension_trade_offs": trade_offs,
    }
