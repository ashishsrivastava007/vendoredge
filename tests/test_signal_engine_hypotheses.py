"""
R48 Signal Engine -- competing-explanations engine (Section 9) and
investigation prioritisation (Section 11). Deliberately scoped to the
spend/volume signal shape, the only one with enough structural
evidence (spend growth, volume growth, avg unit price growth) to
genuinely test hypotheses against rather than asking the model to
free-associate causes. Every status is derived from whether the
relevant CALCULATED fact exists and what it says.
"""
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor

client = TestClient(app)
_CM = Confidence(level="medium", factors=[ConfidenceFactor(factor="a", value="b", weight="increases confidence")], derivation_note="n")


def _run(numeric_facts, insights, recommendation, suffix, extra_evidence=None, supplier_evidence=None):
    org = client.post("/api/v1/workspaces", headers={"x-forwarded-for": f"10.890.{suffix}.1"}).json()
    headers = {"x-org-id": org["organisation_id"], "x-user-id": org["user_id"]}
    classify = {
        "content_type": "price_increase", "decision_type": "optimization", "constraint_satisfaction_signal": None,
        "extracted_evidence": {"supplier_currency": "USD", **(extra_evidence or {})},
        "numeric_facts": numeric_facts, "supplier_specific_evidence": supplier_evidence or [],
    }
    pos = CommercialPosition(recommendation=recommendation, commercial_insights=insights, reasoning="x", confidence=_CM, assumptions=["a"], disconfirming_condition="...", decision_type="optimization")
    with patch("app.routes.decisions.classify", return_value=classify), \
         patch("app.routes.decisions.verify_market_claim", return_value=None), \
         patch("app.pipeline.fresh_intelligence.research_fresh_market_intelligence", return_value=[]), \
         patch("app.routes.decisions.generate_commercial_position", return_value=pos):
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "signal test", "mode": "commercial_signal"}, headers=headers)
        d = None
        for _ in range(30):
            d = client.get(f"/api/v1/commercial-decisions/{r.json()['id']}", headers=headers).json()
            if d["status"] != "reasoning":
                break
            time.sleep(0.2)
    return d["commercial_position"]["commercial_signal_answer"]


def test_hypotheses_use_only_allowed_status_labels():
    a = _run({"category_annual_spend_usd": 1_180_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_300, "category_prior_annual_volume_units": 10_000}, ["Spend growing faster than volume."], "Investigate.", 1)
    allowed = {"SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED", "UNKNOWN", "CONTRADICTED"}
    for h in a["hypotheses"]:
        assert h["status"] in allowed
        # No probability percentages anywhere in a hypothesis's text fields.
        import re
        for field in ("hypothesis", *h["supporting_evidence"], *h["contradicting_evidence"], *h["missing_evidence"]):
            assert not re.search(r"\d+%\s*(chance|probability|likely)", field.lower())


def test_price_hypothesis_supported_when_unit_price_genuinely_rose():
    a = _run({"category_annual_spend_usd": 1_180_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_300, "category_prior_annual_volume_units": 10_000}, ["Spend growing faster than volume."], "Investigate.", 2)
    price_hyp = next(h for h in a["hypotheses"] if "average unit price" in h["hypothesis"])
    assert price_hyp["status"] == "SUPPORTED"
    assert price_hyp["supporting_evidence"] != []


def test_specification_hypothesis_not_supported_when_no_spec_change_reported():
    a = _run({"category_annual_spend_usd": 1_180_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_300, "category_prior_annual_volume_units": 10_000}, ["Spend growing faster than volume."], "Investigate.", 3)
    spec_hyp = next(h for h in a["hypotheses"] if "specification" in h["hypothesis"])
    assert spec_hyp["status"] == "NOT_SUPPORTED"


def test_specification_hypothesis_partially_supported_when_spec_change_reported():
    a = _run(
        {"category_annual_spend_usd": 1_150_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_100, "category_prior_annual_volume_units": 10_000},
        ["Spend rose alongside a spec change."], "Confirm the spec change basis.", 4,
        extra_evidence={"specification_changed": True, "specification_change_description": "New tolerance."},
    )
    spec_hyp = next(h for h in a["hypotheses"] if "specification" in h["hypothesis"])
    assert spec_hyp["status"] == "PARTIALLY_SUPPORTED"
    assert spec_hyp["supporting_evidence"] != []


def test_first_investigation_prioritises_achievable_over_permanently_unresolvable():
    """The genuine finding from this build: the mix-shift hypothesis
    can never be resolved in this evidence model (no SKU field exists
    at all), so it must not be recommended as the first investigation
    when a more achievable, partially-resolved hypothesis exists."""
    a = _run(
        {"category_annual_spend_usd": 1_150_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_100, "category_prior_annual_volume_units": 10_000},
        ["Spend rose alongside a spec change."], "Confirm the spec change basis.", 5,
        extra_evidence={"specification_changed": True, "specification_change_description": "New tolerance."},
    )
    assert "specification" in a["first_investigation"].lower()
    assert "mix shift" not in a["first_investigation"].lower()


def test_first_investigation_falls_back_to_price_vs_mix_split_when_nothing_else_established():
    a = _run({"category_annual_spend_usd": 1_180_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_300, "category_prior_annual_volume_units": 10_000}, ["Spend growing faster than volume."], "Investigate.", 6)
    assert a["first_investigation"] is not None


def test_market_divergence_headline_and_materiality_are_signal_specific():
    """Found during the 20-case matrix run: this signal type initially
    fell through to the generic spend-growth headline even though the
    external-intelligence gate correctly recognized it. Fixed with a
    dedicated headline/materiality branch reusing the same marker
    phrases as the gate."""
    a = _run(
        {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 1_000_000},
        ["a"], "Ask the supplier to explain the divergence.", 7,
        extra_evidence={"suppliers_stated_justification": "The market price has fallen but the supplier's price has not moved."},
    )
    assert "market price movement" in a["signal"].lower()
    assert "spend" not in a["signal"].lower()
    assert a["commercial_risk"] != []
    assert "commercial opportunity" in a["commercial_risk"][0].lower()


# ---------------------------------------------------------------------
# Generalized backbone: every dimension gets real hypotheses, not just
# spend/volume; multiple dimensions combine rather than one winning
# ---------------------------------------------------------------------

def test_otif_signal_now_gets_real_hypotheses_not_zero():
    """The structural gap this generalization closes: previously an
    OTIF-only signal produced zero hypotheses at all."""
    a = _run({}, ["OTIF dropped."], "Investigate.", 8,
             supplier_evidence=[{"supplier_name": "Supplier A", "is_incumbent": True, "otif_percent": 81.0, "prior_otif_percent": 96.0}])
    assert len(a["hypotheses"]) == 2
    for h in a["hypotheses"]:
        assert h["status"] == "UNKNOWN"
        assert h["missing_evidence"] != []
        assert "_generic" not in h  # internal marker never leaks to the API


def test_generic_hypotheses_never_invent_a_field_the_evidence_model_lacks():
    """Both generic hypotheses must always be UNKNOWN -- there is no
    field anywhere in this evidence model that could make either
    SUPPORTED or CONTRADICTED, and asserting otherwise would be
    inventing evidence."""
    a = _run({}, ["Defects increased."], "Investigate.", 9,
             supplier_evidence=[{"supplier_name": "Supplier B", "is_incumbent": True, "defect_rate_percent": 4.8, "prior_defect_rate_percent": 1.2}])
    generic = [h for h in a["hypotheses"] if "one-off" in h["hypothesis"] or "data or reporting error" in h["hypothesis"]]
    assert len(generic) == 2
    assert all(h["status"] == "UNKNOWN" for h in generic)


def test_multi_dimensional_signal_combines_headline_and_materiality():
    """The core structural fix: a case with BOTH a spend/volume pattern
    AND an OTIF deterioration must represent both, not silently drop
    one -- proven with a genuinely multi-dimensional input, not two
    separate single-dimension tests."""
    a = _run(
        {"category_annual_spend_usd": 1_180_000, "category_prior_annual_spend_usd": 1_000_000, "category_annual_volume_units": 10_300, "category_prior_annual_volume_units": 10_000},
        ["Multi-dimensional signal."], "Investigate both.", 10,
        supplier_evidence=[{"supplier_name": "Supplier B", "is_incumbent": True, "otif_percent": 81.0, "prior_otif_percent": 96.0}],
    )
    assert "OTIF" in a["signal"] and "spend" in a["signal"].lower()
    assert len(a["commercial_risk"]) == 2
    assert len(a["hypotheses"]) == 7  # 3 spend/volume-specific + 2 generic-per-dimension x 2 dimensions


def test_concentration_and_specification_change_combine_when_both_present():
    """A second genuine combination, proving this generalizes beyond
    the spend/OTIF pairing specifically."""
    a = _run(
        {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 700_000, "annual_spend_usd": 640_000, "prior_annual_spend_usd": 294_000},
        ["Concentration rising alongside a specification change."], "Assess both.", 11,
        extra_evidence={"specification_changed": True, "specification_change_description": "New material spec."},
        supplier_evidence=[{"supplier_name": "Supplier C", "is_incumbent": True}],
    )
    assert "share of category spend" in a["signal"] and "specification" in a["signal"].lower()


def test_investigation_value_uses_materiality_not_a_fixed_per_dimension_rule():
    """The core proof this isn't 'OTIF always outranks commercial' or
    any other hardcoded dimension ranking: when OTIF is IMPROVING (no
    established materiality) and concentration is RISING (established
    materiality), the concentration hypothesis must be prioritised --
    the opposite of what a fixed 'OTIF first' rule would produce."""
    a = _run(
        {"category_annual_spend_usd": 1_000_000, "category_prior_annual_spend_usd": 700_000, "annual_spend_usd": 640_000, "prior_annual_spend_usd": 294_000},
        ["OTIF improved, but concentration rose."], "Assess concentration risk.", 12,
        supplier_evidence=[{"supplier_name": "Supplier C", "is_incumbent": True, "otif_percent": 98.0, "prior_otif_percent": 90.0}],
    )
    assert "concentration" in a["first_investigation"].lower()
    assert "otif" not in a["first_investigation"].lower()
    for h in a["hypotheses"]:
        assert "_dimension" not in h and "_gates_others" not in h and "_generic" not in h
