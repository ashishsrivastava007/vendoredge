"""
Phase 7 -- Complex Problem Solving reasoning core, structured-evidence
version. Three required proof cases plus adversarial tests for the two
hard disciplines, now reading explicit fields (supporting_evidence,
resource_type, lever_type) rather than keyword-matching free text.
"""
from app.pipeline.problem_solving import (
    diagnose_problem, evaluate_root_cause_evidence, build_countermeasure_analysis,
    build_outcome_tracking, build_problem_solving_reasoning,
)


# ---------------------------------------------------------------------
# Proof case 1: supplier/commercial problem
# ---------------------------------------------------------------------

def test_case1_gap_computed_only_from_stated_conditions():
    diag = diagnose_problem({
        "problem_statement": "On-time delivery from Supplier A has declined.",
        "current_condition": "OTIF 82% over the last 3 months.",
        "desired_condition": "OTIF 97%, the contracted target.",
        "stated_impact": "Two production line stoppages in the last quarter.",
    })
    assert diag["gap"] is not None
    assert diag["gap_evidence_state"] == "VERIFIED"


def test_case1_label_with_no_evidence_is_insufficient_regardless_of_wording():
    rc = evaluate_root_cause_evidence({"label": "supplier issue", "category": "root_cause"})
    assert rc["verdict"] == "insufficient_evidence_for_root_cause"
    assert rc["actual_category"] == "symptom"


def test_case1_same_label_with_real_evidence_is_supported():
    rc = evaluate_root_cause_evidence({
        "label": "supplier issue", "category": "root_cause",
        "supporting_evidence": ["Supplier A's own shipment logs show a consolidation-point change coinciding with the OTIF decline."],
    })
    assert rc["verdict"] == "supported"


def test_case1_headcount_countermeasure_with_no_alternatives_rejected():
    rc = evaluate_root_cause_evidence({"label": "x", "supporting_evidence": ["y"]})
    cm = build_countermeasure_analysis({"proposal": "Hire additional staff to expedite shipments manually.", "resource_type": "headcount"}, rc)
    assert cm["approved"] is False
    assert cm["is_resource_countermeasure"] is True


def test_case1_process_change_not_subject_to_resource_gate():
    rc = evaluate_root_cause_evidence({"label": "x", "supporting_evidence": ["y"]})
    cm = build_countermeasure_analysis({"proposal": "Change the consolidation point requirement in the contract.", "resource_type": "process"}, rc)
    assert cm["approved"] is True
    assert cm["is_resource_countermeasure"] is False


def test_case1_differently_phrased_resource_proposal_still_caught_by_explicit_field():
    """The exact fix requested: a proposal phrased in a way no keyword
    list would catch is still correctly gated, because the gate reads
    the explicit resource_type field, not the proposal's wording."""
    rc = evaluate_root_cause_evidence({"label": "x", "supporting_evidence": ["y"]})
    cm = build_countermeasure_analysis({"proposal": "Bring on board a couple more people to handle the exceptions manually going forward.", "resource_type": "headcount"}, rc)
    assert cm["approved"] is False


# ---------------------------------------------------------------------
# Proof case 2: procurement/process problem
# ---------------------------------------------------------------------

def test_case2_system_countermeasure_with_genuine_structure_approved():
    rc = evaluate_root_cause_evidence({"label": "x", "supporting_evidence": ["y"]})
    cm = build_countermeasure_analysis({
        "proposal": "Add a new approval system to auto-route POs.",
        "resource_type": "system_or_infrastructure",
        "alternatives_considered": [
            {"description": "Standardise sign-off to a single approver for low-risk POs", "lever_type": "governance", "evaluated": True},
            {"description": "Redesign the routing sequence to run sign-offs in parallel", "lever_type": "process_change", "evaluated": True},
        ],
        "why_alternatives_insufficient": "A 4-week trial of parallel routing cut cycle time to 6 days, not the required 3.",
        "evidence": "Trial data on file.",
    }, rc)
    assert cm["approved"] is True


def test_case2_same_proposal_with_unevaluated_alternatives_rejected():
    rc = evaluate_root_cause_evidence({"label": "x", "supporting_evidence": ["y"]})
    cm = build_countermeasure_analysis({
        "proposal": "Add a new approval system to auto-route POs.",
        "resource_type": "system_or_infrastructure",
        "alternatives_considered": [{"description": "thought about it", "lever_type": "other", "evaluated": False}],
    }, rc)
    assert cm["approved"] is False


def test_case2_expected_never_becomes_actual():
    outcome = build_outcome_tracking({"expected_outcome": "Cycle time under 4 days within 60 days of rollout.", "target_outcome": "3 business days"})
    assert outcome["actual"] is None
    assert outcome["status"] == "actual_not_yet_measured"


# ---------------------------------------------------------------------
# Proof case 3: asset/obsolescence problem
# ---------------------------------------------------------------------

def test_case3_oem_claim_with_no_independent_evidence_not_auto_accepted():
    rc = evaluate_root_cause_evidence({"label": "control system obsolete", "category": "root_cause", "source": "oem_or_supplier", "supporting_evidence": []})
    assert rc["verdict"] == "insufficient_evidence_for_root_cause"
    assert "OEM" in rc["reason"] or "not independent evidence" in rc["reason"]


def test_case3_replacement_against_unvalidated_cause_rejected():
    cm = build_countermeasure_analysis(
        {"proposal": "Follow the OEM recommendation: full control system replacement.", "resource_type": "system_or_infrastructure"},
        {"verdict": "insufficient_evidence_for_root_cause"},
    )
    assert cm["approved"] is False


def test_case3_replacement_approved_only_with_genuine_alternative_evaluation():
    rc = evaluate_root_cause_evidence({
        "label": "control board obsolete", "category": "root_cause", "source": "internal_data",
        "supporting_evidence": ["Procurement's independent parts search confirms zero production runs on the control board in 4 years; no third-party equivalent identified."],
    })
    cm = build_countermeasure_analysis({
        "proposal": "Invest in new infrastructure: full control system and press replacement.",
        "resource_type": "system_or_infrastructure",
        "alternatives_considered": [
            {"description": "Alternate/third-party equivalent control board", "lever_type": "alternate_component", "why_insufficient": "None identified as compatible", "evaluated": True},
            {"description": "Refurbish using remaining spare stock", "lever_type": "refurbish", "why_insufficient": "Stock confirmed at zero", "evaluated": True},
            {"description": "Defer with mitigation", "lever_type": "defer_with_mitigation", "why_insufficient": "Unmitigated safety-relevant single point of failure", "evaluated": True},
        ],
        "why_alternatives_insufficient": "No compatible alternate component exists, refurbishment stock is exhausted, and deferment leaves an unmitigated safety-relevant single point of failure.",
        "evidence": "Procurement's independent parts search and maintenance's spare-stock count both confirm this, independently of the OEM.",
    }, rc)
    assert cm["approved"] is True


# ---------------------------------------------------------------------
# Adversarial: outcome tracking never fabricates or conflates
# ---------------------------------------------------------------------

def test_no_evidence_produces_not_established_never_a_guess():
    outcome = build_outcome_tracking({})
    assert outcome["status"] == "not_established"
    assert outcome["actual"] is None


def test_temporary_improvement_never_labeled_sustained():
    outcome = build_outcome_tracking({"actual_outcome": "Cycle time dropped to 5 days for the first month", "outcome_sustained": False})
    assert outcome["status"] == "validated_not_yet_sustained"


def test_partial_countermeasure_structure_still_rejected():
    cm = build_countermeasure_analysis(
        {"proposal": "Hire additional staff.", "resource_type": "headcount", "alternatives_considered": [{"description": "Redesign the process", "lever_type": "process_change", "evaluated": True}]},
        {"verdict": "supported", "label": "x"},
    )
    assert cm["approved"] is False


# ---------------------------------------------------------------------
# Full reasoning-chain assembly
# ---------------------------------------------------------------------

def test_build_problem_solving_reasoning_assembles_full_chain():
    evidence = {
        "problem_statement": "On-time delivery from Supplier A has declined.",
        "current_condition": "OTIF 82%.", "desired_condition": "OTIF 97%.",
        "stated_impact": "Two line stoppages.",
        "root_cause_candidates": [{"label": "supplier issue", "category": "root_cause", "supporting_evidence": ["Shipment logs show a consolidation-point change."]}],
        "countermeasure_proposals": [{"proposal": "Change the consolidation point requirement.", "resource_type": "process"}],
    }
    result = build_problem_solving_reasoning(evidence)
    assert result["diagnosis"]["gap"] is not None
    assert result["root_cause_verdicts"][0]["verdict"] == "supported"
    assert result["countermeasure_verdicts"][0]["approved"] is True
