import sys, json; sys.path.insert(0, ".")
from app.pipeline.normalize import normalize_evidence
from app.pipeline.kernel import build_kernel
from app.pipeline.decision_audit import build_decision_audit
from app.pipeline.problem_solving_profile import build_problem_solving_answer
from app.models import CommercialPosition, Confidence, ConfidenceFactor, DecisionAudit

conf = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")

extracted = {
    "problem_statement": "OEM says the control system on our 15-year-old press is obsolete and wants us to replace the whole machine.",
    "current_condition": "15 years old; four breakdowns in the last 12 months; maintenance cost has increased; critical spares are harder to obtain.",
    "desired_condition": "Reliable, economically viable operation without unplanned downtime risk.",
    "root_cause_candidates": [{"label": "control system obsolete, entire machine no longer viable", "category": "root_cause", "source": "oem_or_supplier", "supporting_evidence": []}],
    "countermeasure_proposals": [{
        "proposal": "Replace the entire machine.",
        "resource_type": "system_or_infrastructure",
        "alternatives_considered": [
            {"description": "Retrofit the control system only", "lever_type": "process_change", "evaluated": True},
            {"description": "Alternate/third-party control component", "lever_type": "alternate_component", "evaluated": True},
            {"description": "Refurbish the existing controls", "lever_type": "refurbish", "evaluated": True},
            {"description": "Defer with risk mitigation", "lever_type": "defer_with_mitigation", "evaluated": True},
        ],
    }],
}
ne, warnings = normalize_evidence("15-year-old press obsolescence.", "problem_solving", extracted, {})
pos = CommercialPosition(recommendation="x", commercial_insights=["a"], reasoning="x", confidence=conf, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
pos.decision_audit = DecisionAudit(**build_decision_audit(ne, pos))
kernel = build_kernel(ne, pos).model_dump()

answer = build_problem_solving_answer(kernel, pos)
print(json.dumps(answer, indent=2))

full_text = json.dumps(answer).lower()
assert "sales position" not in full_text and "dressed as" not in full_text
assert "probably the cheapest" not in full_text and "lowest-cost" not in full_text
assert "independently validated" in full_text and "also supplies" in full_text
assert "do not approve" in answer["my_recommendation"].lower()
print()
print("PASS: no invented motive, no invented economics, correct 'do not approve yet' recommendation, OEM conflict-of-interest note present")
