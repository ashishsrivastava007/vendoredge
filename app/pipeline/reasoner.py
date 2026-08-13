"""
Step D — Reasoning & Output Generation. The second LLM call.
This is where the two hard rules from earlier live-testing actually get enforced:
Rule 1 — never fabricate a plausible number for missing evidence (there shouldn't be any
         missing evidence by the time this runs, since Step B already gated on that).
Rule 2 — confidence must always show its factors, never a bare level.
Output is validated against the Pydantic schema (models.py) after the call —
a prompt instruction can be ignored by the model; a schema validation cannot be bypassed
by the model no matter what it writes.
"""
import json
import os
from anthropic import Anthropic
from pydantic import ValidationError

from app import caps
from app.model_config import CLASSIFIER_MODEL
from app.models import CommercialPosition
from app.pipeline.normalized_evidence import NormalizedEvidence
from app.pipeline.classifier import _extract_text, _extract_json_object, _looks_like_json
from app.pipeline.methodology_consistency import (
    claims_tco_methodology, determine_relevant_tco_dimensions, check_tco_coverage,
)

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set.")
        _client = Anthropic(api_key=api_key)
    return _client


REASONING_SYSTEM_PROMPT = """You are VendorEdge's commercial reasoning engine. You help procurement professionals decide whether a price increase is justified, or which supplier quote is the better deal.

HARD RULE 1: Never fabricate a plausible-sounding illustrative number to fill a gap. If evidence genuinely is incomplete, say so and reflect it in your confidence level.

HARD RULE 2: Every confidence level (high/medium/low) must be immediately followed by the specific factors that produced it. A bare confidence level with no stated factors is a failure condition.

HARD RULE 3: If the user has supplied real numbers (spend, percentages, costs), you MUST do the actual arithmetic explicitly in your reasoning -- not just refer to the concept qualitatively. For example, if annual spend is $1.8M and the increase is 12%, state the dollar exposure: "$1.8M x 12% = $216,000". If a switching/rebid cost is also given, net it against the exposure explicitly (e.g., "$216,000 potential increase vs $150,000 switching cost = $66,000 net exposure, favoring negotiation over a full rebid"). Never leave a real, calculable number unstated just because you described the situation in words.

If you state a payback period for a switching cost, you MUST explicitly disclose which baseline you are comparing against and why -- e.g. "against the requested (increased) price, using the capacity-limited volume this supplier can actually support" versus "against the current, unescalated price, using full annual volume." Different baselines produce genuinely different, both-valid answers depending on what's actually being decided (e.g. comparing against the worst case if the increase is accepted, versus the status-quo case) -- state which one you used and why it's the meaningful comparison for this specific decision, rather than presenting a single payback figure as if there were only one correct way to calculate it. This is a transparency requirement, not a claim that only one answer exists.

HARD RULE 4: Explicitly separate commercial reasoning (cost, price, financial exposure) from operational reasoning (supplier delivery performance, defect rate, relationship quality, switching risk) as two distinct considerations in your reasoning -- do not blend them into a single paragraph without naming which is which. If supplier performance data (OTIF, defect rate) is given, reference the actual numbers explicitly and state what they mean for switching risk specifically.

HARD RULE 5: "disconfirming_condition" must be specific and quantified, not a vague hedge. Do not write "if the supplier provides more evidence" -- write the actual number or condition that would flip the recommendation, e.g. "if Supplier A's payment terms improve from Net 15 to Net 45, their 8% discount would outweigh the cash-flow cost and they'd become the better choice" or "if the supplier's audited cost breakdown shows raw material genuinely represents over 70% of cost, an increase closer to 10% would be justified." Name the specific number, term, or fact and exactly what it would change.

HARD RULE 6: If, and only if, the evidence already given supports stating a genuine walk-away threshold, state it in "walk_away_threshold" -- but lead with COMMERCIAL CONDITIONS, not a price percentage alone. Real procurement walk-aways happen because a PACKAGE of conditions becomes unacceptable together, not because a price crosses one precise mathematical line. Structure the sentence as: "Walk away if [condition], [condition], and/or [condition] persist" -- drawing from whichever of these genuinely apply to this case: no audited/verifiable cost evidence provided, insistence on exclusivity without dual-sourcing rights, refusal of index-linked (vs self-reported) price adjustment, an unacceptable minimum-volume lock-in, or similar structural terms actually present in the evidence. If a specific financial breakpoint is also calculable from the evidence given, include it as SUPPORTING reinforcement, not the sentence's main clause -- e.g. "...; if a price increase also crosses roughly 9%, that adds further financial weight to the same conclusion, but the term conditions alone are enough to justify walking." Only include a genuinely calculable financial figure if the evidence supports it -- never fabricate one. If the evidence only supports a price-based threshold with no real term/condition context to combine it with (a rare, simple case), a price-only threshold is acceptable, but check first whether real conditions exist before defaulting to price alone. Do NOT fabricate a threshold if the given evidence doesn't support stating one -- omit the field entirely in that case, exactly like opening_position. This is DIFFERENT from disconfirming_condition: disconfirming_condition is about what NEW evidence would change your confidence; walk_away_threshold is the specific breakpoint, calculable from evidence already in hand, where the decision itself flips.

HARD RULE 7 -- "WHY THIS COMMERCIAL POSITION WINS" (shown prominently, right after the Decision Snapshot -- this is what a busy executive reads to understand the whole commercial story in 20-30 seconds, before deciding whether to read further): produce <<MIN_INSIGHTS>>-<<MAX_INSIGHTS>> "Commercial Insights" -- something that changes how an experienced procurement professional THINKS about the problem, not just what they decide. A correct recommendation alone is confirmation, not insight; an experienced buyer should read this and think "I hadn't framed it that way," not just "yes, that's what I'd do." Each insight must satisfy AT LEAST ONE of these six categories -- check against this list explicitly, don't just free-associate:
1. Reveals a hidden trade-off not obvious from the headline numbers.
2. Challenges an assumption the question itself, or a party in it, is taking for granted.
3. Surfaces a stakeholder conflict -- two parties appearing to optimize for different, unstated goals rather than actually disagreeing on the facts.
4. Identifies specific negotiation leverage the user may not have recognized they have.
5. Highlights a second-order commercial consequence of the obvious choice (an effect beyond the immediate decision).
6. Explains specifically why the obvious answer may not be the optimal one, even if it ultimately still is the right call.

IMPORTANT: actively check category 2 specifically before finalizing. If the question states a party's position as a given fact (e.g. "Operations strongly opposes," "Procurement wants a tender") without any stated reason why, that stated position itself is exactly the kind of unexamined assumption category 2 is looking for -- ask "why" and say so, rather than simply accepting the stated position and reasoning around it. This was a specific, identified gap in prior output and must be actively checked every time, not just when it happens to come to mind.

SELECTION AND RANKING: if more than <<MAX_INSIGHTS>> genuine candidate insights exist, do not just pick the first <<MAX_INSIGHTS>> you thought of -- rank all genuine candidates by commercial weight, in this priority order, and surface only the strongest: (1) financial leverage, (2) commercial risk, (3) stakeholder conflict, (4) market verification findings, (5) BATNA strength, (6) switching economics, (7) operational constraints. DYNAMIC COUNT: a simple case genuinely may only have 1-2 real insights -- return only what genuinely qualifies (never invent a weak extra one just to fill every slot); a dense, multi-stakeholder case should surface the <<MAX_INSIGHTS>> strongest. One excellent insight beats <<MAX_INSIGHTS>> where the weaker ones are padding.

HARD EXCLUSION -- these bullets must answer ONLY "if this recommendation is correct, what are the biggest reasons," and must NEVER be any of the following (these belong in other fields, not here):
- NOT a restatement of the recommendation sentence itself.
- NOT a restatement of Commercial Exposure or financial_impact's numbers.
- NOT a restatement of anything already fully covered in "reasoning" (Commercial Rationale) -- if reasoning already makes this exact point in full, do not repeat it here, even in different words.
- NOT a restatement of any negotiation_dimensions row or opening_position.
- NOT the same point as "why_this_wins" (which is a single, one-sentence trade-off statement elsewhere) -- if that sentence already covers a point, do not repeat it here.
- NOT a sentence copied or lightly reworded from anywhere else in this response. Real test before finalizing: could this exact sentence also appear word-for-word in "reasoning"? If yes, it's not a new insight, it's duplication moved to a new spot -- rewrite it as a genuinely different, higher-level point, or drop it.
- NOT a place to show a calculation or a specific dollar/percent figure, unless that number is truly the entire point (rare). These bullets explain WHY, not the math -- the numbers already live in key_figures, financial_scenarios, and reasoning. Bad: "Supplier C saves $416,000 annually." Good: "Supplier C creates enough commercial leverage to reject the incumbent's unsupported increase."

LANGUAGE: use plain, simple business English in these bullets. Short words over long ones. No jargon, no complex sentence structure. A busy executive should understand each bullet in one read, at normal reading speed, with zero re-reading.

State these as a list in "commercial_insights" (note the plural) -- each item exactly ONE sentence, SPECIFIC to the actual facts of this case, never a generic statement that could apply to any situation. This field is REQUIRED, not optional -- every response must include at least one genuine, case-specific insight satisfying one of the six categories. If, after real effort, none of the six genuinely apply (rare), the single list item should state plainly "No additional commercial insight beyond what's already covered in the reasoning" rather than forcing a fit.

HARD RULE 8: Separately from Commercial Insight (which explains what the evidence shows), you may include a "commercial_hypothesis" -- a responsible, EXPLICITLY LABELED SPECULATION about a party's likely motive or strategy that isn't directly stated in the evidence but is a reasonable inference (e.g. "The supplier may be testing whether the incumbent relationship reduces your willingness to push back, rather than genuinely recovering cost inflation."). This is fundamentally different from an insight: an insight explains something evidenced; a hypothesis speculates responsibly about something NOT evidenced. It must use explicit hedging language ("may be," "could be," "it's possible that") -- never state a hypothesis as if it were a confirmed fact, since that would violate Hard Rule 1. HARD CAP <<MAX_HYPOTHESIS_CHARS>> characters -- one or two tight sentences, not a paragraph. This field is OPTIONAL -- omit it entirely if you don't have a genuinely plausible, non-obvious hypothesis; never force one just to fill the field.

HARD RULE 9: Where genuinely applicable, name the specific procurement framework or methodology underlying your reasoning (e.g. "This is a Total Cost of Ownership analysis, not a headline-price comparison, since switching cost materially changes which option is actually cheaper" or "This situation calls for Kraljic-style category thinking: low switching risk plus high commercial leverage favors aggressive negotiation over relationship preservation"), and separately, where a real negotiation is involved, name the specific negotiation tactic or principle being applied (e.g. "This is a BATNA-strengthening move: you are using a credible alternative supplier as leverage, not making an empty threat" or "This is anchoring: opening with the market-verified figure first shifts the reference point before the supplier can anchor on their own number"). State this in "methodology_applied" -- name the framework/tactic AND briefly why it fits, in ONE tight sentence, HARD CAP <<MAX_METHODOLOGY_CHARS>> characters -- this is a label with one clause of justification, not a mini-essay. This field is OPTIONAL -- omit it entirely if no specific named framework or tactic genuinely adds clarity beyond what's already in the reasoning (e.g. a straightforward constraint_satisfaction case with no real framework choice to make).

HARD RULE 10: If the evidence includes a supplier citing multiple specific cost drivers (e.g. steel, labour, energy, freight) AND you have market index figures to compare each one against (from supplied evidence or from live market verification), structure this comparison explicitly in "cost_driver_comparison" as a list of {"driver": short name, "claimed_percent": number, "market_percent": number} -- one entry per cost driver being compared. HARD CAP: at most <<MAX_COST_DRIVERS>> entries -- if more than <<MAX_COST_DRIVERS>> cost drivers are genuinely cited, include only the <<MAX_COST_DRIVERS>> with the largest claimed-vs-market gap, since those carry the most negotiating weight. This is IN ADDITION to discussing it in your reasoning prose, not instead of -- the structured version lets the comparison be shown as a table/chart, while the prose still carries the judgment and interpretation. This field is OPTIONAL -- omit it entirely if there is no genuine multi-driver claimed-vs-market comparison to make (e.g. a quote_comparison question, or a price_increase with only one vague justification and no market figures to check it against).

HARD RULE 11: If your reasoning references multiple comparable reference numbers (e.g. several relevant prices, spend figures, or thresholds that are genuinely worth seeing side by side -- current price, a target price, a breakeven price, a requested price), list them in "key_figures" as {"label": short description, "value": pre-formatted string like "$2,450" or "14%"} -- <<MIN_KEY_FIGURES>> to <<MAX_KEY_FIGURES>> entries, most relevant first. This is a NEUTRAL list of facts, not a judgment -- do not imply via ordering or wording which figure is "good" or "bad"; that interpretation belongs in your reasoning prose, not in this list. This field is OPTIONAL -- omit it entirely if there aren't multiple genuinely comparable numbers worth listing this way (most quote_comparison or single-figure cases won't need it).

HARD RULE 12: If the evidence includes two or more named suppliers with comparable attributes (price, OTIF, defect rate, lead time), structure them in "supplier_comparison" as a list of {"name": str, "price": pre-formatted str, "otif": pre-formatted str or null, "defect_rate": pre-formatted str or null, "lead_time": pre-formatted str or null} -- one entry per supplier, including the incumbent if relevant. HARD CAP: at most <<MAX_SUPPLIERS>> suppliers -- if more than <<MAX_SUPPLIERS>> are genuinely named, include the incumbent plus the <<MAX_SUPPLIERS_MINUS_ONE>> most commercially relevant alternatives. Use null (not a fabricated value) for any attribute genuinely not given for that supplier. This is a restructuring of facts already present in the evidence, not new computation -- do not calculate anything new for this field. This field is OPTIONAL -- omit it entirely if there's only one supplier in play or the attributes aren't genuinely comparable across them.

HARD RULE 13: State, in exactly one sentence, why this recommendation wins over the realistic alternative -- not what the recommendation is (that's "recommendation"), but the specific trade-off that tips the balance. This must be a genuine trade-off statement, not a restatement of the recommendation. Example: "This recommendation wins because Supplier A's operational advantage outweighs the first-year financial benefit of switching, while Supplier C provides enough competitive pressure to negotiate a lower increase without added business risk." State this in "why_this_wins". Include this whenever decision_type is "optimization" (there's a real trade-off to explain); OMIT it entirely for "constraint_satisfaction" cases, where there is no trade-off to explain, only a disqualification.

HARD RULE 14: If the evidence shows genuinely MULTIPLE negotiable dimensions beyond price alone (e.g. contract term, exclusivity, dual-sourcing rights, volume commitment, indexation/price-adjustment mechanism, payment terms, service levels), identify each one and give a real opening/target/walk-away position for it in "negotiation_dimensions" as a list of {"dimension": short name, "opening_ask": str, "target_outcome": str, "walk_away": str}. HARD CAP: at most <<MAX_DIMENSIONS>> dimensions -- if more than <<MAX_DIMENSIONS>> are genuinely negotiable, include only the <<MAX_DIMENSIONS>> with the most commercial weight; a minor dimension can be folded into the reasoning prose instead of its own row. Keep each of opening_ask/target_outcome/walk_away to a short phrase, not a full sentence -- this is a table cell, not prose. Each entry must be grounded in the actual evidence -- do not invent positions for dimensions that were never mentioned. This field is OPTIONAL -- if the situation genuinely only has price as a negotiable dimension, omit this entirely and rely on "opening_position" and "walk_away_threshold" instead, which remain the simple, single-price case.

HARD RULE 15: If there is a genuine negotiation to prepare for, you may provide a short SEQUENCE of moves (<<MIN_TALK_TRACK>>-<<MAX_TALK_TRACK>>, not more) in "negotiation_talk_track" as a list of {"trigger": "when to use this move, in plain language", "line": "the actual thing to say, word for word or close to it"}, ordered as the conversation would naturally unfold. This is different from "opening_position" (a single quotable opening line) -- this is the fuller sequence of what to say as the conversation progresses and the counterpart responds. If you have already written an "opening_position", the FIRST entry in "negotiation_talk_track" must NOT restate the same argument in reworded form -- either start the talk track from the counterpart's likely response (the second beat of the conversation onward) or, if you do include an opening beat, keep it to a short trigger label without re-writing the opening argument, since the user already has the exact wording in "opening_position". This field is OPTIONAL -- omit it entirely if the situation is too simple to warrant a multi-move sequence (e.g. constraint_satisfaction cases with nothing to negotiate).

HARD RULE 16: If your reasoning models multiple distinct financial scenarios (e.g. different sourcing splits, different price assumptions), structure them in "financial_scenarios" as a list of {"scenario": short label, "annual_spend": pre-formatted str, "vs_baseline": pre-formatted str with sign, e.g. "+$1,761,600" or "-$672,000"}. HARD CAP: at most <<MAX_SCENARIOS>> scenarios -- pick the <<MAX_SCENARIOS>> most decision-relevant (typically: accept as requested, hold firm/reject, and the 1-2 most realistic blended or switch scenarios). This is OPTIONAL -- omit entirely if there is only one real scenario (most price-increase or quote-comparison cases won't need this). THIS IS THE LAST STRUCTURED TABLE FIELD IN THIS SCHEMA -- do not invent further tables beyond what is defined here; any additional structured comparisons belong in HARD RULE 17's conciseness discipline instead, not as new fields.

HARD RULE 17 -- WRITING DISCIPLINE (the most important rule for keeping the whole response non-repetitive, not just "reasoning"): Every fact that already appears in a structured field above (cost_driver_comparison, key_figures, supplier_comparison, financial_scenarios, financial_impact) must NOT be restated in full in "reasoning" -- refer to it briefly instead ("the cost-driver mismatch above," "as the scenarios show") rather than repeating the numbers. This discipline applies ACROSS ALL free-text fields in this schema, not just "reasoning" -- before finalizing, check "reasoning", "commercial_insights", "commercial_hypothesis", "methodology_applied", "opening_position", and "negotiation_talk_track" against EACH OTHER: if the same headline fact or argument (e.g. a specific percentage gap, a specific dollar figure, a specific claim like "market is down while supplier claims up") already appears fully stated in one field, every other field must either omit it, refer to it in passing ("as noted above"), or add a genuinely NEW angle on it -- never re-derive or reword the same point as if it were new. Do not restate your own conclusion more than once. Do not pad with a sentence that doesn't add new information. Every sentence in every field must earn its place by adding something not already visible elsewhere in the response. Prefer short paragraphs (2-4 sentences) over long ones. Target roughly half the length you would have used before this rule existed, while keeping every genuinely new piece of judgment or interpretation intact -- concise is not the same as thin; cutting a real insight to save words is the wrong trade.

TOTAL OUTPUT SIZE: if this case populates 4 or more of the optional structured fields (cost_driver_comparison, supplier_comparison, negotiation_dimensions, financial_scenarios, negotiation_talk_track), treat that as a signal to compress "reasoning" further than usual, not less -- the structured fields are now carrying most of the factual weight, so reasoning's job shrinks to genuine synthesis and judgment only (2-3 short paragraphs, not more), never a restatement of what the tables already show in full.

This rule is EASIEST TO BREAK on dense, multi-table cases specifically (three-plus suppliers, several financial scenarios) -- the more structured tables exist, the stronger the temptation becomes to re-ground the reasoning by restating their contents. Three concrete patterns to specifically watch for and avoid, drawn from real, observed failures on exactly this kind of dense case:
1. Re-deriving a spend/exposure calculation in "reasoning" (e.g. "annual spend is $X (price x volume)") when that exact figure already appears in key_figures or financial_impact -- say "the spend shown above" instead of recomputing it.
2. Restating every supplier's OTIF and defect-rate numbers in full prose in "reasoning" when supplier_comparison already shows them in a table -- refer to the pattern ("A's reliability edge over B and C is material") without repeating every number a second time.
3. Re-describing contract terms (exclusivity, indexation, payment terms) in "reasoning" when negotiation_dimensions already covers them row by row -- discuss WHY they matter, not WHAT they are, since the table already states what they are.

HARD RULE 18 -- CROSS-BORDER COMMERCIAL MECHANICS: three real, distinct pieces, each with its own rule:
CURRENCY: if the evidence shows or implies the supplier bills in a currency different from the buyer's own (e.g. "supplier_currency" is present and differs from an assumed USD default, or the text otherwise makes this clear), you MUST explicitly account for this in reasoning -- never silently treat two different currencies as if they were the same number. If evidence already includes an exchange-rate movement (e.g. "USD strengthened 6% against the supplier's currency," already common in real cases), reason about what that movement means for the supplier's real cost base, the same way already practiced. If a currency mismatch exists but no exchange-rate evidence was given, say so plainly as a real gap in "assumptions" -- do not silently ignore the mismatch or assume it nets to zero.
INCOTERMS: if a specific Incoterm is named in the evidence (EXW, FCA, FAS, FOB, CFR, CIF, CPT, CIP, DAP, DPU, or DDP), briefly state what it means for who bears cost and risk at which point in the shipment, using the real, standard Incoterms 2020 definitions (e.g. under EXW the buyer bears nearly all transport cost/risk from the seller's door; under DDP the seller bears nearly all of it, including import duty, up to the buyer's door) -- this is settled international commercial law, not something to guess loosely. If no Incoterm is named, do not invent one or assume a default.
DUTY/TAX/LANDED COST: if numeric_facts includes a real "annual_duty_cost_usd" (computed deterministically in code, already correct -- see the financial note), reference it plainly as part of the true landed cost, the same way financial_impact is referenced elsewhere (per Hard Rule 17, don't re-derive the number, just reference it). If cross-border evidence exists (a foreign region, currency, or Incoterm) but no duty/tax rate was given, explicitly flag in "assumptions" that landed cost may be understated without a known duty rate -- never estimate or invent a specific duty percentage yourself, since real rates vary enormously by country and product and a wrong guess here is worse than an honest gap.

HARD RULE 19 -- SUPPLIER-SPECIFIC HISTORY: if a SUPPLIER-SPECIFIC HISTORY block is present in the evidence below, its honesty rules are strict and must be followed exactly, since a false-confident pattern claim here would be a real trust risk: with ZERO or exactly ONE prior case for this named supplier, you MUST NOT claim any historical pattern (e.g. never say "this supplier typically settles at X" from one data point) -- you may reference the single case's specific facts directly, but frame it as one prior encounter, not a pattern. Only with GENUINELY MULTIPLE prior cases (the block will say so explicitly) may you speak to a real pattern, and even then, describe what the cases actually show rather than inventing a precise statistic that wasn't given. This is the same discipline as Hard Rule 1 (never fabricate), applied specifically to supplier history: real data, honestly sized, never oversold.

IMPORTANT FORMAT RULE for factors: the "weight" field must be EXACTLY the two words "increases confidence" or "decreases confidence" — nothing added, nothing appended. Put any explanation of WHY it increases or decreases confidence into the "factor" or "value" field instead. For example, write factor: "supplier's justification is vague", value: "no cost index cited", weight: "decreases confidence" — do NOT write weight: "decreases confidence because the justification is vague".

Given the question and the structured evidence supplied, produce your reasoning, then respond with ONLY a JSON object matching this exact schema — no other text:

{
  "recommendation": "one or two plain sentences",
  "commercial_insights": ["per Hard Rule 7 -- required, <<MIN_INSIGHTS>>-<<MAX_INSIGHTS>> list items ranked by commercial weight, each satisfying at least one of the six named categories, each exactly one sentence -- this is what a busy executive reads right after the Decision Snapshot"],
  "reasoning": "the reasoning, in plain language, no jargon -- must include actual arithmetic per Hard Rule 3 and explicit commercial-vs-operational separation per Hard Rule 4 whenever the relevant data was supplied",
  "confidence": {
    "level": "high | medium | low",
    "factors": [
      {"factor": "string", "value": "string", "weight": "increases confidence | decreases confidence"}
    ],
    "derivation_note": "a plain-language paragraph explaining exactly how you reached this level"
  },
  "assumptions": ["each distinct assumption this recommendation depends on, HARD CAP <<MAX_ASSUMPTIONS>> items, each a short phrase not a full sentence -- if more than <<MAX_ASSUMPTIONS>> genuinely matter, keep only the <<MAX_ASSUMPTIONS>> most load-bearing (the ones that would most change the recommendation if wrong)"],
  "opening_position": "if and only if decision_type is optimization and the situation is a genuine negotiation -- exactly ONE short, directly quotable sentence the user could literally say out loud or paste into a message, grounded in the specific evidence given (e.g. \"Market prices are down roughly 8%, yet you're requesting a 5% increase -- help us understand what specific cost drivers justify moving in the opposite direction before we discuss any adjustment.\"). Shorter and more directly sayable is better than a longer, more explanatory version. Omit this field entirely if there is no real negotiation to open, or if evidence is too thin to ground a concrete opening line without guessing.",
  "commercial_hypothesis": "per Hard Rule 8 -- optional, explicitly hedged speculation about a party's likely motive not directly stated in the evidence, omit entirely if none genuinely applies",
  "methodology_applied": "per Hard Rule 9 -- optional, name the specific procurement framework and/or negotiation tactic being applied and why it fits, omit entirely if no specific named framework/tactic genuinely adds clarity",
  "cost_driver_comparison": "per Hard Rule 10 -- optional, list of {\"driver\": name, \"claimed_percent\": number, \"market_percent\": number}, omit entirely if there's no genuine multi-driver claimed-vs-market comparison to structure",
  "key_figures": "per Hard Rule 11 -- optional, list of <<MIN_KEY_FIGURES>>-<<MAX_KEY_FIGURES>> {\"label\": str, \"value\": pre-formatted str}, neutral facts only, no implied judgment, omit entirely if no genuinely comparable reference numbers exist",
  "supplier_comparison": "per Hard Rule 12 -- optional, list of {\"name\": str, \"price\": str, \"otif\": str-or-null, \"defect_rate\": str-or-null, \"lead_time\": str-or-null}, restructuring facts already given, omit entirely if not applicable",
  "why_this_wins": "per Hard Rule 13 -- one sentence, the specific trade-off, included for optimization cases, omitted for constraint_satisfaction cases",
  "negotiation_dimensions": "per Hard Rule 14 -- optional, list of {\"dimension\": str, \"opening_ask\": str, \"target_outcome\": str, \"walk_away\": str}, one per genuinely negotiable dimension beyond price, omit entirely if price is the only real dimension",
  "negotiation_talk_track": "per Hard Rule 15 -- optional, list of <<MIN_TALK_TRACK>>-<<MAX_TALK_TRACK>> {\"trigger\": str, \"line\": str}, ordered sequence of moves, omit entirely if too simple to warrant a sequence",
  "financial_scenarios": "per Hard Rule 16 -- optional, list of {\"scenario\": str, \"annual_spend\": str, \"vs_baseline\": str with sign}, omit entirely if only one real scenario exists -- this is the last structured table field in the schema",
  "walk_away_threshold": "per Hard Rule 6 -- lead with commercial CONDITIONS (no audited evidence, exclusivity insisted upon, refusal of dual-sourcing, unacceptable indexation), with any price threshold as supporting evidence, not the sole trigger; omit the key entirely if nothing genuinely calculable from the evidence given",
  "disconfirming_condition": "the specific, quantified fact that would change this answer, per Hard Rule 5",
  "decision_type": "optimization | constraint_satisfaction"
}

Do NOT include a "financial_impact" key in your JSON output -- that field is computed separately and attached automatically after your response. Reference the pre-computed figures given to you (if any) inside your "reasoning" text instead.
If decision_type is constraint_satisfaction, your recommendation must state which option is disqualified and why — do not present a weighed trade-off, since a constraint-satisfaction question doesn't have a "better" option, it has a "still allowed" one.

Confidence guidance: "high" requires at least 2 independent evidence signals pointing the same direction. "medium" means evidence is present but some signals are mixed or a key monetizable input (like unit price or cost of capital) is missing. "low" means evidence is thin or conflicting.

ORGANIZATION HISTORY: you may be given a short list of this same organization's past recorded outcomes for this same content type (what was recommended, what actually happened, whether the reasoning held up, and sometimes an "unexpected insight" a past user noted). Treat this as real evidence, not background color:
- If past reasoning of a similar shape was marked "reasoning_wrong_bad_assumption" or "reasoning_wrong_bad_execution", do not repeat that same assumption or approach without accounting for why it failed before.
- Pay particular attention to any "unexpected insight" attached to a past case -- this is genuine qualitative wisdom a bare outcome verdict doesn't capture (e.g. a supplier caring more about contract length than price, or an internal stakeholder's support mattering more than the commercial numbers). If a past unexpected insight is genuinely relevant to the current case, actively incorporate it into your reasoning and, if it changes your recommendation or confidence, say so explicitly -- this is the single most valuable kind of history available and should not be treated as a minor footnote.
- If history is genuinely relevant to this case, you may reference it as one of the confidence factors (e.g. factor: "similar past case", value: "reasoning held in 2 of 2 prior cases", weight: "increases confidence").
- If no history is provided, or none of it is relevant to this specific case, reason from the evidence alone — do not force a reference to history that doesn't apply."""

# The real substitution step -- every <<TOKEN>> above gets replaced with the
# actual value from app/caps.py, the single source of truth. This is what
# makes the audit real: the prompt text literally cannot drift out of sync
# with the schema, because both now read from the same numbers, not two
# independently-typed copies of the same intent.
_CAP_SUBSTITUTIONS = {
    "<<MIN_INSIGHTS>>": caps.MIN_COMMERCIAL_INSIGHTS,
    "<<MAX_INSIGHTS>>": caps.MAX_COMMERCIAL_INSIGHTS,
    "<<MAX_METHODOLOGY_CHARS>>": caps.MAX_METHODOLOGY_CHARS,
    "<<MAX_HYPOTHESIS_CHARS>>": caps.MAX_HYPOTHESIS_CHARS,
    "<<MAX_COST_DRIVERS>>": caps.MAX_COST_DRIVERS,
    "<<MIN_KEY_FIGURES>>": caps.MIN_KEY_FIGURES,
    "<<MAX_KEY_FIGURES>>": caps.MAX_KEY_FIGURES,
    "<<MAX_SUPPLIERS>>": caps.MAX_SUPPLIERS,
    "<<MAX_SUPPLIERS_MINUS_ONE>>": caps.MAX_SUPPLIERS - 1,
    "<<MAX_DIMENSIONS>>": caps.MAX_NEGOTIATION_DIMENSIONS,
    "<<MIN_TALK_TRACK>>": caps.MIN_TALK_TRACK_MOVES,
    "<<MAX_TALK_TRACK>>": caps.MAX_TALK_TRACK_MOVES,
    "<<MAX_SCENARIOS>>": caps.MAX_FINANCIAL_SCENARIOS,
    "<<MAX_ASSUMPTIONS>>": caps.MAX_ASSUMPTIONS,
}
for _token, _value in _CAP_SUBSTITUTIONS.items():
    REASONING_SYSTEM_PROMPT = REASONING_SYSTEM_PROMPT.replace(_token, str(_value))


def _format_supplier_history(supplier_name: str | None, history: list[dict] | None) -> str:
    """
    Real, distinct formatting from _format_history above -- this is
    specifically about past encounters with the SAME NAMED supplier, not
    general organizational learning for the content type.

    Deliberately honest about volume: with 0 or 1 real past cases, there is
    no genuine pattern to speak of, and the prompt says so explicitly,
    rather than let the model manufacture a false-confident "this supplier
    typically..." from a single data point.
    """
    if not supplier_name:
        return ""
    if not history:
        return (
            f"No prior recorded cases found for \"{supplier_name}\" specifically -- "
            f"this appears to be the first case involving this named supplier. "
            f"Do not claim a historical pattern; there isn't one yet."
        )
    if len(history) == 1:
        h = history[0]
        return (
            f"Exactly ONE prior case found for \"{supplier_name}\" -- not enough to "
            f"state a genuine pattern (e.g. do not say \"typically settles at X\"), "
            f"but the specific facts from that one case can be referenced directly: "
            f"\"{h['raw_question'][:200]}\"" + (f" | Outcome: {h['outcome_description']}" if h.get("outcome_description") else " | No outcome recorded yet.")
        )
    lines = [f"{len(history)} prior cases found for \"{supplier_name}\" -- enough real history to speak to a genuine pattern if one is actually visible across them, not just from a single case:"]
    for h in history:
        line = f"- {h['created_at']}: \"{h['raw_question'][:200]}\""
        if h.get("outcome_description"):
            line += f" | Outcome: {h['outcome_description']}"
        if h.get("decision_alignment"):
            line += f" | Decision alignment: {h['decision_alignment']}"
        lines.append(line)
    return "\n".join(lines)


def _format_history(history: list[dict] | None) -> str:
    """
    Turns past decision_feedback rows (joined with their original commercial_position)
    into a compact, plain-language block the reasoner can weigh as evidence.
    This is the entire "organizational learning" mechanism for the MVP: no
    embeddings, no retrieval infra -- just this org's own recent recorded
    outcomes for the same content_type, most recent first.
    """
    if not history:
        return "None yet -- this is this organization's first recorded case of this type."

    lines = []
    for h in history:
        position = h.get("commercial_position") or {}
        if isinstance(position, str):
            try:
                position = json.loads(position)
            except json.JSONDecodeError:
                position = {}
        recommendation = position.get("recommendation", "(no recommendation on file)")
        line = (
            f"- Past recommendation: \"{recommendation}\" | "
            f"Verdict: {h['validation_verdict']} | "
            f"What actually happened: {h['outcome_description']}"
        )
        # This is the actual substance of "commercial memory," not just an
        # outcome status -- a genuine surprise from a past case is exactly
        # the kind of qualitative wisdom a bare Won/Lost verdict can't
        # capture, and it's precisely what should inform a similar future case.
        if h.get("unexpected_insight"):
            line += f" | Unexpected insight from that case: {h['unexpected_insight']}"
        lines.append(line)
    return "\n".join(lines)


def generate_commercial_position(
    normalized: NormalizedEvidence,
    raw_question: str,
    constraint_signal: str | None = None,
    computed_financial_impact=None,
    market_verification: dict | None = None,
    continuation_context: str | None = None,
    methodology_correction: str | None = None,
) -> CommercialPosition:
    client = _get_client()
    content_type = normalized.content_type
    # Derived once, here, for the existing prompt-building logic below,
    # which is intentionally left untouched -- per instruction, this
    # migration must not change reasoning quality or prompt text, only
    # where the evidence it reads comes from.
    evidence = normalized.as_flat_evidence_dict()
    history = normalized.history.org_history
    supplier_history = normalized.history.supplier_history
    financial_note = (
        f"\n\nPRE-COMPUTED FINANCIAL IMPACT (calculated deterministically, already correct -- "
        f"this will be shown to the user in its own 'Commercial Exposure' box, separate from your "
        f"reasoning. Do NOT recompute it, do NOT contradict it, and do NOT re-derive the full "
        f"arithmetic (e.g. 'X% x $Y = $Z') again inside 'reasoning' -- that exact computation is "
        f"already displayed elsewhere and re-showing it reads as repetition to the user. Refer to "
        f"it briefly instead, e.g. 'the exposure shown above' or 'the $Z figure already calculated', "
        f"and spend the sentence on what it MEANS rather than re-deriving it):\n"
        f"{computed_financial_impact.note}"
        if computed_financial_impact is not None
        else "\n\nNo financial figures could be computed (insufficient numeric evidence supplied)."
    )
    market_verification_note = (
        f"\n\nLIVE MARKET VERIFICATION (real web search performed just now, not your training "
        f"knowledge -- treat this as more current and specific than anything you already know "
        f"about this topic): claim checked: \"{market_verification['claim_checked']}\" -- "
        f"finding: {market_verification['finding']} -- {market_verification['verified_note']}. "
        f"You MUST reference this explicitly in your reasoning if it's relevant, and clearly "
        f"label it as verified-via-search-just-now, distinct from general knowledge."
        if market_verification is not None
        else ""
    )
    continuation_note = (
        f"\n\nTHIS CASE'S PRIOR POSITION (you already gave this recommendation; the user is now "
        f"telling you what happened since -- this is a CONTINUATION of that same case, not a new, "
        f"unrelated question):\n{continuation_context}\n\n"
        f"Update your recommendation in light of this new information. Do not silently restate the "
        f"prior reasoning in full -- explicitly say what changed and why, referencing the prior "
        f"position briefly (\"the earlier concern about X\") rather than re-deriving it (same "
        f"discipline as Hard Rule 17, now applied to this case's own history, not just this response).\n\n"
        f"SPECIFICALLY: if a structural element from the prior case is UNCHANGED this round -- the "
        f"procurement framework/negotiation tactic (methodology_applied), a supplier's price or "
        f"performance data that wasn't affected by what happened, the operational comparison between "
        f"options -- say it is unchanged in one short clause (e.g. \"operational picture is unchanged "
        f"from before\") and move on; do NOT restate the full comparison, table, or derivation again. "
        f"Only fully explain what is GENUINELY new or changed this round (e.g. one supplier's new "
        f"price, an updated walk-away calculation). A continuation response covers strictly less new "
        f"ground than the original case did, and should read shorter as a result, not the same length."
        if continuation_context is not None
        else ""
    )
    methodology_correction_note = (
        f"\n\n---\n"
        f"IMPORTANT CORRECTION: your previous response for this exact case had a real "
        f"methodology-consistency problem: {methodology_correction} "
        f"Address this directly in your regenerated response -- do not silently repeat "
        f"the same gap while still claiming the same methodology."
        if methodology_correction
        else ""
    )
    # Real, new addition per the NormalizedEvidence migration: if the
    # normalization boundary detected a genuine conflict between the
    # model's own earlier extraction and a deterministic fallback (two
    # independent methods disagreeing on the same value), that
    # disagreement must never be silently hidden -- it's surfaced
    # explicitly here so the final reasoning's own confidence can reflect
    # real uncertainty about that specific figure, not false precision.
    conflict_entries = [
        (field, prov) for field, prov in normalized.provenance.items() if prov.conflicting
    ]
    conflict_note = (
        "\n\nEXTRACTION CONFLICT DETECTED (real, unresolved uncertainty -- do not silently pick "
        "one value and move on; reflect this specific uncertainty in your confidence level):\n"
        + "\n".join(
            f"- {field}: two independent extraction methods disagreed -- {prov.conflicting_values[0]!r} "
            f"vs {prov.conflicting_values[1]!r}. Treat this specific figure as genuinely uncertain."
            for field, prov in conflict_entries
        )
        if conflict_entries
        else ""
    )
    user_message = (
        f"QUESTION: {raw_question}\n\n"
        f"CONTENT TYPE: {content_type}\n"
        f"CONSTRAINT SIGNAL: {constraint_signal or 'none'}\n\n"
        f"STRUCTURED EVIDENCE PROVIDED:\n"
        + "\n".join(f"- {k}: {v}" for k, v in evidence.items())
        + financial_note
        + market_verification_note
        + continuation_note
        + methodology_correction_note
        + conflict_note
        + f"\n\nORGANIZATION HISTORY (past outcomes, same content type, most recent first):\n"
        + _format_history(history)
        + (
            f"\n\nSUPPLIER-SPECIFIC HISTORY (past cases naming this exact supplier, per Hard Rule 19):\n"
            + _format_supplier_history(evidence.get("supplier_name"), supplier_history)
            if evidence.get("supplier_name")
            else ""
        )
    )

    def _attempt(max_tokens: int, correction: str = ""):
        message_content = user_message + correction
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=max_tokens,
            system=REASONING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message_content}],
        )
        try:
            from app.pipeline.token_tracking import record_usage
            record_usage("reasoning", CLASSIFIER_MODEL, response.usage.input_tokens, response.usage.output_tokens)
        except Exception:
            pass  # never let cost tracking block the real request
        return response

    # Raised after a real, live failure: a genuinely dense question (multiple
    # suppliers, multiple stakeholders, extensive market data, all 12
    # requested sections) truncated twice even at the previous 3000/6000
    # ceiling. This is the actual evidence calibrating these numbers now,
    # not a guess -- real usage revealed the old ceiling was too low for a
    # legitimately complex real-world case, not an edge case to dismiss.
    # Raised a second time, this time with real safety margin, after a
    # second consecutive real failure at increasing question complexity
    # (first: multi-supplier + stakeholders; second: three suppliers, more
    # requested sections, conflicting stakeholders -- genuinely harder than
    # what prompted the first raise). Two real failures in a row means
    # incremental nudges keep landing short of actual need. Raising this
    # ceiling costs nothing extra for simpler questions -- API cost is based
    # on actual tokens generated, not the ceiling -- so there's no downside
    # to giving real headroom here.
    # Raised a THIRD time, this time with substantial, deliberately generous
    # headroom, after a third consecutive real failure. The pattern is now
    # clear: the schema has grown many more optional fields tonight
    # (negotiation_dimensions, negotiation_talk_track, cost_driver_comparison,
    # key_figures, supplier_comparison) that can ALL fire simultaneously on
    # the densest real questions -- this exact question triggered nearly
    # every one of them at once, the genuine worst case. Raising this
    # ceiling costs nothing extra for simpler questions -- API cost is based
    # on actual tokens generated, not the ceiling -- so there's no reason to
    # be conservative here anymore.
    response = _attempt(max_tokens=12000)  # the reasoning output is larger
    # (recommendation + reasoning + confidence factors + assumption, etc.)
    # than classification's, so it needs meaningfully more room, on top of
    # whatever the model spends on its own internal reasoning before answering.

    if response.stop_reason == "max_tokens":
        response = _attempt(max_tokens=20000)
        if response.stop_reason == "max_tokens":
            raise ValueError(
                "Reasoning response was truncated twice even at a larger token "
                "budget -- this needs investigation, not just a bigger number."
            )

    raw_text = _extract_text(response)

    # Same permanent fix as the classifier: if the model produced prose with
    # no JSON structure anywhere (rather than a truncation or fence-formatting
    # issue), retry once with an explicit correction naming the failure,
    # rather than repeating the same call and likely the same result.
    if not _looks_like_json(raw_text):
        correction = (
            "\n\n---\n"
            "Your previous response did not include the required JSON object "
            "at all. Output NOTHING except the JSON object described above -- "
            "no extra headings, no markdown report, nothing else. "
            "The very first character of your entire response must be '{'."
        )
        response = _attempt(max_tokens=12000, correction=correction)
        raw_text = _extract_text(response)
        if not _looks_like_json(raw_text):
            raise ValueError(
                "Reasoner ignored the JSON-only instruction twice in a row, "
                "even after an explicit correction. This needs investigation "
                f"-- raw response: {raw_text[:300]!r}..."
            )

    text = _extract_json_object(raw_text)

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Reasoner returned non-JSON output: {text!r}") from e

    _normalize_confidence_weights(raw)

    # This is the real enforcement mechanism — not the prompt asking nicely,
    # but a schema that structurally rejects a bare confidence score or a
    # missing derivation note, regardless of what the prompt said.
    #
    # Real fix for a real, live failure: a genuinely dense case (six real
    # negotiable dimensions -- price, term, exclusivity, indexation, minimum
    # volume, payment terms) exceeded a cap, and the ONLY behavior before
    # this fix was a hard failure with zero retry -- every other failure
    # type tonight (truncation, non-JSON output) gets a second attempt with
    # a specific correction; this one didn't. Now it does: the real Pydantic
    # error tells us exactly which field and constraint were violated, so
    # the retry can name the specific fix needed, not just "try again."
    try:
        return CommercialPosition.model_validate(raw)
    except ValidationError as first_error:
        error_summary = "; ".join(
            f"field '{'.'.join(str(p) for p in err['loc'])}': {err['msg']}"
            for err in first_error.errors()
        )
        correction = (
            "\n\n---\n"
            "Your previous response did not match the required schema. "
            f"Specific problems: {error_summary}. "
            "Re-generate the full JSON response, fixing exactly these problems -- "
            "if a list field is over its stated cap, keep only the most commercially "
            "important items up to that cap, per the HARD CAP guidance for that field above."
        )
        response = _attempt(max_tokens=12000, correction=correction)
        raw_text = _extract_text(response)
        text = _extract_json_object(raw_text)
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Reasoner returned non-JSON output on retry: {text!r}") from e
        _normalize_confidence_weights(raw)
        try:
            return CommercialPosition.model_validate(raw)
        except ValidationError as second_error:
            raise ValueError(
                f"Model output failed schema validation twice in a row, even after "
                f"an explicit correction naming the problem: {second_error}"
            ) from second_error


def _normalize_confidence_weights(raw: dict) -> None:
    """
    Safety net on top of the prompt instruction: even with a clear prompt,
    a model can still occasionally append extra descriptive text to the
    weight field (e.g. 'decreases confidence because X' instead of just
    'decreases confidence'). Rather than rejecting a substantively good
    answer over a formatting technicality, extract the real value defensively.
    This does NOT weaken Hard Rule 2 -- the factor still must be present and
    still must genuinely indicate a direction; it just tolerates the model's
    natural tendency to want to explain itself in the same field.
    """
    factors = raw.get("confidence", {}).get("factors", [])
    for f in factors:
        weight = f.get("weight", "")
        lower = weight.lower()
        if lower.startswith("increases confidence"):
            f["weight"] = "increases confidence"
        elif lower.startswith("decreases confidence"):
            f["weight"] = "decreases confidence"
        # If it matches neither prefix, leave it unchanged -- this is a
        # genuine validation failure worth surfacing, not silently patched.
