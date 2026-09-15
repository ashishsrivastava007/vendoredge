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


def _build_options(evidence: dict[str, Any], countermeasure_verdicts: list[dict[str, Any]], root_cause_supported: bool) -> list[dict[str, Any]]:
    """Builds the OPTIONS section from the case's own countermeasure
    proposals and their genuinely-considered alternatives -- never
    invents an option the case didn't raise, and never claims an
    option's economic advantage that wasn't stated. Every status
    string here is fixed template text keyed off a real field
    (approved/evaluated/why_insufficient), never free text that could
    smuggle in an unproven claim."""
    options: list[dict[str, Any]] = []
    seen = set()

    def _add(label: str, status: str):
        key = label.strip().lower()
        if key in seen:
            return
        seen.add(key)
        options.append({"option": label, "status": status})

    proposals = evidence.get("countermeasure_proposals") or []
    for proposal, verdict in zip(proposals, countermeasure_verdicts):
        alternatives = proposal.get("alternatives_considered") or []
        for alt in alternatives:
            desc = alt.get("description")
            if not desc:
                continue
            why = alt.get("why_insufficient")
            if why:
                _add(desc, f"Evaluated -- {why}")
            else:
                _add(desc, "An option to evaluate; its advantage over the alternatives is not yet established.")
        # The main proposal itself is also an option, not an assumed answer.
        main = proposal.get("proposal")
        if main:
            if verdict.get("approved"):
                _add(main, "Recommended, based on the evidence provided.")
            else:
                _add(main, "Not yet justified -- the evidence needed to approve this isn't in place.")

    if not root_cause_supported:
        _add("Further investigation", "Needed before any option above can be responsibly chosen.")

    return options[:6]


def _oem_conflict_note(evidence: dict[str, Any]) -> str | None:
    """Deterministic, fixed-wording safety rule: when a root-cause
    candidate's source is the OEM/supplier itself, and a system-or-
    infrastructure countermeasure is on the table, this states the
    plain structural fact -- the same party diagnosing the problem
    also supplies the fix -- without claiming a motive the case never
    proved. This exact sentence is the only thing ever shown for this
    situation; it is never model-generated."""
    candidates = evidence.get("root_cause_candidates") or []
    proposals = evidence.get("countermeasure_proposals") or []
    oem_sourced = any(c.get("source") == "oem_or_supplier" for c in candidates)
    resource_proposal = any(p.get("resource_type") == "system_or_infrastructure" for p in proposals)
    if oem_sourced and resource_proposal:
        return "The OEM's recommendation should be independently validated, since the OEM also supplies the replacement."
    return None


def build_problem_solving_answer(kernel: dict[str, Any], position: Any) -> dict[str, Any] | None:
    """Buyer-facing answer, restructured to fit the problem, not a
    generic commercial template: WHAT'S HAPPENING -> WHAT WE KNOW ->
    WHAT WE DON'T KNOW YET -> OPTIONS -> MY RECOMMENDATION -> NEXT STEP
    -> WHAT COULD CHANGE THIS. Built entirely from problem_solving.py's
    reasoning core; no new judgment is added here, only composition.
    Returns None if this isn't genuinely a problem-solving case."""
    evidence = kernel.get("case", {}).get("problem_solving_evidence") if isinstance(kernel.get("case"), dict) else None
    if not evidence:
        return None

    reasoning = build_problem_solving_reasoning(evidence)
    diagnosis = reasoning["diagnosis"]
    root_cause_verdicts = reasoning["root_cause_verdicts"]
    countermeasure_verdicts = reasoning["countermeasure_verdicts"]
    outcome = reasoning["outcome"]
    root_cause_supported = any(v["verdict"] == "supported" for v in root_cause_verdicts)

    whats_happening = diagnosis.get("problem")

    what_we_know = []
    if diagnosis.get("current_condition"):
        what_we_know.append(diagnosis["current_condition"])
    if diagnosis.get("desired_condition"):
        what_we_know.append(f"Target: {diagnosis['desired_condition']}")
    if diagnosis.get("impact"):
        what_we_know.append(diagnosis["impact"])
    for v in root_cause_verdicts:
        if v["verdict"] == "supported":
            what_we_know.append(f"{v['label'].capitalize()} is supported by the evidence provided.")

    what_we_dont_know_yet = []
    for v in root_cause_verdicts:
        if v["verdict"] == "insufficient_evidence_for_root_cause":
            what_we_dont_know_yet.append(v.get("what_would_establish_this") or f"Evidence connecting \"{v['label']}\" to the problem.")
    if diagnosis.get("gap_evidence_state") == "UNKNOWN":
        what_we_dont_know_yet.append("What's happening now, and what should be happening instead.")

    options = _build_options(evidence, countermeasure_verdicts, root_cause_supported)

    approved = [cm for cm in countermeasure_verdicts if cm["approved"]]
    if approved:
        my_recommendation = approved[0]["proposal"]
        next_step = "Proceed with this, and monitor whether it holds."
    elif not root_cause_supported:
        my_recommendation = "Do not approve a resource-level fix yet. First establish the root cause with independent evidence."
        next_step = "Conduct an independent assessment to establish the cause before committing to any of the options above."
    else:
        rejected = next((cm for cm in countermeasure_verdicts if not cm["approved"]), None)
        root_cause_label = next((v["label"] for v in root_cause_verdicts if v["verdict"] == "supported"), None)
        if root_cause_label and rejected:
            my_recommendation = f"Address the root cause directly -- {root_cause_label} -- before considering {rejected['proposal'].rstrip('.')}."
            next_step = f"Fix {root_cause_label} first, then reassess whether {rejected['proposal'].rstrip('.')} is still needed."
        else:
            my_recommendation = "The proposed fix is not yet justified by the evidence available."
            next_step = rejected["reason"] if rejected else "Evaluate the alternatives before committing to a resource-level fix."

    what_could_change_this = list(what_we_dont_know_yet)
    oem_note = _oem_conflict_note(evidence)
    if oem_note:
        what_could_change_this.append(oem_note)

    result = {
        "whats_happening": whats_happening,
        "what_we_know": what_we_know[:6],
        "what_we_dont_know_yet": what_we_dont_know_yet[:5],
        "options": options,
        "my_recommendation": my_recommendation,
        "next_step": next_step,
        "what_could_change_this": what_could_change_this[:5],
    }
    if outcome["status"] != "not_established":
        result["progress"] = {
            "expected": outcome["expected"],
            "target": outcome["target"],
            "actual": outcome["actual"],
            "sustained": outcome["sustained"],
        }
    return result

