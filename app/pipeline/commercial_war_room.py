"""VendorEdge Release 22 — Commercial War Room.

R22 assembles an evidence-backed negotiation theatre from the already validated
commercial position. It separates what the buyer can credibly use, what the
supplier can credibly defend, what the market/stakeholders signal, and which
moves should be tested.

No LLM call. No new facts. No supplier psychology is invented. Hypothetical
responses are explicitly labelled as scenarios, not predictions.
"""
from __future__ import annotations
from typing import Any

from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence


def _uniq(items: list[str], limit: int = 6) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out[:limit]


def _supplier_card(s, position: CommercialPosition) -> dict[str, Any]:
    facts: list[str] = []
    if s.price_display is not None:
        facts.append(f"Price: {s.price_display}")
    if s.incoterm:
        facts.append(f"Incoterm: {s.incoterm}")
    if s.lead_time_weeks is not None:
        facts.append(f"Lead time: {s.lead_time_weeks:g} weeks")
    if s.otif_percent is not None:
        facts.append(f"OTIF: {s.otif_percent:g}%")
    if s.defect_rate_percent is not None:
        facts.append(f"Defect rate: {s.defect_rate_percent:g}%")
    if s.payment_terms:
        facts.append(f"Payment terms: {s.payment_terms}")
    if s.capacity_percent is not None:
        facts.append(f"Capacity: {s.capacity_percent:g}%")
    if s.qualification_status != "unknown":
        facts.append(f"Qualification: {s.qualification_status}")
    if s.is_incumbent:
        facts.append("Incumbent supplier")
    if s.freight_cost_or_estimate:
        facts.append(f"Freight: {s.freight_cost_or_estimate}")

    defenses: list[str] = []
    if s.capacity_percent is not None:
        defenses.append("Capacity is an evidenced supplier constraint to test rather than assume away.")
    if s.lead_time_weeks is not None:
        defenses.append("Lead time is an evidenced delivery position that can be challenged or traded.")
    if s.payment_terms:
        defenses.append("Payment terms are an evidenced commercial term available for negotiation.")
    if s.qualification_status in {"complete", "in_progress", "not_started"}:
        defenses.append("Qualification status is an explicit constraint in the supplier position.")
    if s.is_incumbent:
        defenses.append("Incumbency creates continuity value, but R22 does not treat it as automatic leverage for either side.")
    if not defenses:
        defenses.append("No supplier-specific constraint beyond the captured evidence is safely established.")

    return {"supplier": s.supplier_name, "facts": facts[:8], "defensible_constraints": defenses[:5]}


def _buyer_leverage(normalized: NormalizedEvidence, position: CommercialPosition) -> list[dict[str, str]]:
    leverage: list[dict[str, str]] = []
    suppliers = normalized.suppliers
    if len(suppliers) >= 2:
        leverage.append({"lever": "Credible alternative", "basis": f"{len(suppliers)} named suppliers are represented in the normalized evidence.", "strength": "EVIDENCED"})
    if any(s.is_incumbent for s in suppliers) and len(suppliers) >= 2:
        leverage.append({"lever": "Competitive tension", "basis": "An incumbent and at least one alternative are explicitly represented.", "strength": "EVIDENCED"})
    if position.negotiation_dimensions:
        for d in position.negotiation_dimensions[:5]:
            leverage.append({"lever": str(d.dimension), "basis": f"Existing negotiation position: {d.opening_ask} → target {d.target_outcome}.", "strength": "EVIDENCED"})
    if position.decision_flip_map:
        for f in position.decision_flip_map.get("flips", [])[:3]:
            if f.get("type") == "price_threshold":
                leverage.append({"lever": "Price boundary", "basis": str(f.get("trigger", "")), "strength": "DETERMINISTIC"})
    return leverage[:8]


def _market_signals(normalized: NormalizedEvidence, position: CommercialPosition) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    scope = position.market_verification_scope
    if scope:
        signals.append({"signal": "Market verification", "basis": f"Verified market evidence was captured for {scope}.", "status": "EVIDENCED"})
    for d in (position.cost_driver_comparison or [])[:5]:
        signals.append({"signal": str(d.driver), "basis": f"Supplier claim {d.claimed_percent:g}% vs market {d.market_percent:g}%.", "status": "EVIDENCED"})
    if not signals:
        signals.append({"signal": "Market position", "basis": "No market signal is safely established from the current evidence.", "status": "UNKNOWN"})
    return signals[:6]


def _stakeholder_positions(normalized: NormalizedEvidence) -> list[dict[str, str]]:
    return [
        {"stakeholder": v.stakeholder_name, "role": v.role or "Not stated", "type": v.view_type, "position": v.statement, "basis": v.basis or "Not stated"}
        for v in normalized.stakeholder_views[:8]
    ]


def _adversarial_challenges(normalized: NormalizedEvidence, position: CommercialPosition) -> list[dict[str, str]]:
    challenges: list[dict[str, str]] = []
    audit = position.decision_audit
    for item in (audit.uncertainties[:4] if audit else []):
        challenges.append({"challenge": f"Attack unresolved evidence: {item}", "purpose": "Test whether the decision survives the unresolved point."})
    for item in (position.decision_flip_map or {}).get("evidence_required", [])[:4]:
        condition = item.get("condition")
        if condition:
            challenges.append({"challenge": f"Ask the supplier/buyer to prove: {condition}", "purpose": "Test a stated reversal condition without inventing a threshold."})
    for item in (position.stress_test or {}).get("warnings", [])[:3]:
        challenges.append({"challenge": str(item), "purpose": "Use the existing stress-test warning as an adversarial question."})
    if not challenges:
        challenges.append({"challenge": "Identify the strongest evidence-supported reason the current recommendation could be wrong.", "purpose": "Mandatory counter-position challenge; no outcome is predicted."})
    return challenges[:8]


def _scenario_matrix(position: CommercialPosition) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for d in (position.negotiation_dimensions or [])[:5]:
        scenarios.append({
            "scenario": f"Push on {d.dimension}",
            "buyer_move": d.opening_ask,
            "target": d.target_outcome,
            "supplier_response": "NOT_PREDICTED",
            "walk_away": d.walk_away,
            "status": "EVIDENCE_BACKED_SCENARIO",
        })
    if position.opening_position:
        scenarios.insert(0, {
            "scenario": "Open the negotiation",
            "buyer_move": position.opening_position,
            "target": position.negotiation_playbook.target if position.negotiation_playbook else None,
            "supplier_response": "NOT_PREDICTED",
            "walk_away": position.walk_away_threshold,
            "status": "EVIDENCE_BACKED_SCENARIO",
        })
    return scenarios[:6]


def build_commercial_war_room(normalized: NormalizedEvidence, position: CommercialPosition) -> dict[str, Any]:
    suppliers = [_supplier_card(s, position) for s in normalized.suppliers[:8]]
    buyer = _buyer_leverage(normalized, position)
    market = _market_signals(normalized, position)
    stakeholders = _stakeholder_positions(normalized)
    scenarios = _scenario_matrix(position)
    challenges = _adversarial_challenges(normalized, position)

    audit = position.decision_audit
    blockers = _uniq((audit.uncertainties if audit else []) + (audit.reversal_conditions if audit else []), 6)
    red_lines = _uniq([d.walk_away for d in (position.negotiation_dimensions or []) if d.walk_away] + ([position.walk_away_threshold] if position.walk_away_threshold else []), 6)

    readiness = "READY_FOR_NEGOTIATION"
    if audit and audit.evidence_integrity_status == "CONTRADICTED":
        readiness = "HOLD_FOR_EVIDENCE_CONFLICT"
    elif blockers:
        readiness = "CONDITIONAL"

    return {
        "available": True,
        "version": "R22.1",
        "title": "Commercial War Room",
        "readiness": readiness,
        "current_recommendation": position.recommendation,
        "buyer_position": {
            "objective": position.recommendation,
            "leverage": buyer,
            "red_lines": red_lines,
            "evidence_to_lead_with": (position.negotiation_playbook.evidence_to_lead_with if position.negotiation_playbook else [])[:5],
        },
        "supplier_positions": suppliers,
        "market_position": market,
        "stakeholder_positions": stakeholders,
        "negotiation_scenarios": scenarios,
        "adversarial_challenges": challenges,
        "open_blockers": blockers,
        "method": "Deterministic war-room assembly from normalized evidence, validated decision fields, negotiation positions, market verification, stakeholder views and existing stress/flip outputs. No new facts, supplier psychology, ranking or LLM call.",
        "simulation_disclaimer": "Supplier responses are deliberately not predicted. Scenarios show evidence-backed buyer moves and the conditions to test; actual counterpart behavior must be observed and recorded.",
    }
