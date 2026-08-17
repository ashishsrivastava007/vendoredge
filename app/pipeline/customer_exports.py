"""Deterministic customer export and Bring-Your-Own-Format helpers."""
from __future__ import annotations
import csv
import io
import json
import re
from app.models import CommercialPosition

ALLOWED_TOKENS = {
    "recommendation", "financial_impact", "confidence", "why_this_wins", "decision_passport", "decision_cockpit", "commercial_truth_model",
    "opening_position", "walk_away", "disconfirming_condition", "assumptions",
    "reasoning", "evidence_integrity", "stakeholder_conflicts", "action_plan",
}
TOKEN_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def _values(p: CommercialPosition, action_plan: dict | None = None) -> dict[str, str]:
    fin = str(p.financial_impact) if p.financial_impact is not None else "Not safely calculable from supplied evidence"
    conflicts = "\n".join(f"- {x}" for x in (p.decision_audit.stakeholder_conflict if p.decision_audit else [])) or "None identified"
    evidence = p.decision_audit.evidence_integrity_status if p.decision_audit else "UNKNOWN"
    return {
        "recommendation": p.recommendation,
        "decision_passport": json.dumps(getattr(p, "decision_passport", None) or {}, indent=2),
        "decision_cockpit": json.dumps(getattr(p, "decision_cockpit", None) or {}, indent=2),
        "commercial_truth_model": json.dumps(getattr(p, "commercial_truth_model", None) or {}, indent=2),
        "financial_impact": fin,
        "confidence": p.confidence.level,
        "why_this_wins": p.why_this_wins or "Not separately stated.",
        "opening_position": p.opening_position or "Not stated.",
        "walk_away": p.walk_away_threshold or "Not stated.",
        "disconfirming_condition": p.disconfirming_condition,
        "assumptions": "\n".join(f"- {a}" for a in p.assumptions),
        "reasoning": p.reasoning,
        "evidence_integrity": evidence,
        "stakeholder_conflicts": conflicts,
        "action_plan": json.dumps(action_plan or {}, indent=2),
    }


def render_custom(p: CommercialPosition, template: str, action_plan: dict | None = None) -> dict[str, str]:
    if len(template) > 12000:
        raise ValueError("Custom template is limited to 12,000 characters.")
    tokens = TOKEN_RE.findall(template)
    unknown = sorted(set(tokens) - ALLOWED_TOKENS)
    if unknown:
        raise ValueError("Unsupported template fields: " + ", ".join(unknown))
    values = _values(p, action_plan)
    body = TOKEN_RE.sub(lambda m: values[m.group(1)], template)
    return {"format": "custom", "title": "CUSTOM DECISION FORMAT", "body": body,
            "method": "Deterministic template rendering of the validated decision; no new facts or LLM call."}


def export_csv(p: CommercialPosition) -> str:
    row = {
        "recommendation": p.recommendation,
        "confidence": p.confidence.level,
        "evidence_integrity": p.decision_audit.evidence_integrity_status if p.decision_audit else "UNKNOWN",
        "financial_impact": str(p.financial_impact) if p.financial_impact else "",
        "opening_position": p.opening_position or "",
        "walk_away": p.walk_away_threshold or "",
        "disconfirming_condition": p.disconfirming_condition,
    }
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(row))
    writer.writeheader(); writer.writerow(row)
    return out.getvalue()
