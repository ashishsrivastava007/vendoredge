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
from typing import Literal

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
