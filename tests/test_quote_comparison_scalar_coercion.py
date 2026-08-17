from app.pipeline.normalized_evidence import QuoteComparisonEvidence


def test_quote_comparison_accepts_numeric_supplier_count_from_llm():
    case = QuoteComparisonEvidence(number_of_suppliers_being_compared=2)
    assert case.number_of_suppliers_being_compared == "2"


def test_quote_comparison_accepts_numeric_scalar_in_other_human_readable_fields():
    case = QuoteComparisonEvidence(
        number_of_suppliers_being_compared=2,
        price_per_supplier=45.5,
        lead_time_per_supplier=35,
    )
    assert case.number_of_suppliers_being_compared == "2"
    assert case.price_per_supplier == "45.5"
    assert case.lead_time_per_supplier == "35"
