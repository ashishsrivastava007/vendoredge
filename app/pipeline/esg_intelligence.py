"""
Category Strategy / ESG architecture.

No live ESG data source, certification registry, or emissions database
exists anywhere in this environment. This module never looks up,
estimates, or fabricates an emissions figure, a certification, an ESG
score, a regulatory obligation, or a reduction target -- it only
reasons over ESGClaim evidence the case itself already stated (see
normalized_evidence.py's ESGClaim model).

Modeled directly on market_intelligence.py's proven chain and
guarantees -- same five-stage separation, same refusal to convert a
general observation into a specific supplier entitlement, same honest
"not established" default when a case states nothing:

ESG FACT             -- what the case states, exactly as stated
CATEGORY RELEVANCE   -- is this dimension/topic material to this
                        category at all, based on stated evidence
                        (never assumed material just because the
                        category exists)
SUPPLIER EXPOSURE    -- is this tied to a specific supplier, or is it
                        a general/category-wide observation
COMMERCIAL/REGULATORY IMPLICATION -- what this means for the decision,
                        including an explicit refusal to imply
                        certification, compliance, or performance that
                        wasn't stated
ACTION               -- what, if anything, this suggests doing next

If a case states no ESG evidence at all -- the overwhelming majority,
including the current Industrial Valves golden case -- this module
correctly produces nothing, not a placeholder ESG section.
"""
from __future__ import annotations
from typing import Any


def build_esg_reasoning(kernel: dict[str, Any]) -> dict[str, Any] | None:
    """Returns None when the case states no ESG claim at all -- the
    correct, honest, overwhelming-majority case. Never returns a
    placeholder structure pretending ESG analysis happened when the
    case gave no basis for it."""
    claims = kernel.get("case", {}).get("esg_claims") if isinstance(kernel.get("case"), dict) else None
    if not claims:
        return None

    subject = kernel.get("case", {}).get("subject")
    entries = [_reason_about_one_esg_claim(c, subject) for c in claims]
    return {"claims": entries}


def _establish_esg_supplier_scope(claim: dict[str, Any], subject: str | None) -> tuple[str | None, bool]:
    """Identical discipline to market_intelligence's
    _establish_supplier_scope: an ESG fact existing is never the same
    thing as a specific supplier's ESG exposure being established.
    Only an explicit applies_to_supplier, or the supplier's own stated
    claim, establishes scope."""
    explicit = claim.get("applies_to_supplier")
    if explicit:
        return explicit, True
    if claim.get("attributed_to") == "supplier" and subject:
        return subject, True
    return None, False


def _reason_about_one_esg_claim(claim: dict[str, Any], subject: str | None) -> dict[str, Any]:
    dimension = claim.get("dimension", "unspecified")
    topic = claim.get("topic", "unspecified topic")
    statement = claim.get("statement", "")
    scoped_supplier, supplier_established = _establish_esg_supplier_scope(claim, subject)

    # ESG FACT: exactly as stated, never upgraded into a certification,
    # score, or verified performance claim the case didn't actually make.
    esg_fact = statement or f"{dimension.capitalize()} claim regarding {topic}."
    if claim.get("direction"):
        esg_fact += f" (stated direction: {claim['direction']})"
    if claim.get("magnitude"):
        esg_fact += f" (stated magnitude: {claim['magnitude']})"
    if claim.get("geography"):
        esg_fact += f" (geography: {claim['geography']})"
    if claim.get("source"):
        esg_fact += f" (source: {claim['source']})"

    # CATEGORY RELEVANCE: stated plainly -- this module never asserts
    # materiality beyond what the claim itself demonstrates by
    # existing; it does not independently judge whether, say, water use
    # matters for this specific category beyond what was actually said.
    category_relevance = (
        f"A{'n' if dimension[0] in 'aeiou' else ''} {dimension} claim about {topic} exists in this case -- its materiality to this category is only "
        f"as established as the claim itself; this does not by itself confirm a broader company-wide obligation or exposure."
    )

    # SUPPLIER EXPOSURE
    if not supplier_established:
        supplier_exposure = f"No specific supplier's exposure on {topic} is established -- this is a general or category-wide observation, not yet tied to a named supplier."
    else:
        supplier_exposure = f"This claim is tied to {scoped_supplier}."

    # COMMERCIAL/REGULATORY IMPLICATION: the mandatory guard -- never
    # implies a certification, compliance status, or performance level
    # that wasn't explicitly stated, and never assumes a reduction
    # target or savings from an ESG initiative.
    requirement = claim.get("stated_requirement")
    if requirement:
        implication = f"A stated requirement exists ({requirement}) -- whether {scoped_supplier or 'the relevant supplier'} currently meets it is not established unless the case says so directly."
    elif not supplier_established:
        implication = f"{topic.capitalize()} is noted as a general observation -- it does not establish any specific supplier's compliance, certification, or performance level."
    else:
        implication = f"This does not establish {scoped_supplier}'s certification, compliance status, or performance level beyond what was explicitly stated."

    # ACTION: only ever a request for more evidence or a genuinely
    # supported next step -- never a fabricated target, savings claim,
    # or reduction commitment.
    action = "Evidence required before a specific ESG target, requirement, or commercial action can be recommended here."
    if requirement:
        action = f"Confirm {scoped_supplier or 'the relevant supplier'}'s current position against the stated requirement ({requirement}) before relying on it in the strategy or contract."

    return {
        "dimension": dimension,
        "topic": topic,
        "esg_fact": esg_fact,
        "category_relevance": category_relevance,
        "supplier_exposure": supplier_exposure,
        "implication": implication,
        "action": action,
        "applies_to_supplier": scoped_supplier if supplier_established else None,
    }


def build_esg_answer_section(kernel: dict[str, Any]) -> dict[str, Any] | None:
    """The buyer-facing ESG section -- plain language, no internal
    key/object names. Returns None when the case states no ESG claim,
    which is the honest, correct state for the current Industrial
    Valves golden case and the overwhelming majority of cases."""
    reasoning = build_esg_reasoning(kernel)
    if reasoning is None:
        return None
    return {
        "what_is_stated": [c["esg_fact"] for c in reasoning["claims"]],
        "category_relevance": [c["category_relevance"] for c in reasoning["claims"]],
        "supplier_exposure": [c["supplier_exposure"] for c in reasoning["claims"]],
        "what_this_means": [c["implication"] for c in reasoning["claims"]],
        "what_to_do_next": [c["action"] for c in reasoning["claims"]],
    }


# ---------------------------------------------------------------------
# Objective-type tagging -- commercial / risk / operational / ESG.
# Used only to LABEL an already-existing recommendation's objective
# type and flag a genuine trade-off between two objective types stated
# in the same strategy -- never to generate new recommendations, and
# never to assume all objectives align by default.
# ---------------------------------------------------------------------

def tag_objective_type(text: str) -> str:
    """A light, keyword-based classifier over recommendation text --
    good enough to label which objective a given item primarily serves
    for trade-off surfacing, not a claim of precise categorization."""
    lowered = text.lower()
    if any(k in lowered for k in ("emission", "carbon", "esg", "sustainab", "labour practice", "modern slavery", "traceability", "circular", "recycled")):
        return "esg"
    if any(k in lowered for k in ("risk", "contradiction", "unresolved", "unvalidated", "concentration", "single-source", "sole-source")):
        return "risk"
    if any(k in lowered for k in ("lead time", "otif", "capacity", "quality", "delivery", "logistics", "inventory")):
        return "operational"
    return "commercial"


def identify_objective_trade_offs(tagged_items: list[dict[str, str]]) -> list[str]:
    """Flags when two DIFFERENT objective types appear together in a
    way that could plausibly conflict -- e.g. an ESG-tagged item and a
    commercial-tagged item recommending opposite directions on the same
    supplier. Deliberately conservative: only flags when both an ESG
    and a commercial/risk item exist AND reference the same supplier
    name, since a genuine trade-off requires the same subject, not just
    the same strategy having multiple objective types present."""
    trade_offs = []
    esg_items = [i for i in tagged_items if i["objective_type"] == "esg"]
    other_items = [i for i in tagged_items if i["objective_type"] in ("commercial", "operational", "risk")]
    for e in esg_items:
        for o in other_items:
            e_words = set(e["text"].lower().split())
            o_words = set(o["text"].lower().split())
            shared_supplier_signal = any(w[0].isupper() and w in o["text"] for w in e["text"].split() if len(w) > 2 and w[0].isupper())
            if shared_supplier_signal:
                trade_offs.append(
                    f"Potential trade-off: \"{e['text']}\" (ESG) and \"{o['text']}\" ({o['objective_type']}) both concern the same supplier -- "
                    f"these may not automatically align and should be weighed together, not assumed compatible."
                )
    return trade_offs
