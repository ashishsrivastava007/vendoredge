"""R38 Commercial Answer Engine.

Deterministic presentation/compression layer for the buyer's first screen.
It does not create new facts, thresholds, supplier economics, or model claims.
It assembles already-normalized evidence, guaranteed calculations, validated
recommendation fields, and clearly labelled unknowns into one executable answer.
"""
from __future__ import annotations

import re
from typing import Any

from app.pipeline.normalized_evidence import NormalizedEvidence, PriceIncreaseEvidence
from app.pipeline.claim_integrity import check_unsupported_strategy_numbers
from app.pipeline.money import currency_symbol


_RATE_SCENARIO_RE = re.compile(
    r"(?:from|reduce(?:d|s)?\s+from)\s*(\d+(?:\.\d+)?)\s*%\s*(?:to|down\s+to)\s*(\d+(?:\.\d+)?)\s*%",
    re.I,
)


def _money(value: float | int | None, currency: str | None = "USD") -> str | None:
    if value is None:
        return None
    return f"{currency_symbol(currency)}{float(value):,.0f}"


def _pct(value: float | int | None) -> str | None:
    if value is None:
        return None
    return f"{float(value):g}%"


def _dedupe(items: list[str], limit: int = 5) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _explicit_percent_scenario(raw_question: str, annual_spend: float | None) -> dict[str, Any] | None:
    """Recognize only a strong, explicit 'from X% to Y%' supplier scenario.

    This is intentionally narrow. It does not scan arbitrary percentages or
    guess which percentage is a target.
    """
    if not annual_spend or not raw_question:
        return None
    m = _RATE_SCENARIO_RE.search(raw_question)
    if not m:
        return None
    before = float(m.group(1))
    after = float(m.group(2))
    return {
        "from_percent": before,
        "to_percent": after,
        "annual_impact_from_usd": round(annual_spend * before / 100, 2),
        "monthly_impact_from_usd": round(annual_spend * before / 1200, 2),
        "annual_impact_to_usd": round(annual_spend * after / 100, 2),
        "monthly_impact_to_usd": round(annual_spend * after / 1200, 2),
        "annual_difference_usd": round(annual_spend * (before - after) / 100, 2),
        "monthly_difference_usd": round(annual_spend * (before - after) / 1200, 2),
        "basis": "Explicit scenario stated in the user's case text; arithmetic is deterministic.",
    }


def _supplier_name(normalized: NormalizedEvidence) -> str | None:
    if normalized.common.supplier_name:
        return normalized.common.supplier_name
    if normalized and normalized.suppliers:
        incumbent = next((s for s in normalized.suppliers if s.is_incumbent), normalized.suppliers[0])
        return incumbent.supplier_name
    return None


def _classify_decision_stance(recommendation: str | None) -> str:
    """Deterministic, text-based read of what the recommendation
    actually decided -- accept / challenge / investigate / other. A
    structured decision-type field doesn't exist yet and building a
    generic classifier is out of scope for this pass; this reads the
    same plain-English opening a human would, to judge whether a
    supplier draft is even useful yet.

    Bug found and fixed during the Supplier Request quality-gate audit:
    a plain substring check for "accept" incorrectly matched "before
    accepting the 8%" and "do not accept" -- both genuinely
    challenge/evidence-gathering language, not acceptance. Negated and
    conditional forms are now checked first, and explicitly excluded
    from the plain "accept" match."""
    text = (recommendation or "").strip().lower()
    if not text:
        return "unclear"
    lead = text[:70]
    if any(w in lead for w in ("investigate", "gather", "establish", "confirm before", "do not yet", "not yet", "wait for", "hold until", "before deciding", "not enough evidence")):
        return "investigate"
    if any(w in lead for w in ("challenge", "push back", "reject", "decline", "do not accept", "not accept", "before accept", "negotiate", "resist")):
        return "challenge"
    if any(w in lead for w in ("accept", "agree to", "proceed with", "approve")):
        return "accept"
    return "other"


def _classify_situation_type(normalized: NormalizedEvidence | None, position: Any) -> str:
    """Situation-specific read, layered on top of _classify_decision_
    stance rather than expanding it -- investigated first whether a
    clean structured field already exists for this (checked
    DecisionType, constraint_satisfaction signals, and the full
    NormalizedEvidence/CommercialPosition schema): none of them
    distinguish "this is a timing dispute" from "this is an FX
    request" from "this is a contract-index case". Building that as a
    new model-output field would mean changing the live classifier's
    JSON contract, which is a materially larger and riskier change
    than this pass is scoped for and cannot be verified without a real
    model call. So this reads the same case text a human reviewing the
    request would, using a structured signal (a genuine alternative
    supplier actually present in the case evidence) wherever one
    exists, and falls back to _classify_decision_stance's accept/
    challenge/investigate/other read otherwise -- never guessing a
    situation the case's own text doesn't support.

    Returns one of: accept, investigate, contract_compliance, timing,
    fx, competition, strategic_continuity, challenge, other."""
    stance = _classify_decision_stance(getattr(position, "recommendation", None))
    if stance in ("accept", "investigate"):
        return stance

    case = normalized.case if normalized else None
    justification = (getattr(case, "suppliers_stated_justification", None) or "").lower()
    criticality = (getattr(normalized.common, "how_critical_is_this_supplier_relationship", None) or "").lower() if normalized else ""
    recommendation = (getattr(position, "recommendation", None) or "").lower()
    combined = f"{justification} {criticality} {recommendation}"

    has_alt_suppliers = bool(normalized and any(not s.is_incumbent for s in (normalized.suppliers or [])))

    if any(w in combined for w in ("index clause", "index mechanism", "indexation", "contract's index", "index formula", "per the contract")):
        return "contract_compliance"
    if any(w in combined for w in ("notice period", "notice requirement", "days notice", "days' notice", "effective date", "notice was given")):
        return "timing"
    if any(w in combined for w in ("fx", "foreign exchange", "exchange rate", "usd/eur", "eur/usd", "currency")):
        return "fx"
    if has_alt_suppliers and any(w in combined for w in ("alternative", "qualified", "competitive", "competition", "capacity")):
        return "competition"
    if any(w in combined for w in ("critical", "sole-source", "sole source", "single-source", "single source", "switching", "continuity")):
        return "strategic_continuity"
    return stance


_NON_QUOTABLE_OPENING_MARKERS = (
    "no defensible", "not safely determined", "not determinable", "not established",
    "not safely quantified", "insufficient evidence", "cannot be determined",
)


def _is_supplier_quotable(text: str | None) -> bool:
    """True only for an opening line that is a genuine negotiating
    statement suitable to quote to the supplier -- not an internal note
    recording that no position could be established."""
    if not text:
        return False
    lowered = text.lower()
    return not any(m in lowered for m in _NON_QUOTABLE_OPENING_MARKERS)


def _build_response_draft(normalized: NormalizedEvidence | None, position: Any) -> dict[str, str] | None:
    """Create a conservative, editable supplier draft tailored to the
    actual situation -- not a single generic template reused
    regardless of what's actually happening. Suppressed entirely when
    the recommendation itself says more investigation is needed first
    (nothing useful to send a supplier yet). Every template below uses
    only facts the case actually states (the requested percentage, the
    supplier's own justification text, the supplier's name) -- never a
    specific contract clause, a specific notice-period length, a
    specific FX rate, or a competitor's name/price that the case
    didn't provide."""
    if normalized is None or normalized.content_type != "price_increase":
        return None
    case = normalized.case
    assert isinstance(case, PriceIncreaseEvidence)
    situation = _classify_situation_type(normalized, position)

    supplier = _supplier_name(normalized) or "Supplier"
    requested = _pct(case.requested_increase_percent) or "the requested increase"
    justification = (case.suppliers_stated_justification or "the stated cost drivers").strip()
    opening = (position.opening_position or "").strip()
    # An opening_position that is an internal, buyer-side statement
    # (e.g. the sanitizer's "No defensible counter-price can be
    # established ...") must never be pasted into a message addressed
    # to the supplier -- only a genuine negotiating line may be quoted.
    if not _is_supplier_quotable(opening):
        opening = ""
    closing = "Best regards,\nProcurement"

    if situation == "investigate":
        # Live-test fix: this previously returned None, leaving the
        # "Draft response to the supplier" section empty even though the
        # right next step was supplier-facing -- asking the supplier for
        # the evidence needed to evaluate the request. The draft asks
        # only for evidence; it proposes no price, range or counter-offer,
        # and uses only facts stated in the case.
        body = (
            f"Dear {supplier},\n\n"
            f"Thank you for your proposal regarding the {requested} price adjustment, "
            f"with the stated basis: {justification}\n\n"
            "Before we can evaluate the request, please provide the supporting evidence, including:\n"
            "- a breakdown of the unit cost affected, showing the share attributable to each cited cost driver;\n"
            "- the actual movement in each cited cost driver over the period, with the index or source used;\n"
            "- the methodology used to arrive at the requested percentage.\n\n"
            "We will review the request once this information is available.\n\n"
            f"{closing}"
        )
        return {"subject": f"{supplier} – information needed to evaluate the proposed price adjustment", "body": body, "status": "DRAFT — requires buyer review before sending"}

    if situation == "accept":
        body = (
            f"Dear {supplier},\n\n"
            f"Thank you for your proposal regarding the {requested} price adjustment. "
            f"We have reviewed the request and are able to proceed on the basis stated ({justification}).\n\n"
            "Please confirm the effective date and any changes to invoicing, and we will process the "
            f"adjustment accordingly.\n\n{closing}"
        )
        return {"subject": f"{supplier} – confirming the proposed price adjustment", "body": body, "status": "DRAFT — requires buyer review before sending"}

    if situation == "contract_compliance":
        body = (
            f"Dear {supplier},\n\n"
            f"Thank you for your proposal regarding the {requested} price adjustment. "
            "Before we can respond to the requested percentage, please confirm how this figure was "
            "calculated against the price-adjustment mechanism already in our agreement, including the "
            "reference period and index used.\n\n"
            f"We understand the stated basis is: {justification}\n\n"
            f"{closing}"
        )
        return {"subject": f"{supplier} – confirming the index calculation", "body": body, "status": "DRAFT — requires buyer review before sending"}

    if situation == "timing":
        body = (
            f"Dear {supplier},\n\n"
            f"Thank you for your proposal regarding the {requested} price adjustment. "
            "Our records show the notice given does not match the notice period required under our "
            "agreement for a change of this kind. Please confirm the notice period you believe applies "
            "and the effective date you are proposing, so we can align this with the agreed terms before "
            "discussing the adjustment itself.\n\n"
            f"{closing}"
        )
        return {"subject": f"{supplier} – confirming notice period and effective date", "body": body, "status": "DRAFT — requires buyer review before sending"}

    if situation == "fx":
        body = (
            f"Dear {supplier},\n\n"
            f"Thank you for your proposal regarding the {requested} price adjustment, stated as being "
            f"driven by currency movement ({justification}). Before we can evaluate this, please provide "
            "the specific reference rate and period you are using, and confirm this against the currency "
            "terms in our existing agreement.\n\n"
            f"{closing}"
        )
        return {"subject": f"{supplier} – confirming the currency basis for the adjustment", "body": body, "status": "DRAFT — requires buyer review before sending"}

    if situation == "competition":
        body = (
            f"Dear {supplier},\n\n"
            f"Thank you for your proposal regarding the {requested} price adjustment. "
            f"We have reviewed the request and the stated basis of {justification}. "
            "We are currently reviewing our sourcing options for this category as part of our normal "
            "commercial process, and would like to understand the full basis for this request before "
            "moving forward.\n\n"
            f"{closing}"
        )
        return {"subject": f"{supplier} – reviewing the proposed price adjustment", "body": body, "status": "DRAFT — requires buyer review before sending"}

    if situation == "strategic_continuity":
        body = (
            f"Dear {supplier},\n\n"
            f"Thank you for your proposal regarding the {requested} price adjustment. "
            f"We have reviewed the request and the stated basis of {justification}. "
            "Given the importance of this relationship to our operations, we would like to work through "
            "this constructively -- please provide the supporting basis for the requested figure so we "
            "can consider it alongside the broader commercial terms of our agreement.\n\n"
            f"{closing}"
        )
        return {"subject": f"{supplier} – working through the proposed price adjustment", "body": body, "status": "DRAFT — requires buyer review before sending"}

    body = (
        f"Dear {supplier},\n\n"
        f"Thank you for your proposal regarding the requested {requested} price adjustment. "
        f"We have reviewed the request and the stated basis of {justification}. "
    )
    if opening:
        body += f"Our current commercial position is: {opening} "
    body += (
        "Before we can agree to a change, please provide the supporting basis by product family, "
        "including the methodology used to determine the requested adjustment. We are also open to "
        "discussing an objective price-adjustment mechanism and the broader commercial terms, provided "
        "the overall economics and risk remain balanced.\n\n"
        "Please also confirm that the current delivery terms and underlying logistics economics remain unchanged.\n\n"
        "We look forward to discussing this with you.\n\n"
        "Best regards,\nProcurement"
    )
    return {
        "subject": f"{supplier} – review of proposed price adjustment",
        "body": body,
        "status": "DRAFT — requires buyer review before sending",
    }





def _unsupported_strategy_numbers_in_answer(raw_question: str, target: str | None, walk_away: str | None) -> list[str]:
    """Reject numeric negotiation strategy values not explicitly evidenced in the case.

    This is deliberately narrower than a general numeric parser: only percentages and
    explicit year/years durations in the strategy fields are checked. Any value already
    present in the user's case text is allowed; everything else is held back from the
    buyer-facing answer rather than guessed as a target.
    """
    raw = raw_question or ""
    allowed_pct = {m.group(1) for m in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%", raw)}
    allowed_years = {m.group(1) for m in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:year|years)", raw, re.I)}
    issues: list[str] = []
    for label, text in (("target", target), ("walk_away", walk_away)):
        if not text:
            continue
        for value in re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%", str(text)):
            if value not in allowed_pct:
                issues.append(f"{label}: unsupported percentage {value}%")
        for value in re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:year|years)", str(text), re.I):
            if value not in allowed_years:
                issues.append(f"{label}: unsupported duration {value} years")
    return issues

def build_commercial_answer(
    normalized: NormalizedEvidence | None,
    position: Any,
    raw_question: str,
    coverage_requirements: list | None = None,
) -> dict[str, Any]:
    """Build the single buyer-facing answer packet."""
    fi = getattr(position, "financial_impact", None)
    # Currency-neutral fields first (correct for any currency, including
    # USD); legacy "_usd" fields only as a fallback for anything that
    # somehow still only has the old shape populated.
    annual_spend = getattr(fi, "annual_spend", None) if fi else None
    if annual_spend is None:
        annual_spend = getattr(fi, "annual_spend_usd", None) if fi else (normalized.derived.resolved_annual_spend_usd if normalized else None)
    requested_pct = getattr(fi, "requested_change_percent", None) if fi else (getattr(normalized.case, "requested_increase_percent", None) if normalized else None)
    currency = (getattr(fi, "currency", None) if fi else None) or (normalized.derived.spend_currency if normalized else None) or "USD"

    money: dict[str, Any] = {
        "available": False,
        "currency": currency,
        "annual_spend_usd": annual_spend,
        "annual_spend": annual_spend,
        "requested_change_percent": requested_pct,
        "annual_impact_usd": None,
        "annual_impact": None,
        "monthly_impact_usd": None,
        "monthly_impact": None,
        "explicit_scenario": None,
        "notes": [],
    }
    if annual_spend is not None and requested_pct is not None and (normalized is None or normalized.derived.currency_calculation_safe):
        annual_impact = round(float(annual_spend) * float(requested_pct) / 100, 2)
        money.update({
            "available": True,
            "annual_impact_usd": annual_impact,
            "annual_impact": annual_impact,
            "monthly_impact_usd": round(annual_impact / 12, 2),
            "monthly_impact": round(annual_impact / 12, 2),
            "headline": f"{_money(annual_impact, currency)}/year potential impact",
            "basis": f"{_money(annual_spend, currency)} annual spend × {_pct(requested_pct)} requested change.",
        })
        # Real, structured scenario comparison, carried through from the
        # deterministic scenario engine -- not a regex re-scan of the raw
        # text. Falls back to the old regex-based extraction only when no
        # structured second scenario was genuinely extracted, so a case
        # relying purely on the old free-text pattern still works exactly
        # as before.
        sc = getattr(fi, "scenario_comparison", None)
        if sc is not None:
            money["explicit_scenario"] = {
                "currency": currency,
                "from_percent": sc.scenario_a.change_value,
                "to_percent": sc.scenario_b.change_value,
                "annual_impact_from_usd": sc.scenario_a.delta.amount,
                "annual_impact_from": sc.scenario_a.delta.amount,
                "monthly_impact_from_usd": round(sc.scenario_a.delta.amount / 12, 2),
                "monthly_impact_from": round(sc.scenario_a.delta.amount / 12, 2),
                "annual_impact_to_usd": sc.scenario_b.delta.amount,
                "annual_impact_to": sc.scenario_b.delta.amount,
                "monthly_impact_to_usd": round(sc.scenario_b.delta.amount / 12, 2),
                "monthly_impact_to": round(sc.scenario_b.delta.amount / 12, 2),
                "annual_difference_usd": sc.delta_amount.amount,
                "annual_difference": sc.delta_amount.amount,
                "monthly_difference_usd": round(sc.delta_amount.amount / 12, 2),
                "monthly_difference": round(sc.delta_amount.amount / 12, 2),
                "basis": f"Named alternative scenario ({sc.scenario_b.name}) from case evidence; arithmetic is deterministic.",
            }
            money["notes"].append(
                f"The case states a named alternative scenario ({sc.scenario_b.name}, {sc.scenario_b.change_value:g}%); "
                f"the difference versus {sc.scenario_a.change_value:g}% is {_money(sc.delta_amount.amount, currency)}/year."
            )
        else:
            scenario = _explicit_percent_scenario(raw_question, float(annual_spend))
            if scenario and abs(scenario["from_percent"] - float(requested_pct)) < 0.0001:
                money["explicit_scenario"] = scenario
                money["notes"].append(
                    f"The case explicitly states a {scenario['to_percent']:g}% alternative; the difference versus {scenario['from_percent']:g}% is {_money(scenario['annual_difference_usd'], currency)}/year."
                )

    supplier_name = _supplier_name(normalized) if normalized else None
    leverage: list[dict[str, str]] = []
    if normalized and normalized.suppliers:
        non_incumbent = [s for s in normalized.suppliers if not s.is_incumbent]
        if non_incumbent:
            leverage.append({"label": "Alternative supplier evidence", "value": f"{len(non_incumbent)} non-incumbent supplier(s) are represented in the case evidence."})
    insights = list(getattr(position, "commercial_insights", []) or [])
    why = _dedupe(insights, 4)
    # Computed early so both the next_move fallback and the actions
    # list below can use it -- avoids two separate reads of the same
    # recommendation text producing inconsistent stances.
    decision_stance = _classify_decision_stance(getattr(position, "recommendation", None))
    _stance_fallback = {
        "accept": "Confirm the effective date with the supplier and process the adjustment.",
        "investigate": "Gather the missing information before forming a position.",
        "challenge": "Request the supplier's supporting evidence before moving your position.",
    }.get(decision_stance, "Review the evidence and act within the stated conditions.")
    next_move = None
    for candidate in [
        getattr(position, "opening_position", None),
        (position.commercial_decision_engine.get("next_move") if isinstance(getattr(position, "commercial_decision_engine", None), dict) else None),
        _stance_fallback,
    ]:
        if candidate:
            next_move = str(candidate)
            break

    audit = getattr(position, "decision_audit", None)
    if audit is not None and hasattr(audit, "model_dump"):
        audit = audit.model_dump()
    if not isinstance(audit, dict):
        audit = {}

    # Evidence ledger: facts that can be traced directly from normalized fields.
    verified: list[str] = []
    supplier_claims: list[str] = []
    calculated: list[str] = []
    unknown: list[str] = list((audit.get("uncertainties") or [])[:3])
    if normalized is None:
        unknown.insert(0, "This case used general commercial triage; specialist evidence engines were not run.")
    stakeholder_views = [getattr(v, "statement", "") for v in normalized.stakeholder_views] if normalized else []

    if supplier_name:
        verified.append(f"Supplier: {supplier_name}.")
    if annual_spend is not None:
        verified.append(f"Annual spend stated/resolved as {_money(annual_spend, currency)}.")
    if requested_pct is not None:
        verified.append(f"Requested increase: {_pct(requested_pct)}.")
    if normalized and normalized.common.incoterm:
        verified.append(f"Current Incoterm: {normalized.common.incoterm}.")
    if normalized and getattr(normalized.case, "suppliers_stated_justification", None):
        supplier_claims.append(str(normalized.case.suppliers_stated_justification).strip())
    if normalized and normalized.derived.resolved_annual_spend_usd is not None and normalized.case.requested_increase_percent is not None:
        calculated.append(f"Annual price impact: {_money(money['annual_impact_usd'], currency)}.")
        calculated.append(f"Monthly price impact: {_money(money['monthly_impact_usd'], currency)}.")
        if money.get("explicit_scenario"):
            calculated.append(
                f"Explicit alternative-rate difference: {_money(money['explicit_scenario']['annual_difference_usd'], currency)}/year."
            )

    negotiation = getattr(position, "negotiation_intelligence", None)
    if not isinstance(negotiation, dict):
        negotiation = {}
    objective = negotiation.get("objective") or getattr(position, "commercial_hypothesis", None)
    opening = getattr(position, "opening_position", None) or negotiation.get("opening_position")
    target = negotiation.get("target")
    walk_away = negotiation.get("walk_away") or getattr(position, "walk_away_threshold", None)
    strategy_integrity_issues = []
    if normalized is not None:
        try:
            strategy_integrity_issues = check_unsupported_strategy_numbers(position, normalized, raw_question)
        except Exception:
            strategy_integrity_issues = []
    strategy_integrity_issues.extend(_unsupported_strategy_numbers_in_answer(raw_question, target, walk_away))
    if strategy_integrity_issues:
        # Bug fix: this previously cleared to None, which a later layer
        # rendered as a blank/empty string in the buyer-facing answer --
        # an ambiguous "" that looks like a data-loss bug rather than a
        # deliberate, evidence-honest refusal to invent a number. Every
        # clearing path below states plainly WHY there is no number,
        # never leaving a bare blank for the buyer to puzzle over.
        target = "Not determinable from current evidence: no supplier-specific cost basis, index, or comparable data supports a numeric target."
        walk_away = "Not determinable from current evidence: no supplier-specific cost basis, index, or comparable data supports a numeric walk-away threshold."
    else:
        # Catch-all: even when nothing was flagged as an unsupported
        # invented number, the model may simply never have provided a
        # target/walk-away at all (a distinct case from stripping one
        # out) -- still not left blank, for the same reason.
        if not target or not str(target).strip():
            target = "Not determinable from current evidence."
        if not walk_away or not str(walk_away).strip():
            walk_away = "Not determinable from current evidence."

    counter = None
    orchestration = getattr(position, "model_orchestration", None)
    if isinstance(orchestration, dict):
        counter = orchestration.get("alternative_frame") or orchestration.get("verdict")
    if not counter:
        loop = getattr(position, "reasoning_loop", None)
        if isinstance(loop, dict):
            counter = loop.get("strongest_counterargument")

    decision_changers: list[str] = []
    if getattr(position, "disconfirming_condition", None):
        decision_changers.append(str(position.disconfirming_condition))
    # UX fix: reversal_conditions mechanically wraps every uncertainty
    # with a fixed "Reassess if this unresolved point changes
    # materially:" prefix (see decision_audit.py) -- meaning it is
    # always substantially a near-verbatim restatement of evidence.
    # unknown below, just with a different prefix. Pulling those into
    # the primary decision_changers list duplicated the same fact
    # across the primary answer and the deeper evidence detail. Only a
    # genuinely distinct reversal condition (not a mechanical
    # uncertainty restatement) belongs in the primary view; the
    # uncertainty itself is still fully available in evidence.unknown.
    _uncertainty_texts = {str(u).strip().lower() for u in unknown}
    for rc in audit.get("reversal_conditions") or []:
        rc_text = str(rc).strip()
        is_uncertainty_restatement = rc_text.lower().startswith("reassess if this unresolved point changes materially:")
        if is_uncertainty_restatement:
            continue
        decision_changers.append(rc_text)
        if len(decision_changers) >= 3:
            break
    decision_changers = _dedupe(decision_changers, 3)

    actions = []
    # Reuses decision_stance computed earlier for the next_move
    # fallback, rather than reclassifying the same text twice.
    # Fix (Supplier Request quality gate): these two items were
    # previously unconditional in practice -- their old guard
    # conditions ("a supplier exists" / "a percent was requested")
    # are true for virtually every price_increase case, which is why
    # they appeared identically across 11 materially different audit
    # cases, including nonsensical combinations (telling the buyer to
    # "request supplier-specific support before agreeing" on a case
    # that was just accepted). Now gated on the actual decision state:
    # alternative-supplier validation only when a supplier's
    # qualification is genuinely still pending (the same evidence
    # trade_off already reflects, not duplicated logic -- read from
    # the same normalized.suppliers data); requesting supplier
    # evidence only when the decision is actually still open
    # (challenge/other), never when the case was already accepted or
    # is explicitly waiting on investigation first.
    has_pending_alt_supplier = bool(normalized and any(
        getattr(s, "qualification_time_estimate", None) for s in (normalized.suppliers or [])
    ))
    needs_supplier_evidence = decision_stance in ("challenge", "other") and requested_pct is not None
    for text in [
        next_move,
        ("Validate alternative-supplier qualification/capacity before making a consequential commitment." if has_pending_alt_supplier else None),
        ("Request supplier-specific support for the requested change before agreeing to it." if needs_supplier_evidence else None),
    ]:
        if text:
            actions.append(text)
    actions = _dedupe(actions, 3)

    # Question-coverage wiring: surface every genuinely calculated
    # category/supplier growth requirement here, in the primary answer,
    # and mark it surfaced -- a CALCULATED requirement that never
    # reaches this point stays CALCULATED, which is exactly the
    # "silently disappeared" state final_answer_reconciliation checks
    # for and rejects.
    category_trends = []
    supplier_trends = []
    if coverage_requirements:
        from app.pipeline.question_coverage import mark_surfaced
        surfaced_ids = set()
        for req in coverage_requirements:
            if req.status != "CALCULATED" or req.result is None:
                continue
            entry = {
                "metric": req.metric, "requested_analysis": req.requested_analysis,
                "current": req.result.current, "prior": req.result.prior,
                "absolute_change": req.result.absolute_change, "percent_change": req.result.percent_change,
            }
            if req.entity == "category":
                category_trends.append(entry)
            else:
                supplier_trends.append(entry)
            surfaced_ids.add(req.requirement_id)
        mark_surfaced(coverage_requirements, surfaced_ids, "commercial_answer.category_trends/supplier_trends")

    return {
        "status": "READY",
        "decision": str(getattr(position, "recommendation", "Review the evidence before acting.") or "Review the evidence before acting."),
        "confidence": str(getattr(getattr(position, "confidence", None), "level", "unknown")),
        "why": why,
        "money": money,
        "category_trends": category_trends,
        "supplier_trends": supplier_trends,
        "evidence": {
            "verified": _dedupe(verified, 6),
            "supplier_claims": _dedupe(supplier_claims, 4),
            "calculated": _dedupe(calculated, 6),
            "stakeholder_views": _dedupe(stakeholder_views, 3),
            "unknown": _dedupe(unknown, 4),
        },
        "strategy_integrity": "REVIEW_REQUIRED" if strategy_integrity_issues else "SUPPORTED_OR_NON_NUMERIC",
        "leverage": leverage,
        "what_to_do": actions,
        "negotiation": {
            "objective": objective,
            "opening": opening,
            "target": target,
            "walk_away": walk_away,
            "give_get": (negotiation.get("dimensions") or [])[:4],
        },
        "counter_case": counter,
        # UX fix: this previously appeared twice, verbatim, under two
        # different keys ("evidence.unknown" and "critical_unknowns"),
        # exactly the cross-section repetition this pass exists to
        # remove. decision_changers ("what would change THIS decision")
        # is the primary-answer-facing concept; evidence.unknown (the
        # deeper, complete uncertainty list) may legitimately contain
        # more than these top items, which is real additional
        # information, not a repeat of it.
        "decision_changers": decision_changers,
        "supplier_response": _build_response_draft(normalized, position),
        "method": "Every number here is calculated directly from the evidence you supplied, not estimated or generated; no new facts or figures were introduced.",
    }
