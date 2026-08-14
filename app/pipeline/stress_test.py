"""Deterministic commercial recommendation stress testing.

The model recommends; this module tries to invalidate the commercial logic using
only explicitly available normalized evidence and transparent hypothetical shocks.
Hypothetical shocks are labelled as scenarios, never presented as facts.
"""
from __future__ import annotations

from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence


def _price_change(spend: float, pct: float) -> float:
    return round(spend * pct / 100.0, 2)


def _supplier_name(position: CommercialPosition, suppliers) -> str | None:
    text = f"{position.recommendation} {position.reasoning}".lower()
    for s in suppliers:
        if s.supplier_name and s.supplier_name.lower() in text:
            return s.supplier_name
    return None


def build_stress_test(normalized: NormalizedEvidence, position: CommercialPosition) -> dict:
    """Return a deterministic challenge set, or an honest unavailable result.

    This is deliberately not an LLM second-opinion call. It tests numerical and
    structural pressure points only; it never invents freight, FX, duty, quality,
    capacity or market facts.
    """
    tests: list[dict] = []
    warnings: list[str] = []

    if normalized.content_type == "price_increase":
        spend = normalized.derived.resolved_annual_spend_usd
        requested = normalized.case.requested_increase_percent
        if spend is None or requested is None or not normalized.derived.currency_calculation_safe:
            return {
                "available": False,
                "status": "NOT_TESTABLE",
                "summary": "The recommendation cannot be numerically stress-tested safely from the available evidence.",
                "tests": [],
                "warnings": ["Safe annual spend and requested price-change evidence are incomplete or currency-unsafe."],
            }
        spend = float(spend)
        requested = float(requested)

        # Scenario shocks are explicitly hypothetical. They do not assert that
        # these outcomes will occur.
        for label, pct in (("No increase", 0.0), ("Requested increase", requested), ("2× requested increase", requested * 2.0)):
            impact = _price_change(spend, pct)
            tests.append({
                "name": label,
                "type": "price_shock",
                "scenario": f"If the supplier price changed by {pct:g}% while all other stated inputs stayed unchanged",
                "annual_impact_usd": impact,
                "result": "higher_cost" if pct > 0 else "baseline",
            })

        unresolved = []
        for supplier in normalized.suppliers:
            if supplier.supplier_name and supplier.qualification_status != "complete":
                unresolved.append(f"{supplier.supplier_name} qualification is not complete")
        if unresolved:
            warnings.extend(unresolved[:4])

        if position.disconfirming_condition:
            tests.append({
                "name": "Model-stated reversal condition",
                "type": "evidence_reversal",
                "scenario": position.disconfirming_condition,
                "annual_impact_usd": None,
                "result": "requires_new_evidence",
            })

    else:
        volume = normalized.common.annual_volume_units
        suppliers = [s for s in normalized.suppliers if s.price_usd is not None]
        if volume is None or len(suppliers) < 2:
            return {
                "available": False,
                "status": "NOT_TESTABLE",
                "summary": "The recommendation cannot be allocation-stress-tested safely: at least two explicit supplier prices and annual volume are required.",
                "tests": [],
                "warnings": [],
            }
        if not all((s.currency or "").upper() in {"USD", "US DOLLAR", "US DOLLARS"} for s in suppliers):
            return {
                "available": False,
                "status": "NOT_TESTABLE",
                "summary": "Allocation stress testing is disabled because supplier currencies are not all explicitly USD.",
                "tests": [],
                "warnings": ["No FX assumptions are permitted."],
            }

        # Only test the two lowest explicitly priced suppliers. We never assume
        # that a third supplier can replace either one.
        suppliers = sorted(suppliers, key=lambda s: float(s.price_usd))[:2]
        a, b = suppliers
        for share in (0, 25, 50, 75, 100):
            spend = round(float(volume) * (share / 100 * float(a.price_usd) + (1 - share / 100) * float(b.price_usd)), 2)
            tests.append({
                "name": f"{a.supplier_name} {share}% / {b.supplier_name} {100-share}%",
                "type": "allocation_shock",
                "scenario": f"Hypothetical allocation with {a.supplier_name} at {share}% and {b.supplier_name} at {100-share}%",
                "annual_spend_usd": spend,
                "result": "lower_spend" if spend < float(volume) * max(float(a.price_usd), float(b.price_usd)) else "higher_or_equal_spend",
            })
        for s in suppliers:
            if s.capacity_percent is not None and s.capacity_percent < 100:
                warnings.append(f"{s.supplier_name} has an explicitly stated {s.capacity_percent:g}% capacity ceiling; full substitution is not assumed feasible.")

        if position.disconfirming_condition:
            tests.append({
                "name": "Model-stated reversal condition",
                "type": "evidence_reversal",
                "scenario": position.disconfirming_condition,
                "annual_spend_usd": None,
                "result": "requires_new_evidence",
            })

    # The stress result is deliberately conservative: unresolved material
    # conditions make the recommendation "SENSITIVE" rather than pretending
    # the available scenarios prove robustness.
    if not tests:
        status = "NOT_TESTABLE"
    elif warnings:
        status = "SENSITIVE"
    else:
        status = "SURVIVES_AVAILABLE_TESTS"

    return {
        "available": bool(tests),
        "status": status,
        "summary": {
            "SURVIVES_AVAILABLE_TESTS": "The recommendation has no unresolved structural warning in the scenarios that can be tested from stated evidence.",
            "SENSITIVE": "The recommendation has one or more explicit evidence constraints that could materially change the decision.",
            "NOT_TESTABLE": "The available evidence is insufficient for a safe deterministic stress test.",
        }[status],
        "tests": tests[:8],
        "warnings": warnings[:6],
        "method": "Deterministic what-if scenarios using stated evidence only; hypothetical shocks are not predictions and no missing commercial inputs are invented.",
    }
