"""
Phase 7 -- Complex Problem Solving Engine.

Redesigned this round per explicit instruction: the two hard
disciplines below now read explicit, structured evidence fields
(RootCauseCandidateEvidence.supporting_evidence,
CountermeasureProposalEvidence.resource_type,
AlternativeLeverEvidence.lever_type -- see normalized_evidence.py) --
not keyword/substring matching against free text. A differently-phrased
resource proposal can no longer evade the gate, because the gate no
longer reads phrasing at all; it reads a field the extraction step (or
caller) must state directly, the same discipline every other evidence
type in this codebase already follows (attributed_to, dimension,
evidence_state, etc. are all explicit fields, never inferred from
wording).

Two hard disciplines enforced in code, not prompt instruction:

1. ROOT-CAUSE DISCIPLINE (item 6): a root-cause candidate is never
   "supported" without supporting_evidence. The label's wording is
   never inspected -- a genuinely well-evidenced "operator error" is
   accepted; a bare, unevidenced one is not, on the SAME basis: does
   real supporting evidence exist, not how the label sounds.

2. COUNTERMEASURE DISCIPLINE / MAERSK PRINCIPLE (item 8): a
   countermeasure with resource_type in {"headcount",
   "system_or_infrastructure"} is never approved without: a validated
   root cause, at least one alternative genuinely marked evaluated=True
   with a real lever_type, an explicit why_alternatives_insufficient,
   and evidence. All four, not any one.
"""
from __future__ import annotations
from typing import Any

_RESOURCE_TYPES = ("headcount", "system_or_infrastructure")


def diagnose_problem(statement: dict[str, Any]) -> dict[str, Any]:
    """Converts a raw problem statement into Problem / Current Condition
    / Desired Condition / Gap / Impact -- each populated ONLY from what
    was explicitly given, never invented. Accepts the same key names as
    ProblemSolvingEvidence for direct pass-through: problem_statement,
    current_condition, desired_condition, stated_impact."""
    problem = statement.get("problem_statement") or statement.get("problem")
    current = statement.get("current_condition")
    desired = statement.get("desired_condition")
    impact = statement.get("stated_impact")

    gap = None
    gap_evidence_state = "UNKNOWN"
    if current is not None and desired is not None:
        gap = f"Current: {current}. Desired: {desired}."
        gap_evidence_state = "VERIFIED"

    return {
        "problem": problem,
        "current_condition": current,
        "desired_condition": desired,
        "gap": gap,
        "gap_evidence_state": gap_evidence_state,
        "impact": impact,
        "impact_evidence_state": "VERIFIED" if impact is not None else "UNKNOWN",
    }


def evaluate_root_cause_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    """Item 6's core enforcement, now structural rather than
    keyword-based: `candidate` matches RootCauseCandidateEvidence's
    shape -- {"label": str, "category": str (the case's own claim),
    "supporting_evidence": list[str], "source": str}. The verdict
    depends ONLY on whether supporting_evidence is genuinely present --
    never on whether the label sounds generic. A source of
    "oem_or_supplier" with no independent supporting_evidence is
    explicitly flagged as unverified-by-VendorEdge, since a claim made
    BY the party proposing the fix is not independent evidence of it."""
    label = (candidate.get("label") or "").strip()
    supporting_evidence = candidate.get("supporting_evidence") or []
    claimed_category = candidate.get("category", "unspecified")
    source = candidate.get("source", "unspecified")

    if not supporting_evidence:
        note = ""
        if source == "oem_or_supplier":
            note = " This label originates from the party proposing the fix (OEM/supplier), which is not independent evidence of the cause."
        return {
            "label": label,
            "verdict": "insufficient_evidence_for_root_cause",
            "actual_category": "symptom" if claimed_category == "root_cause" else claimed_category,
            "claimed_category": claimed_category,
            "source": source,
            "reason": f"\"{label}\" has no supporting evidence.{note} This describes what was observed or claimed, not a validated cause.",
            "what_would_establish_this": f"Evidence showing WHY \"{label}\" occurred -- e.g. what specific process step, specification gap, or system condition made it likely or possible.",
        }

    return {
        "label": label,
        "verdict": "supported",
        "actual_category": claimed_category if claimed_category != "unspecified" else "contributing_cause",
        "claimed_category": claimed_category,
        "source": source,
        "supporting_evidence": supporting_evidence,
        "reason": f"\"{label}\" is supported by stated evidence, independent of how the label itself is phrased.",
    }


def build_countermeasure_analysis(countermeasure: dict[str, Any], root_cause_verdict: dict[str, Any]) -> dict[str, Any]:
    """The Maersk principle, now structural. `countermeasure` matches
    CountermeasureProposalEvidence's shape -- {"proposal": str,
    "resource_type": str (explicit, not inferred), "alternatives_
    considered": list of {"description", "lever_type", "why_
    insufficient", "evaluated"}, "why_alternatives_insufficient": str,
    "evidence": str}. resource_type in {"headcount", "system_or_
    infrastructure"} triggers the gate; any other resource_type
    (process/governance/supplier/specification/other) is approved
    directly, since the gate is specifically about resource/system
    investment, not about countermeasures generally."""
    proposal = (countermeasure.get("proposal") or "").strip()
    resource_type = countermeasure.get("resource_type", "other")
    is_resource_proposal = resource_type in _RESOURCE_TYPES

    if not is_resource_proposal:
        return {
            "proposal": proposal,
            "approved": True,
            "is_resource_countermeasure": False,
            "resource_type": resource_type,
            "reason": f"Not a headcount or major system/infrastructure proposal -- this kind of countermeasure doesn't need the same level of justification.",
        }

    if root_cause_verdict.get("verdict") != "supported":
        return {
            "proposal": proposal,
            "approved": False,
            "is_resource_countermeasure": True,
            "resource_type": resource_type,
            "reason": (
                "A resource/system countermeasure cannot be approved against an unvalidated root cause -- "
                "the cause behind this problem has not yet been established with real evidence."
            ),
        }

    alternatives = countermeasure.get("alternatives_considered") or []
    why_insufficient = countermeasure.get("why_alternatives_insufficient")
    evidence = countermeasure.get("evidence")

    genuinely_evaluated = [a for a in alternatives if a.get("evaluated") is True and a.get("lever_type") and a.get("lever_type") != "other"]

    missing = []
    if not genuinely_evaluated:
        missing.append("no genuine non-resource alternative (process change, specification change, governance, etc.) was shown to have been considered")
    if not why_insufficient:
        missing.append("no explanation of why those alternatives cannot solve the validated root cause")
    if not evidence:
        missing.append("no evidence supporting that conclusion")

    if missing:
        return {
            "proposal": proposal,
            "approved": False,
            "is_resource_countermeasure": True,
            "resource_type": resource_type,
            "reason": "Rejected: " + "; ".join(missing) + ". A resource/system countermeasure requires all three before it can be recommended.",
        }

    return {
        "proposal": proposal,
        "approved": True,
        "is_resource_countermeasure": True,
        "resource_type": resource_type,
        "root_cause": root_cause_verdict.get("label"),
        "alternatives_considered": [a["description"] for a in genuinely_evaluated],
        "why_alternatives_insufficient": why_insufficient,
        "evidence": evidence,
        "reason": "Approved: validated root cause, non-resource alternatives genuinely evaluated (explicit lever type, not inferred) and shown insufficient, with supporting evidence.",
    }


def build_outcome_tracking(outcome: dict[str, Any]) -> dict[str, Any]:
    """Preserves the expected/target/actual/sustained distinction --
    item 9's requirement. Accepts ProblemSolvingEvidence's key names
    directly (expected_outcome/target_outcome/actual_outcome/
    outcome_sustained) as well as the shorter aliases for direct calls.
    Anything not stated stays None, never inferred from another field."""
    expected = outcome.get("expected_outcome", outcome.get("expected"))
    target = outcome.get("target_outcome", outcome.get("target"))
    actual = outcome.get("actual_outcome", outcome.get("actual"))
    sustained = outcome.get("outcome_sustained", outcome.get("sustained"))
    return {
        "expected": expected,
        "target": target,
        "actual": actual,
        "sustained": sustained,
        "status": (
            "validated_and_sustained" if actual is not None and sustained is True else
            "validated_not_yet_sustained" if actual is not None and sustained is False else
            "actual_not_yet_measured" if actual is None and (expected is not None or target is not None) else
            "not_established"
        ),
    }


def build_problem_solving_reasoning(evidence: dict[str, Any]) -> dict[str, Any]:
    """Assembles the full reasoning chain from a ProblemSolvingEvidence-
    shaped dict: diagnosis, every root-cause candidate's verdict, every
    countermeasure's approval decision (against the STRONGEST supported
    root cause, if any), and outcome tracking. Pure assembly -- no new
    judgment beyond what the three functions above already establish."""
    diagnosis = diagnose_problem(evidence)

    root_cause_verdicts = [evaluate_root_cause_evidence(c) for c in (evidence.get("root_cause_candidates") or [])]
    supported = [v for v in root_cause_verdicts if v["verdict"] == "supported"]
    best_root_cause = supported[0] if supported else (root_cause_verdicts[0] if root_cause_verdicts else {"verdict": "insufficient_evidence_for_root_cause", "label": None})

    countermeasure_verdicts = [build_countermeasure_analysis(c, best_root_cause) for c in (evidence.get("countermeasure_proposals") or [])]

    outcome = build_outcome_tracking(evidence)

    return {
        "diagnosis": diagnosis,
        "root_cause_verdicts": root_cause_verdicts,
        "countermeasure_verdicts": countermeasure_verdicts,
        "outcome": outcome,
    }
