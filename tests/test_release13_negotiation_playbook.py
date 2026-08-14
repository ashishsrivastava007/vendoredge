from types import SimpleNamespace
from app.pipeline.negotiation_playbook import build_negotiation_playbook

def pos():
    return SimpleNamespace(
        recommendation="Hold price and dual-source 30%",
        opening_position="No increase",
        walk_away_threshold="12% without evidence",
        disconfirming_condition="Audited evidence supports the increase",
        negotiation_dimensions=[SimpleNamespace(dimension="Price", opening="0%", target="Flat", walk_away="12% without evidence")],
        negotiation_talk_track=[SimpleNamespace(trigger="Supplier defends increase", say="Show the evidence", purpose="Verify claim")],
        supplier_comparison=[SimpleNamespace(supplier="Atlas", price="€48", quality="99% OTIF", lead_time="6 weeks")],
        decision_audit=SimpleNamespace(material_evidence=["Current price is €48"], uncertainties=["Freight is missing"]),
    )

def test_playbook_is_deterministic_and_source_bound():
    r=build_negotiation_playbook(pos())
    assert r["objective"].startswith("Hold price")
    assert r["dimensions"][0]["target"] == "Flat"
    assert "Freight is missing" in r["questions_to_resolve"]
    assert r["method"].startswith("Deterministic")

def test_playbook_does_not_invent():
    r=build_negotiation_playbook(pos())
    assert all("invent" not in str(v).lower() for v in r.values())
