"""
Curated benchmark cases. Each checks structural correctness (did a
guaranteed or reliably-triggered field show up, or correctly stay absent)
-- NOT reasoning quality, which remains a human judgment call.

Deliberately varied: simple vs. dense, both content types, both decision
types, a case that should trigger optional fields and one that correctly
shouldn't. Grow this list with real pilot cases as they come in -- that's
better test data than more synthetic examples.
"""


def has_field(field_name, min_items=1):
    def check(position):
        val = position.get(field_name)
        if val is None:
            return False
        if isinstance(val, list):
            return len(val) >= min_items
        return True
    return check


def lacks_field(field_name):
    def check(position):
        return position.get(field_name) is None
    return check


def financial_impact_equals(expected_annual_impact):
    def check(position):
        fi = position.get("financial_impact")
        if not fi:
            return False
        return abs(fi.get("potential_annual_impact_usd", 0) - expected_annual_impact) < 1
    return check


BENCHMARK_CASES = [
    {
        "name": "Simple price increase (baseline case)",
        "question": "Our supplier wants a 10% price increase on our annual spend of $1,800,000, citing raw material inflation. We have alternative suppliers available.",
        "evidence_answers": {
            "current_price_or_terms": "$1,800,000 annual spend",
            "suppliers_stated_justification": "raw material inflation",
            "how_critical_is_this_supplier_relationship": "alternatives exist",
        },
        "checklist": [
            (financial_impact_equals(180000), "Financial impact correctly computed as $180,000 (10% of $1.8M)"),
            (has_field("commercial_insights"), "At least one commercial insight present (required field)"),
            (has_field("assumptions"), "At least one assumption listed (required field)"),
            (has_field("confidence"), "Confidence block present (required field)"),
            (lacks_field("supplier_comparison"), "Correctly no supplier comparison table -- only one supplier in this case"),
        ],
    },
    {
        "name": "Dense multi-supplier case (marine bearing, reused from tonight's real test)",
        "question": (
            "Our global contract for high-pressure marine bearing assemblies is due for renewal. "
            "Current supplier wants a 13% price increase on $31,200,000 annual spend (6,000 units at $5,200/unit), "
            "citing stainless steel +19%, nickel +16%, labour +11%, energy +14%, freight +9%. "
            "Market indices show stainless steel +8%, nickel +7%, labour +5%, energy +4%, freight -5%. "
            "Supplier B quotes $4,780/unit, Supplier C quotes $4,920/unit and can supply 40% of demand "
            "with a 5-year price freeze if awarded at least 35% of volume."
        ),
        "evidence_answers": {},  # this case is dense enough to likely need no follow-up, or the harness will report if it does
        "checklist": [
            (has_field("cost_driver_comparison", min_items=3), "Cost driver comparison table present with multiple drivers"),
            (has_field("supplier_comparison", min_items=2), "Supplier comparison table present with multiple suppliers"),
            (has_field("key_figures"), "Key figures present"),
            (has_field("why_this_wins"), "Trade-off summary present for this optimization case"),
        ],
    },
    {
        "name": "Quote comparison (different content type)",
        "question": (
            "Comparing two supplier quotes for the same component: Supplier A quotes $50/unit with "
            "97% OTIF and 8-week lead time. Supplier B quotes $46/unit with 92% OTIF and 14-week lead time. "
            "Annual volume is 10,000 units."
        ),
        "evidence_answers": {},
        "checklist": [
            (has_field("supplier_comparison", min_items=2), "Supplier comparison table present for a quote comparison"),
            (lacks_field("cost_driver_comparison"), "Correctly no cost-driver comparison -- this is quote_comparison, not price_increase"),
            (has_field("why_this_wins"), "Trade-off summary present"),
        ],
    },
    {
        "name": "Genuinely underspecified case (evidence gate should fire)",
        "question": "Our supplier wants more money. What should we do?",
        "evidence_answers": {
            "current_price_or_terms": "not specified in original question, testing evidence gate",
            "requested_increase_percent": "unknown",
            "suppliers_stated_justification": "unspecified",
            "how_critical_is_this_supplier_relationship": "unknown",
        },
        "checklist": [
            (has_field("assumptions"), "Even with thin evidence, assumptions are still stated"),
            (has_field("confidence"), "Confidence still present, should reasonably be low or medium given thin evidence"),
        ],
    },
    {
        # Reused from a real, successful live test: a zip bundle of 6 files
        # (an email, 3 CSVs, 2 internal notes) proved the pipeline correctly
        # synthesizes multi-document input without a dedicated synthesis
        # stage. This case protects that specific, validated finding from
        # a future prompt change silently breaking it -- it's the
        # combined text as it actually appeared after real extraction,
        # not a fresh synthetic paraphrase.
        "name": "Multi-document synthesis (real zip-upload scenario, proven to work)",
        "question": (
            "--- File: Category_Risk_Assessment.txt ---\n"
            "Category: Hydraulic Valve Assemblies. Business Criticality: Very High. "
            "Fleet affected: 185 vessels. Inventory cover: 7 weeks. Off-hire cost: USD 1.8 million/week. "
            "Supplier A: 15-year relationship, USD 5.5M dedicated investment, USD 2.4M value engineering "
            "savings. Current ESG investigation: Open. Market outlook: two new competitors next year, "
            "ocean freight soft, USD strengthened 6%.\n\n"
            "--- File: Internal_Stakeholder_Notes.txt ---\n"
            "Operations: strongly prefers Supplier A, no disruption acceptable, excellent quality. "
            "Finance: 8% cost reduction target, reject double-digit increase. "
            "Engineering: Supplier B approved, 7-month requalification, packaging redesign required; "
            "Supplier C approved, can supply 35% today, more capacity next year. "
            "Legal: contract expires in 42 days.\n\n"
            "--- File: Supplier_A_Renewal_Email.txt ---\n"
            "Subject: Contract Renewal Proposal. We request an 11% price adjustment. "
            "Main drivers: Stainless Steel +18%, Energy +12%, Labour +9%, Freight +7%. "
            "We also request a 5-year contract extension, exclusive supplier status, and quarterly "
            "price adjustment linked to commodity movement.\n\n"
            "--- File: Market_Indices.csv ---\n"
            "Cost Driver,Supplier Claim %,Market Index %\n"
            "Steel,18,9\nEnergy,12,3\nLabour,9,4.5\nFreight,7,-6\nUSD Strengthening,,6\n\n"
            "--- File: Spend_Summary.csv ---\n"
            "Annual Volume,Current Price (USD),Annual Spend (USD)\n4800,3850,18480000\n\n"
            "--- File: Supplier_Quotes.csv ---\n"
            "Supplier,Unit Price (USD),OTIF %,Defect %,Lead Time (Weeks),Switching Cost (USD),Capacity\n"
            "Supplier A,3850,99.6,0.15,9,0,100%\nSupplier B,3520,97.4,0.90,16,1200000,100%\n"
            "Supplier C,3610,98.9,0.35,10,700000,35%"
        ),
        "evidence_answers": {
            # Covers both possible classifications defensively, since the
            # real live run revealed this scenario was actually classified
            # as quote_comparison (it asked for payment terms, a
            # quote_comparison-specific field) -- not price_increase as
            # might be assumed just from the incumbent's price-increase
            # email being one of the six files.
            "payment_terms_per_supplier": "not specified in any file -- this exact gap was correctly caught in the real live run",
            "quality_or_defect_history_per_supplier": "see Supplier_Quotes.csv defect rates already provided",
            "is_this_a_new_or_incumbent_relationship": "Supplier A is the 15-year incumbent; B and C are alternatives",
        },
        "checklist": [
            (financial_impact_equals(2032800), "Financial impact correctly computed as $2,032,800 (11% of $18.48M) -- proves correct cross-file arithmetic, not confused data"),
            (has_field("supplier_comparison", min_items=3), "All three suppliers correctly present in the comparison table"),
            (has_field("cost_driver_comparison", min_items=4), "All four cost drivers correctly compared, including the inverted freight direction"),
            (has_field("financial_scenarios"), "Multiple financial scenarios present, correctly synthesized across files"),
        ],
    },
]
