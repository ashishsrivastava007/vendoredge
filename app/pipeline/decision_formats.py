"""Release 14: deterministic customer-native decision formats."""
from __future__ import annotations
from app.models import CommercialPosition
FORMATS=("decision_cockpit","cfo_brief","category_review","supplier_meeting","one_page","executive_60_second")
def render_decision(p: CommercialPosition, format_name: str)->dict[str,str]:
    if format_name not in FORMATS: raise ValueError(f"Unsupported format: {format_name}")
    fin = str(p.financial_impact) if p.financial_impact is not None else "Not safely calculable from supplied evidence"
    cockpit = getattr(p, "decision_cockpit", None) or {}
    why=p.why_this_wins or "Not separately stated."
    if format_name=="decision_cockpit":
        title="VENDOREDGE COMMERCIAL DECISION COCKPIT"
        econ=(cockpit.get("economics") or {}).get("headline", "Not safely quantified")
        why="\n".join(f"- {x}" for x in (cockpit.get("why") or [])[:3]) or "- No concise reason resolved."
        blockers="\n".join(f"- {x}" for x in (cockpit.get("blockers") or [])[:3]) or "- None identified."
        changers="\n".join(f"- {x}" for x in (cockpit.get("decision_changers") or [])[:3]) or "- None stated."
        body=(f"VERDICT\n{cockpit.get('verdict', p.recommendation)}\n\n"
              f"STATUS / CONFIDENCE\n{cockpit.get('readiness','CONDITIONAL')} / {p.confidence.level.upper()}\n\n"
              f"ECONOMICS\n{econ}\n\nWHY\n{why}\n\n"
              f"BEFORE ACTION\n{blockers}\n\nNEXT MOVE\n{cockpit.get('next_move','Review the evidence before acting.')}\n\n"
              f"WHAT CHANGES IT\n{changers}")
    elif format_name=="cfo_brief":
        title="CFO BRIEF"; body=f"DECISION\n{p.recommendation}\n\nFINANCIAL IMPACT\n{fin}\n\nCONFIDENCE\n{p.confidence.level}\n\nWHY\n{why}\n\nDECISION CHANGER\n{p.disconfirming_condition}"
    elif format_name=="category_review":
        title="CATEGORY REVIEW"; body=f"RECOMMENDATION\n{p.recommendation}\n\nCOMMERCIAL RATIONALE\n{why}\n\nOPENING POSITION\n{p.opening_position or 'Not stated.'}\n\nWALK-AWAY\n{p.walk_away_threshold or 'Not stated.'}\n\nASSUMPTIONS\n"+"\n".join(f"- {a}" for a in p.assumptions)
    elif format_name=="supplier_meeting":
        title="SUPPLIER MEETING BRIEF"; dims=(p.negotiation_playbook.dimensions if p.negotiation_playbook else [])
        body=f"OBJECTIVE\n{p.recommendation}\n\nOPENING\n{p.opening_position or 'Not stated.'}\n\nTARGET / WALK-AWAY\n"+"\n".join(f"- {d.get('dimension')}: target={d.get('target')}; walk-away={d.get('walk_away')}" for d in dims[:6])
    elif format_name=="one_page":
        title="VENDOREDGE ONE-PAGE DECISION"; body=f"RECOMMENDATION: {p.recommendation}\nCONFIDENCE: {p.confidence.level}\nFINANCIAL: {fin}\nWHY: {why}\nDECISION CHANGER: {p.disconfirming_condition}"
    else:
        passport = getattr(p, "decision_passport", None) or {}
        econ = passport.get("economics", {}) if isinstance(passport, dict) else {}
        title="VENDOREDGE 60-SECOND DECISION"
        body=(f"DECISION\n{p.recommendation}\n\nSTATUS / CONFIDENCE\n{passport.get('readiness','CONDITIONAL')} / {p.confidence.level.upper()}\n\nECONOMICS\n{econ.get('headline','Not safely quantified')}\n\nWHY\n" + "\n".join(f"- {x}" for x in (passport.get("why") or [])[:3]) + "\n\nNEXT MOVE\n" + str(passport.get("next_move") or "Review evidence before acting.") + "\n\nWHAT CHANGES IT\n" + "\n".join(f"- {x}" for x in (passport.get("decision_changers") or [])[:2]))
    return {"format":format_name,"title":title,"body":body,"method":"Deterministic rendering of the validated decision; no new facts, assumptions or LLM call."}
