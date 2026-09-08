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


def _build_response_draft(normalized: NormalizedEvidence | None, position: Any) -> dict[str, str] | None:
    """Create a conservative, editable supplier draft from existing case facts."""
    if normalized is None or normalized.content_type != "price_increase":
        return None
    case = normalized.case
    assert isinstance(case, PriceIncreaseEvidence)
    supplier = _supplier_name(normalized) or "Supplier"
    requested = _pct(case.requested_increase_percent) or "the requested increase"
    justification = (case.suppliers_stated_justification or "the stated cost drivers").strip()
    opening = (position.opening_position or "").strip()
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
    next_move = None
    for candidate in [
        getattr(position, "opening_position", None),
        (position.commercial_decision_engine.get("next_move") if isinstance(getattr(position, "commercial_decision_engine", None), dict) else None),
        "Review the evidence and act within the stated conditions.",
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
        target = None
        walk_away = None

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
    if audit.get("reversal_conditions"):
        decision_changers.extend(audit["reversal_conditions"][:2])
    decision_changers = _dedupe(decision_changers, 3)

    actions = []
    for text in [
        next_move,
        ("Validate alternative-supplier qualification/capacity before making a consequential commitment." if normalized and normalized.suppliers else None),
        ("Request supplier-specific support for the requested change before agreeing to it." if requested_pct is not None and normalized else None),
    ]:
        if text:
            actions.append(text)
    actions = _dedupe(actions, 3)

    return {
        "version": "R38.0",
        "status": "READY",
        "decision": str(getattr(position, "recommendation", "Review the evidence before acting.") or "Review the evidence before acting."),
        "confidence": str(getattr(getattr(position, "confidence", None), "level", "unknown")),
        "why": why,
        "money": money,
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
        "decision_changers": decision_changers,
        "critical_unknowns": _dedupe(unknown, 3),
        "supplier_response": _build_response_draft(normalized, position),
        "method": "Deterministic R38 answer assembly from normalized evidence, guaranteed calculations, validated decision fields and explicitly-labelled uncertainty; no new commercial facts or thresholds created.",
    }
