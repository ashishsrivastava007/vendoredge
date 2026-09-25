"""
Category Strategy Slice 1 -- the foundational "THINK 360, SHOW SIMPLY"
layer, built on top of the existing category_strategy_profile.py
rather than duplicating it. This module owns exactly the capabilities
the Slice 1 spec calls genuinely new:

- objective inference (from the raw question text, local to this
  journey -- not a shared classifier change)
- category boundary assessment (evidence-triggered only, never an
  automatic broadening)
- the 360-degree finding model (dimension/finding/evidence/evidence_
  state/decision_impact/implication/possible_action/source)
- decision-impact classification (DECISION_CHANGING / MATERIAL_RISK /
  DECISION_CRITICAL_UNKNOWN / BACKGROUND) -- the mechanism that turns
  a 360-degree internal picture into a small, high-value surfaced set
- a minimal question engine (0-3 questions, only for decision-critical
  unknowns, each carrying its own information-value justification)

Everything here reads the SAME kernel diagnosis/supplier_strategies
that category_strategy_profile.py already computes -- it classifies
and composes, it never recalculates spend, share, or growth. No
external research, no invented market facts, no category memory: none
of that exists yet, and this module does not pretend otherwise.
"""
from __future__ import annotations
from typing import Any


# ---------------------------------------------------------------------
# Objective inference -- local to this journey, not a shared classifier
# change. Deliberately narrow: only infers an objective when the raw
# text actually contains language for it; returns None (ambiguous)
# rather than guessing, so the caller can decide whether the ambiguity
# is worth a question.
# ---------------------------------------------------------------------

_OBJECTIVE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("reduce cost", ("reduce cost", "cut cost", "lower cost", "cost down", "save money", "reduce spend", "cheaper")),
    ("improve service or availability", ("availability", "reliability", "service level", "on-time delivery", "hurting availability", "supply reliability")),
    ("reduce supplier dependency or risk", ("supplier dependency", "single source", "sole source", "over-reliant", "dependency on", "reduce risk", "resilience")),
    ("improve quality", ("improve quality", "quality issue", "defect", "reject rate")),
    ("standardise the category", ("standardise", "standardize", "consolidat", "rationalis", "rationaliz")),
    ("support growth", ("scale up", "growth", "expanding", "new plants", "new sites")),
    ("improve sustainability", ("sustainab", "carbon", "esg", "emissions")),
]


def infer_category_objective(raw_question: str) -> tuple[str | None, list[str]]:
    """Returns (objective_summary, matched_signals). objective_summary
    is None when nothing in the text indicates an objective clearly
    enough to state one -- an honest "ambiguous", not a forced guess.
    Multiple matched objectives are combined (e.g. "reduce cost without
    hurting availability" legitimately states two), not silently
    reduced to one."""
    text = (raw_question or "").lower()
    matched = [label for label, keywords in _OBJECTIVE_PATTERNS if any(k in text for k in keywords)]
    if not matched:
        return None, []
    if len(matched) == 1:
        return matched[0], matched
    return " and ".join(matched[:2]), matched


# ---------------------------------------------------------------------
# Category boundary assessment -- flags an adjacent dimension only when
# the case's OWN text mentions it; never auto-broadens the category or
# invents an adjacency the user never raised.
# ---------------------------------------------------------------------

_BOUNDARY_SIGNALS: tuple[tuple[str, str], ...] = (
    ("spare part", "spare parts may sit outside the stated category spend but affect total cost of ownership"),
    ("maintenance", "maintenance spend may sit outside the stated category figure but is often linked to the same supplier relationship"),
    ("installation", "installation cost may be a separate line from the stated category spend"),
    ("service contract", "service contracts may be priced and sourced separately from the core category spend"),
    ("warranty", "warranty terms may affect total cost of ownership beyond the stated purchase price"),
)


def assess_category_boundary(raw_question: str, subject: str | None) -> str | None:
    """Returns a single boundary note when the case's own text
    mentions something adjacent to the stated category that could
    materially affect the decision -- never a taxonomy lecture, never
    more than one note, never triggered by the category name alone."""
    text = (raw_question or "").lower()
    subject_lower = (subject or "").lower()
    for keyword, note in _BOUNDARY_SIGNALS:
        if keyword in text and keyword not in subject_lower:
            return note.capitalize() + "."
    return None


# ---------------------------------------------------------------------
# 360-degree finding model + decision-impact classification. Every
# finding traces to a real kernel fact or a real kernel-derived
# classification (diagnosis, supplier_strategies, unknowns) -- nothing
# here computes a new number.
# ---------------------------------------------------------------------

_VALID_IMPACTS = ("DECISION_CHANGING", "MATERIAL_RISK", "DECISION_CRITICAL_UNKNOWN", "BACKGROUND")


def _detect_supplier_claim_vs_price_history_contradiction(stated_text: str, stated_price_history: list[str]) -> dict[str, Any] | None:
    """Foundation gap 3 (fixed): Something I Noticed's contradiction
    detector compares a text claim against a CALCULATED number -- a
    genuinely different mechanism from what this needs (a text claim
    against a HISTORICAL PATTERN parsed from stated_price_history), so
    this is a new, narrow function rather than a forced reuse of that
    one, but it follows the identical evidence discipline: never
    declares the supplier dishonest or infers motive, preserves both
    the claim and the internal evidence as their own evidence states,
    and only asserts a contradiction when the history is unambiguous
    (every stated entry at or below zero) -- a mixed history (some
    years up, some flat) is not treated as a contradiction, since that
    would be a real, disputable judgment call this function has no
    basis to make.
    """
    if not stated_price_history or not stated_text:
        return None
    import re
    percentages: list[float] = []
    for entry in stated_price_history:
        m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", str(entry))
        if m:
            percentages.append(float(m.group(1)))
    if not percentages:
        return None
    history_shows_no_increase = all(p <= 0 for p in percentages)
    claims_cost_increase = any(p in stated_text for p in (
        "costs have increased", "cost increase", "costs have risen", "prices have risen",
        "costs are rising", "cost pressures", "costs going up", "costs up",
    ))
    if not (history_shows_no_increase and claims_cost_increase):
        return None
    return {
        "dimension": "cost_and_price_economics",
        "finding": "The supplier's stated justification claims costs have increased, but the case's own documented price history shows no increase over the stated period.",
        "evidence": f"Stated price history: {'; '.join(stated_price_history)}.",
        "evidence_state": "CONTRADICTED",
        "decision_impact": "MATERIAL_RISK",
        "implication": "This does not establish the supplier's current underlying cost position, but the stated justification is not supported by the available historical price evidence and should be validated before being accepted.",
        "possible_action": "Ask the supplier for a specific, itemized cost breakdown rather than accepting the general justification as given.",
        "source": "kernel:facts+kernel:case",
    }


def build_360_findings(kernel: dict[str, Any], diagnosis: dict[str, Any], supplier_strategies: list[dict[str, Any]], retrieved_memory: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Converts what category_strategy_profile.py already computed
    into a structured, decision-impact-classified finding list. Rules
    are evidence-derived thresholds already used elsewhere in this
    codebase (>=50% concentration is the same threshold classify_
    supplier_strategy already uses for "challenge"), not new invented
    cutoffs."""
    findings: list[dict[str, Any]] = []
    facts = kernel.get("facts", [])

    # Master spec CASE 6: a contractual adjustment mechanism referenced
    # in the case's own stated text is a real, relevant fact -- but the
    # mechanism existing is not the same as the requested adjustment
    # having been validated against it. Reuses the same stated_
    # justification text already flowing into the kernel for every
    # journey (see commercial_signal_profile.py's contradiction
    # detector for the same pattern), not a new evidence path.
    stated_text = " ".join(str(f.get("value") or "") for f in facts if f.get("metric") == "stated_justification").lower()
    # M1.4 content-quality fix: the ORIGINAL-case (not lower-cased)
    # stated text is what actually carries the distinctive commercial
    # detail (e.g. "accepted 6% for a two-year volume commitment") --
    # previously this variable existed only for pattern-matching below
    # and the finding text that follows never referenced it at all,
    # so that detail was discarded at the source, before Memory was
    # ever involved. This is the true root cause of the "generic
    # finding text" defect found during independent validation: it
    # isn't a finding-vs-implication mix-up in the Memory layer, it's
    # that neither field ever captured the specific text in the first
    # place.
    stated_text_original = " ".join(str(f.get("value") or "") for f in facts if f.get("metric") == "stated_justification").strip()
    _contract_mechanism_markers = ("indexation", "index clause", "adjustment clause", "annual adjustment", "contract permits", "per the contract", "contractual mechanism")
    if any(m in stated_text for m in _contract_mechanism_markers):
        # The proposition (WHAT the case actually states) now carries
        # the specific text when available, falling back to the
        # generic statement only when no specific text exists to
        # quote -- never fabricating a detail that wasn't stated.
        _mechanism_finding = "A contractual adjustment mechanism has been referenced for this category."
        if stated_text_original:
            _mechanism_finding = f"A contractual adjustment mechanism has been referenced for this category. The case states: \"{stated_text_original}\""
        findings.append({
            "dimension": "contract_and_commercial_architecture",
            "finding": _mechanism_finding,
            "evidence": "The case's own stated text references a contract or indexation mechanism.",
            "evidence_state": "SUPPLIER_CLAIM",
            "decision_impact": "DECISION_CRITICAL_UNKNOWN",
            "implication": "The mechanism existing is not the same as the requested adjustment having been validated against it -- the two must not be conflated.",
            "possible_action": "Validate the requested adjustment against the contract's own formula before agreeing to it.",
            "source": "kernel:facts",
        })

    _price_history_contradiction = _detect_supplier_claim_vs_price_history_contradiction(
        stated_text, kernel.get("case", {}).get("stated_price_history") or []
    )
    if _price_history_contradiction:
        findings.append(_price_history_contradiction)

    # Suppliers that get their own strategy finding below already cite
    # their concentration figure in that finding's evidence -- skip the
    # standalone concentration finding for them to avoid stating the
    # same fact twice under two headings.
    _strategized_suppliers = {s["supplier"] for s in supplier_strategies if s.get("strategy") in ("challenge", "develop")}
    for s in diagnosis.get("suppliers_by_spend", []):
        if s["supplier"] in _strategized_suppliers:
            continue
        share = s.get("category_share_percent")
        if share is None:
            continue
        impact = "DECISION_CHANGING" if share >= 50 else ("MATERIAL_RISK" if share >= 25 else "BACKGROUND")
        findings.append({
            "dimension": "supplier_landscape",
            "finding": f"{s['supplier']} holds {share}% of category spend.",
            "evidence": f"Calculated from {s['supplier']}'s spend against total category spend.",
            "evidence_state": "CALCULATED",
            "decision_impact": impact,
            "implication": "A concentration this high limits negotiating leverage and creates continuity risk." if impact != "BACKGROUND" else "Within a normal range for this evidence.",
            "possible_action": f"Consider dual-sourcing or a competitive round for {s['supplier']}." if impact == "DECISION_CHANGING" else None,
            "source": "kernel:category_diagnosis",
        })

    for s in supplier_strategies:
        strategy = s.get("strategy")
        impact = {"challenge": "DECISION_CHANGING", "qualify": "DECISION_CRITICAL_UNKNOWN", "develop": "MATERIAL_RISK"}.get(strategy, "BACKGROUND")
        findings.append({
            "dimension": "supplier_landscape",
            "finding": f"{s['supplier']}: {strategy.replace('_', ' ')}.",
            "evidence": s.get("reason", ""),
            "evidence_state": "CALCULATED" if strategy != "qualify" else "UNKNOWN",
            "decision_impact": impact,
            "implication": s.get("reason", ""),
            "possible_action": s.get("reason", "") if strategy in ("challenge", "qualify") else None,
            "source": "kernel:supplier_strategy",
        })

    if any(f.get("evidence_state") == "CONTRADICTED" for f in facts):
        findings.append({
            "dimension": "cost_and_price_economics",
            "finding": "A supplier claim conflicts with the case's own documented history.",
            "evidence": "One or more kernel facts are marked CONTRADICTED.",
            "evidence_state": "CONTRADICTED",
            "decision_impact": "MATERIAL_RISK",
            "implication": "Any cost narrative built on the contradicted claim cannot be trusted until reconciled.",
            "possible_action": "Reconcile the contradiction before relying on the supplier's stated justification.",
            "source": "kernel:facts",
        })

    price_growth = diagnosis.get("category_price_growth_percent")
    case_spec_changed = bool(kernel.get("case", {}).get("specification_changed") or kernel.get("case", {}).get("specification_change_description"))
    market_driver_claims = kernel.get("case", {}).get("market_driver_claims") or []
    if price_growth is not None:
        if price_growth <= 0:
            # A negative (or flat) unit-price movement is a resolved
            # decomposition, not an open question: whatever drove the
            # spend change, it was not a genuine price increase. Framed
            # as background/reassuring rather than DECISION_CRITICAL_
            # UNKNOWN, which would wrongly suggest something material
            # remains unresolved here.
            findings.append({
                "dimension": "cost_and_price_economics",
                "finding": f"The unit price has moved {price_growth:+.1f}% -- the spend change is driven by volume, not price.",
                "evidence": "Calculated from category spend and volume.",
                "evidence_state": "CALCULATED",
                "decision_impact": "BACKGROUND",
                "implication": "Any spend increase here should not be treated as inflation -- do not open a price negotiation on this basis.",
                "possible_action": None,
                "source": "kernel:category_diagnosis",
            })
        elif case_spec_changed:
            # A genuine price increase exists, but a specification
            # change was also reported -- the increase must not be
            # automatically attributed to supplier inflation. Decision-
            # critical because which portion is genuine inflation vs.
            # a specification-driven cost change is not yet isolated.
            findings.append({
                "dimension": "specification_and_requirement_intelligence",
                "finding": f"Unit price has moved {price_growth:+.1f}%, but a specification change was also reported for this category.",
                "evidence": "Calculated price movement from category spend/volume; specification change reported in the case.",
                "evidence_state": "CALCULATED",
                "decision_impact": "DECISION_CRITICAL_UNKNOWN",
                "implication": f"The full {price_growth:+.1f}% must not be treated as supplier inflation -- the specification change may account for some or all of it, and that split has not been established.",
                "possible_action": "Ask the supplier to quantify the cost impact of the specification change separately from any underlying price movement.",
                "source": "kernel:category_diagnosis",
            })
        elif market_driver_claims:
            # A market driver was reported alongside this price
            # movement -- the calculated movement may be broadly
            # explained by an external factor, but the supplier's own
            # cost structure remains unverified (a market movement is
            # never the same fact as a supplier's actual cost
            # exposure). This is what lets VendorEdge challenge a
            # user's "the supplier raised the price" framing when the
            # evidence points to a market-wide explanation instead --
            # without inventing a supplier margin or cost-share figure
            # that was never stated.
            driver_names = ", ".join(sorted({str(c.get("driver", "")).strip() for c in market_driver_claims if c.get("driver")})) or "an unspecified market factor"
            findings.append({
                "dimension": "supply_market_intelligence",
                "finding": f"Unit price has moved {price_growth:+.1f}%, and a market movement in {driver_names} was also reported for this period.",
                "evidence": "Calculated price movement from category spend/volume; market driver reported in the case.",
                "evidence_state": "CALCULATED",
                "decision_impact": "DECISION_CRITICAL_UNKNOWN",
                "implication": f"The reported market movement may broadly explain the {price_growth:+.1f}% shift, but this supplier's own cost structure has not been independently verified -- treating the full movement as this supplier's own margin decision would be unsupported.",
                "possible_action": "Ask the supplier to show how their cost structure connects to the reported market movement, rather than accepting the price increase as self-evidently justified.",
                "source": "kernel:category_diagnosis",
            })
        else:
            findings.append({
                "dimension": "cost_and_price_economics",
                "finding": f"Average unit price has moved {price_growth:+.1f}%.",
                "evidence": "Calculated from category spend and volume.",
                "evidence_state": "CALCULATED",
                "decision_impact": "DECISION_CRITICAL_UNKNOWN",
                "implication": "Whether this is genuine like-for-like inflation or a mix effect is not yet established -- it changes what action, if any, is justified.",
                "possible_action": "Run a SKU-level like-for-like comparison.",
                "source": "kernel:category_diagnosis",
            })
    else:
        # Foundation gap 1 (fixed): price_growth requires a volume
        # basis to compute a per-unit figure. Previously, when only
        # spend data existed, this whole section produced nothing --
        # a genuine spend movement with a weak or absent supplier
        # justification silently disappeared. Fixed by surfacing the
        # spend movement itself, explicitly as a SPEND figure, never
        # promoted to a price or unit-price claim, with the missing
        # volume evidence named as exactly what's blocking attribution.
        spend_growth = diagnosis.get("category_spend_growth_percent")
        if spend_growth is not None and spend_growth != 0:
            findings.append({
                "dimension": "spend_and_commercial_baseline",
                "finding": f"Category spend has changed {spend_growth:+.1f}%. Volume data is unavailable, so this cannot yet be attributed to price rather than volume or mix.",
                "evidence": "Calculated from category spend (current vs. prior period).",
                "evidence_state": "CALCULATED",
                "decision_impact": "DECISION_CRITICAL_UNKNOWN",
                "implication": "Do not treat this spend change as a price increase -- volume data is the missing evidence that would establish or rule that out.",
                "possible_action": "Obtain category volume for the same period to establish whether this is a genuine price movement.",
                "source": "kernel:category_diagnosis",
            })

    # Foundation gap 2 (fixed): a market-driver claim with no
    # corresponding internal spend or price movement previously
    # produced nothing at all -- the user's own question about
    # exposure went unanswered. Fixed as an independent finding (not
    # nested under price_growth, since this is exactly the case where
    # no internal movement exists yet): the external signal is
    # surfaced and explicitly labelled EXTERNAL_MARKET_EVIDENCE, never
    # claiming the category is already affected, never manufacturing a
    # spend or price impact that isn't evidenced.
    _no_internal_movement = price_growth is None and (diagnosis.get("category_spend_growth_percent") in (None, 0))
    if market_driver_claims and _no_internal_movement:
        driver_names = ", ".join(sorted({str(c.get("driver", "")).strip() for c in market_driver_claims if c.get("driver")})) or "an unspecified market factor"
        findings.append({
            "dimension": "external_market_intelligence",
            "finding": f"An external market movement in {driver_names} has been reported, but no corresponding internal spend or price movement is currently evidenced for this category.",
            "evidence": "Market driver claim reported in the case; no internal spend/price change calculated.",
            "evidence_state": "EXTERNAL_MARKET_EVIDENCE",
            "decision_impact": "DECISION_CRITICAL_UNKNOWN",
            "implication": "This does not establish that the category is currently exposed or affected -- exposure should be verified before changing the category position on this basis alone.",
            "possible_action": "Check whether this category's suppliers are genuinely exposed to the reported market movement before acting.",
            "source": "kernel:case",
        })

    # Memory reconciliation (Category Strategy Memory Reconciliation
    # slice): happens HERE, inside finding construction -- the actual
    # reasoning path -- not as a step added after the answer exists.
    # Every current finding is checked against retrieved memory
    # sharing its exact (entity, fact_type); the current finding's own
    # value is NEVER altered by this -- only a separate,
    # clearly-labelled historical_precedent field is attached, and
    # only for a relationship the evidence actually supports (never
    # invented). Absence of retrieved_memory (None, or no relevant
    # items) leaves every finding exactly as it would have been built
    # without this step at all.
    if retrieved_memory:
        try:
            from app.pipeline.memory_service import classify_fact_type, reconcile_one, _entity_for
            # current_event_date: this case's own KNOWN business-event
            # date, if any -- never the analysis timestamp (see
            # memory_service.reconcile_one's own docstring). This
            # evidence model has no such field yet, so it stays None;
            # reconcile_one correctly falls back to COMPLEMENTS rather
            # than guessing CONTRADICTS or TEMPORAL_CHANGE from
            # request timing.
            _current_event_date = None
            for finding in findings:
                fact_type = classify_fact_type(finding)
                if fact_type is None:
                    continue
                category, supplier = _entity_for(finding, kernel)
                match = next(
                    (m for m in retrieved_memory if m.get("fact_type") == fact_type
                     and (m.get("entity_supplier") == supplier if supplier else m.get("entity_category") == category)),
                    None,
                )
                if match is None:
                    continue
                reconciled = reconcile_one(match, finding, _current_event_date)
                if reconciled["relationship"] in ("STALE", "NOT_RELEVANT"):
                    continue
                finding["historical_precedent"] = reconciled
                if reconciled["relationship"] == "HISTORICAL_PRECEDENT":
                    finding["possible_action"] = (finding.get("possible_action") or "") + " This matches a previous pattern for this supplier/category -- current evidence still requires independent validation."
                elif reconciled["relationship"] == "SUPPORTS":
                    finding["possible_action"] = (finding.get("possible_action") or "") + " This is consistent with a previously recorded observation."
                elif reconciled["relationship"] == "CONTRADICTS":
                    finding["possible_action"] = (finding.get("possible_action") or "") + " Note: this differs from a previously recorded observation -- the current, more recent evidence is what this finding is based on."
                elif reconciled["relationship"] == "TEMPORAL_CHANGE":
                    # Distinct from CONTRADICTS: the metric genuinely
                    # evolved over time -- stated as change, not
                    # conflict (the direct fix for the audit's finding
                    # that these were previously mislabelled).
                    finding["possible_action"] = (finding.get("possible_action") or "") + f" This reflects genuine change over time from a previously recorded observation ({reconciled['finding_text']}), not a discrepancy."
                elif reconciled["relationship"] == "COMPLEMENTS" and reconciled.get("values_differ_unknown_period"):
                    # M1.2 fix B: same distinction as classify_supplier_
                    # strategy's own fix -- when values genuinely differ
                    # and the period is unknown, "recurs" is misleading.
                    finding["possible_action"] = (finding.get("possible_action") or "") + f" This differs from a previously recorded observation ({reconciled['finding_text']}); whether that reflects genuine change over time or a conflicting observation is not established, since the period of the prior observation is unknown."
                elif reconciled["relationship"] == "COMPLEMENTS":
                    # Same proposition, non-numeric text (e.g. a
                    # repeated supplier-strategy classification like
                    # "challenge") -- this is exactly the spec's own
                    # precedent example (a supplier previously
                    # classified/challenged again now). Worth surfacing
                    # even though the two values weren't compared as
                    # numerically equal.
                    finding["possible_action"] = (finding.get("possible_action") or "") + f" This recurs a previous observation for this supplier/category ({reconciled['finding_text']}) -- current evidence still requires independent validation."
        except Exception as e:
            # Section 11: a reconciliation failure must never break the
            # primary answer -- findings already computed above (from
            # current evidence alone) are returned exactly as they are,
            # simply without any historical_precedent annotation.
            print(f"Category Memory reconciliation failed (non-blocking, findings computed from current evidence only): {type(e).__name__}: {e}")

    return findings


def surfaced_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The default rendering rule: surface DECISION_CHANGING,
    MATERIAL_RISK, and DECISION_CRITICAL_UNKNOWN; retain BACKGROUND
    internally. This is the single place that rule lives, so it stays
    testable and cannot silently drift between callers."""
    return [f for f in findings if f.get("decision_impact") in ("DECISION_CHANGING", "MATERIAL_RISK", "DECISION_CRITICAL_UNKNOWN")]


def apply_decision_impact_guardrails(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic guardrails that validate -- and correct -- the
    classification every finding already received, rather than trust
    it blindly. Written as a genuine safety net: build_360_findings is
    entirely rule-based today, so these invariants already hold by
    construction, but this function is what keeps holding them true if
    a future classification path (an LLM proposing decision_impact,
    say) is ever added on top, per the spec's own "LLM proposes,
    deterministic rules validate" principle. Two concrete, enforced
    rules:
      1. A CONTRADICTED finding can never be BACKGROUND -- a real
         conflict in the evidence is never safe to bury.
      2. A finding resting solely on an unverified SUPPLIER_CLAIM can
         never be DECISION_CHANGING -- a claim is not yet a settled
         fact, however material it might turn out to be, so it is
         downgraded to DECISION_CRITICAL_UNKNOWN (needs verification)
         rather than treated as already decided.
    Violations are corrected in place (with a note of what changed),
    not merely flagged, since a silently-wrong classification is the
    exact failure mode this function exists to prevent."""
    corrected = []
    for f in findings:
        finding = dict(f)
        if finding.get("evidence_state") == "CONTRADICTED" and finding.get("decision_impact") == "BACKGROUND":
            finding["decision_impact"] = "MATERIAL_RISK"
            finding["_guardrail_applied"] = "CONTRADICTED evidence cannot be BACKGROUND"
        if finding.get("evidence_state") == "SUPPLIER_CLAIM" and finding.get("decision_impact") == "DECISION_CHANGING":
            finding["decision_impact"] = "DECISION_CRITICAL_UNKNOWN"
            finding["_guardrail_applied"] = "An unverified supplier claim cannot be treated as already decided"
        corrected.append(finding)
    return corrected


# ---------------------------------------------------------------------
# Minimal question engine -- 0-3 questions, only for genuinely
# decision-critical unknowns, each with its own information-value
# justification, never asked merely because a field is empty.
# ---------------------------------------------------------------------

def build_minimal_questions(findings: list[dict[str, Any]], objective_summary: str | None, boundary_note: str | None) -> list[dict[str, str]]:
    """0-3 questions maximum. Every DECISION_CRITICAL_UNKNOWN finding is
    considered, but most do NOT become a user-facing question -- a
    qualification timeline is a known, tracked process (not something
    the user needs to answer), and a like-for-like price check is
    internal work VendorEdge/the buyer can do without the user's input.
    For Slice 1's evidence model, the objective is the one genuine gap
    that reaching the user actually resolves; this is intentional, not
    an oversight -- future evidence types (e.g. contract exclusivity)
    can extend this list once the kernel actually carries that field."""
    questions: list[dict[str, str]] = []
    if objective_summary is None:
        questions.append({
            "question": "What matters most here: reducing cost, improving supply reliability, or reducing supplier dependency?",
            "information_value": "The objective is not yet clear from the case, and different objectives point to materially different strategies.",
        })
    return questions[:3]
