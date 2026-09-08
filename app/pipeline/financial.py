"""
Deterministic financial impact calculation. This is the real fix for a
repeated, validated finding: asking an LLM to "show its math" in prose is
not reliable enough on its own, even with an explicit hard rule telling it
to. The same lesson was already learned once with confidence scores
(Hard Rule 2) -- the durable fix is always to move the requirement out of
the prompt and into code wherever the underlying values are genuinely
available, so it can never be silently skipped, forgotten, or done
inconsistently.

MIGRATED (NormalizedEvidence architecture): this function no longer
derives annual spend from unit price x volume itself -- that derivation
happens exactly once, in normalize_evidence(), and is read here as
normalized.derived.resolved_annual_spend_usd. Same for the parsed
freight-per-unit figure. This function's only job now is the arithmetic
itself, not re-deciding what the inputs mean.

CURRENCY FIX: this function previously hardcoded every displayed amount
with a literal "$", and normalize.py's own safety gate refused to
calculate at all for a case genuinely, consistently denominated in a
non-USD currency (see normalize.py's currency_calculation_safe fix for
the full root-cause trace). Both are fixed here: the actual currency is
read from normalized.common.supplier_currency (falling back to the
existing conventional USD default only when no currency was stated at
all), and every number below is produced by the currency-safe
Money/scenario_engine primitives rather than an f-string with a baked-in
symbol. The "_usd"-suffixed fields on FinancialImpact are legacy and are
only ever populated when the case's real currency genuinely is USD.

SCENARIO FIX: this function previously could only ever represent one
percentage at a time. When the evidence contains a second, comparable
scenario (normalized.case.alternative_scenario_percent -- e.g. a
supplier's conditional offer), this now computes both scenarios AND
their structured comparison in one pass, via scenario_engine, rather
than requiring a caller (or a model) to invoke this twice and subtract
the results by hand.
"""
from app.models import FinancialImpact
from app.pipeline.normalized_evidence import NormalizedEvidence
from app.pipeline.money import Money, currency_symbol
from app.pipeline.scenario_engine import compute_scenario, compare_scenarios


def compute_financial_impact(normalized: NormalizedEvidence) -> FinancialImpact | None:
    """
    Returns a FinancialImpact if the minimum required numbers (resolved
    annual spend and requested change percent) are present, else None --
    never fabricates a value for a number that wasn't genuinely supplied,
    consistent with Hard Rule 1.

    Only meaningful for price_increase cases -- quote_comparison has no
    equivalent spend/percent fields in its evidence schema, so this
    correctly returns None immediately for that content_type, exactly
    matching pre-migration behavior.
    """
    if normalized.content_type != "price_increase":
        return None

    # Fixed: previously refused calculation for ANY explicitly stated
    # currency unless a literal "$" also appeared in the raw text -- see
    # normalize.py's currency_calculation_safe for the full fix. This
    # flag now correctly means "genuine ambiguity was detected", not
    # "a non-USD currency was mentioned at all".
    if not normalized.derived.currency_calculation_safe:
        return None

    spend = normalized.derived.resolved_annual_spend_usd
    percent = normalized.case.requested_increase_percent
    if spend is None or percent is None:
        return None

    try:
        spend = float(spend)
        percent = float(percent)
    except (TypeError, ValueError):
        return None

    # The real currency the resolved spend figure is in -- computed once
    # in normalize.py with the correct priority (see DerivedEvidence.
    # spend_currency), not re-derived here.
    currency = normalized.derived.spend_currency.upper()
    baseline = Money(amount=spend, currency=currency)

    primary = compute_scenario("Requested change", baseline, "percent", percent)
    potential_annual_impact = primary.delta.amount

    scenario_comparison = None
    alt_percent = normalized.case.alternative_scenario_percent
    if alt_percent is not None:
        try:
            alt_percent = float(alt_percent)
            alt_label = normalized.case.alternative_scenario_label or "Alternative scenario"
            alternative = compute_scenario(alt_label, baseline, "percent", alt_percent)
            scenario_comparison = compare_scenarios(primary, alternative)
        except (TypeError, ValueError):
            scenario_comparison = None

    sym = currency_symbol(currency)
    note = (
        f"{sym}{spend:,.0f} annual spend x {percent:g}% requested change "
        f"= {sym}{potential_annual_impact:,.0f} potential annual impact."
    )
    if scenario_comparison is not None:
        note += (
            f" A named alternative scenario ({scenario_comparison.scenario_b.name}, "
            f"{scenario_comparison.scenario_b.change_value:g}%) would instead be "
            f"{sym}{scenario_comparison.scenario_b.delta.amount:,.0f}/year -- a "
            f"{sym}{scenario_comparison.delta_amount.amount:,.0f}/year difference "
            f"between the two scenarios."
        )

    switching_cost = normalized.case.switching_cost_usd
    net_exposure = None
    if switching_cost is not None:
        try:
            switching_cost = float(switching_cost)
            net_exposure = round(potential_annual_impact - switching_cost, 2)
            note += (
                f" Against an estimated {sym}{switching_cost:,.0f} switching cost, "
                f"net exposure difference = {sym}{net_exposure:,.0f}."
            )
        except (TypeError, ValueError):
            switching_cost = None

    duty_percent = normalized.common.duty_or_tax_rate_percent
    annual_duty_cost = None
    if duty_percent is not None:
        try:
            duty_percent = float(duty_percent)
            annual_duty_cost = round(spend * (duty_percent / 100), 2)
            note += (
                f" A stated {duty_percent:g}% duty/import tax adds an estimated "
                f"{sym}{annual_duty_cost:,.0f}/year in landed cost, on top of the "
                f"price impact above."
            )
        except (TypeError, ValueError):
            annual_duty_cost = None

    freight_per_unit = normalized.derived.freight_cost_per_unit_usd
    annual_volume = normalized.common.annual_volume_units
    annual_freight_cost = None
    if freight_per_unit is not None and annual_volume is not None:
        try:
            annual_freight_cost = round(float(freight_per_unit) * float(annual_volume), 2)
            note += (
                f" A stated freight cost of {sym}{float(freight_per_unit):,.2f}/unit adds an "
                f"estimated {sym}{annual_freight_cost:,.0f}/year in landed cost."
            )
        except (TypeError, ValueError):
            annual_freight_cost = None

    is_usd = currency == "USD"
    return FinancialImpact(
        currency=currency,
        annual_spend=spend,
        potential_annual_impact=potential_annual_impact,
        switching_cost=switching_cost,
        net_exposure=net_exposure,
        annual_duty_cost=annual_duty_cost,
        annual_freight_cost=annual_freight_cost,
        scenario_comparison=scenario_comparison,
        requested_change_percent=percent,
        # Legacy USD-only mirror -- populated only when the case genuinely
        # is USD, never repurposed to carry a EUR/GBP amount under a USD name.
        annual_spend_usd=spend if is_usd else None,
        potential_annual_impact_usd=potential_annual_impact if is_usd else None,
        switching_cost_usd=switching_cost if is_usd else None,
        net_exposure_usd=net_exposure if is_usd else None,
        annual_duty_cost_usd=annual_duty_cost if is_usd else None,
        annual_freight_cost_usd=annual_freight_cost if is_usd else None,
        note=note,
    )
