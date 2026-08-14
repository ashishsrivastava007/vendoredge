"""Deterministic decision-integrity helpers.

This module is intentionally small and conservative. It does not make the
commercial decision; it defines the boundaries within which the reasoning
model is allowed to operate.

Two jobs:
1. Build a deterministic stakeholder-handling protocol from attributed views.
2. Compute a system-owned confidence level from evidence quality and material
   stakeholder conflict. The LLM may explain the confidence, but it does not
   own the final level.
"""
from __future__ import annotations

import re

from app.pipeline.normalized_evidence import NormalizedEvidence

_LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}


def _min_level(a: str, b: str) -> str:
    return a if _LEVEL_RANK[a] <= _LEVEL_RANK[b] else b


def _stakeholder_mentions_supplier(statement: str, supplier_names: list[str]) -> set[str]:
    lowered = statement.lower()
    found: set[str] = set()
    for name in supplier_names:
        first = name.split()[0].lower() if name else ""
        if name.lower() in lowered or (len(first) >= 4 and re.search(rf"\b{re.escape(first)}\b", lowered)):
            found.add(name)
    return found


def stakeholder_conflict_summary(normalized: NormalizedEvidence) -> tuple[bool, list[str]]:
    """Return whether stakeholder views contain a material, supplier-choice conflict.

    This deliberately detects only the high-signal case where different
    stakeholders express competing supplier choices. It does not pretend to
    understand arbitrary natural-language disagreement deterministically.
    """
    suppliers = [s.supplier_name for s in normalized.suppliers if s.supplier_name]
    choice_views = []
    for view in normalized.stakeholder_views:
        if view.view_type not in {"preference", "recommendation", "constraint", "risk_concern"}:
            continue
        mentioned = _stakeholder_mentions_supplier(view.statement, suppliers)
        if mentioned:
            choice_views.append((view.stakeholder_name, mentioned, view.view_type))

    conflicts: list[str] = []
    for i, (name_a, suppliers_a, type_a) in enumerate(choice_views):
        for name_b, suppliers_b, type_b in choice_views[i + 1 :]:
            if name_a == name_b or suppliers_a == suppliers_b:
                continue
            if suppliers_a.isdisjoint(suppliers_b):
                conflicts.append(
                    f"{name_a} ({type_a}) favors/flags {', '.join(sorted(suppliers_a))} while "
                    f"{name_b} ({type_b}) favors/flags {', '.join(sorted(suppliers_b))}"
                )
    return bool(conflicts), conflicts


def build_stakeholder_decision_protocol(normalized: NormalizedEvidence) -> str:
    """Build a short deterministic protocol for the reasoning model."""
    if not normalized.stakeholder_views:
        return "No stakeholder views were explicitly supplied. Do not invent stakeholder preferences."

    conflict, details = stakeholder_conflict_summary(normalized)
    lines = [
        "STAKEHOLDER DECISION PROTOCOL (system rule):",
        "- Objective statements are evidence candidates, but still require the same factual discipline as other evidence.",
        "- Preferences and recommendations are decision inputs, not objective facts; use them to understand priorities, not to manufacture supplier superiority.",
        "- Risk concerns and experience reports are signals. If they materially affect the recommendation, state them and identify what should be validated.",
        "- A constraint is hard only when the evidence identifies a genuine policy, contractual, regulatory, safety, or explicit operational constraint. Do not promote a preference into a hard constraint.",
        "- Rumors and insider information are NEVER verified facts. Preserve the attribution and recommend validation when material.",
        "- Never average conflicting stakeholder views into a fake consensus. Explain what each party is optimizing for and how the recommendation balances those interests.",
    ]
    if conflict:
        lines.append("- MATERIAL STAKEHOLDER CONFLICT DETECTED: " + " | ".join(details))
        lines.append("- Because the conflict is material, do not present one stakeholder's preference as the organization's settled position.")
    return "\n".join(lines)


def compute_pre_reasoning_confidence(normalized: NormalizedEvidence) -> tuple[str, list[str]]:
    """Compute the evidence-only confidence ceiling BEFORE the LLM reasons.

    This is deliberately independent of the model's prose. A recommendation
    can become more specific later, but evidence that is already incomplete or
    materially conflicted cannot become complete merely because the model is
    eloquent.
    """
    level = "high"
    reasons: list[str] = []

    if normalized.content_type == "price_increase":
        if normalized.derived.resolved_annual_spend_usd is None:
            level = _min_level(level, "medium")
            reasons.append("annual spend is not deterministically resolved")

    load_bearing = {
        "price_increase": {"current_price_or_terms", "requested_increase_percent", "suppliers_stated_justification", "annual_spend_usd"},
        "quote_comparison": {"price_per_supplier", "number_of_suppliers_being_compared"},
    }.get(normalized.content_type, set())
    conflicts = [f for f, p in normalized.provenance.items() if p.conflicting and f in load_bearing]
    if conflicts:
        level = _min_level(level, "medium")
        reasons.append("unresolved extraction conflict on " + ", ".join(conflicts))

    # Alternative-supplier qualification is deliberately NOT used here. Before
    # reasoning, the system cannot know whether the final recommendation will
    # actually rely on that supplier. The post-reasoning gate makes that
    # recommendation-specific decision. This prevents the pre-pass from being
    # needlessly conservative while keeping the final confidence deterministic.

    fallback_only = [f for f in load_bearing if normalized.provenance.get(f) and normalized.provenance[f].source == "deterministic_fallback"]
    present = [f for f in load_bearing if f in normalized.provenance]
    if present and len(fallback_only) / len(present) > 0.5:
        level = _min_level(level, "medium")
        reasons.append("a majority of load-bearing evidence came only from deterministic fallback extraction")

    conflict, _ = stakeholder_conflict_summary(normalized)
    if conflict:
        level = _min_level(level, "medium")
        reasons.append("material stakeholder views point toward different supplier choices")

    return level, reasons
