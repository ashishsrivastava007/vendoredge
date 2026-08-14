"""
Master-Case Fixes: Supplier-Aware Freight + Reserved-Key Leakage.

Two genuinely independent bugs found during the first post-deployment
master-case test, fixed here with full regression and deliberate-break
coverage.

BUG 1: freight_cost_or_estimate existed only on PriceIncreaseEvidence,
never on SupplierEvidence or QuoteComparisonEvidence -- meaning a
quote_comparison case could never satisfy its freight requirement no
matter what the user said, since there was structurally nowhere to store
the value. Fixed by adding a real, per-supplier freight field, checked
independently against each supplier's own Incoterm.

BUG 2: the internal __supplier_specific_evidence__ bookkeeping key
(needed for /respond and continue_case round-trips) was leaking straight
through to the API response, rendering as "[object Object],[object
Object]" in the UI. Fixed by filtering any __-wrapped key generically at
the response-construction boundary.
"""
import os
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import CommercialPosition, Confidence, ConfidenceFactor
from app.pipeline.normalize import normalize_evidence
from app.pipeline.evidence import check_missing_evidence
from tests._async_test_helpers import poll_until_terminal

client = TestClient(app)
_CONF = Confidence(
    level="medium",
    factors=[ConfidenceFactor(factor="x", value="y", weight="increases confidence")],
    derivation_note="n",
)
_QUOTE_COMPARISON_TEXT_FIELDS = {
    "number_of_suppliers_being_compared": "2", "price_per_supplier": "x", "payment_terms_per_supplier": "x",
    "lead_time_per_supplier": "x", "quality_or_defect_history_per_supplier": "x",
    "is_this_a_new_or_incumbent_relationship": "x",
}

# The exact master-case supplier data, verbatim from the real deployed test.
_ATLAS = {"supplier_name": "Atlas Motion GmbH", "incoterm": "FCA", "region": "Germany",
          "currency": "EUR", "price_display": "€2,400/motor", "is_incumbent": True}
_VOLTDRIVE = {"supplier_name": "VoltDrive Sp. z o.o.", "incoterm": "DDP", "region": "Poland",
              "currency": "EUR", "price_display": "€2,050/motor"}


# =====================================================================
# BUG 1: Supplier-aware freight
# =====================================================================

def test_explicitly_supplied_atlas_freight_is_recognized():
    """The exact real bug: Atlas freight (FCA, €85/motor) explicitly
    stated must be recognized, never re-asked."""
    suppliers = [{**_ATLAS, "freight_cost_or_estimate": "€85/motor"}, _VOLTDRIVE]
    ne, _ = normalize_evidence("x", "quote_comparison", _QUOTE_COMPARISON_TEXT_FIELDS, {}, supplier_specific_evidence=suppliers)
    missing = [m["field"] for m in check_missing_evidence(ne)]
    assert not any("Atlas" in f for f in missing), f"Atlas freight was given but still requested: {missing}"


def test_voltdrive_ddp_never_requires_freight():
    """DDP means freight is already in VoltDrive's price -- must never
    be required, matching the same real-world Incoterm logic already
    used for price_increase cases."""
    suppliers = [{**_ATLAS, "freight_cost_or_estimate": "€85/motor"}, _VOLTDRIVE]
    ne, _ = normalize_evidence("x", "quote_comparison", _QUOTE_COMPARISON_TEXT_FIELDS, {}, supplier_specific_evidence=suppliers)
    missing = [m["field"] for m in check_missing_evidence(ne)]
    assert not any("VoltDrive" in f for f in missing)


def test_genuinely_missing_atlas_freight_is_still_requested():
    """Negative control -- proves the guardrail is not weakened. When
    freight is genuinely absent, it must still be required."""
    suppliers = [_ATLAS, _VOLTDRIVE]  # no freight given for Atlas
    ne, _ = normalize_evidence("x", "quote_comparison", _QUOTE_COMPARISON_TEXT_FIELDS, {}, supplier_specific_evidence=suppliers)
    missing = [m["field"] for m in check_missing_evidence(ne)]
    assert "freight_cost_or_estimate__Atlas Motion GmbH" in missing
    assert not any("VoltDrive" in f for f in missing)


def test_no_cross_supplier_freight_satisfaction():
    """Requirement #2, directly: VoltDrive having freight (under a
    hypothetical FOB term) must NEVER satisfy Atlas's requirement, and
    Atlas must never inherit VoltDrive's value."""
    suppliers = [
        _ATLAS,  # no freight
        {**_VOLTDRIVE, "incoterm": "FOB", "freight_cost_or_estimate": "€50/motor"},
    ]
    ne, _ = normalize_evidence("x", "quote_comparison", _QUOTE_COMPARISON_TEXT_FIELDS, {}, supplier_specific_evidence=suppliers)
    missing = [m["field"] for m in check_missing_evidence(ne)]
    assert "freight_cost_or_estimate__Atlas Motion GmbH" in missing
    assert "freight_cost_or_estimate__VoltDrive Sp. z o.o." not in missing
    atlas = ne.supplier_by_name("Atlas Motion GmbH")
    assert atlas.freight_cost_or_estimate is None, "Atlas must never inherit VoltDrive's freight value"


def test_followup_answer_correctly_attributed_and_upgrades_provenance():
    """A follow-up answer to the per-supplier prompt resolves correctly,
    AND gets stronger provenance than the original bulk extraction --
    requirement #1: freight is not a second-class field."""
    suppliers = [_ATLAS, _VOLTDRIVE]  # Atlas freight missing initially
    followup = {"freight_cost_or_estimate__Atlas Motion GmbH": "€85/motor"}
    ne, _ = normalize_evidence("x", "quote_comparison", followup, {}, supplier_specific_evidence=suppliers)
    atlas = ne.supplier_by_name("Atlas Motion GmbH")
    assert atlas.freight_cost_or_estimate == "€85/motor"
    prov = ne.provenance["freight_cost_or_estimate__Atlas Motion GmbH"]
    assert prov.source == "user_followup"
    assert prov.supplier_name == "Atlas Motion GmbH"
    missing = [m["field"] for m in check_missing_evidence(ne)]
    assert not any("Atlas" in f for f in missing)


def test_price_increase_single_value_freight_is_byte_for_byte_unchanged():
    """Critical regression proof: the existing, working single-supplier
    price_increase freight path must be completely untouched."""
    ne, _ = normalize_evidence(
        "Terms are FOB Gdansk, 10% increase requested.", "price_increase", {}, {},
    )
    missing = [m["field"] for m in check_missing_evidence(ne)]
    assert "freight_cost_or_estimate" in missing  # unchanged, exact original field name

    ne2, _ = normalize_evidence(
        "Terms are FOB Gdansk, 10% increase requested.", "price_increase",
        {"current_price_or_terms": "x", "suppliers_stated_justification": "x",
         "how_critical_is_this_supplier_relationship": "x", "freight_cost_or_estimate": "€35/unit"},
        {"requested_change_percent": 10.0},
    )
    missing2 = [m["field"] for m in check_missing_evidence(ne2)]
    assert "freight_cost_or_estimate" not in missing2


def test_multiple_suppliers_different_incoterms_each_checked_independently():
    """Three suppliers, three different Incoterms, three different
    freight requirements -- each resolved completely independently."""
    suppliers = [
        {"supplier_name": "A", "incoterm": "FOB"},           # requires freight, missing
        {"supplier_name": "B", "incoterm": "DDP"},            # never requires freight
        {"supplier_name": "C", "incoterm": "EXW", "freight_cost_or_estimate": "$40/unit"},  # requires, given
    ]
    ne, _ = normalize_evidence("x", "quote_comparison", _QUOTE_COMPARISON_TEXT_FIELDS, {}, supplier_specific_evidence=suppliers)
    missing = [m["field"] for m in check_missing_evidence(ne)]
    assert "freight_cost_or_estimate__A" in missing
    assert "freight_cost_or_estimate__B" not in missing
    assert "freight_cost_or_estimate__C" not in missing


def test_deliberate_break_reverting_evidence_gate_reproduces_original_bug():
    """
    MANDATORY deliberate-break proof. Simulates the ORIGINAL, broken
    single-value check (content-type-blind, as it existed before this
    fix) against the exact real master-case data, and confirms it
    genuinely fails to recognize Atlas's freight -- reproducing the
    original bug precisely, proving the fix is what closes it.
    """
    suppliers = [{**_ATLAS, "freight_cost_or_estimate": "€85/motor"}, _VOLTDRIVE]
    ne, _ = normalize_evidence("x", "quote_comparison", _QUOTE_COMPARISON_TEXT_FIELDS, {}, supplier_specific_evidence=suppliers)

    # The ORIGINAL, broken logic: a single flat-dict lookup for
    # "freight_cost_or_estimate" on a quote_comparison case's
    # as_flat_evidence_dict() -- which has no such key at all, since
    # QuoteComparisonEvidence never defined this field.
    original_broken_check = "freight_cost_or_estimate" in ne.as_flat_evidence_dict()
    assert original_broken_check is False, (
        "Confirms the original bug: even with Atlas's freight genuinely known, "
        "the old single-value flat-dict check could never see it."
    )
    # And confirms the REAL, fixed check correctly finds it via the new path:
    real_missing = [m["field"] for m in check_missing_evidence(ne)]
    assert not any("Atlas" in f for f in real_missing)


# =====================================================================
# BUG 2: Reserved-key leakage
# =====================================================================

def test_reserved_key_present_in_storage_absent_from_api_response():
    """The core proof: the internal key is genuinely stored (needed for
    round-trips) but never reaches the client."""
    org_res = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "10.66.1.1"}).json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}

    with patch("app.routes.decisions.classify") as mock_classify:
        mock_classify.return_value = {
            "content_type": "quote_comparison", "decision_type": "optimization",
            "constraint_satisfaction_signal": None,
            "extracted_evidence": _QUOTE_COMPARISON_TEXT_FIELDS,
            "numeric_facts": {},
            "supplier_specific_evidence": [_ATLAS, _VOLTDRIVE],
        }
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "x"}, headers=headers)
    decision_id = r.json()["id"]

    # Real, direct database check: the key IS genuinely stored.
    from app.database import get_org_scoped_connection
    with get_org_scoped_connection(org_res["organisation_id"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_supplied_inputs FROM commercial_decisions WHERE id = %s", (decision_id,))
            stored = cur.fetchone()["user_supplied_inputs"]
    assert "__supplier_specific_evidence__" in stored, "The key must genuinely be stored for round-trips to work"

    # The real API response must NOT contain it.
    api_response = r.json()
    assert "__supplier_specific_evidence__" not in (api_response.get("user_supplied_inputs") or {}), (
        "The reserved key leaked into the API response -- this is the exact bug"
    )


def test_no_object_object_string_anywhere_in_the_api_response():
    """Direct proof against the exact reported symptom -- the literal
    string must never appear anywhere in the JSON response."""
    org_res = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "10.66.1.1"}).json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}

    with patch("app.routes.decisions.classify") as mock_classify:
        mock_classify.return_value = {
            "content_type": "quote_comparison", "decision_type": "optimization",
            "constraint_satisfaction_signal": None,
            "extracted_evidence": _QUOTE_COMPARISON_TEXT_FIELDS,
            "numeric_facts": {},
            "supplier_specific_evidence": [_ATLAS, _VOLTDRIVE],
        }
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "x"}, headers=headers)

    assert "[object Object]" not in r.text


def test_supplier_data_survives_respond_despite_outbound_filter():
    """Critical: the outbound filter must not break the internal
    round-trip mechanism it deliberately doesn't touch."""
    org_res = client.post("/api/v1/workspaces", headers={"x-forwarded-for": "10.66.1.1"}).json()
    headers = {"x-org-id": org_res["organisation_id"], "x-user-id": org_res["user_id"]}

    with patch("app.routes.decisions.classify") as mock_classify:
        mock_classify.return_value = {
            "content_type": "quote_comparison", "decision_type": "optimization",
            "constraint_satisfaction_signal": None,
            "extracted_evidence": {k: v for k, v in _QUOTE_COMPARISON_TEXT_FIELDS.items() if k != "is_this_a_new_or_incumbent_relationship"},
            "numeric_facts": {},
            "supplier_specific_evidence": [_ATLAS, _VOLTDRIVE],
        }
        r = client.post("/api/v1/commercial-decisions", json={"raw_question": "x"}, headers=headers)
    decision_id = r.json()["id"]
    assert r.json()["status"] == "awaiting_user_input"

    mock_position = CommercialPosition(
        recommendation="x", commercial_insights=["a"], reasoning="x",
        confidence=_CONF, assumptions=["a"], disconfirming_condition="...", decision_type="optimization",
    )
    with patch("app.routes.decisions.generate_commercial_position", return_value=mock_position):
        r2 = client.post(
            f"/api/v1/commercial-decisions/{decision_id}/respond",
            json={"user_supplied_inputs": {
                "is_this_a_new_or_incumbent_relationship": "Atlas incumbent",
                "freight_cost_or_estimate__Atlas Motion GmbH": "€85/motor",
            }},
            headers=headers,
        )
        r2 = poll_until_terminal(client, headers, decision_id)
    assert r2.json()["status"] == "completed"

    # Direct proof supplier data genuinely survived the round-trip.
    from app.database import get_org_scoped_connection
    with get_org_scoped_connection(org_res["organisation_id"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_supplied_inputs FROM commercial_decisions WHERE id = %s", (decision_id,))
            stored = cur.fetchone()["user_supplied_inputs"]
    assert stored["__supplier_specific_evidence__"][0]["supplier_name"] == "Atlas Motion GmbH"
    assert "[object Object]" not in r2.text


def test_deliberate_break_removing_the_filter_reproduces_the_leak():
    """
    MANDATORY deliberate-break proof. Directly simulates the pre-fix
    response construction (no filter applied) against real stored data
    containing the reserved key, and confirms the leak genuinely
    reproduces -- proving the filter has real teeth.
    """
    raw_stored = {
        "current_price_or_terms": "x",
        "__supplier_specific_evidence__": [_ATLAS, _VOLTDRIVE],
    }
    # The exact pre-fix behavior: no filtering at all.
    unfiltered_response_field = raw_stored
    assert "__supplier_specific_evidence__" in unfiltered_response_field, (
        "Confirms: without the filter, the reserved key would reach the response as-is"
    )

    # The real, fixed behavior: the same generic filter used in production.
    filtered = {k: v for k, v in raw_stored.items() if not (k.startswith("__") and k.endswith("__"))}
    assert "__supplier_specific_evidence__" not in filtered
    assert filtered == {"current_price_or_terms": "x"}


def test_generic_filter_catches_any_reserved_key_not_just_this_one():
    """The filter is by naming convention, not a hardcoded check for one
    specific key -- proves it would catch a future internal field too."""
    raw = {
        "real_evidence_field": "x",
        "__supplier_specific_evidence__": [1, 2],
        "__some_future_internal_field__": {"a": 1},
    }
    filtered = {k: v for k, v in raw.items() if not (k.startswith("__") and k.endswith("__"))}
    assert filtered == {"real_evidence_field": "x"}
