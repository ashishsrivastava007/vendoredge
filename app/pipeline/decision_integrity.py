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


def _supplier_aliases(name: str) -> set[str]:
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    aliases = {name.lower().strip()}
    if parts:
        aliases.add(parts[0].lower())
    # Preserve common legal-name forms while avoiding unsafe one-letter aliases.
    if len(parts) >= 2 and len(parts[0]) >= 4:
        aliases.add(" ".join(parts[:2]).lower())
    return aliases


def _stakeholder_supplier_stance(statement: str, supplier_names: list[str]) -> dict[str, str]:
    """Extract only explicit directional supplier choices from a stakeholder view.

    This is intentionally conservative. Mere mention of two suppliers is NOT a
    conflict. We look for preference/recommendation verbs and simple comparative
    constructions such as 'safer than'. Anything ambiguous remains unclassified.
    """
    text = statement.lower()
    stances: dict[str, str] = {}
    for name in supplier_names:
        aliases = sorted(_supplier_aliases(name), key=len, reverse=True)
        if not any(re.search(rf"\b{re.escape(a)}\b", text) for a in aliases):
            continue
        label = name
        escaped = "(?:" + "|".join(re.escape(a) for a in aliases) + ")"
        if re.search(rf"(?:prefers?|recommend(?:s|ed)?|favors?|supports?|select(?:s|ed)?|wants?|chooses?)\s+{escaped}", text):
            stances[label] = "positive"
        elif re.search(rf"{escaped}\s+(?:is|seems|looks)\s+(?:safer|better|stronger|more reliable|preferred)", text):
            stances[label] = "positive"
        elif re.search(rf"{escaped}\s+(?:is|seems|looks)\s+(?:riskier|worse|weaker|less reliable|not preferred)", text):
            stances[label] = "negative"
        elif re.search(rf"(?:avoid|reject|exclude|oppose|do not choose|does not prefer)\s+{escaped}", text):
            stances[label] = "negative"

    # Comparative forms: 'A is safer than B' => A positive, B negative.
    for a_name in supplier_names:
        a_aliases = sorted(_supplier_aliases(a_name), key=len, reverse=True)
        for b_name in supplier_names:
            if a_name == b_name:
                continue
            b_aliases = sorted(_supplier_aliases(b_name), key=len, reverse=True)
            a = "(?:" + "|".join(re.escape(x) for x in a_aliases) + ")"
            b = "(?:" + "|".join(re.escape(x) for x in b_aliases) + ")"
            if re.search(rf"{a}\s+(?:is|seems|looks)\s+(?:safer|better|stronger|more reliable|preferred)\s+than\s+{b}", text):
                stances[a_name] = "positive"
                stances[b_name] = "negative"
    return stances


def stakeholder_conflict_summary(normalized: NormalizedEvidence) -> tuple[bool, list[str]]:
    """Return material supplier-choice conflicts only when direction is explicit.

    A statement mentioning two suppliers is not itself a conflict. The prior
    implementation treated any two names in disjoint stakeholder statements as
    competing preferences, which could invert a statement such as 'NordValve is
    safer than EuroMotion' when all three names were present.
    """
    suppliers = [s.supplier_name for s in normalized.suppliers if s.supplier_name]
    choice_views = []
    for view in normalized.stakeholder_views:
        if view.view_type not in {"preference", "recommendation", "constraint", "risk_concern", "experience"}:
            continue
        stances = _stakeholder_supplier_stance(view.statement, suppliers)
        if stances:
            choice_views.append((view.stakeholder_name, stances, view.view_type))

    conflicts: list[str] = []
    for i, (name_a, stances_a, type_a) in enumerate(choice_views):
        for name_b, stances_b, type_b in choice_views[i + 1:]:
            if name_a == name_b:
                continue
            positives_a = {s for s, stance in stances_a.items() if stance == "positive"}
            positives_b = {s for s, stance in stances_b.items() if stance == "positive"}
            if positives_a and positives_b and positives_a.isdisjoint(positives_b):
                conflicts.append(
                    f"{name_a} ({type_a}) favors {', '.join(sorted(positives_a))} while "
                    f"{name_b} ({type_b}) favors {', '.join(sorted(positives_b))}"
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
