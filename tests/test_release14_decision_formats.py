from types import SimpleNamespace
from app.pipeline.decision_formats import render_decision, FORMATS

def p():
    return SimpleNamespace(recommendation="Hold price", confidence=SimpleNamespace(level="medium"), financial_impact=None, why_this_wins="Evidence is incomplete", disconfirming_condition="Audited evidence arrives", opening_position="No increase", walk_away_threshold="Unsupported increase", assumptions=["Freight not provided"], negotiation_playbook=SimpleNamespace(dimensions=[{"dimension":"Price","target":"Flat","walk_away":"Unsupported increase"}]))

def test_all_customer_formats_render_from_same_position():
    for f in FORMATS:
        r=render_decision(p(),f); assert r["format"]==f and "Hold price" in r["body"] and "no new facts" in r["method"]

def test_unknown_format_rejected():
    try: render_decision(p(),"made_up")
    except ValueError: pass
    else: assert False
