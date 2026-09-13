"""
A reusable, currency-safe deterministic scenario/economics engine.

Built to fix a specific, proven gap: the Industrial Valves & Actuators
golden case needs three numbers together -- an 11% scenario, a 7%
scenario, and the EUR 222,000 difference between them -- and the
existing financial.py can only ever compute one percentage at a time,
handing callers no way to relate two calculated results to each other
except by re-deriving the delta themselves outside the deterministic
boundary. That "compute twice, subtract in prose" pattern is exactly
the kind of thing this whole codebase's Hard Rule 1 exists to prevent:
if code can do arithmetic, code does the arithmetic, not the model,
and not a second, uncoordinated call site.

Deliberately NOT specific to "price increase". A Scenario is any named,
deterministic change applied to a baseline Money amount -- a discount,
a volume change, an alternative-supplier price, anything expressible as
a percentage or an absolute delta against one baseline. Nothing here
knows what a "price increase" or "requested_increase_percent" is; that
mapping lives in financial.py, which is the one place price-increase
evidence gets translated into a scenario request. This keeps the engine
itself honestly general rather than a price-increase calculator with a
generic-sounding name.

No FX conversion, anywhere in this module, ever. Combining two
scenarios (for a comparison) requires them to share a currency; if they
don't, that is a hard error, not a silent guess.
"""
from typing import Literal, Optional

from pydantic import BaseModel

from app.pipeline.money import Money

ChangeType = Literal["percent", "absolute"]


class Scenario(BaseModel):
    """One named, deterministic change against a baseline. `state` is
    always CALCULATED for anything this module returns -- there is no
    path through this file that produces an estimated or assumed
    result, consistent with every other deterministic engine in this
    codebase."""

    name: str
    change_type: ChangeType
    change_value: float  # a percent (e.g. 11.0 for 11%) or an absolute Money delta
    baseline: Money
    result: Money
    delta: Money  # result - baseline, same currency, always
    formula: str
    state: Literal["CALCULATED"] = "CALCULATED"


class ScenarioComparison(BaseModel):
    """Two scenarios against the same baseline, with their own
    difference computed once, here, rather than left for a caller (or
    worse, a model) to re-derive."""

    scenario_a: Scenario
    scenario_b: Scenario
    delta_amount: Money  # scenario_a.delta - scenario_b.delta, i.e. the "prize"
    comparison_basis: str
    state: Literal["CALCULATED"] = "CALCULATED"


def compute_scenario(
    name: str,
    baseline: Money,
    change_type: ChangeType,
    change_value: float,
) -> Scenario:
    """The one place a scenario's arithmetic happens. `change_value` is
    a percent (positive for an increase, negative for a decrease/
    discount -- there is no separate "discount" change_type, a discount
    is simply a negative percent or a negative absolute delta) or an
    absolute Money amount, matching change_type.

    Zero and negative changes are both fully supported and not treated
    as edge cases needing special handling -- a 0% scenario and a -5%
    scenario go through the identical arithmetic path as an 11%
    scenario."""
    if change_type == "percent":
        delta_amount = round(baseline.amount * (change_value / 100), 2)
        formula = f"{baseline.currency} {baseline.amount:,.0f} x {change_value:g}% = {baseline.currency} {delta_amount:,.0f}"
    else:
        delta_amount = round(change_value, 2)
        formula = f"{baseline.currency} {baseline.amount:,.0f} + {baseline.currency} {delta_amount:,.0f} (absolute)"

    result_amount = round(baseline.amount + delta_amount, 2)
    return Scenario(
        name=name,
        change_type=change_type,
        change_value=change_value,
        baseline=baseline,
        result=Money(amount=result_amount, currency=baseline.currency),
        delta=Money(amount=delta_amount, currency=baseline.currency),
        formula=formula,
    )


def compare_scenarios(scenario_a: Scenario, scenario_b: Scenario) -> ScenarioComparison:
    """The engine calculates the relationship itself -- callers never
    subtract two scenario results by hand. Requires both scenarios to
    share a currency and a baseline amount (i.e. both scenarios are
    genuinely about the same underlying spend); anything else is a
    caller error, surfaced as a hard ValueError rather than a silently
    wrong comparison."""
    if scenario_a.baseline.currency != scenario_b.baseline.currency:
        raise ValueError(
            f"Cannot compare a {scenario_a.baseline.currency} scenario against a "
            f"{scenario_b.baseline.currency} scenario without an explicit FX rate."
        )
    if scenario_a.baseline.amount != scenario_b.baseline.amount:
        raise ValueError(
            "Cannot compare two scenarios with different baseline amounts -- "
            "they are not variations of the same underlying spend."
        )
    delta = scenario_a.delta - scenario_b.delta
    return ScenarioComparison(
        scenario_a=scenario_a,
        scenario_b=scenario_b,
        delta_amount=delta,
        comparison_basis=f"{scenario_a.name} vs {scenario_b.name}, same {scenario_a.baseline.currency} baseline",
    )


class GrowthResult(BaseModel):
    """A generic current-vs-prior comparison. Deliberately not specific
    to spend, volume, or price -- one reusable primitive for "how much
    did X change year over year", used identically for category spend,
    category volume, supplier spend, supplier volume, and (by dividing
    two GrowthResults' current/prior pairs) average price and spend
    share. Built because none of these existed anywhere in the codebase
    before this fix -- there was no YoY growth calculation of any kind,
    for either a category or a specific supplier."""
    metric: str
    entity: str
    current: float
    prior: float
    absolute_change: float
    percent_change: Optional[float] = None  # None only when prior is genuinely 0 -- division by zero is never silently coerced to a number
    state: Literal["CALCULATED"] = "CALCULATED"


def compute_growth(metric: str, entity: str, current: float, prior: float) -> GrowthResult:
    """The one place year-over-year growth arithmetic happens, for any
    entity and any metric. Never estimates, never infers -- both current
    and prior must be genuinely, deterministically known numbers before
    this is ever called."""
    absolute_change = round(current - prior, 4)
    percent_change = round((absolute_change / prior) * 100, 2) if prior else None
    return GrowthResult(
        metric=metric, entity=entity, current=current, prior=prior,
        absolute_change=absolute_change, percent_change=percent_change,
    )


def compute_share_change(entity: str, current_part: float, current_whole: float, prior_part: float, prior_whole: float) -> GrowthResult:
    """Point-change in one entity's share of a whole (e.g. a supplier's
    share of category spend), current period vs prior period. Returns
    the share itself as `current`/`prior` (already expressed as a
    percentage, e.g. 66.07 not 0.6607) and the point-change as
    `absolute_change` -- percent_change is deliberately left None here,
    since "percent change in a percentage-point figure" is not a
    meaningful, commonly-understood number and would risk being
    misread as something it isn't."""
    current_share = round((current_part / current_whole) * 100, 4) if current_whole else None
    prior_share = round((prior_part / prior_whole) * 100, 4) if prior_whole else None
    if current_share is None or prior_share is None:
        return GrowthResult(metric="spend_share_percent", entity=entity, current=0, prior=0, absolute_change=0, percent_change=None)
    return GrowthResult(
        metric="spend_share_percent", entity=entity, current=current_share, prior=prior_share,
        absolute_change=round(current_share - prior_share, 2), percent_change=None,
    )
