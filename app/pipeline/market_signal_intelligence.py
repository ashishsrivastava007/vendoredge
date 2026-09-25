"""
Market Signal Intelligence -- Phase 1 foundation.

Target capability: given ANY external signal (a supplier claim, a news
item, a LinkedIn post, a regulatory development, a technology shift --
anything with POTENTIAL procurement relevance), determine what the
user is really asking, what must be investigated, which dimensions
genuinely matter for THIS problem, what evidence supports or
contradicts the signal, what changed, how it could affect procurement,
and what to do next -- without a fixed industry taxonomy and without a
fixed response template.

Architecture (see the Phase 1 design note for the full rationale):

    understand_and_plan()      -- LLM call. Signal understanding +
                                   validation-target flagging +
                                   evidence-gap discovery + dimension
                                   discovery, combined into one
                                   structured response (these are all
                                   "what do we need to figure out"
                                   questions an analyst asks together
                                   before research begins).
    build_research_plan()      -- deterministic. Caps research volume
                                   (cost control), builds search
                                   prompts.
    execute_research()         -- deterministic orchestration, reuses
                                   app/research_tool.py directly. Never
                                   blocks; each call independently
                                   try/excepted.
    classify_evidence()        -- deterministic. Assigns evidence_state
                                   from the EXISTING 9-value taxonomy
                                   based on what a search actually
                                   returned -- never self-reported by
                                   the model. This is the central
                                   fabrication guardrail.
    synthesize_and_translate() -- LLM call, SEPARATE from the first.
                                   Receives findings with evidence_state
                                   already fixed in the prompt (cannot
                                   be upgraded). Produces per-dimension
                                   impact, procurement translation (or
                                   an explicit "not established"), and
                                   decision analysis.
    build_dynamic_answer()     -- deterministic. Section inclusion
                                   decided by which upstream outputs
                                   are genuinely non-empty -- never a
                                   fixed heading list.

Dimensions are free text discovered per-problem by the LLM in
understand_and_plan() -- validated only for SHAPE (non-empty, a
plausible short label), never checked against a fixed list. This is
the direct fix for fresh_intelligence.py's fixed seven-section
template, which this module does not inherit.

Provider independence: every LLM call goes through get_llm_client();
every search goes through get_research_tool() (app/research_tool.py,
unchanged). No new provider-specific code anywhere in this module.
"""
from __future__ import annotations
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

from app.llm_client import get_llm_client
from app.research_tool import get_research_tool
from app.model_config import MARKET_MODEL

PROVIDER_OPERATION_TIMEOUT_SECONDS = 20 * 60
_MAX_RESEARCH_QUESTIONS = 3  # cost control, matching this codebase's "near-zero cash cost" discipline elsewhere

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set.")
        _client = get_llm_client(api_key, PROVIDER_OPERATION_TIMEOUT_SECONDS)
    return _client


def _extract_text(response) -> str:
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _extract_json_object(text: str) -> dict | None:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------
# Stage 1: signal understanding + validation-target flagging +
# evidence-gap discovery + dimension discovery (responsibilities 1-4)
# ---------------------------------------------------------------------

_UNDERSTAND_SYSTEM_PROMPT = """You are the signal-understanding component of a procurement intelligence system. You do not answer the user's question or perform any research yourself -- you only analyze the signal and plan what must be investigated.

VendorEdge is sector-agnostic and category-agnostic. Do NOT assume any particular industry. Discover what matters for THIS specific signal -- do not reuse a template from a different domain.

Respond with ONLY a JSON object, no other text, shaped exactly as:
{
  "actual_question": "a precise restatement of what the user is actually asking, in your own words",
  "claimed_facts": ["each distinct factual claim the signal makes or implies, stated plainly"],
  "entities": ["companies, suppliers, categories, or specific things named in the signal"],
  "category_context": "the procurement category this most plausibly concerns, or null if none is identifiable",
  "research_questions": [
    {"question": "a specific, checkable question", "why_it_matters": "why the answer could change the conclusion"}
  ],
  "dimensions": [
    {"dimension": "a short, specific label for an analytical angle genuinely relevant to THIS signal (e.g. 'fabrication capacity expansion', 'contract renewal mechanics', 'regulatory compliance timeline' -- invent whatever label actually fits; do not pick from a fixed list)", "why_relevant": "why this dimension matters for this specific signal"}
  ]
}

Rules:
- claimed_facts must be things the signal itself states or clearly implies -- never things you already believe to be true from your own knowledge.
- research_questions: only include a question whose answer could plausibly change the conclusion. 1-3 questions is normal; do not pad the list.
- dimensions: only include dimensions genuinely relevant to this specific signal. A simple, narrow signal may have only one relevant dimension. Do not force a fixed set of categories (strategic/commercial/operational/etc.) onto every signal -- invent the dimension names that actually fit this problem.
- If the signal has no plausible procurement relevance at all, dimensions and research_questions may both be empty arrays -- that is a valid, correct result, not a failure."""


def understand_and_plan(raw_question: str) -> dict[str, Any] | None:
    """Stage 1 (responsibilities 1-4). Returns None on any failure --
    the caller must degrade gracefully, never fabricate an
    understanding."""
    try:
        client = _get_client()
        response = client.messages.create(
            model=MARKET_MODEL,
            max_tokens=1200,
            system=_UNDERSTAND_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Signal: {raw_question}"}],
        )
        parsed = _extract_json_object(_extract_text(response))
        if not parsed:
            return None
        # Deterministic shape validation only -- never validates
        # dimension CONTENT against a fixed list, per the explicit
        # "sector-agnostic, dimensions discovered not hardcoded"
        # requirement.
        dimensions = [d for d in (parsed.get("dimensions") or []) if isinstance(d, dict) and str(d.get("dimension", "")).strip()]
        research_questions = [q for q in (parsed.get("research_questions") or []) if isinstance(q, dict) and str(q.get("question", "")).strip()][:_MAX_RESEARCH_QUESTIONS]
        return {
            "actual_question": str(parsed.get("actual_question") or raw_question).strip(),
            "claimed_facts": [str(f).strip() for f in (parsed.get("claimed_facts") or []) if str(f).strip()],
            "entities": [str(e).strip() for e in (parsed.get("entities") or []) if str(e).strip()],
            "category_context": (str(parsed.get("category_context")).strip() if parsed.get("category_context") else None),
            "research_questions": research_questions,
            "dimensions": dimensions,
        }
    except Exception as e:
        print(f"Market signal understanding skipped (non-blocking): {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------
# Stage 2: research plan (responsibility 5) -- deterministic
# ---------------------------------------------------------------------

def build_research_plan(signal_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Caps research volume (cost control) and builds the actual
    search prompt for each planned item. Never itself calls a search
    -- purely deterministic construction from what understand_and_plan
    already proposed."""
    if not signal_plan:
        return []
    plan = []
    for q in signal_plan.get("research_questions", [])[:_MAX_RESEARCH_QUESTIONS]:
        question = q.get("question", "").strip()
        if not question:
            continue
        prompt = (
            f"Using web search, investigate this specific question: \"{question}\" "
            f"Context: {signal_plan.get('actual_question', '')}. "
            f"Respond with ONLY a JSON object, no other text: "
            f'{{"answer_found": true or false, "finding": "what the search actually found, in plain language, or empty string if nothing found", '
            f'"evidence_proposition": {{'
            f'"subject": "who/what the evidence is actually about, precisely -- e.g. \'global steel market\', \'Supplier X\', \'the regulator\' -- never the buyer/customer unless the evidence is genuinely about them specifically", '
            f'"predicate": "the core claim/action in a few words, e.g. \'price increased\', \'no measurable change\', \'capacity expanded\'", '
            f'"quantitative_value": "the specific number/percentage/amount the evidence itself states, or null if none", '
            f'"scope": "global_market | regional_market | supplier_specific | customer_specific | industry_general", '
            f'"geography": "the specific geography the evidence covers, or null if global/unspecified", '
            f'"timeframe": "the specific time period the evidence covers, or null if unspecified", '
            f'"negated": true or false (true ONLY if the evidence explicitly states the predicate did NOT happen, e.g. \'prices did not increase\'), '
            f'"attribution": "verified_fact | official_source | third_party_report | supplier_claim | unclear"'
            f'}}, '
            f'"supports_or_contradicts_signal": "supports | contradicts | inconclusive | not_applicable", '
            f'"sources": [{{"title": "source name", "url": "https://..."}}]}}'
        )
        plan.append({"question": question, "why_it_matters": q.get("why_it_matters", ""), "prompt": prompt})
    return plan


# ---------------------------------------------------------------------
# Stage 3: research execution (responsibility 6) -- reuses
# research_tool.py directly, deterministic orchestration only
# ---------------------------------------------------------------------

def _parse_evidence_proposition(raw: Any) -> dict[str, Any]:
    """Deterministic shape validation for the LLM-extracted structured
    proposition -- fails closed to the most conservative defaults
    (unclear attribution, industry_general scope, not negated, no
    quantity) on any malformed or missing field, never guesses a
    stronger value than what was actually given."""
    if not isinstance(raw, dict):
        raw = {}
    valid_scopes = {"global_market", "regional_market", "supplier_specific", "customer_specific", "industry_general"}
    valid_attributions = {"verified_fact", "official_source", "third_party_report", "supplier_claim", "unclear"}
    scope = raw.get("scope") if raw.get("scope") in valid_scopes else "industry_general"
    attribution = raw.get("attribution") if raw.get("attribution") in valid_attributions else "unclear"
    return {
        "subject": str(raw.get("subject") or "").strip(),
        "predicate": str(raw.get("predicate") or "").strip(),
        "quantitative_value": str(raw.get("quantitative_value")).strip() if raw.get("quantitative_value") else None,
        "scope": scope,
        "geography": str(raw.get("geography")).strip() if raw.get("geography") else None,
        "timeframe": str(raw.get("timeframe")).strip() if raw.get("timeframe") else None,
        "negated": bool(raw.get("negated") is True),
        "attribution": attribution,
    }


def _span_exists(span: str | None, source_text: str) -> bool:
    """Deterministic check: is the claimed span an actual substring of
    the source text (normalized for whitespace/case)? A hallucinated
    span -- one the extraction claims exists but doesn't -- fails
    this immediately, independent of anything else."""
    if not span or not source_text:
        return False
    norm_span = re.sub(r"\s+", " ", span).strip().lower()
    norm_source = re.sub(r"\s+", " ", source_text).strip().lower()
    return bool(norm_span) and norm_span in norm_source


_VERIFY_SYSTEM_PROMPT = """You are an independent verification component. You are given ONLY a piece of source text -- you have NOT seen any prior extraction or analysis of it, and you must form your own judgment from the text alone, as if reading it for the first time. Do not assume any of these things are true merely because they are asked about; answer based only on what the text actually states.

Respond with ONLY a JSON object, no other text:
{
  "negates_claim": true or false (true ONLY if the text explicitly states something did NOT happen, was NOT the case, remained unchanged, or was denied -- e.g. "prices did not rise," "the company denies," "no requirement was introduced"),
  "asserts_causation": true or false (true ONLY if the text explicitly states or clearly implies one thing CAUSED, EXPLAINED, JUSTIFIED, VALIDATED, or DROVE another -- not merely that two things are both mentioned or happened around the same time),
  "asserts_entitlement": true or false (true ONLY if the text explicitly states a party IS JUSTIFIED, ENTITLED, PERMITTED, or HAS GROUNDS to do something -- a normative/contractual claim, not merely a factual one),
  "is_self_report": true or false (true if the text is presenting a claim made BY the entity it concerns, ABOUT ITSELF -- e.g. a supplier's own statement about its own costs -- rather than an independent third party reporting on it),
  "subject": "who/what this text is actually about, precisely -- e.g. 'global steel market', 'Supplier A', 'the buyer' -- be precise: if the text discusses multiple entities (e.g. a market AND a specific supplier separately), identify the MAIN subject of the primary claim, not whichever entity happens to be mentioned",
  "predicate": "the core claim/action in a few words, in your own reading of the text",
  "quantitative_value": "the specific number/percentage/amount THIS text itself states for its main claim, or null if none",
  "scope": "global_market | regional_market | supplier_specific | customer_specific | industry_general -- based only on what this text itself establishes",
  "geography": "the specific geography this text itself states, or null if the text does not specify one",
  "timeframe": "the specific time period this text itself states (e.g. 'this quarter', '2024', or null if the text does not specify one) -- do not assume 'current' unless the text says so"
}"""


def independently_extract_proposition(source_text: str) -> dict[str, Any] | None:
    """M1.5.2: the verifier is now a full SECOND, INDEPENDENT
    EXTRACTION -- not a narrower "please check this claim" question,
    which the spec explicitly warns risks anchoring bias. Given only
    the raw source text, it produces its own reading of every material
    field, blind to what the first pass claimed. reconcile_dual_
    extraction() then deterministically compares the two independent
    readings; agreement is what earns trust, not either pass alone.

    This directly closes the "span exists but doesn't support the
    claimed proposition" gap: if pass 1 wrongly claims subject=
    "Supplier A" for a sentence that's actually about the whole
    market, pass 2 -- reading fresh, with no knowledge of pass 1's
    claim -- has a genuine, independent chance to identify the correct
    subject, and the two will disagree, triggering rejection rather
    than silent agreement.

    Returns None on any failure -- see reconcile_dual_extraction for
    how callers must treat an unreachable second opinion (never as a
    free pass for the first one)."""
    try:
        client = _get_client()
        response = client.messages.create(
            model=MARKET_MODEL, max_tokens=500, system=_VERIFY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Source text: {source_text}"}],
        )
        parsed = _extract_json_object(_extract_text(response))
        if not parsed:
            return None
        result = _parse_evidence_proposition(parsed)
        result["negates_claim"] = bool(parsed.get("negates_claim") is True)
        result["asserts_causation"] = bool(parsed.get("asserts_causation") is True)
        result["asserts_entitlement"] = bool(parsed.get("asserts_entitlement") is True)
        result["is_self_report"] = bool(parsed.get("is_self_report") is True)
        return result
    except Exception as e:
        print(f"Market signal independent verification skipped (non-blocking): {type(e).__name__}: {e}")
        return None


# Backward-compatible alias -- M1.5.1 code and tests call this name;
# the function now does strictly more (full dual extraction rather
# than four narrow questions), a superset, not a behavior change for
# the four original fields.
verify_proposition_claims = independently_extract_proposition


_SCOPE_SPECIFICITY_ORDER = ["industry_general", "global_market", "regional_market", "supplier_specific", "customer_specific"]


def reconcile_dual_extraction(pass1: dict[str, Any], pass2: dict[str, Any] | None) -> dict[str, Any]:
    """Deterministic comparison of two independent readings of the
    same source text. Agreement earns trust; disagreement -- or an
    unreachable second pass -- falls back to the SAFE direction for
    that specific field, never to pass 1's own claim (which is exactly
    what was being distrusted in the first place):

    - subject: disagreement -> cleared to "" (unidentified) -- an
      implication naming a specific party can then never ground
      against an unidentified subject (see validate_procurement_
      implication's scope checks, which key off evidence scope, not
      subject text directly, but an unidentified subject is a strong
      signal the extraction itself is unreliable).
    - predicate: disagreement -> the two candidate predicates neither
      match, so downstream relevance checking (which compares against
      the question) uses whichever predicate string pass 1 supplied,
      but the finding is additionally flagged predicate_disputed=True,
      which classify_evidence treats as UNKNOWN regardless of verdict
      (a predicate that a second independent reading contradicts is
      not safe to trust either way).
    - quantitative_value: disagreement (including one-sided: only one
      pass found a number) -> None (cannot trust either figure).
      Agreement -> the agreed value.
    - scope: disagreement -> falls back to the LESS SPECIFIC of the
      two (using _SCOPE_SPECIFICITY_ORDER) -- the safe direction,
      since a narrower scope (customer_specific/supplier_specific) is
      what grounds a riskier, more targeted implication; when in
      doubt, prefer the reading that grounds less, not more.
    - geography: disagreement -> None (unconfirmed geography cannot
      ground a geography-specific implication).
    - timeframe: disagreement -> None (unconfirmed timeframe cannot
      ground a "current" framing).
    - negated/attribution: unchanged from M1.5.1's own conservative
      OR-based reconciliation (either pass flagging the risky
      property is sufic ient).
    """
    reconciled = dict(pass1)
    if pass2 is None:
        reconciled["subject"] = ""  # cannot confirm -> cleared, not trusted from pass 1 alone
        reconciled["quantitative_value"] = None
        reconciled["geography"] = None
        reconciled["timeframe"] = None
        reconciled["predicate_disputed"] = True
        # negated is deliberately left UNCHANGED (pass1's own value)
        # here, not forced to True -- classify_evidence's separate
        # verification_unavailable flag already routes this case to
        # UNKNOWN before the negated check matters (see its own
        # docstring for why forcing negated=True on unavailability
        # would produce a false, specific CONTRADICTED claim instead
        # of an honest "cannot confirm"). Forcing it here would
        # silently re-introduce that exact defect by having this
        # check fire before verification_unavailable gets a chance to.
        reconciled["attribution"] = "supplier_claim"  # cannot confirm it's NOT a self-report -> the safe, weaker attribution
        return reconciled

    def _norm(s):
        return re.sub(r"\s+", " ", str(s or "")).strip().lower()

    # For every field below: pass2 being EMPTY/absent (no opinion) is
    # treated as "nothing to dispute" -- pass1's value is trusted.
    # Only an EXPLICIT, DIFFERING value from pass2 counts as genuine
    # disagreement and clears/downgrades the field. This is what makes
    # the mechanism attack-resistant (a lying pass1 cannot avoid a
    # genuinely independent pass2 noticing the truth) while remaining
    # tolerant of a second pass that simply doesn't comment on a field
    # it wasn't confident about -- silence is not itself a signal.
    p1_subject, p2_subject = _norm(pass1.get("subject")), _norm(pass2.get("subject"))
    subject_conflicts = bool(p2_subject) and p1_subject != p2_subject and p1_subject not in p2_subject and p2_subject not in p1_subject
    reconciled["subject"] = "" if subject_conflicts else pass1.get("subject")

    qty1, qty2 = _extract_numeric_tokens(str(pass1.get("quantitative_value") or "")), _extract_numeric_tokens(str(pass2.get("quantitative_value") or ""))
    qty_conflicts = bool(qty2) and qty1 != qty2
    reconciled["quantitative_value"] = None if qty_conflicts else pass1.get("quantitative_value")

    scope1, scope2 = pass1.get("scope", "industry_general"), pass2.get("scope")
    if not scope2 or scope1 == scope2:
        reconciled["scope"] = scope1
    else:
        idx1 = _SCOPE_SPECIFICITY_ORDER.index(scope1) if scope1 in _SCOPE_SPECIFICITY_ORDER else 0
        idx2 = _SCOPE_SPECIFICITY_ORDER.index(scope2) if scope2 in _SCOPE_SPECIFICITY_ORDER else 0
        reconciled["scope"] = _SCOPE_SPECIFICITY_ORDER[min(idx1, idx2)]

    p1_geo, p2_geo = _norm(pass1.get("geography")), _norm(pass2.get("geography"))
    geo_conflicts = bool(p2_geo) and p1_geo != p2_geo
    reconciled["geography"] = None if geo_conflicts else pass1.get("geography")

    p1_time, p2_time = _norm(pass1.get("timeframe")), _norm(pass2.get("timeframe"))
    time_conflicts = bool(p2_time) and p1_time != p2_time
    reconciled["timeframe"] = None if time_conflicts else pass1.get("timeframe")

    # Predicate agreement is deliberately STRICTER than the shared-
    # keyword relevance check elsewhere: "price increased" and "price
    # declined" share the word "price" but are OPPOSITE claims -- a
    # naive shared-word check would treat these as agreeing, exactly
    # missing the predicate-inversion attack this field exists to
    # catch. A small, explicit set of directional/polarity word pairs
    # is checked; if pass1 and pass2 land on opposing sides of any
    # pair, they are disputed. An EMPTY pass2 predicate (no opinion)
    # never disputes -- only an actual, detected polarity conflict
    # does, so a differently-worded-but-agreeing predicate (e.g.
    # "price increased" vs "cost rose") is correctly never disputed
    # either.
    _POLARITY_PAIRS = [
        ("increase", "decrease"), ("increase", "decline"), ("increase", "fall"), ("increase", "reduce"),
        ("rise", "fall"), ("rise", "decline"), ("expand", "contract"), ("expand", "reduce"),
        ("introduce", "remove"), ("introduce", "eliminate"), ("grow", "shrink"), ("gain", "lose"),
    ]

    def _polarity_conflict(p1: str, p2: str) -> bool:
        p1w, p2w = _norm(p1), _norm(p2)
        for a, b in _POLARITY_PAIRS:
            if (a in p1w and b in p2w) or (b in p1w and a in p2w):
                return True
        return False

    pred1, pred2 = str(pass1.get("predicate") or ""), str(pass2.get("predicate") or "")
    reconciled["predicate_disputed"] = _polarity_conflict(pred1, pred2)

    reconciled["negated"] = _reconcile_conservatively(pass1.get("negated", False), pass2.get("negates_claim"))
    if _reconcile_conservatively(pass1.get("attribution") == "supplier_claim", pass2.get("is_self_report")):
        reconciled["attribution"] = "supplier_claim"
    return reconciled


def _reconcile_conservatively(extracted_value: bool, verified_value: bool | None) -> bool:
    """Fail-closed reconciliation: if EITHER the original extraction
    OR the independent verifier says a risky property is present, or
    the verifier could not be reached at all, treat it as present.
    Both must agree it is safely ABSENT for the conservative
    (permissive) outcome -- a single pass claiming safety is never
    sufficient on its own."""
    if verified_value is None:
        return True  # verifier unavailable -- cannot confirm safety, so do not grant it
    return extracted_value or verified_value


def execute_research(research_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One search call per planned item. Never raises -- a failed
    individual search just means that one item's finding is empty, not
    a blocked answer. Matches market_verification.py's and
    fresh_intelligence.py's established never-blocks discipline
    exactly."""
    _empty_proposition = _parse_evidence_proposition(None)
    results = []
    for item in research_plan:
        try:
            tool = get_research_tool()
            raw_text = tool.search(item["prompt"], model=MARKET_MODEL, max_tokens=800)
            parsed = _extract_json_object(raw_text) if raw_text else None
            if not parsed:
                results.append({"question": item["question"], "why_it_matters": item["why_it_matters"], "answer_found": False, "finding": "", "evidence_proposition": _empty_proposition, "supports_or_contradicts_signal": "inconclusive", "sources": []})
                continue
            cleaned_sources = []
            for src in parsed.get("sources") or []:
                if not isinstance(src, dict):
                    continue
                title = str(src.get("title") or "").strip()
                url = str(src.get("url") or "").strip()
                if title and re.match(r"^https?://", url):
                    cleaned_sources.append({"title": title[:180], "url": url[:500]})
            results.append({
                "question": item["question"],
                "why_it_matters": item["why_it_matters"],
                "answer_found": bool(parsed.get("answer_found")),
                "finding": str(parsed.get("finding") or "").strip(),
                "evidence_proposition": _parse_evidence_proposition(parsed.get("evidence_proposition")),
                "supports_or_contradicts_signal": parsed.get("supports_or_contradicts_signal") if parsed.get("supports_or_contradicts_signal") in ("supports", "contradicts", "inconclusive", "not_applicable") else "inconclusive",
                "sources": cleaned_sources[:5],
            })
        except Exception as e:
            print(f"Market signal research item skipped (non-blocking): {type(e).__name__}: {e}")
            results.append({"question": item["question"], "why_it_matters": item["why_it_matters"], "answer_found": False, "finding": "", "evidence_proposition": _empty_proposition, "supports_or_contradicts_signal": "inconclusive", "sources": []})
    return results


# ---------------------------------------------------------------------
# Stage 4: evidence-state classification (responsibility 7) --
# deterministic, the central fabrication guardrail. The model NEVER
# self-reports an evidence_state; code assigns it from what the search
# actually produced.
# ---------------------------------------------------------------------

_VALID_EVIDENCE_STATES = {"VERIFIED", "CALCULATED", "SUPPLIER_CLAIM", "STAKEHOLDER_VIEW", "EXTERNAL_MARKET_EVIDENCE", "INFERRED", "ASSUMED", "UNKNOWN", "CONTRADICTED"}

# M1.5 Part 3 -- minimal, deterministic, extensible source-quality tiers.
# Metadata only: a tier is attached to every source for downstream
# visibility, but per the explicit instruction "source quality is one
# input into evidence integrity, not a replacement for proposition
# validation," tier alone never changes evidence_state here -- a Tier
# 1 source can still fail to support the proposition (see the
# relevance check below, which is independent of tier). Kept
# deliberately small; extend the tuples, not the tiering logic.
_TIER_1_PRIMARY_MARKERS = (".gov", ".gov.uk", ".europa.eu", "sec.gov", "sec.report", ".mil", "federalregister.gov")
_TIER_2_SPECIALIST_MARKERS = ("iso.org", "ietf.org", "who.int", "imo.org", "iea.org", "oecd.org", "worldbank.org")
_TIER_3_INDEPENDENT_MARKERS = ("reuters.com", "bloomberg.com", "ft.com", "wsj.com", "apnews.com", "economist.com")


def _classify_source_tier(url: str) -> str:
    """Anchored to the actual hostname's suffix, never a substring
    search over the full URL. M1.5-rebuild fix for the confirmed
    domain-spoofing defect: "https://fake-sec.gov.evil.com/filing"
    previously matched the substring ".gov" anywhere in the string and
    was classified TIER_1_PRIMARY; here the parsed hostname is
    "fake-sec.gov.evil.com", which does NOT end in ".gov" (it ends in
    ".evil.com"), so it correctly falls through to TIER_4_GENERAL.
    "https://example.com/sec.gov/filing" -- hostname "example.com" --
    is unaffected by the path segment "sec.gov" entirely, since only
    the hostname is ever inspected."""
    if not url:
        return "UNCLASSIFIED"
    try:
        hostname = (urlparse(url).hostname or "").lower()
    except ValueError:
        hostname = ""
    if not hostname:
        return "UNCLASSIFIED"

    def _suffix_match(markers: tuple[str, ...]) -> bool:
        return any(hostname == m.lstrip(".") or hostname.endswith(m if m.startswith(".") else "." + m) for m in markers)

    if _suffix_match(_TIER_1_PRIMARY_MARKERS):
        return "TIER_1_PRIMARY"
    if _suffix_match(_TIER_2_SPECIALIST_MARKERS):
        return "TIER_2_SPECIALIST"
    if _suffix_match(_TIER_3_INDEPENDENT_MARKERS):
        return "TIER_3_INDEPENDENT"
    return "TIER_4_GENERAL"


# M1.5 Part 2 -- deterministic relevance check, independent of the
# research-step model's own self-reported verdict. This is the fix for
# the confirmed gap: previously, "supports"/"contradicts" from the
# model was trusted outright; a finding whose own text has no
# meaningful overlap with the question it claims to answer is now
# downgraded to UNKNOWN regardless of what the model self-reported --
# directly targeting the confirmed failure where the model said
# "supports" but the content was actually irrelevant (test I) or only
# tangentially related (test H). Deliberately NOT a second LLM system:
# plain keyword-overlap, no semantic model involved.
_STOPWORDS = {"the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for", "and", "or", "this",
              "that", "does", "do", "did", "has", "have", "had", "will", "would", "could", "should", "with",
              "by", "at", "as", "be", "been", "it", "its", "what", "how", "why", "when", "which", "who"}


def _significant_words(text: str) -> set[str]:
    """Basic plural normalization (strip a trailing 's' from words
    longer than 4 characters) -- cheap, deliberately not a real
    stemmer, but enough to stop "price" vs "prices" from being treated
    as unrelated words, which the M1.5-rebuild validation's own test
    matrix explicitly calls out as a case to handle."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    normalized = set()
    for w in words:
        if len(w) <= 3 or w in _STOPWORDS:
            continue
        normalized.add(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    return normalized


def _finding_relevant_to_question(question: str, finding: str) -> bool:
    """Conservative, deterministic relevance gate: the finding must
    share at least one significant word with the question it claims
    to answer. This does not prove semantic support -- it only rules
    out the confirmed failure mode of a finding that isn't even about
    the same subject. A real proposition-entailment check is out of
    scope for this slice, per the explicit "do not over-engineer
    semantic entailment" instruction."""
    q_words = _significant_words(question)
    f_words = _significant_words(finding)
    if not q_words:
        return True  # nothing to check against; do not manufacture a rejection
    return bool(q_words & f_words)


def classify_evidence(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reuses the existing 9-value evidence-state taxonomy unchanged.
    M1.5-rebuild: proposition-aware, not just verdict-aware. The
    self-reported supports/contradicts/inconclusive/not_applicable
    verdict is an input signal, never the sole authority -- it is
    checked against the finding's own structured evidence_proposition
    before being trusted:

    - negated=True (the evidence explicitly states the predicate did
      NOT happen)                                          -> CONTRADICTED, ALWAYS, regardless of
                                                              what the self-reported verdict claims.
                                                              This is the fix for the confirmed truth-
                                                              inversion defect: a finding stating
                                                              "prices did NOT increase" could
                                                              previously be classified as SUPPORTING a
                                                              price-increase proposition merely
                                                              because the verdict field said
                                                              "supports."
    - no answer, or an empty finding                        -> UNKNOWN (no evidence)
    - the evidence_proposition's own predicate/quantitative_value
      share no genuine overlap with the question's core claim
      (a narrower, more precise check than whole-finding-text
      keyword overlap -- operates on the extracted predicate
      specifically, not incidental context words elsewhere in the
      finding text)                                          -> UNKNOWN, regardless of verdict
    - verdict is "contradicts" AND relevant                  -> CONTRADICTED
    - verdict is "inconclusive" or "not_applicable"           -> UNKNOWN
    - attribution == "supplier_claim"                         -> capped at INFERRED at most, NEVER
                                                                EXTERNAL_MARKET_EVIDENCE regardless of
                                                                any source tier attached to the same
                                                                finding entry -- fix for the confirmed
                                                                defect where an unrelated Tier-1/2/3
                                                                source silently promoted a supplier's
                                                                own self-interested claim
    - verdict is "supports" AND relevant AND NOT a supplier
      claim AND has a TIER_1/2/3 source                       -> EXTERNAL_MARKET_EVIDENCE
    - verdict is "supports" AND relevant but only TIER_4/
      UNCLASSIFIED sources (or none)                          -> INFERRED
    """
    classified = []
    for f in findings:
        verdict = f.get("supports_or_contradicts_signal")
        question = f.get("question", "")
        finding_text = f.get("finding", "")
        proposition = _parse_evidence_proposition(f.get("evidence_proposition"))
        # M1.5.1 Layer 2: independent verification, given ONLY the raw
        # finding text -- never told what the extraction above
        # claimed -- so it has a genuine, separate chance to catch a
        # mislabeled negated/attribution field. Reconciled
        # conservatively: either source flagging the risky property
        # is enough to treat it as present (see _reconcile_
        # conservatively's own docstring for why).
        #
        # M1.5.2: full dual-independent-extraction reconciliation --
        # replaces the narrower M1.5.1 four-question verifier. pass2
        # is a genuinely independent second reading of the SAME raw
        # finding text (never shown pass1's claimed values), and
        # reconcile_dual_extraction deterministically compares every
        # material field, not just negation/causation/entitlement/
        # attribution. Disagreement on subject/quantity/geography/
        # timeframe clears that field to unconfirmed rather than
        # trusting pass1; disagreement on scope falls back to the
        # LESS specific (safer) of the two readings; a disputed
        # predicate is tracked and forces UNKNOWN below, regardless of
        # the self-reported verdict.
        verification = independently_extract_proposition(finding_text) if finding_text else None
        verification_unavailable = bool(finding_text) and verification is None
        proposition = reconcile_dual_extraction(proposition, verification)

        # EVIDENCE-GROUNDING REBUILD: the deterministic grounding layer
        # is now the PRIMARY, authoritative check -- dual-extraction
        # agreement (above) is demoted to a secondary signal, per the
        # explicit instruction "LLM agreement = secondary consistency
        # signal, NOT source verification." Grounding is checked
        # against finding_text (the RAW research text), never the
        # extractions' own claims. A grounding CONTRADICTED verdict
        # overrides whatever dual-extraction concluded; a grounding
        # GROUNDED verdict confirms it; only when grounding itself is
        # silent (UNGROUNDED) does dual-extraction's own conclusion
        # stand, unchanged.
        if finding_text:
            neg_status, _ = ground_field_deterministic("negated", True, finding_text)
            if neg_status == "GROUNDED":
                proposition["negated"] = True

            attr_status, _ = ground_field_deterministic("self_report", True, finding_text)
            if attr_status == "GROUNDED":
                proposition["attribution"] = "supplier_claim"

            if proposition.get("quantitative_value"):
                qty_status, _ = ground_proposition_field("quantity", proposition["quantitative_value"], finding_text, claim_description=f"the value is {proposition['quantitative_value']}")
                if qty_status == "CONTRADICTED":
                    proposition["quantitative_value"] = None
                elif qty_status == "UNGROUNDED":
                    proposition["quantitative_value"] = None  # claimed number isn't actually traceable to this text -- clear it, don't trust either extraction's agreement alone

            claimed_predicate = str(proposition.get("predicate") or "")
            claimed_direction = _find_polarity(claimed_predicate)
            if claimed_direction:
                pred_status, _ = ground_proposition_field(f"predicate_{claimed_direction}", True, finding_text, claim_description=claimed_predicate)
                if pred_status == "CONTRADICTED":
                    proposition["predicate_disputed"] = True

            if proposition.get("scope") == "global_market":
                geo_status, _ = ground_field_deterministic("geography_universal", True, finding_text)
                if geo_status == "UNGROUNDED":
                    # An unqualified "global_market" claim the source
                    # itself never asserts as universal is an
                    # unsupported scope expansion -- downgrade to the
                    # narrower, safer reading rather than trust
                    # whatever either extraction pass agreed on.
                    proposition["scope"] = "regional_market"

            # Gap-closure: the claimed geography ITSELF (not just the
            # global/non-global scope distinction above) is now
            # grounded via the general narrower-only region mechanism.
            # A claimed geography broader than, or disjoint from, what
            # the source actually names is cleared -- but a genuinely
            # narrower reading (source mentions Europe+Asia, claim
            # says Europe) is preserved, per the explicit "may narrow,
            # must never broaden" principle.
            if proposition.get("geography"):
                geo_claim_status, _ = ground_geography_claim(proposition["geography"], finding_text)
                if geo_claim_status != "GROUNDED":
                    proposition["geography"] = None

        sources = [dict(s, source_tier=_classify_source_tier(s.get("url", ""))) for s in (f.get("sources") or [])]
        has_credible_source = any(s["source_tier"] in ("TIER_1_PRIMARY", "TIER_2_SPECIALIST", "TIER_3_INDEPENDENT") for s in sources)

        # Proposition-level relevance: the evidence_proposition's own
        # predicate and quantitative_value fields, compared to the
        # question -- narrower and more precise than whole-finding-
        # text overlap, since a finding can contain plenty of
        # incidental context words that inflate a naive whole-text
        # match without the CORE CLAIM actually addressing the
        # question at all.
        # Predicate-level relevance ONLY (not the whole finding text)
        # when the structured extraction actually populated it -- this
        # is the real fix, since a finding can contain plenty of
        # topically-adjacent context words that inflate a naive
        # whole-text match without the CORE CLAIM addressing the
        # question at all (e.g. "semiconductor industry employs
        # thousands of workers" shares "semiconductor" with a wafer-
        # supply question while its actual predicate, "employment
        # increased," shares nothing). Falls back to the full finding
        # text only when predicate/quantitative_value are both empty
        # (extraction unavailable or malformed) -- this is what
        # preserves backward compatibility with findings constructed
        # before this field existed, which would otherwise always
        # resolve to UNKNOWN.
        core_claim_text = " ".join(filter(None, [proposition["predicate"], proposition["quantitative_value"]])) or finding_text
        is_relevant = _finding_relevant_to_question(question, core_claim_text)

        if proposition["negated"]:
            evidence_state = "CONTRADICTED"
        elif verification_unavailable:
            # M1.5.1: cannot independently confirm the evidence is NOT
            # negated -- rather than guessing either way (both a false
            # CONTRADICTED and a false EXTERNAL_MARKET_EVIDENCE are
            # unsupported claims), the honest, fail-closed answer is
            # UNKNOWN. This is a deliberate availability/safety
            # trade-off: a transient verifier failure now downgrades
            # otherwise-good evidence rather than silently trusting the
            # unverified extraction, per the explicit "verifier
            # uncertain -> UNKNOWN" requirement.
            evidence_state = "UNKNOWN"
        elif proposition.get("predicate_disputed"):
            # M1.5.2: the two independent readings of this text
            # disagreed on the core predicate (e.g. one reading
            # supports "increased," the other doesn't corroborate that
            # direction at all) -- this is exactly the predicate-
            # inversion attack the independent validation reproduced.
            # Neither reading is trusted over the other; the honest
            # answer is UNKNOWN, not a guess in either direction.
            evidence_state = "UNKNOWN"
        elif not f.get("answer_found") or not finding_text:
            evidence_state = "UNKNOWN"
        elif not is_relevant:
            evidence_state = "UNKNOWN"
        elif verdict == "contradicts":
            evidence_state = "CONTRADICTED"
        elif verdict in ("inconclusive", "not_applicable"):
            evidence_state = "UNKNOWN"
        elif proposition["attribution"] == "supplier_claim":
            evidence_state = "INFERRED"
        elif has_credible_source:
            evidence_state = "EXTERNAL_MARKET_EVIDENCE"
        else:
            evidence_state = "INFERRED"

        item = dict(f)
        item["evidence_state"] = evidence_state
        item["sources"] = sources
        item["evidence_proposition"] = proposition
        item["verification"] = verification
        classified.append(item)
    return classified


# ---------------------------------------------------------------------
# Stage 5: synthesis + procurement translation + decision analysis
# (responsibilities 8-10) -- SEPARATE LLM call, receives evidence_state
# already fixed and cannot alter it.
# ---------------------------------------------------------------------

_SYNTHESIZE_SYSTEM_PROMPT = """You are the impact-synthesis component of a procurement intelligence system. You are given a signal, the analytical dimensions already identified as relevant, and research findings with their evidence states ALREADY DETERMINED -- you must never change, upgrade, or restate an evidence_state as something stronger than what is given to you (e.g. never call an UNKNOWN finding "confirmed", never call INFERRED "verified").

Do not force every dimension to have a procurement implication. "There is not yet enough evidence to establish a procurement impact" is a valid, correct, and preferred answer over a speculative one.

Respond with ONLY a JSON object, no other text, shaped exactly as:
{
  "dimension_impacts": [
    {"dimension": "...", "finding": "what the evidence actually shows for this dimension, in plain language", "evidence_state": "ECHO THE EXACT evidence_state GIVEN TO YOU for the finding(s) this is based on", "implication": "why this may matter, if it does", "procurement_translation": "a specific, evidence-supported procurement consequence, or null if not established", "implication_proposition": {"subject": "who/what procurement_translation is actually claiming about -- e.g. 'the global market', 'the supplier', 'the buyer/customer' -- be precise, do not default to the buyer/customer unless the translation genuinely concerns them specifically", "scope": "market | supplier | customer | category -- market means a general/global statement with no specific party named; supplier means a claim about the supplier's own position; customer means a claim about the buyer's own cost/price/exposure; category means a claim about the procurement category's cost as a whole", "quantitative_value": "the specific number/percentage the translation itself states, or null if none", "causal_claim": true or false (true if the translation asserts that one thing CAUSED or JUSTIFIES another, e.g. 'X caused Y', 'this explains Y', 'this justifies Y'), "entitlement_claim": true or false (true if the translation asserts a party IS JUSTIFIED/ENTITLED/CAN REASONABLY do something, e.g. 'the supplier can recover X', 'the supplier is entitled to Y'), "geography": "the specific geography procurement_translation itself claims (e.g. 'Europe', 'global'), or null if it names none"}}
  ],
  "decision_analysis": {
    "what_could_change": "which procurement decision(s) this signal could plausibly affect, or null if none",
    "what_to_do_now": "a concrete, evidence-bounded next step, or null if nothing is actionable yet",
    "what_not_to_do_yet": "an action that would be premature given current evidence, or null",
    "what_would_change_the_conclusion": "what evidence, if found, would materially change this analysis, or null"
  }
}"""


# =======================================================================
# SOURCE GROUNDING LAYER (evidence-grounding rebuild)
#
# Replaces "two LLM calls agree" with "the deterministic layer checks
# the RAW SOURCE TEXT directly, and its verdict cannot be overridden."
# One general mechanism (ground_proposition_field), not ten field-
# specific patches -- each field_type dispatches to a shared checker
# shape (numeric / polarity / marker-presence / specificity), and the
# same two-layer precedence rule applies uniformly:
#
#   Layer 1 (deterministic, regex/lexicon only, ZERO LLM calls) is the
#   non-bypassable safety floor. It scans source_text directly and
#   never takes any LLM's claimed value as an input to its own
#   verdict -- only as what gets checked against that independently-
#   formed verdict. A CONTRADICTED result from Layer 1 can NEVER be
#   overridden by anything downstream, including semantic grounding,
#   dual-extraction agreement, or an LLM's own confidence.
#
#   Layer 2 (semantic, one narrowly-scoped LLM call, invoked ONLY when
#   Layer 1 found no positive or negative textual signal) can UPGRADE
#   an UNGROUNDED verdict to GROUNDED when genuine paraphrase support
#   exists (e.g. "climbed by roughly eight percent" grounding "8%").
#   It can never touch a CONTRADICTED verdict, and on its own failure
#   the result simply stays UNGROUNDED -- never promoted.
#
# This is what closes the common-mode failure M1.5.2's audit exposed:
# two same-model LLM calls agreeing on a wrong value has no bearing on
# Layer 1's verdict, since Layer 1 never reads either call's output as
# input -- only the raw source text.
# =======================================================================

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}

_POLARITY_PAIRS = [
    ("increase", "decrease"), ("increase", "decline"), ("increase", "fall"), ("increase", "reduce"),
    ("increase", "drop"), ("rise", "fall"), ("rise", "decline"), ("rise", "drop"),
    ("expand", "contract"), ("expand", "reduce"), ("expand", "shrink"),
    ("introduce", "remove"), ("introduce", "eliminate"), ("grow", "shrink"), ("gain", "lose"),
    ("climb", "drop"), ("climb", "fall"), ("surge", "plunge"), ("higher", "lower"), ("up", "down"),
]
# Words on the "increase" side of any pair above, and the "decrease" side -- used to detect
# a claimed direction's polarity without needing the exact word pair matched.
_INCREASE_WORDS = {a for a, _ in _POLARITY_PAIRS} | {"increased", "increasing", "rising", "rose", "grew", "growing", "higher", "climbing", "climbed", "surged", "surging", "gained", "gaining", "expanded", "expanding"}
_DECREASE_WORDS = {b for _, b in _POLARITY_PAIRS} | {"decreased", "decreasing", "declined", "declining", "falling", "fell", "shrank", "shrinking", "lower", "dropping", "dropped", "plunged", "plunging", "lost", "losing", "contracted", "contracting", "reduced", "reducing"}

_NEGATION_MARKERS = ("did not", "did n't", "does not", "does n't", "was not", "were not", "has not", "have not",
                     "no increase", "no change", "not increase", "remained unchanged", "remained flat",
                     "denies", "denied", "failed to increase", "without any increase", "never increased")

_ATTRIBUTION_SELF_REPORT_MARKERS = ("claims", "claimed", "asserts", "alleges", "maintains that")
# "says"/"said"/"according to"/"reports that"/"states that" were
# deliberately removed from this list: they are just as commonly used
# for a NEUTRAL third-party citation ("according to the index",
# "Reuters reports that...") as for a party's own self-interested
# claim about itself, and including them produced a confirmed false
# positive (a plain index citation was wrongly flagged as a self-
# report) during implementation. The remaining words skew more
# reliably toward an assertive, self-interested claim, though this
# remains an imperfect, disclosed heuristic, not a semantic parse of
# who the grammatical subject actually is.

_CAUSAL_MARKERS = ("therefore", "as a result", "because", "due to", "caused", "causing", "resulted in", "led to",
                   "driven by", "explains", "validates", "justifies", "attributable to")

_ENTITLEMENT_MARKERS = ("entitled", "entitles", "entitle", "justified", "justifies", "permitted", "permits",
                        "has the right", "is allowed", "can recover", "may recover",
                        "contractually", "pass-through right", "indexation clause")

_UNIVERSAL_SCOPE_MARKERS = ("global", "globally", "worldwide", "all regions", "across all markets", "every market")

# A small, fixed, genuinely general set of major region names -- not
# an industry taxonomy, applicable to any procurement category. Kept
# deliberately short: continents plus a few common trading-bloc/
# regional terms, each variant (noun/adjective form) mapped to one
# CANONICAL key so "Europe" and "European" are recognized as the same
# region rather than two unrelated strings. This is what lets the
# grounding mechanism support "Europe + Asia -> Europe: GROUNDED" and
# "Europe -> Asia: UNGROUNDED" without a large, ever-growing geography
# database.
_REGION_VARIANTS = {
    "europe": "europe", "european": "europe", "eu": "europe",
    "asia": "asia", "asian": "asia", "apac": "asia",
    "africa": "africa", "african": "africa",
    "north america": "north_america", "north american": "north_america",
    "south america": "south_america", "south american": "south_america",
    "latin america": "latin_america", "latam": "latin_america",
    "oceania": "oceania", "australia": "oceania", "australian": "oceania",
    "middle east": "middle_east", "emea": "middle_east",
    "uk": "uk", "united kingdom": "uk", "britain": "uk", "british": "uk",
    "united states": "us", "us": "us", "usa": "us", "american": "us",
    "china": "china", "chinese": "china",
    "india": "india", "indian": "india",
    "japan": "japan", "japanese": "japan",
    "germany": "germany", "german": "germany",
    "france": "france", "french": "france",
}


def _extract_regions(text: str) -> set[str]:
    """Deterministic, general region-mention extraction. Returns the
    set of CANONICAL region keys (not raw matched strings -- see
    _REGION_VARIANTS) that literally appear in text, so "Europe" and
    "European" are correctly recognized as the same region. No
    paraphrase/semantic matching here by design -- this is Layer 1's
    job (exact, checkable presence); Layer 2 can still be consulted
    separately for a region expressed only descriptively."""
    if not text:
        return set()
    lowered = text.lower()
    found = set()
    for variant, canonical in _REGION_VARIANTS.items():
        if re.search(rf"\b{re.escape(variant)}\b", lowered):
            found.add(canonical)
    return found



def ground_geography_claim(claimed_geography: str | None, source_text: str) -> tuple[str, str]:
    """General mechanism (not a field-specific patch) for the
    narrower-only geography principle: a claim may narrow what the
    source supports (source mentions Europe+Asia, claim says Europe:
    GROUNDED -- the narrower reading is a subset of what's genuinely
    established) but must never broaden it (source mentions only
    Europe, claim says Asia, or claims global/worldwide coverage:
    UNGROUNDED/CONTRADICTED)."""
    if not claimed_geography:
        return "UNGROUNDED", "no geography claimed"
    claimed_lower = claimed_geography.lower()
    if any(m in claimed_lower for m in _UNIVERSAL_SCOPE_MARKERS):
        universal_status, universal_reason = ground_field_deterministic("geography_universal", True, source_text)
        return universal_status, universal_reason
    claimed_regions = _extract_regions(claimed_geography) or {claimed_lower.strip()}
    source_regions = _extract_regions(source_text)
    if not source_regions:
        return "UNGROUNDED", "source names no specific region at all"
    if claimed_regions <= source_regions:
        return "GROUNDED", f"claimed region(s) {claimed_regions} are a subset of source region(s) {source_regions}"
    if claimed_regions & source_regions:
        return "UNGROUNDED", f"claim partially overlaps source regions {source_regions} but also names an unsupported region"
    return "CONTRADICTED", f"source names region(s) {source_regions}, not {claimed_regions}"


_CURRENT_TIME_MARKERS = ("currently", "right now", "as of today", "presently", "at this time", "is now", "are now")
_HISTORICAL_TIME_MARKERS_PATTERN = re.compile(r"\b(19|20)\d{2}\b|\blast (quarter|year|month)\b|\bpreviously\b|\bhistorically\b|\bwas\b|\bwere\b")
_FORECAST_TIME_MARKERS = ("forecast", "forecasted", "expected to", "is expected", "target", "targeted", "planned",
                          "plans to", "announced", "announcement", "will increase", "will rise", "will fall",
                          "projected", "anticipated", "is set to", "due to be")


def _classify_temporal_status(text: str) -> str:
    """General, category-agnostic temporal classifier -- one shared
    mechanism, reused for both evidence and implication text (the
    grounding gap this closes: the mechanism already existed for
    evidence via ground_field_deterministic's "timeframe_current"
    check, but nothing compared it against the IMPLICATION's own
    temporal framing). Returns "current" | "historical" | "forecast" |
    "unspecified". A text can only be one classification here --
    checked in the order that favors the more cautious reading when
    multiple markers are present (forecast/historical checked before
    "current", since an explicit date or forecast marker is a stronger
    signal than the mere absence of one)."""
    if not text:
        return "unspecified"
    lowered = text.lower()
    if any(m in lowered for m in _FORECAST_TIME_MARKERS):
        return "forecast"
    if _HISTORICAL_TIME_MARKERS_PATTERN.search(lowered):
        return "historical"
    if any(m in lowered for m in _CURRENT_TIME_MARKERS):
        return "current"
    return "unspecified"


def _extract_all_numbers(text: str) -> set[str]:
    """Digits/percentages AND spelled-out English number words (a
    small, genuinely general lexicon -- not sector vocabulary),
    normalized to comparable numeric strings. This is what lets Layer
    1 ground "eight percent" against a claim of "8%" without needing
    Layer 2 at all for that specific gap."""
    if not text:
        return set()
    lowered = text.lower()
    found = set(re.findall(r"\d+(?:\.\d+)?", lowered.replace(",", "")))
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", lowered):
            found.add(str(value))
    return found


def _find_polarity(text: str) -> str | None:
    """Returns 'increase', 'decrease', or None (neither found) based on
    which side's vocabulary actually appears in the text."""
    lowered = text.lower()
    has_inc = any(re.search(rf"\b{re.escape(w)}\b", lowered) for w in _INCREASE_WORDS)
    has_dec = any(re.search(rf"\b{re.escape(w)}\b", lowered) for w in _DECREASE_WORDS)
    if has_inc and not has_dec:
        return "increase"
    if has_dec and not has_inc:
        return "decrease"
    return None  # neither, or both (genuinely mixed text) -- Layer 1 stays silent either way


def ground_field_deterministic(field_type: str, claimed_value: Any, source_text: str) -> tuple[str, str]:
    """Layer 1. Returns (status, reason) where status is one of
    GROUNDED / CONTRADICTED / UNGROUNDED. Never calls an LLM. Never
    takes any extraction's claimed value for OTHER fields as input --
    only source_text and the one claimed_value being checked.

    field_type is one of: "quantity", "predicate_increase",
    "predicate_decrease", "geography_universal", "scope_party",
    "timeframe_current", "negated", "self_report", "causal_claim",
    "entitlement_claim"."""
    source_text = source_text or ""
    if not source_text:
        return "UNGROUNDED", "no source text available"

    if field_type == "quantity":
        if not claimed_value:
            return "UNGROUNDED", "no quantity claimed"
        claimed_nums = _extract_numeric_tokens(str(claimed_value))
        source_nums = _extract_all_numbers(source_text)
        if claimed_nums and claimed_nums <= source_nums:
            return "GROUNDED", "claimed number(s) found in source"
        if source_nums and claimed_nums and not (claimed_nums & source_nums):
            return "CONTRADICTED", f"source states different number(s) {source_nums}, not {claimed_nums}"
        return "UNGROUNDED", "claimed number not found in source"

    if field_type in ("predicate_increase", "predicate_decrease"):
        polarity = _find_polarity(source_text)
        claimed_polarity = "increase" if field_type == "predicate_increase" else "decrease"
        if polarity is None:
            return "UNGROUNDED", "no directional language found in source"
        if polarity == claimed_polarity:
            return "GROUNDED", f"source states {polarity}"
        return "CONTRADICTED", f"source states {polarity}, claim asserts {claimed_polarity}"

    if field_type == "geography_universal":
        if any(m in source_text.lower() for m in _UNIVERSAL_SCOPE_MARKERS):
            return "GROUNDED", "source itself states universal/global scope"
        return "UNGROUNDED", "source does not establish universal/global scope"

    if field_type == "negated":
        if any(m in source_text.lower() for m in _NEGATION_MARKERS):
            return "GROUNDED", "negation marker found in source"
        return "UNGROUNDED", "no negation marker found"

    if field_type == "self_report":
        if any(m in source_text.lower() for m in _ATTRIBUTION_SELF_REPORT_MARKERS):
            return "GROUNDED", "attribution marker found in source"
        return "UNGROUNDED", "no attribution marker found"

    if field_type == "causal_claim":
        if any(m in source_text.lower() for m in _CAUSAL_MARKERS):
            return "GROUNDED", "causal marker found in source"
        return "UNGROUNDED", "no causal marker found -- co-occurrence is not causation"

    if field_type == "entitlement_claim":
        if any(m in source_text.lower() for m in _ENTITLEMENT_MARKERS):
            return "GROUNDED", "entitlement marker found in source"
        return "UNGROUNDED", "no entitlement/normative marker found"

    if field_type == "timeframe_current":
        if any(m in source_text.lower() for m in _CURRENT_TIME_MARKERS):
            return "GROUNDED", "source itself uses present-tense/current framing"
        if _HISTORICAL_TIME_MARKERS_PATTERN.search(source_text.lower()):
            return "CONTRADICTED", "source uses historical/past framing (a date, 'previously', 'was', etc.)"
        return "UNGROUNDED", "no explicit temporal marker found"

    return "UNGROUNDED", f"unrecognized field_type {field_type!r}"


_SEMANTIC_GROUND_SYSTEM_PROMPT = """You are a narrow fact-checking component. You are given a piece of source text and a single specific candidate claim. Your ONLY job is to determine whether the source text actually supports that exact claim -- you are not extracting new information, only checking one claim against the text you're given.

Respond with ONLY a JSON object:
{
  "verdict": "SUPPORTED" | "CONTRADICTED" | "NOT_ESTABLISHED"
}

SUPPORTED: the source text, in different words or the same words, genuinely asserts this claim (paraphrase counts -- "climbed by roughly eight percent" supports "increased approximately 8%").
CONTRADICTED: the source text asserts something that directly conflicts with this claim.
NOT_ESTABLISHED: the source text does not address this specific claim clearly enough either way (e.g. "costs rose materially" does not establish a specific 8% figure -- that would be NOT_ESTABLISHED, not SUPPORTED, since no percentage is actually stated)."""


def ground_claim_semantically(source_text: str, claim_description: str) -> str | None:
    """Layer 2. A single, narrowly-scoped verification call -- not a
    re-extraction of the whole proposition, and never shown any
    field's prior extraction. Returns "SUPPORTED"/"CONTRADICTED"/
    "NOT_ESTABLISHED", or None on any failure (treated by the caller
    as NOT_ESTABLISHED -- never a free pass)."""
    try:
        client = _get_client()
        response = client.messages.create(
            model=MARKET_MODEL, max_tokens=100, system=_SEMANTIC_GROUND_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Source text: {source_text}\n\nCandidate claim: {claim_description}"}],
        )
        parsed = _extract_json_object(_extract_text(response))
        if not parsed or parsed.get("verdict") not in ("SUPPORTED", "CONTRADICTED", "NOT_ESTABLISHED"):
            return None
        return parsed["verdict"]
    except Exception as e:
        print(f"Market signal semantic grounding skipped (non-blocking): {type(e).__name__}: {e}")
        return None


def ground_proposition_field(field_type: str, claimed_value: Any, source_text: str, claim_description: str | None = None) -> tuple[str, str]:
    """Combines both layers with the mandatory precedence rule: Layer
    1's CONTRADICTED can NEVER be overridden. Layer 2 is invoked ONLY
    when Layer 1 returns UNGROUNDED (genuinely silent, not
    contradictory), and can only ever upgrade that UNGROUNDED to
    GROUNDED (on SUPPORTED) or leave it as UNGROUNDED (on
    NOT_ESTABLISHED or its own unavailability) -- or, if Layer 2
    itself detects a contradiction Layer 1's lexicon missed, downgrade
    to CONTRADICTED (still a downgrade, never an upgrade past what
    Layer 1 already ruled out)."""
    status, reason = ground_field_deterministic(field_type, claimed_value, source_text)
    if status != "UNGROUNDED" or not claim_description:
        return status, reason
    verdict = ground_claim_semantically(source_text, claim_description)
    if verdict == "SUPPORTED":
        return "GROUNDED", "semantic layer: paraphrase support found (Layer 1 was silent)"
    if verdict == "CONTRADICTED":
        return "CONTRADICTED", "semantic layer: contradiction found (Layer 1 was silent)"
    return "UNGROUNDED", reason  # NOT_ESTABLISHED, or Layer 2 unavailable -- stays UNGROUNDED either way


def _norm_geo(geo: str | None) -> str:
    return re.sub(r"\s+", " ", str(geo or "")).strip().lower()


def _extract_numeric_tokens(text: str) -> set[str]:
    """Digit sequences only, stripped of currency/percent symbols and
    formatting, so "8%" and "8 percent" and "$8" all normalize to the
    same comparable token "8". Used purely for containment checking,
    not for interpreting magnitude."""
    return set(re.findall(r"\d+(?:\.\d+)?", text.replace(",", "")))


# M1.5 Part 1 -- the highest-priority guardrail. A procurement
# translation must not introduce a numeric value, or assert a specific
# party's outcome, that the finding it's attached to does not itself
# support. This is a deterministic comparison against the finding
# text (the authoritative evidence input) -- never a check of the
# LLM's internal self-consistency alone, per the explicit instruction.
#
# "your price"/"your cost"/"your category"/"your customer"/"you will
# pay" assert a direct, customer-specific financial outcome that
# market-level research alone cannot establish in this architecture --
# these are rejected outright, not conditionally, since nothing in
# this pipeline currently produces the customer-specific evidence that
# would justify them.
_DIRECT_CUSTOMER_OUTCOME_MARKERS = (
    r"\byour\s+(?:price|prices|cost|costs|category|customer|customers)\b",
    r"\byou\s+will\s+pay\b",
)
# "your supplier"/"supplier X" (a named party) combined with an
# assertive/predictive verb about cost or price -- conditionally
# rejected: allowed only when the finding itself already concerns a
# supplier (i.e. the underlying evidence is supplier-specific, not a
# bare general/global market statistic), so a translation that merely
# restates or interprets already-supplier-specific evidence is not
# blocked.
_SUPPLIER_OUTCOME_MARKERS_CASE_INSENSITIVE = (
    r"\byour\s+supplier(?:'s)?\b.{0,40}\b(?:will|should|must|going to)\b",
)
# Deliberately CASE-SENSITIVE: "[A-Z]" is what identifies this as a
# named party ("Supplier X") rather than a generic lowercase noun --
# applying IGNORECASE here would defeat that distinction entirely.
_SUPPLIER_OUTCOME_MARKERS_CASE_SENSITIVE = (
    r"\bsupplier\s+[A-Z]\w*\b.{0,40}\b(?:will|should|must|going to)\b",
)


def validate_procurement_translation(translation: str | None, finding: str) -> str | None:
    """Cheap, always-on defense-in-depth layer catching the literal
    marker phrases directly, at zero cost, before the heavier
    proposition-based check (validate_procurement_implication) runs.
    Kept deliberately narrow -- see that function's own docstring for
    why the REAL protection now lives there, not here."""
    if not translation:
        return None
    if any(re.search(p, translation, re.IGNORECASE) for p in _DIRECT_CUSTOMER_OUTCOME_MARKERS):
        return None
    _has_supplier_outcome_marker = (
        any(re.search(p, translation, re.IGNORECASE) for p in _SUPPLIER_OUTCOME_MARKERS_CASE_INSENSITIVE)
        or any(re.search(p, translation) for p in _SUPPLIER_OUTCOME_MARKERS_CASE_SENSITIVE)
    )
    if _has_supplier_outcome_marker and "supplier" not in finding.lower():
        return None
    translation_numbers = _extract_numeric_tokens(translation)
    finding_numbers = _extract_numeric_tokens(finding)
    if translation_numbers - finding_numbers:
        return None
    return translation


def _parse_implication_proposition(raw: Any) -> dict[str, Any]:
    """Same fail-closed shape discipline as _parse_evidence_proposition.
    A missing/malformed scope defaults to "market" -- this is the LEAST
    restrictive of the four scopes in validate_procurement_implication
    (no explicit grounding check at all, only the quantity check still
    applies), matching Part 7's own example that a plain market-fact
    restatement ("Global steel prices increased 8%") is explicitly
    allowed. This is a safe default specifically because "market" is
    also the correct, intended classification for that legitimate
    case -- it is not a conservative fallback in the sense of being
    stricter; it is a permissive one that happens to be right for the
    most common legitimate translation."""
    if not isinstance(raw, dict):
        raw = {}
    valid_scopes = {"market", "supplier", "customer", "category"}
    scope = raw.get("scope") if raw.get("scope") in valid_scopes else "market"
    return {
        "subject": str(raw.get("subject") or "").strip(),
        "scope": scope,
        "quantitative_value": str(raw.get("quantitative_value")).strip() if raw.get("quantitative_value") else None,
        "causal_claim": bool(raw.get("causal_claim") is True),
        "entitlement_claim": bool(raw.get("entitlement_claim") is True),
        "geography": str(raw.get("geography")).strip() if raw.get("geography") else None,
    }


def validate_procurement_implication(implication_proposition: dict[str, Any], evidence_proposition: dict[str, Any], finding: str, translation_text: str = "") -> bool:
    """M1.5-rebuild -- the real protection. Compares STRUCTURED FIELDS
    (extracted by the model, validated deterministically here) rather
    than matching surface phrasing against a fixed list. This is what
    generalizes across paraphrase: "your landed cost exposure is 8%"
    and "the buyer will face higher prices" and "you should expect to
    pay 8% more" all extract to scope="customer" from any reasonably
    competent model, where no regex list can recognize all three as
    the same underlying claim.

    Returns True (allowed) only if every check passes:
    - causal_claim: ALWAYS rejected in this phase -- nothing in this
      pipeline independently establishes causation (Part 3E of the
      spec), so any assertion that one event caused another is
      unsupported by construction, regardless of wording.
    - entitlement_claim: ALWAYS rejected -- commercial entitlement
      (a party being "justified"/"can recover"/"should be allowed to")
      is a normative/contractual judgment this pipeline cannot
      establish from market research alone.
    - scope == "customer": rejected unless evidence_proposition.scope
      == "customer_specific" (i.e. the evidence itself is genuinely
      about the buyer, not a market-level statistic being extended to
      them).
    - scope == "supplier": rejected unless evidence_proposition.scope
      == "supplier_specific" OR the word "supplier" literally grounds
      in finding (kept as a permissive fallback for cases the
      extraction under-scopes, matching the prior slice's grounding
      exception).
    - scope == "category": rejected unless evidence_proposition.scope
      in ("customer_specific",) -- a category-cost claim is, in
      substance, a customer-exposure claim under a different name.
    - quantitative_value: rejected if present and not grounded in the
      evidence_proposition's own quantitative_value.
    - temporal status (grounding-closure fix): the translation_text's
      own temporal framing (via _classify_temporal_status, the SAME
      general mechanism used for evidence, not a case-specific patch)
      must not assert "current" when the evidence's own grounded
      finding is "historical" or "forecast" -- this is what stops
      "European steel prices increased 8% in 2024" from silently
      becoming "prices are currently 8% higher" or "supplier pricing
      should currently increase 8%": the translation's own tense/
      marker choice is checked against the evidence's, independent of
      what either extraction pass claimed.
    """
    if implication_proposition["causal_claim"]:
        return False
    if implication_proposition["entitlement_claim"]:
        return False
    evidence_temporal = _classify_temporal_status(finding)
    implication_temporal = _classify_temporal_status(translation_text)
    if implication_temporal == "current" and evidence_temporal in ("historical", "forecast"):
        return False
    scope = implication_proposition["scope"]
    if scope == "customer" and evidence_proposition.get("scope") != "customer_specific":
        return False
    if scope == "category" and evidence_proposition.get("scope") != "customer_specific":
        return False
    if scope == "supplier" and evidence_proposition.get("scope") != "supplier_specific" and "supplier" not in finding.lower():
        return False
    imp_qty = implication_proposition.get("quantitative_value")
    if imp_qty:
        ev_qty = evidence_proposition.get("quantitative_value") or ""
        if not (_extract_numeric_tokens(imp_qty) <= _extract_numeric_tokens(ev_qty)):
            return False
    # Gap-closure geography check: replaces the prior exact-equality
    # comparison with the general narrower-only subset mechanism
    # (ground_geography_claim). An implication with no stated
    # geography is still treated as an implicit universality claim
    # ("Global steel prices increased 8%" reads as global) -- if the
    # evidence's own confirmed geography is regional, that implicit
    # universality is unsupported. But an implication that names a
    # geography which is a genuine SUBSET of what the evidence
    # establishes (e.g. evidence mentions "Europe and Asia," claim
    # says "Europe") is now correctly allowed, not just exact matches.
    ev_geo = evidence_proposition.get("geography")
    if ev_geo:
        imp_geo = implication_proposition.get("geography")
        if not imp_geo:
            return False  # implicit universality against confirmed-regional evidence
        claimed_regions = _extract_regions(imp_geo) or {_norm_geo(imp_geo)}
        evidence_regions = _extract_regions(ev_geo) or {_norm_geo(ev_geo)}
        if not (claimed_regions <= evidence_regions):
            return False
    return True


def synthesize_and_translate(signal_plan: dict[str, Any], classified_findings: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Stage 5 (responsibilities 8-10). Returns None on failure -- the
    caller degrades to showing only what stages 1-4 already
    established, never fabricates a synthesis."""
    try:
        client = _get_client()
        findings_text = "\n".join(
            f"- Question: {f['question']}\n  Evidence state: {f['evidence_state']}\n  Finding: {f['finding'] or '(nothing found)'}"
            for f in classified_findings
        ) or "(no research findings)"
        dimensions_text = "\n".join(f"- {d['dimension']}: {d.get('why_relevant', '')}" for d in signal_plan.get("dimensions", [])) or "(no dimensions identified)"
        prompt = (
            f"Signal understanding: {signal_plan.get('actual_question', '')}\n\n"
            f"Dimensions identified as potentially relevant:\n{dimensions_text}\n\n"
            f"Research findings (evidence_state already fixed -- do not alter):\n{findings_text}"
        )
        response = client.messages.create(model=MARKET_MODEL, max_tokens=1500, system=_SYNTHESIZE_SYSTEM_PROMPT, messages=[{"role": "user", "content": prompt}])
        parsed = _extract_json_object(_extract_text(response))
        if not parsed:
            return None
        # Fabrication guardrail, made strict on purpose: only the
        # evidence_state values ACTUALLY PRESENT in this call's own
        # findings are accepted -- never the full canonical set. If
        # only INFERRED findings were ever given, the model claiming
        # VERIFIED for any dimension must be rejected outright, not
        # merely "a valid state in general." An earlier version of
        # this guardrail unioned with the full 9-value taxonomy by
        # mistake, which silently defeated its own purpose; fixed here
        # and confirmed by a dedicated adversarial test.
        valid_states = {f["evidence_state"] for f in classified_findings}
        if not classified_findings:
            # No findings at all (e.g. no research was planned) -- the
            # only defensible state a dimension_impact could cite is
            # UNKNOWN, since nothing was ever verified either way.
            valid_states = {"UNKNOWN"}
        # Approximate finding->evidence_proposition lookup by the
        # evidence_state the dimension_impact echoes, matching the
        # existing state-membership check's own granularity (a
        # dimension_impact isn't linked to one specific finding index
        # anywhere in this architecture, only via the state it cites).
        proposition_by_state = {f["evidence_state"]: f.get("evidence_proposition") or _parse_evidence_proposition(None) for f in classified_findings}
        finding_text_by_state = {f["evidence_state"]: f.get("finding", "") for f in classified_findings}
        dimension_impacts = []
        for d in parsed.get("dimension_impacts", []):
            if not isinstance(d, dict) or not d.get("dimension"):
                continue
            # Deterministic guardrail: an evidence_state not present in
            # what was actually given, or not a canonical value at all,
            # is rejected outright rather than trusted -- this is what
            # prevents the model from inventing a stronger state.
            state = d.get("evidence_state")
            if state not in valid_states:
                continue
            dimension_finding = str(d.get("finding") or "").strip()
            raw_translation = str(d.get("procurement_translation")).strip() if d.get("procurement_translation") else None
            # Layer 1: cheap literal-phrase defense-in-depth (unchanged
            # from the prior slice).
            translation = validate_procurement_translation(raw_translation, dimension_finding)
            # Layer 2: the real protection -- structured proposition
            # comparison, which is what generalizes past paraphrase.
            # Both layers must pass; either rejecting is sufficient to
            # null the translation (fail closed).
            if translation is not None:
                implication_proposition = _parse_implication_proposition(d.get("implication_proposition"))
                evidence_proposition = proposition_by_state.get(state) or _parse_evidence_proposition(None)
                evidence_finding_text = finding_text_by_state.get(state, dimension_finding)
                # M1.5.1: the causal/entitlement claim actually lives in
                # the TRANSLATION text itself (e.g. "...therefore the
                # supplier increased prices"), not the evidence finding
                # -- verifying against the evidence text would miss it
                # entirely, since the evidence may contain no causal
                # language at all while the translation adds it. A
                # dedicated verifier call against the translation text
                # is required here; the evidence-level verification
                # (reused for negated/attribution in classify_evidence)
                # answers a different question and cannot substitute.
                translation_verification = verify_proposition_claims(translation) if translation else None
                implication_proposition["causal_claim"] = _reconcile_conservatively(implication_proposition["causal_claim"], translation_verification["asserts_causation"] if translation_verification else None)
                implication_proposition["entitlement_claim"] = _reconcile_conservatively(implication_proposition["entitlement_claim"], translation_verification["asserts_entitlement"] if translation_verification else None)
                if not validate_procurement_implication(implication_proposition, evidence_proposition, evidence_finding_text, translation_text=translation):
                    translation = None
            dimension_impacts.append({
                "dimension": str(d["dimension"]).strip(),
                "finding": dimension_finding,
                "evidence_state": state,
                "implication": str(d.get("implication") or "").strip() or None,
                # M1.5 Part 1: the guardrail runs here, comparing the
                # translation against THIS dimension's own finding
                # text (the authoritative evidence for this specific
                # claim), not against the raw_question or any other
                # dimension's evidence. Fails closed to None.
                "procurement_translation": translation,
            })
        da = parsed.get("decision_analysis") or {}
        decision_analysis = {k: (str(da.get(k)).strip() if da.get(k) else None) for k in ("what_could_change", "what_to_do_now", "what_not_to_do_yet", "what_would_change_the_conclusion")}
        return {"dimension_impacts": dimension_impacts, "decision_analysis": decision_analysis}
    except Exception as e:
        print(f"Market signal synthesis skipped (non-blocking): {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------
# Stage 6: dynamic response architecture (responsibility 11) --
# deterministic. Section inclusion decided by non-empty content, never
# a fixed heading list.
# ---------------------------------------------------------------------

def build_dynamic_answer(raw_question: str, signal_plan: dict[str, Any] | None, classified_findings: list[dict[str, Any]], synthesis: dict[str, Any] | None) -> dict[str, Any]:
    """Never raises. Always returns a usable answer dict, even when
    every upstream stage failed -- the primary response must survive
    regardless of research/LLM availability, matching this codebase's
    established non-blocking discipline throughout."""
    answer: dict[str, Any] = {"raw_question": raw_question}
    if signal_plan is None:
        answer["understood"] = False
        answer["message"] = "Unable to analyze this signal -- the understanding step did not complete. No fabricated analysis is shown."
        return answer

    answer["understood"] = True
    answer["actual_question"] = signal_plan.get("actual_question")
    if signal_plan.get("claimed_facts"):
        answer["claimed_facts"] = signal_plan["claimed_facts"]
    if classified_findings:
        answer["research_findings"] = classified_findings  # each carries its own evidence_state, source list, question
    if synthesis and synthesis.get("dimension_impacts"):
        answer["dimension_impacts"] = synthesis["dimension_impacts"]
    if synthesis and any(synthesis.get("decision_analysis", {}).values()):
        answer["decision_analysis"] = synthesis["decision_analysis"]
    if not classified_findings and not (synthesis and synthesis.get("dimension_impacts")):
        answer["message"] = "No dimension yet has evidence-supported procurement relevance for this signal."
    return answer
