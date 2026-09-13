"""Phase 4 — Negotiation Intelligence.

Builds an evidence-backed negotiation operating brief from the validated
CommercialPosition. No LLM call and no new facts. The module turns existing
negotiation dimensions into give/get rules, response scenarios, escalation
triggers, and a concise preparation checklist.
"""
from __future__ import annotations
from typing import Any
from app.models import CommercialPosition


def _clean(v: Any) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


# Target/walk-away integrity fix, confirmed root cause: this module
# previously treated ANY non-empty target_outcome/walk_away string as a
# genuine, established value worth "holding" in negotiation, generating
# "Hold the stated target" regardless of whether that string was
# actually a real, evidence-backed figure or a hedge like "Not safely
# quantified from the supplied evidence" -- the model's own honest
# statement that no numeric target exists. That produced a real,
# user-visible contradiction: one section of the same answer correctly
# says "no target established" while another instructs the buyer to
# "hold" one. Deliberately narrow, explicit phrase list rather than a
# broad heuristic -- these are the specific hedge phrases this
# codebase's own evidence-firewall prompts instruct the model to use
# when a target/walk-away genuinely isn't supported.
_UNESTABLISHED_PHRASES = (
    "not safely quantified", "not established", "no supported numeric",
    "insufficient evidence", "cannot be determined", "not yet established",
    "not currently established", "no numeric target", "no numeric walk-away",
)


def _is_established(text: str | None) -> bool:
    """True only when the text looks like a genuine, stated value -- not
    empty, and not one of the model's own honest hedge phrases for "no
    supported number exists". Deliberately a narrow, explicit check
    rather than trying to parse out a real number: the point isn't to
    validate the value's precision, only to stop treating a hedge
    sentence as if it were one."""
    if not text:
        return False
    lowered = text.lower()
    return not any(phrase in lowered for phrase in _UNESTABLISHED_PHRASES)


def build_negotiation_intelligence(position: CommercialPosition) -> dict[str, Any]:
    dims = position.negotiation_dimensions or []
    audit = position.decision_audit
    # UX fix: evidence gaps (an absence of information, e.g. "qualification
    # timeline unknown") and genuine escalation triggers (a decision-
    # changing condition, e.g. "supplier refuses benchmark rights") are
    # different concepts and were previously conflated -- every audit
    # uncertainty was appended directly as an "escalation trigger" with
    # the same generic action text, regardless of whether it was
    # actually decision-changing. Kept as two separate, distinctly
    # labeled lists below.
    evidence_gaps = [str(x).strip() for x in (audit.uncertainties if audit else []) if str(x).strip()][:5]
    blockers = evidence_gaps  # readiness gating below still treats any open evidence gap as blocking readiness

    give_get = []
    for d in dims[:6]:
        target_established = _is_established(str(d.target_outcome))
        walk_away_established = _is_established(str(d.walk_away))
        # UX fix: this previously repeated the identical generic sentence
        # on every row. The governing principle is now stated once, at
        # the top level (see "trading_principle" below); each row's own
        # "rule" is specific to that row's actual target/boundary values,
        # not a repeated boilerplate sentence.
        if target_established and walk_away_established:
            rule = f"Concede toward {d.target_outcome} only for a measurable supplier concession; do not go beyond {d.walk_away} without escalating."
        elif target_established:
            rule = f"Concede toward {d.target_outcome} only for a measurable supplier concession; no walk-away boundary is established for this dimension yet."
        else:
            rule = "No supported numeric target established for this dimension; do not concede on it until the evidence needed to set one is available."
        give_get.append({
            "dimension": str(d.dimension),
            "buyer_opening": str(d.opening_ask),
            "buyer_target": str(d.target_outcome),
            "target_state": "ESTABLISHED" if target_established else "NOT_ESTABLISHED",
            "buyer_boundary": str(d.walk_away),
            "walk_away_state": "ESTABLISHED" if walk_away_established else "NOT_ESTABLISHED",
            "rule": rule,
        })

    response_scenarios = []
    for d in dims[:5]:
        if _is_established(str(d.target_outcome)):
            move = f"Hold the stated target for {d.dimension}; ask what equivalent commercial value the supplier can provide."
        else:
            move = f"No supported numeric target established for {d.dimension} from current evidence; do not concede, and ask for the evidence that would establish one before trading value."
        response_scenarios.append({
            "trigger": f"Supplier resists on {d.dimension}",
            "buyer_move": move,
            "target_state": "ESTABLISHED" if _is_established(str(d.target_outcome)) else "NOT_ESTABLISHED",
            "status": "SCENARIO_NOT_PREDICTION",
        })
    if position.opening_position:
        response_scenarios.insert(0, {
            "trigger": "Supplier challenges the opening position",
            "buyer_move": "Ask for the evidence supporting the supplier's counter-position before trading value.",
            "status": "SCENARIO_NOT_PREDICTION",
        })

    # UX fix, the core of this pass: escalation_triggers now contains
    # ONLY genuine decision-changing conditions -- a stated boundary
    # actually being reached, or a real structural conflict. Evidence
    # gaps (missing information) are surfaced separately, above, as
    # evidence_gaps -- never mislabeled as an escalation trigger merely
    # because a fact is missing.
    escalation = []
    if position.walk_away_threshold:
        escalation.append({"trigger": f"Negotiation reaches the stated boundary: {position.walk_away_threshold}", "action": "Stop trading beyond the approved boundary and escalate for a new decision."})
    if audit and audit.contradictions:
        escalation.append({"trigger": "Supplier's own claim conflicts with the case's documented evidence", "action": "Resolve the reconciliation issue with the supplier directly before treating either figure as settled."})
    if not escalation:
        escalation.append({"trigger": "Supplier asks for a concession outside the captured position", "action": "Pause and re-run the commercial decision before committing."})

    checklist = [
        "Confirm the evidence supporting the opening position.",
        "Know the target and walk-away boundary before the meeting.",
        "Lead with the strongest evidenced commercial point.",
        "Trade concessions conditionally rather than giving them away.",
        "Capture the supplier response as new evidence after the interaction.",
    ]

    readiness = "READY" if not blockers else "CONDITIONAL"
    if audit and audit.evidence_integrity_status == "CONTRADICTED":
        readiness = "HOLD_FOR_EVIDENCE_CONFLICT"

    return {
        "available": True,
        "readiness": readiness,
        "trading_principle": "Trade any dimension only for a measurable supplier concession; never concede unconditionally.",
        "objective": position.recommendation,
        "opening_position": position.opening_position,
        "target": next((d.target_outcome for d in dims if d.target_outcome and _is_established(str(d.target_outcome))), None),
        "walk_away": position.walk_away_threshold,
        "give_get_matrix": give_get,
        "response_scenarios": response_scenarios[:6],
        "escalation_triggers": escalation[:6],
        # UX fix: this previously re-listed the exact same uncertainty
        # text already shown in the primary answer's evidence section --
        # a genuine, if smaller, instance of the same cross-section
        # duplication this whole pass exists to remove. The real,
        # non-duplicative value negotiation intelligence adds here is
        # readiness (above) and evidence_gap_count -- a count is new
        # information; re-listing the same sentences verbatim is not.
        "evidence_gap_count": len(evidence_gaps),
        "preparation_checklist": checklist,
        "evidence_to_lead_with": (position.negotiation_playbook.evidence_to_lead_with if position.negotiation_playbook else [])[:5],
        "questions_to_resolve": (position.negotiation_playbook.questions_to_resolve if position.negotiation_playbook else [])[:6],
        "method": "Supplier reactions shown here are scenarios to prepare for, not predictions of what they'll actually say.",
    }
