"""Deterministic safety contract for the non-specialist triage route."""
from __future__ import annotations

import re

from app.models import CommercialPosition, ConfidenceFactor, DecisionAudit

_PROHIBITED = re.compile(r"\b(fair|best price|market proven|market[- ]verified|liable|liability|breach|legally|required by contract|must accept)\b", re.I)
_NUMBER = re.compile(r"(?<![\w.])\$?\d+(?:[,.]\d+)?\s*%?")


def apply_generic_integrity_contract(position: CommercialPosition, raw_evidence: str) -> CommercialPosition:
    """Fail closed on claims generic triage cannot prove deterministically.

    Generic triage may only offer a reversible protective next step. It cannot
    make a procurement decision, certify facts, or introduce a numeric claim
    not present in the submitted evidence.
    """
    text = "\n".join(filter(None, [
        position.recommendation, position.reasoning, position.why_this_wins,
        position.opening_position, position.disconfirming_condition,
        *position.commercial_insights, *position.assumptions,
    ]))
    if _PROHIBITED.search(text):
        raise ValueError("Generic triage contained a claim reserved for specialist evidence checks.")

    supplied_numbers = {m.group(0).replace(",", "").replace(" ", "") for m in _NUMBER.finditer(raw_evidence)}
    response_numbers = {m.group(0).replace(",", "").replace(" ", "") for m in _NUMBER.finditer(text)}
    if not response_numbers.issubset(supplied_numbers):
        raise ValueError("Generic triage introduced a numeric claim not present in submitted evidence.")

    # No model-owned confidence or irreversible DECIDE outcome is allowed in
    # this route. The system supplies the same conservative, auditable state
    # every time.
    position.confidence.level = "low"
    position.confidence.derivation_note = (
        "System-set low confidence: this is general commercial triage without "
        "specialist evidence normalization, economics, market, legal, or contract analysis."
    )
    position.confidence.factors = [ConfidenceFactor(
        factor="Specialist evidence and calculation coverage was not run.",
        value="general triage only",
        weight="decreases confidence",
    )]
    position.decision_under_uncertainty = {
        "mode": "PROTECT",
        "label": "PROTECT — DO NOT MAKE AN IRREVERSIBLE COMMITMENT",
        "recommendation": position.recommendation,
        "confidence": "low",
        "known": [],
        "unknowns": ["Specialist evidence validation has not been performed for this decision type."],
        "question": None,
        "question_why": None,
        "safe_now": True,
        "reversibility": "Use only reversible protection while the relevant facts are verified.",
        "review_trigger": position.disconfirming_condition,
    }
    position.decision_audit = DecisionAudit(
        material_evidence=[],
        inferred_signals=[],
        uncertainties=["General triage uses only submitted text and cannot certify procurement facts."],
        stakeholder_tradeoffs=[], stakeholder_conflict=[],
        reversal_conditions=[position.disconfirming_condition],
        evidence_integrity_status="UNKNOWN", normalization_warnings=[],
        evidence_counts={"submitted_text_only": 1},
    )
    return position
