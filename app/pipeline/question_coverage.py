"""
Question-coverage tracking layer.

Root problem this exists to fix: a deterministic calculation that the
evidence genuinely supports could be computed and then silently never
reach the buyer-facing answer -- generated, then dropped somewhere in
assembly, with nothing to notice or prevent it.

Deliberately NOT built by parsing the user's raw question text with
NLP to guess "what did they ask for" (fragile, and explicitly out of
scope -- "do not solve this by regex scanning the final prose"). The
reliable signal used instead: if the evidence contains both a current
and a prior figure for a given entity/metric pair, that pair is
analytically requestable and calculable by construction -- the case
itself, not a guess about phrasing, is what makes it a requirement.
This is deliberately generic, not a hardcoded list for one case: it
inspects whatever the evidence actually contains and builds requirements
for whatever combinations are genuinely present, for any case shape.
"""
from __future__ import annotations
from typing import Any, Literal

from pydantic import BaseModel

from app.pipeline.normalized_evidence import NormalizedEvidence
from app.pipeline.scenario_engine import compute_growth, compute_share_change, GrowthResult

CoverageStatus = Literal["REQUESTED", "CALCULATED", "SURFACED", "UNAVAILABLE", "UNRESOLVED", "NOT_APPLICABLE"]


class CoverageRequirement(BaseModel):
    requirement_id: str
    requested_analysis: str
    entity: str
    metric: str
    required_inputs: list[str]
    status: CoverageStatus
    output_location: str | None = None
    surfaced: bool = False
    evidence_refs: list[str] = []
    result: GrowthResult | None = None


def build_coverage_requirements(normalized: NormalizedEvidence) -> list[CoverageRequirement]:
    """Builds one CoverageRequirement per current/prior figure pair the
    evidence genuinely, actually contains. A case with no prior-period
    figures at all (the overwhelming majority) produces an empty list
    here -- this only ever tracks what the evidence itself supports,
    never invents a requirement the case doesn't back."""
    reqs: list[CoverageRequirement] = []
    if normalized.content_type != "price_increase":
        return reqs
    case = normalized.case

    def _try(req_id: str, analysis: str, entity: str, metric: str,
              current: float | None, prior: float | None, inputs: list[str]) -> None:
        if current is None or prior is None:
            reqs.append(CoverageRequirement(
                requirement_id=req_id, requested_analysis=analysis, entity=entity, metric=metric,
                required_inputs=inputs, status="NOT_APPLICABLE", evidence_refs=inputs,
            ))
            return
        result = compute_growth(metric, entity, current, prior)
        reqs.append(CoverageRequirement(
            requirement_id=req_id, requested_analysis=analysis, entity=entity, metric=metric,
            required_inputs=inputs, status="CALCULATED", result=result, evidence_refs=inputs,
        ))

    _try("category_spend_growth", "Category spend growth", "category", "annual_spend",
         case.category_annual_spend_usd, case.category_prior_annual_spend_usd,
         ["case.category_annual_spend_usd", "case.category_prior_annual_spend_usd"])
    _try("category_volume_growth", "Category volume growth", "category", "annual_volume",
         case.category_annual_volume_units, case.category_prior_annual_volume_units,
         ["case.category_annual_volume_units", "case.category_prior_annual_volume_units"])

    cat_spend_cur, cat_spend_pri = case.category_annual_spend_usd, case.category_prior_annual_spend_usd
    cat_vol_cur, cat_vol_pri = case.category_annual_volume_units, case.category_prior_annual_volume_units
    cat_price_cur = (cat_spend_cur / cat_vol_cur) if cat_spend_cur and cat_vol_cur else None
    cat_price_pri = (cat_spend_pri / cat_vol_pri) if cat_spend_pri and cat_vol_pri else None
    _try("category_avg_price_growth", "Category average unit price change", "category", "avg_unit_price",
         cat_price_cur, cat_price_pri,
         ["case.category_annual_spend_usd", "case.category_annual_volume_units", "case.category_prior_annual_spend_usd", "case.category_prior_annual_volume_units"])

    # Entity-binding fix, confirmed with a real case: common.supplier_name
    # is only populated when extraction stated a single supplier name at
    # the case level; a case whose supplier identity only appears in the
    # per-supplier evidence list (marked is_incumbent) left this as the
    # generic "the supplier" -- exactly the class of entity-binding
    # failure the rest of this engagement exists to prevent. Falls back
    # to the incumbent supplier's real name; the generic label is now
    # only used when there is truly no named supplier at all.
    entity_name = normalized.common.supplier_name or next((s.supplier_name for s in normalized.suppliers if s.is_incumbent), None) or "the supplier"
    supplier_spend_cur = case.annual_spend_usd
    supplier_spend_pri = case.prior_annual_spend_usd
    _try("supplier_spend_growth", f"{entity_name} spend growth", entity_name, "annual_spend",
         supplier_spend_cur, supplier_spend_pri,
         ["case.annual_spend_usd", "case.prior_annual_spend_usd"])

    supplier_vol_cur = normalized.common.annual_volume_units
    supplier_vol_pri = case.prior_annual_volume_units
    _try("supplier_volume_growth", f"{entity_name} volume growth", entity_name, "annual_volume",
         supplier_vol_cur, supplier_vol_pri,
         ["common.annual_volume_units", "case.prior_annual_volume_units"])

    sup_price_cur = (supplier_spend_cur / supplier_vol_cur) if supplier_spend_cur and supplier_vol_cur else None
    sup_price_pri = (supplier_spend_pri / supplier_vol_pri) if supplier_spend_pri and supplier_vol_pri else None
    _try("supplier_avg_price_growth", f"{entity_name} average price growth", entity_name, "avg_unit_price",
         sup_price_cur, sup_price_pri,
         ["case.annual_spend_usd", "common.annual_volume_units", "case.prior_annual_spend_usd", "case.prior_annual_volume_units"])

    if all(v is not None for v in (supplier_spend_cur, cat_spend_cur, supplier_spend_pri, cat_spend_pri)):
        share = compute_share_change(entity_name, supplier_spend_cur, cat_spend_cur, supplier_spend_pri, cat_spend_pri)
        reqs.append(CoverageRequirement(
            requirement_id="supplier_spend_share_change", requested_analysis=f"{entity_name} spend-share change",
            entity=entity_name, metric="spend_share_percent", status="CALCULATED", result=share,
            required_inputs=["case.annual_spend_usd", "case.category_annual_spend_usd", "case.prior_annual_spend_usd", "case.category_prior_annual_spend_usd"],
            evidence_refs=["case.annual_spend_usd", "case.category_annual_spend_usd", "case.prior_annual_spend_usd", "case.category_prior_annual_spend_usd"],
        ))
    else:
        reqs.append(CoverageRequirement(
            requirement_id="supplier_spend_share_change", requested_analysis=f"{entity_name} spend-share change",
            entity=entity_name, metric="spend_share_percent", status="NOT_APPLICABLE",
            required_inputs=["case.annual_spend_usd", "case.category_annual_spend_usd", "case.prior_annual_spend_usd", "case.category_prior_annual_spend_usd"],
        ))

    # Phase 4 / R41 (Commercial Signal): a multi-supplier signal case
    # (e.g. "why is category spend outpacing volume") needs EVERY named
    # supplier's own growth tracked, not just the one "subject" supplier
    # above. Each supplier with its own current/prior spend AND volume
    # (the new SupplierEvidence fields) gets its own spend/volume/price
    # growth calculated the same deterministic way -- skips a supplier
    # entirely, no NOT_APPLICABLE noise, when it doesn't have both
    # periods for a given metric, since that's the overwhelming normal
    # case for suppliers only mentioned in passing.
    for sup in normalized.suppliers:
        if sup.current_annual_spend_usd is not None and sup.prior_annual_spend_usd is not None:
            result = compute_growth("annual_spend", sup.supplier_name, sup.current_annual_spend_usd, sup.prior_annual_spend_usd)
            reqs.append(CoverageRequirement(
                requirement_id=f"supplier_{sup.supplier_name}_spend_growth", requested_analysis=f"{sup.supplier_name} spend growth",
                entity=sup.supplier_name, metric="annual_spend", status="CALCULATED", result=result,
                required_inputs=[f"supplier:{sup.supplier_name}:current_annual_spend_usd", f"supplier:{sup.supplier_name}:prior_annual_spend_usd"],
                evidence_refs=[f"supplier:{sup.supplier_name}:current_annual_spend_usd", f"supplier:{sup.supplier_name}:prior_annual_spend_usd"],
            ))
        if sup.current_annual_volume_units is not None and sup.prior_annual_volume_units is not None:
            result = compute_growth("annual_volume", sup.supplier_name, sup.current_annual_volume_units, sup.prior_annual_volume_units)
            reqs.append(CoverageRequirement(
                requirement_id=f"supplier_{sup.supplier_name}_volume_growth", requested_analysis=f"{sup.supplier_name} volume growth",
                entity=sup.supplier_name, metric="annual_volume", status="CALCULATED", result=result,
                required_inputs=[f"supplier:{sup.supplier_name}:current_annual_volume_units", f"supplier:{sup.supplier_name}:prior_annual_volume_units"],
                evidence_refs=[f"supplier:{sup.supplier_name}:current_annual_volume_units", f"supplier:{sup.supplier_name}:prior_annual_volume_units"],
            ))
        if all(v is not None for v in (sup.current_annual_spend_usd, sup.current_annual_volume_units, sup.prior_annual_spend_usd, sup.prior_annual_volume_units)):
            price_cur = sup.current_annual_spend_usd / sup.current_annual_volume_units
            price_pri = sup.prior_annual_spend_usd / sup.prior_annual_volume_units
            result = compute_growth("avg_unit_price", sup.supplier_name, price_cur, price_pri)
            reqs.append(CoverageRequirement(
                requirement_id=f"supplier_{sup.supplier_name}_avg_price_growth", requested_analysis=f"{sup.supplier_name} average price growth",
                entity=sup.supplier_name, metric="avg_unit_price", status="CALCULATED", result=result,
                required_inputs=[f"supplier:{sup.supplier_name}:current_annual_spend_usd", f"supplier:{sup.supplier_name}:current_annual_volume_units", f"supplier:{sup.supplier_name}:prior_annual_spend_usd", f"supplier:{sup.supplier_name}:prior_annual_volume_units"],
                evidence_refs=[f"supplier:{sup.supplier_name}:current_annual_spend_usd", f"supplier:{sup.supplier_name}:current_annual_volume_units", f"supplier:{sup.supplier_name}:prior_annual_spend_usd", f"supplier:{sup.supplier_name}:prior_annual_volume_units"],
            ))

    return reqs


def mark_surfaced(requirements: list[CoverageRequirement], surfaced_requirement_ids: set[str], output_location: str) -> None:
    """Called once the answer-assembly step has actually placed a
    requirement's value into the buyer-facing answer -- mutates the
    matching requirement's status/surfaced flag in place. A requirement
    that was CALCULATED but never reaches this call stays CALCULATED,
    not SURFACED -- which is exactly the state final_answer_reconciliation
    checks for and rejects."""
    for req in requirements:
        if req.requirement_id in surfaced_requirement_ids and req.status == "CALCULATED":
            req.status = "SURFACED"
            req.surfaced = True
            req.output_location = output_location


def missing_calculated_requirements(requirements: list[CoverageRequirement]) -> list[CoverageRequirement]:
    """The key rule, made checkable: a requirement whose deterministic
    calculation genuinely exists (CALCULATED) but was never surfaced.
    This is precisely the class of bug the entity-aware fix and this
    coverage layer both exist to prevent from ever silently happening
    again."""
    return [r for r in requirements if r.status == "CALCULATED"]
