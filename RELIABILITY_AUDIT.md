# VendorEdge Reliability Audit
Traced directly against the real, current codebase — every claim below is backed by a specific file and line, not a general impression.

---

## PART 1 — Full Lifecycle Trace

```
raw_question (user text)
  │
  ▼
[classify()] — classifier.py, ONE LLM call
  produces: content_type, decision_type, constraint_signal,
            extracted_evidence{}, numeric_facts{}
  │
  ▼
create_decision() — decisions.py
  ├─ NEW fallback pass (annual_spend, requested_change_percent only):
  │    backfills BOTH numeric_facts AND extracted_evidence, before storage
  ├─ STORE: user_supplied_inputs = extracted_evidence, numeric_facts = numeric_facts
  ▼
check_missing_evidence() — evidence.py, deterministic, no LLM
  reads: extracted_evidence + (conditionally) incoterm
  │
  ├─ missing fields exist → status = awaiting_user_input, STOP HERE
  │      (user answers via /respond, evidence merged, check_missing_evidence runs AGAIN)
  │
  └─ nothing missing → _run_reasoning()
       ├─ SECOND, duplicate fallback pass for annual_spend/requested_change_percent
       │    (numeric_facts only this time — evidence already fixed upstream)
       ├─ freight fallback: text → number, numeric_facts only
       ├─ region fallback: text → market_verification target ONLY
       │    (never written to evidence, never stored, never reaches evidence-gate)
       ├─ compute_financial_impact() — financial.py, deterministic
       ├─ verify_market_claim() — live web search, non-blocking
       ├─ generate_commercial_position() — reasoner.py, SECOND LLM call
       │    internal retry: schema validation (ValidationError → 1 retry)
       ├─ financial_impact FORCE-ATTACHED (overwrites model's own value)
       ├─ TCO methodology check → up to 1 more full regeneration
       ├─ Kraljic methodology check → up to 1 more full regeneration
       └─ confidence_calibration_note attached (deterministic, DB query)
  │
  ▼
final CommercialPosition → stored → returned → telemetry (fallback_events)
```

**Worst-case real LLM call count for one response**: classify (1) + reasoning (1, +1 internal retry) + TCO retry (1) + Kraljic retry (1) = up to **5 real API calls** for a single dense answer. This is a real cost/latency fact, not a bug, but nobody has stated it plainly before — worth knowing.

---

## PART 2 — Audit Matrix (per evidence type)

| Evidence | Extracted by model | Deterministic fallback | Available before evidence-gate | Available during reasoning | Used in calculation | Tested end-to-end |
|---|---|---|---|---|---|---|
| Annual spend | Yes (numeric_facts) | ✅ Yes (both layers) | ✅ **Yes, fixed** | ✅ Yes | ✅ Yes | ✅ Yes (`test_evidence_gate_backfill.py`) |
| Requested increase % | Yes (numeric_facts) | ✅ Yes (both layers) | ✅ **Yes, fixed** | ✅ Yes | ✅ Yes | ✅ Yes |
| Supplier region/country | Yes (extracted_evidence) | ⚠️ Partial | ❌ **No** | ✅ Yes (market verification only) | ❌ No (not a calc input) | ⚠️ Unit-only |
| Incoterm | Yes (extracted_evidence) | ❌ **None** | ❌ **No** | Only if model extracted it | Gates freight requirement | ❌ No |
| Freight cost | User-typed text (post-gate) | ✅ Yes (numeric_facts only) | N/A (post-gate field) | ✅ Yes | ⚠️ **Only if annual_volume_units also present** | ✅ Partial |
| Duty/tax | Model only (numeric_facts) | ❌ **None** | N/A | Only if model extracted it | ✅ If present | ❌ No |
| Currency | Yes (extracted_evidence) | ❌ **None** | N/A | Referenced in prompt only, no calc | ❌ No conversion logic exists at all | ❌ No |
| Supplier price | Yes (both fields) | ❌ None | Partial (evidence-gate checks text only) | ✅ Yes | ✅ Yes (price_increase) | ✅ Pipeline-level |
| Supplier comparison data | Yes (quote_comparison fields) | ❌ None | ✅ Yes (evidence-gate) | ✅ Yes | Not calculated, displayed only | ✅ Pipeline-level |
| Payment terms | Yes (quote_comparison only) | ❌ None | ✅ Yes (quote_comparison) / ❌ **N/A for price_increase** | ✅ Yes if present | ❌ No cost-of-capital calc exists | ⚠️ Partial |
| Lead time | Yes (quote_comparison only) | ❌ None | ✅ Yes (quote_comparison) | ✅ Yes | Not calculated | ⚠️ Partial |
| Quality/defect data | Yes (quote_comparison only) | ❌ None | ✅ Yes (quote_comparison) | ✅ Yes | Not calculated | ⚠️ Partial |
| Switching cost | Yes (numeric_facts) | ❌ None | N/A | ✅ Yes | ✅ Yes, if given | ✅ Pipeline-level |
| Supplier history | N/A (DB-derived) | N/A — deterministic by design | N/A | ✅ Yes | Not a calc, informs reasoning | ✅ Yes, real DB test |
| Annual volume (units) | Model only (numeric_facts) | ❌ **None** | N/A | Only if model extracted it | **Silently gates freight calc** | ❌ No |

**Six real, undertested or unprotected fields**: Incoterm, Duty, Currency, Annual volume, Region, Payment terms (in price_increase context). Every one of these shares the exact structural weakness the annual-spend bug had — just not yet discovered by a real user.

---

## PART 3 — Classifier Audit

**Correction to the audit brief itself, stated plainly**: "Contract Review," "Supplier Evaluation," and "Cost Reduction" are not real content types in this codebase. `EVIDENCE_REQUIREMENTS` (evidence.py) defines exactly two: `price_increase` and `quote_comparison`. Anything else is classified `unsupported` and rejected outright before reaching evidence-gating at all. This isn't a gap to audit — it's a scope fact worth being precise about, since auditing a content type that doesn't exist would produce a false finding.

**The real classifier risk, confirmed**: `payment_terms_per_supplier`, `lead_time_per_supplier`, and `quality_or_defect_history_per_supplier` exist **only** under `quote_comparison`. If a case is genuinely a price-increase negotiation but the classifier miscategorizes it as `quote_comparison` (exactly the incident from a few messages ago, still unresolved), the evidence-gate silently applies the wrong requirement set — asking for supplier-comparison fields on what may actually be a single-supplier negotiation, or vice versa. **This is a real, live, previously-flagged incident that this audit confirms is architecturally possible, not a one-off.**

**A second, quieter classifier risk**: `classify()` has retries for non-JSON output and for truncation, but **none for a structurally valid JSON response that's simply missing an expected key**. `classification.get("numeric_facts") or {}` silently accepts an empty dict with zero detection or logging that the key was ever absent. A classifier response that's technically well-formed JSON but omits `numeric_facts` entirely produces the exact same downstream symptom as tonight's incidents — with no signal anywhere that it happened.

---

## PART 4 — Single Source of Truth Audit

| Concern | Finding |
|---|---|
| Size caps (Kraljic dims, insights, etc.) | ✅ Genuinely single-sourced via `app/caps.py`, actively tested (`test_caps_consistency.py`) |
| Model version string | ✅ Fixed earlier tonight — single source, `app/model_config.py` |
| `INCOTERMS_WHERE_BUYER_BEARS_FREIGHT` | ✅ Genuinely shared — `methodology_consistency.py` imports it from `evidence.py`, not duplicated |
| **Fallback logic for annual_spend / requested_change_percent** | 🔴 **Duplicated, not shared.** The same extraction-and-backfill logic is written out twice — once in `create_decision`, once in `_run_reasoning` — rather than one shared function called from both places. They currently produce the same result only because the second copy's guard (`if "annual_spend_usd" not in numeric_facts`) correctly no-ops once the first has already run. But they are two independent pieces of code that happen to agree today, not one enforced rule. |
| Evidence field names vs. prompt text | ⚠️ `_build_field_reference()` in classifier.py dynamically pulls from `FIELD_PROMPTS`, which is good — but the reasoner's own JSON-output schema example is a separate, hand-written block in `reasoner.py`, not generated from `models.py`. No automated check confirms these stay in sync beyond the caps-consistency tests, which only check numeric limits, not full field-name presence. |

---

## PART 5 — Test Coverage Audit

**Classification of all 67 tests, by what they actually prove:**

| Category | Count | What's genuinely proven |
|---|---|---|
| Unit / extraction (isolated function calls) | 22 | Pattern-matching correctness in isolation |
| Fallback logic (isolated) | 13 | The fallback function itself works, called directly |
| Evidence-gate logic (isolated) | 6 | `check_missing_evidence()` returns correct lists given a hand-built dict |
| Schema/model integrity | 15 | Pydantic fields exist, caps enforce correctly |
| Real end-to-end (create → complete, real DB, real HTTP) | 2 | `test_integration_full_flow.py`, `test_evidence_gate_backfill.py` |
| Security / tenant isolation | 3 | Real, DB-level, genuinely rigorous |
| Methodology contracts | 8 | Mostly isolated function tests; retry mechanism tested once via full mock chain |

**The honest gap, stated in your own terms**: of 67 tests, only **2** prove "a real user question containing X reaches the correct evidence gate, X is available there, the user isn't unnecessarily asked, X reaches reasoning, and X is correctly used in the final calculation" — for annual spend and requested percent specifically. **Zero** tests prove that same full chain for region, Incoterm, duty, currency, or annual volume. The 13 "fallback" tests are real and correct, but every one of them stops at "the extraction function returns the right value" — none of them prove the value survives the full journey to a calculation or a user-facing decision.

---

## PART 6 — Findings, by severity

### 🔴 Critical

**1. Incoterm has zero deterministic fallback, and its absence causes a silent skip, not a visible error.**
- File/function: `evidence.py:check_missing_evidence()`, gated by `evidence.get("incoterm")`
- What happens today: if the classifier misses a stated Incoterm on a dense question (the same failure class already proven twice tonight), the conditional freight requirement simply never triggers — `incoterm in INCOTERMS_WHERE_BUYER_BEARS_FREIGHT` evaluates False on an empty string, exactly like "no Incoterm was ever mentioned."
- Why risky: this is silent, not loud. The other bugs found tonight were annoying (re-asked a question) or visibly wrong (missing financial figure). This one produces a response that looks complete and confident while quietly missing a cost dimension it should have caught — the worst kind of failure for a product whose entire pitch is "never silently guess."
- Real user impact: a genuine FOB or EXW case, on a dense question, could get a full recommendation with no freight consideration at all, and nothing in the output would flag that this happened.
- Recommended fix: a deterministic Incoterm-detection fallback, same pattern as region — a fixed list of the 11 real terms, checked via word-boundary regex against the raw text.
- Test required: the exact real-world equivalent of the region test — a dense question stating "FOB" in a way a busy classifier could plausibly skip, proving the fallback catches it and the freight requirement still fires.

**2. Duty rate and currency have zero deterministic fallback at all.**
- File/function: `classifier.py` prompt only; no fallback module exists for either.
- What happens today: entirely dependent on one LLM extraction pass, same single point of failure already proven fragile twice.
- Real user impact: a stated duty rate or foreign currency could be silently dropped on a dense case, understating true landed cost with no visible flag.
- Recommended fix: same pattern as `financial_fallback.py` — regex-based backup extraction for a stated duty percentage and named currency codes/symbols.
- Test required: real sentences containing both, structured exactly like the aluminum/Kowalski/Meridian cases that found the other three.

**3. `annual_volume_units` has zero fallback, and its absence silently breaks the freight calculation even when freight cost itself is captured correctly.**
- File/function: `financial.py:compute_financial_impact()`, the `if freight_per_unit is not None and annual_volume is not None` guard.
- What happens today: a case stating spend as one lump figure (exactly the common, now-fixed pattern) will never populate `annual_volume_units`, silently preventing the freight-cost guarantee from ever firing, even on a case where the user typed a clean per-unit freight figure into the evidence-gate.
- Real user impact: the same "TCO claims coverage, coverage is actually missing" failure that started this whole audit — but through a different door, one the methodology checker would only catch if the model happens to also skip mentioning freight in prose.
- Recommended fix: either (a) a fallback for annual volume, or (b) restructure the freight calculation to also accept a directly-stated total annual freight figure, not only a per-unit-times-volume path.
- Test required: a real case with lump-sum spend, a clean per-unit freight answer, and an assertion that `annual_freight_cost_usd` is still populated.

### 🟠 Structural risk

**4. The annual_spend/requested_change_percent fallback logic is duplicated, not shared, across two functions.**
- File/function: `decisions.py`, both `create_decision()` and `_run_reasoning()`.
- Why risky: they agree today only because of a defensive guard, not because they're one enforced rule. A future edit to one (a new pattern, a bug fix) has no mechanism forcing the other to match — this is exactly the class of drift this audit was commissioned to find.
- Recommended fix: extract to one shared function, e.g. `_backfill_financial_evidence(raw_question, extracted_evidence, numeric_facts)`, called from both places, so there is structurally one place this logic can ever live.
- Test required: a test that would fail if the two call sites ever diverged in behavior — e.g., asserting both code paths produce identical output for the same input, or better, deleting the duplication so the test becomes moot.

**5. Payment terms, lead time, and quality data exist only inside `quote_comparison`'s evidence schema — invisible to `price_increase` entirely.**
- File/function: `evidence.py:EVIDENCE_REQUIREMENTS`.
- Why risky: this is fine *as designed* — but it means a genuine price-increase negotiation involving an alternative supplier's payment terms (exactly the Kowalski/Meridian case) has no formal evidence-gate path for that data; it currently only reaches VendorEdge because `how_critical_is_this_supplier_relationship`'s free-text prompt happens to invite it informally. If that one field's wording ever changes, this entire category of insight quietly disappears with no test to catch it.
- Recommended fix: not urgent to fix architecturally, but worth a permanent test locking in that free-text invitation's current behavior specifically, since it's carrying real structural weight informally.

**6. Up to two additional full LLM regenerations can be triggered per response (TCO + Kraljic), with no shared retry budget or cost visibility.**
- File/function: `decisions.py`, the sequential TCO and Kraljic check blocks.
- Why risky: not a correctness bug, but a real, silent cost and latency multiplier that grows every time a new methodology contract is added, with nothing tracking or capping the combined effect.
- Recommended fix: a shared, named constant for max total regenerations per response, and logging (reusing `fallback_events`-style instrumentation) for how often multiple contracts fire on the same response.

### 🟡 Test gap

**7. Region fallback has real unit tests and zero integration proof.**
- Confirmed directly: all three tests in `test_region_fallback.py` call `detect_supplier_region_fallback()` in isolation. None create a real decision and verify the region actually reaches `market_verification_scope` in a stored, returned response.
- Test required: the same shape as `test_evidence_gate_backfill.py`, but proving the region reaches the final response's `market_verification_scope` field.

**8. No test proves what happens when `numeric_facts` is a well-formed but empty dict from a technically-valid classifier response.**
- This is the exact failure mode described in Part 3 — a structurally valid response missing an expected key, silently accepted with `or {}`.
- Test required: simulate a classifier response with `content_type` present but `numeric_facts` key entirely absent, and confirm the system either logs this distinctly from a genuine "nothing to extract" case, or explicitly document why that distinction doesn't matter.

**9. No test proves the classifier correctly distinguishes a price-increase-with-a-mentioned-alternative from a genuine quote-comparison.**
- This is the still-unresolved incident from earlier. It remains genuinely unverified, not fixed, not disproven.
- Test required: the exact real case, submitted as a single message, with an assertion on which `content_type` comes back.

### 🟢 Healthy

- Tenant isolation / RLS: genuinely proven, DB-level, adversarially tested.
- Caps consistency: genuinely single-sourced, actively regression-tested, proven to catch drift by deliberate re-break.
- Supplier memory honesty calibration: genuinely tested against zero/one/many real cases.
- Confidence calibration minimum-sample gate: genuinely tested, including cross-tenant isolation specifically.
- Schema validation retry: real, proven with a real ValidationError reproduction.
- Annual spend / requested percent, end-to-end: the one pair genuinely proven from raw text to final calculation, including the evidence-gate layer specifically.

---

## PART 7 — Proposed Reliability Architecture

**Direct answer to whether the current architecture already supports "extract once, normalize once, use everywhere": no, not yet. It's currently three overlapping ad-hoc layers that happen to agree in the cases we've tested, not one enforced source of truth.**

Right now, "does this evidence exist" gets asked in at least three genuinely different ways depending on which stage is asking: `extracted_evidence` (text, checked by the evidence-gate), `numeric_facts` (numbers, checked by the calculation), and inline fallback calls scattered at the exact point each stage happens to need something. There is no single moment where "what do we actually know about this case" gets decided once, correctly, and handed downstream as a settled fact.

**Proposed shape — a real, single normalization stage, inserted right after classification, before anything else touches the data:**

```
raw_question
  │
  ▼
classify()  →  raw classifier output (unchanged)
  │
  ▼
normalize_evidence(raw_question, classifier_output)
  │  ONE function, ONE place, that:
  │  - runs EVERY deterministic fallback (spend, percent, freight,
  │    region, incoterm, duty, currency, volume) unconditionally
  │  - backfills BOTH the text evidence dict AND the numeric dict
  │    together, always, never one without the other
  │  - returns one object: NormalizedEvidence
  │       (guaranteed internally consistent — if incoterm is set,
  │        the freight-relevance flag is already computed and attached,
  │        not re-derived separately in evidence.py AND
  │        methodology_consistency.py)
  ▼
check_missing_evidence(normalized)     ← reads ONLY normalized data
_run_reasoning(normalized)             ← reads ONLY normalized data
determine_relevant_tco_dimensions(normalized)  ← reads ONLY normalized data
```

**The one rule this enforces that nothing today enforces**: no stage is ever allowed to call a fallback function directly. Every stage receives `NormalizedEvidence` and trusts it completely — the guarantee becomes true exactly once, at one single, testable boundary, instead of becoming true gradually and inconsistently as execution happens to pass through different functions.

This also directly fixes Finding 4 (duplicated fallback logic) as a side effect, not a separate task — there would be structurally only one place fallback logic could live.

---

## PART 8 — The direct question, answered honestly

**"If we continue fixing bugs one-by-one as we discover them, are we likely to keep finding this same class of bug indefinitely?"**

Yes. With near certainty, based on what this audit actually found. Three more fields — Incoterm, duty, currency — have the *exact* structural shape that produced the last three real incidents: a single LLM extraction pass, no deterministic backup, no test proving the value survives to where it's needed. This isn't a prediction; it's the same measurement that already fired twice tonight, still sitting unfired a third and fourth and fifth time, waiting on the next dense real question that happens to stress the right field.

**The architectural change that stops it**: not another fallback function. A structural rule that no stage may read raw extraction output directly — every stage reads only from one normalized, fully-backfilled evidence object, produced once, immediately after classification. That single change turns "did we remember to add a fallback here too" from a thing a human has to notice, case by case, into something that's structurally impossible to get wrong, because there is no longer a second place to forget.

**What this audit deliberately did not do**: fix anything. Per your instruction, this is diagnosis only.
