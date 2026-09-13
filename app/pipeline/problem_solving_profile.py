"""
Phase 7 -- Complex Problem Solving reasoning profile.

Buyer-facing structure, per explicit instruction: Problem -> What we
know -> What is likely -> What still needs checking -> Recommendation
-> Next action. No A3/Lean/methodology terminology exposed unless
genuinely useful; no internal key/object names in any prose value.

Reuses problem_solving.py's reasoning core (diagnose_problem,
evaluate_root_cause_evidence, build_countermeasure_analysis,
build_outcome_tracking) -- this module only builds prompt context and
curates the buyer-facing view from that core's output, never
recomputes any of it.
"""
from __future__ import annotations
from typing import Any

from app.pipeline.problem_solving import build_problem_solving_reasoning

PROBLEM_SOLVING_REASONING_SEQUENCE = """You are helping diagnose and solve a real procurement/operational problem. Work through these questions in order, using ONLY the evidence below for anything it already states.

1. What is the problem, current condition, desired condition, and impact -- exactly as stated, nothing invented?
2. What do we know (evidence-backed facts)?
3. What is likely (a reasoned inference from the evidence, clearly labelled as inference, never stated as fact)?
4. What still needs checking (a genuine unknown that could change the diagnosis or recommendation)?
5. What is the validated root cause, if one exists yet -- and if not, say so plainly rather than guessing?
6. What countermeasure is justified by the evidence?

Hard rules, never break these:
- A generic-sounding cause ("supplier issue", "operator error", "system problem") is not automatically wrong -- but it is never accepted as a validated root cause without independent supporting evidence. If none exists, say the cause is not yet established, not "probably X".
- An OEM's or supplier's own claim about what's wrong is a claim, not independent evidence -- never present it as a settled fact.
- Never default to recommending additional headcount, a new organizational layer, new software, or major system/infrastructure investment. Before recommending any of those, you must show: the validated root cause, which non-resource alternatives (process change, specification change, governance, sequencing, existing-system use, supplier change, and for equipment: alternate component, refurbish, defer with mitigation) were genuinely considered, why they are insufficient, and the evidence supporting that. Absent that structure, the correct answer is a non-resource countermeasure or "insufficient evidence yet for a resource-level recommendation" -- not a default assumption that more people or a new system is needed.
- Keep expected, target, actual, and sustained results explicitly separate. Never present an expected or target figure as if it were an achieved, measured result.
- Ask the user for at most one missing fact -- whichever single fact would most change the diagnosis or recommendation. Do not present a list of questions.
- Simple English. No AI/framework jargon. No unnecessary section the evidence doesn't support.
"""


def build_problem_solving_prompt_addition(kernel: dict[str, Any]) -> str:
    """Added to the reasoning prompt only when the case actually is a
    problem-solving case -- silently omitted otherwise."""
    evidence = kernel.get("case", {}).get("problem_solving_evidence") if isinstance(kernel.get("case"), dict) else None
    if not evidence:
        return ""
    lines = ["PROBLEM-SOLVING EVIDENCE STATED IN THIS CASE:", ""]
    if evidence.get("problem_statement"):
        lines.append(f"Problem: {evidence['problem_statement']}")
    if evidence.get("current_condition"):
        lines.append(f"Current condition: {evidence['current_condition']}")
    if evidence.get("desired_condition"):
        lines.append(f"Desired condition: {evidence['desired_condition']}")
    if evidence.get("stated_impact"):
        lines.append(f"Stated impact: {evidence['stated_impact']}")
    if evidence.get("root_cause_candidates"):
        lines.append("")
        lines.append("Candidate root causes stated in the case (evidence status shown, never treat an unevidenced one as validated):")
        for c in evidence["root_cause_candidates"]:
            ev = f" -- supporting evidence: {'; '.join(c['supporting_evidence'])}" if c.get("supporting_evidence") else " -- NO supporting evidence stated"
            src = f" (source: {c['source']})" if c.get("source") and c["source"] != "unspecified" else ""
            lines.append(f"  - \"{c['label']}\"{src}{ev}")
    if evidence.get("countermeasure_proposals"):
        lines.append("")
        lines.append("Countermeasures proposed in the case:")
        for cm in evidence["countermeasure_proposals"]:
            lines.append(f"  - {cm['proposal']} (resource_type: {cm.get('resource_type', 'other')})")
    for k, label in (("expected_outcome", "Expected"), ("target_outcome", "Target"), ("actual_outcome", "Actual")):
        if evidence.get(k):
            lines.append(f"{label} outcome: {evidence[k]}")
    if evidence.get("outcome_sustained") is not None:
        lines.append(f"Sustained: {evidence['outcome_sustained']}")
    lines.append("")
    return "\n\n" + PROBLEM_SOLVING_REASONING_SEQUENCE + "\n" + "\n".join(lines)


def build_problem_solving_answer(kernel: dict[str, Any], position: Any) -> dict[str, Any] | None:
    """Buyer-facing answer: Problem -> What we know -> What is likely ->
    What still needs checking -> Recommendation -> Next action. Built
    from problem_solving.py's reasoning core, never recomputed here.
    Returns None if this isn't genuinely a problem-solving case."""
    evidence = kernel.get("case", {}).get("problem_solving_evidence") if isinstance(kernel.get("case"), dict) else None
    if not evidence:
        return None

    reasoning = build_problem_solving_reasoning(evidence)
    diagnosis = reasoning["diagnosis"]
    root_cause_verdicts = reasoning["root_cause_verdicts"]
    countermeasure_verdicts = reasoning["countermeasure_verdicts"]
    outcome = reasoning["outcome"]

    what_we_know = []
    if diagnosis.get("current_condition"):
        what_we_know.append(f"Current: {diagnosis['current_condition']}")
    if diagnosis.get("desired_condition"):
        what_we_know.append(f"Desired: {diagnosis['desired_condition']}")
    if diagnosis.get("impact"):
        what_we_know.append(f"Impact: {diagnosis['impact']}")
    for v in root_cause_verdicts:
        if v["verdict"] == "supported":
            what_we_know.append(f"\"{v['label']}\" is supported by the evidence provided.")

    what_is_likely = []
    what_still_needs_checking = []
    for v in root_cause_verdicts:
        if v["verdict"] == "insufficient_evidence_for_root_cause":
            what_is_likely.append(f"\"{v['label']}\" may be a factor, but this is not yet established as the validated cause.")
            what_still_needs_checking.append(v.get("what_would_establish_this") or f"Evidence connecting \"{v['label']}\" to the problem.")
    if diagnosis.get("gap_evidence_state") == "UNKNOWN":
        what_still_needs_checking.append("What's happening now, and what should be happening instead -- the gap isn't measurable yet.")

    recommendation = []
    next_action = []
    for cm in countermeasure_verdicts:
        if cm["approved"]:
            recommendation.append(cm["proposal"])
        else:
            next_action.append(f"Not yet recommended: \"{cm['proposal']}\" -- {cm['reason']}")
    if not recommendation and not next_action:
        if any(v["verdict"] == "insufficient_evidence_for_root_cause" for v in root_cause_verdicts) or not root_cause_verdicts:
            next_action.append("Establish the root cause first -- no countermeasure can be responsibly recommended yet.")

    result = {
        "problem": diagnosis.get("problem"),
        "what_we_know": what_we_know[:6],
        "what_is_likely": what_is_likely[:4],
        "what_still_needs_checking": what_still_needs_checking[:4],
        "recommendation": recommendation[:3],
        "next_action": next_action[:3],
    }
    if outcome["status"] != "not_established":
        result["progress"] = {
            "expected": outcome["expected"],
            "target": outcome["target"],
            "actual": outcome["actual"],
            "sustained": outcome["sustained"],
        }
    return result
