"""Red-team tests for the LLM -> typed NormalizedEvidence boundary.

The classifier is a model-generated JSON contract. These tests prove that
reasonable representation drift is accepted while malformed types degrade to
missing evidence instead of producing a production 500 or an invented value.
"""
from app.pipeline.normalize import normalize_evidence


def test_numeric_scalars_as_json_numbers_are_safe():
    ne, _ = normalize_evidence(
        "Compare two suppliers",
        "quote_comparison",
        {
            "number_of_suppliers_being_compared": 2,
            "price_per_supplier": 45.5,
            "payment_terms_per_supplier": 60,
        },
        {"annual_volume_units": 8400, "requested_change_percent": 6.4},
    )
    assert ne.case.number_of_suppliers_being_compared == "2"
    assert ne.case.price_per_supplier == "45.5"
    assert ne.case.payment_terms_per_supplier == "60"
    assert ne.common.annual_volume_units == 8400.0


def test_malformed_numeric_strings_become_unknown_not_500():
    ne, _ = normalize_evidence(
        "Compare two suppliers",
        "quote_comparison",
        {},
        {"annual_volume_units": "8,400 units", "requested_change_percent": "six percent"},
    )
    assert ne.common.annual_volume_units is None
    assert ne.normalization_warnings
    assert any("annual_volume_units" in x for x in ne.normalization_warnings)


def test_supplier_malformed_numeric_fields_are_downgraded():
    ne, _ = normalize_evidence(
        "Compare suppliers",
        "quote_comparison",
        {},
        {},
        supplier_specific_evidence=[
            {
                "supplier_name": "Atlas",
                "lead_time_weeks": "21 weeks",
                "otif_percent": "ninety nine",
                "qualification_percent": {"value": 70},
                "qualification_status": ["complete"],
            }
        ],
    )
    supplier = ne.supplier_by_name("Atlas")
    assert supplier is not None
    assert supplier.lead_time_weeks is None
    assert supplier.otif_percent is None
    assert supplier.qualification_percent is None
    assert supplier.qualification_status == "unknown"
    assert len(ne.normalization_warnings) >= 4


def test_malformed_top_level_extraction_shapes_do_not_500():
    ne, _ = normalize_evidence(
        "Compare suppliers",
        "quote_comparison",
        ["not", "an", "object"],
        {"annual_volume_units": []},
        supplier_specific_evidence={"not": "an array"},
        stakeholder_views={"not": "an array"},
    )
    assert ne.common.annual_volume_units is None
    assert ne.suppliers == []
    assert ne.stakeholder_views == []
    assert len(ne.normalization_warnings) >= 4


def test_numeric_text_representation_is_only_coerced_for_explicit_text_fields():
    ne, _ = normalize_evidence(
        "Compare suppliers",
        "quote_comparison",
        {"price_per_supplier": 45.5, "number_of_suppliers_being_compared": 2},
        {},
    )
    assert ne.case.price_per_supplier == "45.5"
    assert ne.case.number_of_suppliers_being_compared == "2"


def test_boolean_is_never_silently_coerced_to_numeric_or_text():
    ne, _ = normalize_evidence(
        "Compare suppliers",
        "quote_comparison",
        {"number_of_suppliers_being_compared": True},
        {"annual_volume_units": False},
    )
    assert ne.case.number_of_suppliers_being_compared is None
    assert ne.common.annual_volume_units is None
    assert any("number_of_suppliers_being_compared" in x for x in ne.normalization_warnings)
    assert any("annual_volume_units" in x for x in ne.normalization_warnings)
