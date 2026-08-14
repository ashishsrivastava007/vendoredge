from app.pipeline.normalize import normalize_evidence


def test_stakeholder_views_are_preserved_as_attributed_evidence():
    ne, _ = normalize_evidence(
        "Finance wants 5% savings; Operations prefers Atlas because of reliability.",
        "price_increase",
        {"current_price_or_terms": "$100"},
        {},
        stakeholder_views=[
            {"stakeholder_name": "Finance", "role": "finance", "view_type": "objective", "statement": "wants 5% savings"},
            {"stakeholder_name": "Operations", "role": "operations", "view_type": "preference", "statement": "prefers Atlas because of reliability"},
        ],
    )
    assert len(ne.stakeholder_views) == 2
    assert ne.stakeholder_views[0].stakeholder_name == "Finance"
    assert ne.stakeholder_views[1].view_type == "preference"
    flat = ne.as_flat_evidence_dict()
    assert "__stakeholder_views__" not in flat


def test_invalid_or_empty_stakeholder_entries_fail_closed():
    ne, _ = normalize_evidence(
        "x", "price_increase", {}, {},
        stakeholder_views=[
            {"stakeholder_name": "", "view_type": "preference", "statement": "x"},
            {"stakeholder_name": "Finance", "view_type": "made_up", "statement": "x"},
            {"stakeholder_name": "Operations", "view_type": "risk_concern", "statement": ""},
        ],
    )
    assert ne.stakeholder_views == []


def test_conflicting_stakeholder_views_are_not_merged():
    ne, _ = normalize_evidence(
        "Operations prefers Atlas; Finance prefers EuroMotion.",
        "price_increase", {}, {},
        stakeholder_views=[
            {"stakeholder_name": "Operations", "view_type": "preference", "statement": "prefers Atlas"},
            {"stakeholder_name": "Finance", "view_type": "preference", "statement": "prefers EuroMotion"},
        ],
    )
    assert [(v.stakeholder_name, v.statement) for v in ne.stakeholder_views] == [
        ("Operations", "prefers Atlas"),
        ("Finance", "prefers EuroMotion"),
    ]
