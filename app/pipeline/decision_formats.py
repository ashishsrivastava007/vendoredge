"""Release 14: deterministic customer-native decision formats."""
from __future__ import annotations
from app.models import CommercialPosition
FORMATS=("cfo_brief","category_review","supplier_meeting","one_page")
def render_decision(p: CommercialPosition, format_name: str)->dict[str,str]:
    if format_name not in FORMATS: raise ValueError(f"Unsupported format: {format_name}")
    fin = str(p.financial_impact) if p.financial_impact is not None else "Not safely calculable from supplied evidence"
    why=p.why_this_wins or "Not separately stated."
    if format_name=="cfo_brief":
        title="CFO BRIEF"; body=f"DECISION\n{p.recommendation}\n\nFINANCIAL IMPACT\n{fin}\n\nCONFIDENCE\n{p.confidence.level}\n\nWHY\n{why}\n\nDECISION CHANGER\n{p.disconfirming_condition}"
    elif format_name=="category_review":
        title="CATEGORY REVIEW"; body=f"RECOMMENDATION\n{p.recommendation}\n\nCOMMERCIAL RATIONALE\n{why}\n\nOPENING POSITION\n{p.opening_position or 'Not stated.'}\n\nWALK-AWAY\n{p.walk_away_threshold or 'Not stated.'}\n\nASSUMPTIONS\n"+"\n".join(f"- {a}" for a in p.assumptions)
    elif format_name=="supplier_meeting":
        title="SUPPLIER MEETING BRIEF"; dims=(p.negotiation_playbook.dimensions if p.negotiation_playbook else [])
        body=f"OBJECTIVE\n{p.recommendation}\n\nOPENING\n{p.opening_position or 'Not stated.'}\n\nTARGET / WALK-AWAY\n"+"\n".join(f"- {d.get('dimension')}: target={d.get('target')}; walk-away={d.get('walk_away')}" for d in dims[:6])
    else:
        title="VENDOREDGE ONE-PAGE DECISION"; body=f"RECOMMENDATION: {p.recommendation}\nCONFIDENCE: {p.confidence.level}\nFINANCIAL: {fin}\nWHY: {why}\nDECISION CHANGER: {p.disconfirming_condition}"
    return {"format":format_name,"title":title,"body":body,"method":"Deterministic rendering of the validated decision; no new facts, assumptions or LLM call."}
