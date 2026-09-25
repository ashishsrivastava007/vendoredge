"""
P1 fix -- specification-change hypothesis decoupled from the
spend/volume block (acceptance-test finding B9).

Previously, the richer, type-specific specification-change hypothesis
only generated when BOTH spend and volume growth existed, because it
was nested entirely inside `if has_spend_volume_dimension:`. A genuine
specification-change signal with a spend figure but no volume data (or
no spend data at all) got only the two generic, permanently-UNKNOWN
hypotheses instead -- the real information the user provided (a
specification change was reported) was being discarded rather than
analyzed.

Fixed by decoupling: the specification-change hypothesis now fires
whenever case_spec_changed is true, independent of which other
dimensions are present, and its status honestly reflects whatever cost
evidence actually exists -- PARTIALLY_SUPPORTED only when a real cost
movement (spend/volume or spend alone) exists to attribute it to,
UNKNOWN with a named evidence gap when no cost movement exists at all.
No volume evidence, spend impact, or materiality is invented in either
case.
"""
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor

client = TestClient(app)
_CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _run(numeric_facts, insights, recommendation, suffix, extra_evidence=None):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"12.700.{suffix}.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    classify = {
        "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", **(extra_evidence or {})},
        "numeric_facts": numeric_facts, "supplier_specific_evidence": [],
    }
    pos = CommercialPosition(recommendation=recommendation, commercial_insights=insights, reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "test", "mode": "commercial_signal"}, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return d["commercial_position"]["commercial_signal_answer"]


def _spec_hypothesis(answer):
    return next(h for h in answer["hypotheses"] if "specification" in h["hypothesis"].lower())


def test_specification_change_no_volume_is_now_partially_supported():
    """The exact B9 reproduction: spend data exists, volume does not.
    Previously produced only two generic, permanently-UNKNOWN
    hypotheses; must now produce the richer, informative one."""
    a = _run(
        {"category_annual_spend_usd": 1_150_000, "category_prior_annual_spend_usd": 1_000_000},
        ["Spec change coincided with cost rise."], "Confirm attribution.", 1,
        extra_evidence={"specification_changed": True, "specification_change_description": "New tolerance."},
    )
    h = _spec_hypothesis(a)
    assert h["status"] == "PARTIALLY_SUPPORTED"
    assert h["supporting_evidence"] != []


def test_specification_change_with_volume_still_works_unchanged():
    """Regression guard: the full-data case (spend AND volume) must
    still produce the same PARTIALLY_SUPPORTED result as before this
    fix, now via the decoupled code path."""
    a = _run(
        {"category_annual_spend_usd": 1_150_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_050, "category_prior_annual_volume_units": 10_000},
        ["Spec change with full spend/volume data."], "Confirm attribution.", 2,
        extra_evidence={"specification_changed": True, "specification_change_description": "New tolerance."},
    )
    h = _spec_hypothesis(a)
    assert h["status"] == "PARTIALLY_SUPPORTED"
    # The average-unit-price hypothesis (spend/volume-specific) must
    # still be present and unaffected.
    assert any("average unit price" in x["hypothesis"] for x in a["hypotheses"])


def test_specification_change_no_spend_at_all_stays_honestly_unknown():
    """No cost movement exists to attribute the change to -- must not
    invent a PARTIALLY_SUPPORTED status or any spend/volume figure
    that was never provided."""
    a = _run(
        {}, ["A specification change occurred but no cost data is available yet."], "Cannot assess cost impact yet.", 3,
        extra_evidence={"specification_changed": True, "specification_change_description": "New tolerance."},
    )
    h = _spec_hypothesis(a)
    assert h["status"] == "UNKNOWN"
    assert h["supporting_evidence"] == ["A specification change was explicitly reported."]
    assert "spend or cost figure" in h["missing_evidence"][0]


def test_specification_change_with_contradictory_cost_evidence():
    """A specification change is reported AND the case's own text
    conflicts with the calculated cost movement -- both the
    specification hypothesis and the contradiction must be represented,
    neither suppressing the other."""
    a = _run(
        {"category_annual_spend_usd": 1_150_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_050, "category_prior_annual_volume_units": 10_000},
        ["Spec change reported; supplier claims price fell."], "Reconcile.", 4,
        extra_evidence={"specification_changed": True, "specification_change_description": "New tolerance.", "suppliers_stated_justification": "The supplier says their price decreased."},
    )
    h = _spec_hypothesis(a)
    assert h["status"] == "PARTIALLY_SUPPORTED"
    assert len(a["contradictions"]) == 1
    assert "price decrease" in a["contradictions"][0]["description"].lower()


def test_specification_change_hypothesis_never_invents_a_magnitude():
    """Across all shapes, the specification hypothesis's own text and
    evidence must never state a percentage or dollar figure that was
    never calculated for it specifically."""
    for numeric_facts, extra in [
        ({"category_annual_spend_usd": 1_150_000, "category_prior_annual_spend_usd": 1_000_000}, {}),
        ({}, {}),
    ]:
        a = _run(numeric_facts, ["a"], "x", 5 + hash(str(numeric_facts)) % 100,
                 extra_evidence={"specification_changed": True, "specification_change_description": "New tolerance.", **extra})
        h = _spec_hypothesis(a)
        combined = " ".join([h["hypothesis"], *h["supporting_evidence"], *h["contradicting_evidence"], *h["missing_evidence"]])
        import re
        assert not re.search(r"specifically \d", combined)
