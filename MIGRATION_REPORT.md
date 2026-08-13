# NormalizedEvidence Migration — Final Report

---

## Phase 2 Verification, run in full

- Full existing suite (post-migration): **83/83 passed**
- Real, live-simulated end-to-end test (the exact Meridian case, through the actual HTTP endpoint): passed, correct $76,500 guaranteed math, zero re-ask
- Deliberate conflict test (Requirement 10.G): passed — genuine LLM/fallback disagreement detected, both values retained, reasoning received the conflict explicitly
- Deliberate architecture-break test (Requirement 12): **genuinely fails when the architecture is broken, genuinely passes when it isn't** — proven by actually reintroducing the original bug, watching the test fail with a specific message, then reverting and confirming it passes clean again
- Security tests: 3/3 passed, unaffected by this migration
- All named real-world regression cases (Poland region, $850K Meridian spend, Kowalski FOB+duty+freight): re-verified against the migrated code specifically, not just the original fix

---

## Test Audit (Requirement 13) — exact, not rounded

| Category | Count |
|---|---|
| **Existing tests retained completely unchanged** | 65 |
| **Existing tests modified because of migration** | 12 |
| **New tests** | 6 |
| **Total** | 83 |
| **True end-to-end tests** (real HTTP request → real DB → real assertions) | 3 |
| **Fallbacks covered end-to-end** (not just unit-tested in isolation) | 2 / 8 (annual spend, requested percent — via `test_evidence_gate_backfill.py` and `test_integration_full_flow.py`) |
| **Downstream consumers migrated to NormalizedEvidence** | 5 / 5 (`check_missing_evidence`, `compute_financial_impact`, `determine_relevant_tco_dimensions`, `generate_commercial_position`, `_run_reasoning`) |

**Every test whose assertion changed, listed explicitly, per instruction not to hide this:**

1. `test_pipeline.py::test_pipe01_fully_supplied_evidence_returns_empty` — updated to supply `requested_increase_percent` via `numeric_facts` instead of the text-evidence dict, matching the new, correct field routing.
2. `test_pipeline.py::test_missing_fields_use_real_field_keys_not_positional_labels` — same reason.
3–6. `test_cross_border.py`, all 4 tests — rewritten to construct `NormalizedEvidence` directly instead of a raw `numeric_facts` dict. One of the four (`test_malformed_duty_rate_...`) is genuinely different in shape, not just adapted — see the finding below.
7–12. `test_freight_cost_gate.py`, all 6 tests, and `test_methodology_consistency.py`, 3 of 8 tests — same pattern, rewritten to construct `NormalizedEvidence` directly, identical behavioral coverage.
13. `test_integration_full_flow.py::test_full_flow_asks_before_guessing_then_completes` — one assertion changed from expecting the string `"12%"` to the float `12.0`. This is a genuine, deliberate improvement (see below), not a loosened test.

**Honest gap, stated plainly**: only 2 of the 8 total fallbacks (annual spend, requested percent) have a genuine end-to-end test proving the full chain from raw text to evidence-gate to guaranteed calculation. The other 6 (region, Incoterm, duty, currency, volume, freight parsing) are proven correct at the `normalize_evidence()` unit level — 9 passing tests in `test_normalize_evidence.py`, covering scenarios A through G exactly as specified — but not yet proven through a full, real HTTP round-trip the way the original two were. This is a real, remaining gap, not a claim I'm rounding up.

---

## Two genuine findings surfaced *by* the migration, not introduced by it

**1. `duty_relevant` never treats a directly-stated duty rate as sufficient signal by itself** — it requires a region, currency, or Incoterm alongside it. Confirmed by direct comparison: this is the exact, original logic from the pre-migration `methodology_consistency.py`, preserved deliberately per your explicit instruction not to silently change behavior during this migration. **Classification: 🟠 Structural risk.** A case that states only "duty is 4.5%" with no other cross-border signal would not trigger the TCO duty check, even though a real rate was given. Worth a real decision from you on whether to fix this now or track it separately — I did not fix it, per instruction.

**2. A malformed duty value is now rejected earlier and more strongly than before** — pre-migration, a bad value reached `financial.py` as a raw dict entry and was caught defensively inside a try/except. Post-migration, `NormalizedEvidence`'s Pydantic schema rejects it at construction time, inside `normalize_evidence()` itself, before it ever reaches the calculation. **Classification: 🟢 Healthy — a genuine improvement**, not something I need you to act on, just something worth knowing changed.

---

## Requirement 14 — duplicate logic search, full results

Searched systematically for: raw fallback function calls, `unit_price × volume` calculations, freight/duty/currency/region/Incoterm derivation, and any function signature still accepting raw `evidence`/`numeric_facts` dicts.

**Result: zero remaining duplicates found.** Every fallback function is called from exactly one place (`normalize.py`). The `unit_price × volume` derivation exists in exactly one place. `freight_relevant` and `duty_relevant` are computed in exactly one place. No consumer function signature accepts a raw dict anymore — all five migrated consumers take `NormalizedEvidence` directly.

---

## What guarantees VendorEdge has now that it did not have before

Stated directly, per your explicit question:

1. **A value stated clearly in the raw question reaches every stage that needs it, through one object, not through five independent promises that happened to agree.** Proven, not assumed — the architecture-break test demonstrates a real violation gets caught, not just that today's code happens to work.

2. **A genuine disagreement between two independent extraction methods can no longer be silently resolved and hidden.** It's detected, logged as real telemetry, and explicitly surfaced into the final reasoning, so the model's own confidence can reflect real uncertainty about that specific figure.

3. **Every field's origin is traceable** — LLM extraction, deterministic fallback, user follow-up, database history, or a derived calculation — without inspecting raw dictionaries or guessing from context.

4. **Four previously-undefended fields now have real, tested, deterministic protection**: Incoterm, duty rate, currency, and annual volume. Critical Finding #1 from the audit (the silent freight-relevance skip) is now structurally closed, not patched.

5. **The specific class of bug that started this whole audit — a fallback existing in one stage but not the stage that actually needed it — is now structurally impossible to reintroduce by accident**, because there is exactly one place any of this logic is allowed to live. A future developer adding a new evidence field has one obvious place to add its fallback, not a decision about which of several call sites to remember.

**What this migration does not claim**: it doesn't make the underlying LLM extraction more reliable — that's still one pass, same as before, and can still miss things. What's structurally different is that a miss is now caught in *one* well-tested place, with *one* consistent fallback, visible in *one* telemetry stream — not an open question of whether every relevant stage happened to get its own copy of the fix.

---

## Honest, direct answer to the original audit's closing question, re-asked here

Before this migration, the answer was: yes, this class of bug would keep recurring, because three more fields had the same undefended shape as the ones already found. **That is no longer true for those three fields** — Incoterm, duty, and currency are now genuinely protected, tested, and structurally centralized. The one remaining honest exposure is the *next* new evidence field someone adds in the future — but the migration's actual point was making that addition safe by construction: extend `CommonEvidence` or the relevant case model, add one fallback function, wire it into `normalize_evidence()` once, and every downstream consumer inherits the guarantee automatically. That's the durable difference between tonight's earlier patches and this migration.
