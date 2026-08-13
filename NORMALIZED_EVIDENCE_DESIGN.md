# NormalizedEvidence — Design Document
No code changes in this document. Design only, per instruction.

---

## 0. The core design decision this rests on

Every field is stored as a **clean, typed value** in the main object — never wrapped, never `.value`-unwrapped by downstream code. Provenance (source, confidence, conflict status) lives in a **separate, parallel ledger**, keyed by field name. This is a deliberate choice: wrapping every field infects every downstream read with unwrapping noise, which makes the object unpleasant to actually use and defeats the goal of a clean consumer boundary. The ledger gives full traceability without that cost.

```
NormalizedEvidence
├── common: CommonEvidence            # true regardless of content_type
├── case: PriceIncreaseEvidence | QuoteComparisonEvidence   # discriminated by content_type
├── derived: DerivedEvidence          # computed ONCE here, never re-derived downstream
└── provenance: dict[str, FieldProvenance]   # the traceability ledger
```

---

## 1 & 2. Every field, and its source

### `CommonEvidence` — true regardless of case type

| Field | Type | Source(s) |
|---|---|---|
| `supplier_name` | `str \| None` | LLM extraction only (never fallback — a generic name like "Supplier A" is deliberately excluded, see classifier.py) |
| `supplier_region_or_market` | `str \| None` | LLM extraction, deterministic fallback (`region_fallback.py`) |
| `supplier_currency` | `str \| None` | LLM extraction, **new** deterministic fallback (does not exist today — Critical Finding #2) |
| `incoterm` | `str \| None` | LLM extraction, **new** deterministic fallback (does not exist today — Critical Finding #1) |
| `duty_or_tax_rate_percent` | `float \| None` | LLM extraction, **new** deterministic fallback (does not exist today — Critical Finding #2) |
| `annual_volume_units` | `float \| None` | LLM extraction, **new** deterministic fallback (does not exist today — Critical Finding #3) |
| `unit_price_usd` | `float \| None` | LLM extraction |

### `PriceIncreaseEvidence` — case-specific

| Field | Type | Source(s) |
|---|---|---|
| `current_price_or_terms` | `str` (required) | LLM extraction, deterministic fallback, user follow-up |
| `requested_increase_percent` | `float` (required) | LLM extraction, deterministic fallback (existing, proven), user follow-up |
| `suppliers_stated_justification` | `str` (required) | LLM extraction, user follow-up |
| `how_critical_is_this_supplier_relationship` | `str` (required) | LLM extraction, user follow-up |
| `annual_spend_usd` | `float \| None` | LLM extraction, deterministic fallback (existing, proven) |
| `switching_cost_usd` | `float \| None` | LLM extraction |
| `freight_cost_or_estimate` | `str \| None` | User follow-up **only** (conditionally required, never asked unless `derived.freight_relevant`) |

### `QuoteComparisonEvidence` — case-specific

| Field | Type | Source(s) |
|---|---|---|
| `number_of_suppliers_being_compared` | `str` (required) | LLM extraction, user follow-up |
| `price_per_supplier` | `str` (required) | LLM extraction, user follow-up |
| `payment_terms_per_supplier` | `str` (required) | LLM extraction, user follow-up |
| `lead_time_per_supplier` | `str` (required) | LLM extraction, user follow-up |
| `quality_or_defect_history_per_supplier` | `str` (required) | LLM extraction, user follow-up |
| `is_this_a_new_or_incumbent_relationship` | `str` (required) | LLM extraction, user follow-up |

### `DerivedEvidence` — computed once, here, never re-derived downstream

| Field | Type | Computed from |
|---|---|---|
| `resolved_annual_spend_usd` | `float \| None` | `case.annual_spend_usd` if present, else `common.unit_price_usd × common.annual_volume_units` if both present, else `None` |
| `annual_spend_resolution_method` | `enum: direct \| derived_from_price_and_volume \| unresolved` | Which branch above actually fired — this answers "how do spend/volume/price interact" (requirement 8) explicitly, as data, not implicit code paths |
| `freight_relevant` | `bool` | `common.incoterm in INCOTERMS_WHERE_BUYER_BEARS_FREIGHT` — this is the fix for Critical Finding #1; computed here means it can never be silently skipped downstream |
| `duty_relevant` | `bool` | `common.supplier_region_or_market or common.supplier_currency or common.incoterm` present |
| `currency_mismatch` | `bool` | `common.supplier_currency` present and differs from an implied USD default |

### `history: HistoryContext` — from database, not extraction

| Field | Type | Source |
|---|---|---|
| `org_history` | `list[dict]` | Database query, same content_type, existing `_get_org_history` |
| `supplier_history` | `list[dict]` | Database query, matched by `common.supplier_name`, existing `_get_supplier_specific_history` |
| `confidence_calibration_note` | `str \| None` | Database query, existing `_compute_confidence_calibration` |

This is explicitly its own top-level section, not folded into `derived` — it answers requirement 2's fourth source category directly, and it's structurally different from everything else (it never comes from the current question's text at all).

---

## 3. Required vs optional

- **Required fields are exactly the current `EVIDENCE_REQUIREMENTS` lists**, unchanged — this design doesn't change *what's* required, only *where the guarantee that it's available lives*.
- **`freight_cost_or_estimate` becomes required conditionally**, gated by `derived.freight_relevant` — computed once, correctly, in the normalization stage itself, not re-checked separately in `evidence.py` as it is today.
- Everything in `CommonEvidence` and `DerivedEvidence` is optional by nature — none of it blocks the evidence-gate; it enriches reasoning when present, and its *absence* is itself meaningful, honest information (e.g., `duty_relevant=True` but `duty_or_tax_rate_percent=None` is precisely the "landed cost may be understated" case Hard Rule 18 already handles).

---

## 4. Conflict resolution — LLM vs deterministic fallback disagreement

This has never actually happened in any real case found so far — every real incident has been "LLM missed it, fallback caught it," never "LLM said one thing, fallback found a different number in the same text." But the design needs a real rule, not silence, for when it does.

**The rule:**
1. Only one source has a value → use it, mark provenance as that source.
2. Both sources have a value and **agree** (numerically equal, or case-insensitive equal for strings) → use the LLM's value, mark provenance `both_agree` (a small, genuine confidence boost — two independent methods concurring).
3. Both sources have a value and **disagree** → use the LLM's value as primary (it has more context than a regex ever will), but:
   - Mark provenance `conflicting`, storing both values in the ledger, not just the winner.
   - Log a new telemetry event (`fallback_conflict`, reusing the existing `fallback_events` table shape) — this is a **new, real signal** worth having: a conflict is arguably more interesting than either value being individually missing, since it might mean the fallback pattern itself is too naive for that sentence shape, or the LLM misread the question.
   - Surface the conflict explicitly into the reasoning prompt as a stated fact ("Two independent extraction methods disagreed on X: LLM found $2.0M, pattern match found $2.4M — treat this specific figure as uncertain"), so it's never silently resolved and hidden from the final answer's own confidence reasoning.

---

## 5. Provenance storage

```
FieldProvenance:
    source: enum {
        llm_extraction,
        deterministic_fallback,
        user_followup,
        database_history,
        derived_calculation,
        both_agree,
    }
    conflicting: bool
    conflicting_values: tuple[Any, Any] | None   # only set when conflicting=True
    stage_captured: str   # e.g. "classification", "evidence_gate_backfill", "respond_endpoint"
```

One entry per field name in `NormalizedEvidence.provenance`, covering every field across `common`, `case`, and `derived`. This directly answers requirement 5: for any value, at any point downstream, `evidence.provenance["incoterm"].source` tells you definitively whether it came from the user's original text via the model, a regex fallback, a follow-up answer, or a calculation — without guessing from context.

---

## 6. Confidence / verification status

Deliberately **not** a separate numeric confidence score per field — that would invite exactly the false-precision problem Hard Rule 1 exists to prevent (a fabricated-feeling "87% confident" on an extraction). Instead, verification status is a **direct consequence of source**, not a separate invented number:

| Source | Verification status |
|---|---|
| `user_followup` | Highest — the user directly typed this in response to a specific question |
| `both_agree` | High — two independent extraction methods concurred |
| `llm_extraction` (alone) | Standard — the existing, already-proven level of trust |
| `deterministic_fallback` (alone) | Standard — proven equally reliable in every real incident so far |
| `conflicting` | Explicitly flagged, never silently trusted at standard level |
| `derived_calculation` | Inherits the lower of its inputs' statuses |

This mirrors the existing, working design principle behind `financial_impact`: never invent a confidence number, but do let the *origin* of a value honestly speak to how much it should be trusted.

---

## 7. How Incoterm determines freight requirements

Fully computed inside the normalization stage, once:

```
derived.freight_relevant = common.incoterm in INCOTERMS_WHERE_BUYER_BEARS_FREIGHT
```

`evidence.py:check_missing_evidence()` becomes a **consumer**, not a re-deriver: it reads `derived.freight_relevant` directly and conditionally adds `freight_cost_or_estimate` to the required list. It never computes this itself again. This is the direct fix for Critical Finding #1 — because `common.incoterm` is now guaranteed to include the deterministic-fallback value (not just whatever the LLM happened to catch), the derivation that depends on it is correspondingly guaranteed too, for the first time.

---

## 8. How annual spend, annual volume, and unit price interact

This is `DerivedEvidence.resolved_annual_spend_usd`, computed with one explicit, ordered rule, in one place:

1. If `case.annual_spend_usd` (price_increase) is present → use it directly. `annual_spend_resolution_method = direct`.
2. Else, if `common.unit_price_usd` **and** `common.annual_volume_units` are both present → multiply them. `annual_spend_resolution_method = derived_from_price_and_volume`.
3. Else → `None`. `annual_spend_resolution_method = unresolved`.

**This exact logic currently lives duplicated inside `financial.py:compute_financial_impact()` and is silently re-derived there.** Under this design, `compute_financial_impact()` stops doing this derivation itself — it simply reads `derived.resolved_annual_spend_usd`. This directly closes Critical Finding #3 (freight silently failing) as a side effect: once `annual_volume_units` has its own fallback (new work, listed below) and this resolution happens once, upstream, the freight calculation's dependency on volume is satisfied by the same guaranteed value everything else uses — not a second, independent, unprotected read.

---

## 9. How currency and duty flow into TCO

`derived.duty_relevant` and `derived.currency_mismatch` are computed once, here — reusing and *replacing* the logic currently duplicated inside `methodology_consistency.py:determine_relevant_tco_dimensions()`. That function becomes a consumer: instead of re-deriving relevance from raw evidence, it reads `derived.freight_relevant` and `derived.duty_relevant` directly. Hard Rule 18 (currency/Incoterm/duty reasoning) reads the same `common` and `derived` fields the calculation used — meaning the prose and the guaranteed number are now provably looking at the same data, not two independent reads of a similar-but-not-identical dict.

---

## 10. Sharing common evidence between quote_comparison and price_increase without forcing irrelevant fields

This is why the three-tier split exists at all. `CommonEvidence` contains only fields that are **singular and case-type-independent** by their real-world nature — one supplier name, one shipping lane, one currency, one Incoterm, one duty rate, one volume figure. These make sense identically whether the case is "should we accept this increase" or "which of these three quotes is better."

Price and terms, by contrast, are **inherently per-supplier** in a quote comparison (`price_per_supplier` is a map/list) but **inherently singular** in a price increase (`current_price_or_terms` is one value for the one existing relationship). Trying to unify these into one shared field would force one of the two cases into an unnatural shape — exactly the anti-pattern you flagged. They stay in their respective case-specific objects, genuinely separate, with no shared field pretending otherwise.

A `quote_comparison` case's `NormalizedEvidence.common` block is fully populated the same way a `price_increase` case's is — region, currency, Incoterm, duty all matter equally to "should I switch suppliers to save 8%, considering their different Incoterms and currencies" as they do to "should I accept this price increase." Only `.case` differs in shape.

---

## Before / After Pipeline

**Before (today):**
```
classify() → raw dicts → create_decision() [ad-hoc fallback #1]
    → check_missing_evidence() [own incoterm re-check]
    → _run_reasoning() [ad-hoc fallback #2, duplicate of #1]
    → compute_financial_impact() [own unit_price×volume re-derivation]
    → determine_relevant_tco_dimensions() [own incoterm/region re-check, again]
```
Four separate places independently decide "do I have what I need," using overlapping but not identical logic.

**After:**
```
classify() → raw dicts
    → normalize_evidence(raw_question, raw_dicts, db_history)
         [THE ONLY place any fallback function is ever called]
         [THE ONLY place any derivation happens]
    → NormalizedEvidence  (immutable once created)
    → check_missing_evidence(normalized)        — reads derived.freight_relevant, nothing else
    → _run_reasoning(normalized)                 — reads common/case directly
    → compute_financial_impact(normalized)       — reads derived.resolved_annual_spend_usd directly
    → determine_relevant_tco_dimensions(normalized)  — reads derived.freight_relevant / duty_relevant directly
```
One place decides. Everything else trusts it.

---

## Migration Plan

**Functions that disappear entirely (logic moves into `normalize_evidence()`):**
- The duplicated fallback block inside `create_decision()` (decisions.py)
- The duplicated fallback block inside `_run_reasoning()` (decisions.py)
- The `unit_price × volume` derivation currently inside `compute_financial_impact()` (financial.py)
- The incoterm/region/currency relevance re-check currently inside `determine_relevant_tco_dimensions()` (methodology_consistency.py)

**Functions that become pure consumers of `NormalizedEvidence` (signature changes, internal logic simplifies):**
- `check_missing_evidence(content_type, supplied)` → `check_missing_evidence(normalized: NormalizedEvidence)`
- `compute_financial_impact(numeric_facts)` → `compute_financial_impact(normalized: NormalizedEvidence)`
- `determine_relevant_tco_dimensions(evidence, numeric_facts)` → `determine_relevant_tco_dimensions(normalized: NormalizedEvidence)`
- `generate_commercial_position(...)` → accepts `normalized: NormalizedEvidence` instead of separate `evidence` and `numeric_facts` dicts

**Fallback modules kept, but relocated to be called only from `normalize_evidence()`:**
- `region_fallback.py`, `financial_fallback.py`, `numeric_parsing.py` — unchanged internally, just called from one place instead of two.

**New fallback modules required** (currently don't exist — these are net-new work, not migration):
- Incoterm fallback (Critical Finding #1)
- Duty rate fallback (Critical Finding #2)
- Currency fallback (Critical Finding #2)
- Annual volume fallback (Critical Finding #3)

**Tests that need rewriting** (currently assert against raw dicts, will need to assert against `NormalizedEvidence` instead):
- `test_financial_fallback.py`, `test_region_fallback.py` — the underlying extraction-function tests stay valid unchanged (they test pure functions); only the small number of tests that construct raw dicts by hand to simulate pipeline state need updating.
- `test_evidence_gate_backfill.py` — becomes the template for the new required end-to-end tests below, not deleted.
- `test_methodology_consistency.py`, `test_kraljic_contract.py` — signature changes only, assertions stay the same in spirit.

**New end-to-end tests required** (the actual proof this design is meant to deliver):
- One test per common field (region, incoterm, duty, currency, volume) proving: stated clearly in raw text → present in `NormalizedEvidence.common` → evidence-gate does not ask for it → reaches reasoning → (where applicable) reaches the guaranteed calculation. This is the exact shape already proven for annual spend; this design's real deliverable is making that shape true for all five remaining fields, not just two.
- One test proving `derived.freight_relevant` is correctly `True` even when Incoterm was caught only by fallback, not the LLM — this is the direct regression test for Critical Finding #1.
- One conflict-resolution test: construct a case where LLM and fallback disagree, confirm the `conflicting` provenance flag and telemetry log fire, and confirm the *disagreement itself* reaches the reasoning prompt.
- **The specific regression test you asked for, stated precisely**: given a raw question stating a value clearly, assert that `check_missing_evidence`, `compute_financial_impact`, and `determine_relevant_tco_dimensions` all receive it via the *same* `NormalizedEvidence` object reference — not that they each independently re-extract and happen to agree. This proves "one source of truth" structurally, not just behaviorally.

**How existing behavior is not lost:**
- Every current required-field list, every current cap, every current Hard Rule stays exactly as-is — this design touches *where evidence becomes available*, not what's asked for or how reasoning is instructed.
- The full existing 67-test suite continues to run against the migrated functions' new signatures; a test failing during migration means either a real behavior change (investigate) or a stale assertion about internal structure that no longer applies (update, the same honest process used for the two integration tests fixed during the Meridian incident).

---

## What I'm explicitly not deciding here, awaiting your call

- Whether `NormalizedEvidence` is a Pydantic model (validates structurally, integrates cleanly with the rest of the codebase's style) or a plain dataclass (lighter weight). Recommend Pydantic, for consistency with `CommercialPosition` and to get free JSON serialization for the `user_supplied_inputs` storage column, but this is a real, cheap-to-reverse implementation choice, not a design commitment.
- Whether the four new fallback modules (Incoterm, duty, currency, volume) get built as part of this migration, or as a immediately-following second phase. Recommend building them *inside* this same phase, since `normalize_evidence()` calling four fallbacks and three placeholder no-ops (waiting on future modules) is a strange, half-finished shape to ship.

Awaiting your approval before any code is written.
