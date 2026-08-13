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
"""
from app.models import FinancialImpact
from app.pipeline.normalized_evidence import NormalizedEvidence


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

    # Production Hardening fix for the confirmed red-team finding:
    # structurally refuses to calculate when a real currency mismatch
    # exists and no genuine "$" figure was ever stated -- this makes it
    # impossible for the guaranteed calculation to silently treat a
    # foreign-currency number as if it were already in USD.
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

    potential_annual_impact = round(spend * (percent / 100), 2)

    switching_cost = normalized.case.switching_cost_usd
    net_exposure = None
    note = (
        f"${spend:,.0f} annual spend x {percent:g}% requested change "
        f"= ${potential_annual_impact:,.0f} potential annual impact."
    )
    if switching_cost is not None:
        try:
            switching_cost = float(switching_cost)
            net_exposure = round(potential_annual_impact - switching_cost, 2)
            note += (
                f" Against an estimated ${switching_cost:,.0f} switching cost, "
                f"net exposure difference = ${net_exposure:,.0f}."
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
                f"${annual_duty_cost:,.0f}/year in landed cost, on top of the "
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
                f" A stated freight cost of ${float(freight_per_unit):,.2f}/unit adds an "
                f"estimated ${annual_freight_cost:,.0f}/year in landed cost."
            )
        except (TypeError, ValueError):
            annual_freight_cost = None

    return FinancialImpact(
        annual_spend_usd=spend,
        requested_change_percent=percent,
        potential_annual_impact_usd=potential_annual_impact,
        switching_cost_usd=switching_cost,
        net_exposure_usd=net_exposure,
        annual_duty_cost_usd=annual_duty_cost,
        annual_freight_cost_usd=annual_freight_cost,
        note=note,
    )
