# VendorEdge — Architecture

This document exists so a future maintainer (including a future version of the current team) doesn't have to reconstruct these decisions by reading commit history. It explains *why* the code is shaped the way it is, not just what it does.

---

## The core idea

VendorEdge answers one question: **"Is this price fair, and what should I do about it?"** — for either a supplier price increase or a quote comparison. The whole system is built around one non-negotiable principle: **never let the model's own arithmetic or self-reported confidence be the thing the user trusts.** Anywhere a number or a claim can be guaranteed by code, it is. Everywhere else, the schema and prompt work together to make the model's reasoning checkable, not just plausible.

---

## The pipeline, step by step

A question moves through four stages, in `app/routes/decisions.py`:

1. **Classify** (`app/pipeline/classifier.py`) — one AI call. Decides if this is a `price_increase` or `quote_comparison`, extracts structured evidence, and pulls out any real numbers (`numeric_facts`) mentioned in the text — never guessing, only extracting what's genuinely stated.
2. **Evidence check** (`app/pipeline/evidence.py`) — deterministic, no AI call. Compares what was extracted against a fixed list of required fields for that content type. If something's missing, the user is asked directly, rather than letting the model fill the gap with a plausible-sounding assumption.
3. **Financial calculation** (`app/pipeline/financial.py`) — pure Python, no AI call. Computes the real dollar exposure from the extracted numbers. This result is attached to the final response *regardless of what the model's own prose says* — the guarantee is the code's arithmetic, not the model's.
4. **Reasoning** (`app/pipeline/reasoner.py`) — one AI call, the main one. Produces the full `CommercialPosition` — recommendation, structured tables, negotiation strategy, confidence — following a large system prompt (`REASONING_SYSTEM_PROMPT`) organized as 17 "Hard Rules," each enforcing one specific behavior (never fabricate, always show arithmetic, cap this field at N items, etc).

A fifth, optional step — **market verification** (`app/pipeline/market_verification.py`) — runs a real web search to check a supplier's claimed cost driver (e.g. "steel is up 18%") against actual current market data, only for `price_increase` questions with a genuinely checkable claim. It never blocks the main flow; if it fails or finds nothing, reasoning proceeds without it.

---

## `app/caps.py` — the single source of truth for every size limit

**The problem this solves**: every structured field in a `CommercialPosition` (cost driver tables, supplier comparisons, negotiation dimensions, etc.) needs an upper bound — without one, a dense enough case can generate more content than fits in a single response, causing truncation. Early versions of this limit lived in three separate places: the Pydantic schema (`app/models.py`), the prompt's Hard Rule text, and the prompt's JSON schema example. When one got updated and the others didn't, the model would generate something valid *by the prompt's own instructions* that the schema then rejected — a real, live bug, more than once.

**The fix**: `app/caps.py` is the only file where a limit number is ever typed. Everything else derives from it:

- `app/models.py` imports `caps` and uses `Field(max_length=caps.MAX_COST_DRIVERS)` — never a bare number.
- `app/pipeline/reasoner.py` writes its Hard Rule text with placeholder tokens like `<<MAX_COST_DRIVERS>>`, then does a single substitution pass (right after the prompt string is defined) replacing every token with the real value from `caps.py`. This keeps the substitution safe even though the surrounding prompt is full of literal JSON braces that would make a plain f-string risky.
- `tests/test_caps_consistency.py` is the permanent guard: it reads the *live* schema's `max_length` and the *live* prompt text, and asserts they agree — for every capped field. If someone ever bypasses `caps.py` and hardcodes a number directly (the exact mistake that caused the original bug), this test fails immediately and specifically, naming the field and the mismatch.

If a limit ever needs to change: change the one number in `caps.py`. Nothing else needs to be touched.

---

## Validation and retry flow

The reasoning call doesn't just trust whatever comes back. In order:

1. **Token budget retry** — if the response gets cut off (`stop_reason == "max_tokens"`), retry once with a larger budget. If it truncates twice, fail with a clear error rather than a third silent attempt.
2. **JSON-shape retry** — if the response isn't recognizably JSON at all, retry once with an explicit correction telling the model to output nothing but the JSON object.
3. **Schema validation retry** — the response is parsed and validated against `CommercialPosition`. If it fails (e.g. a list field exceeds its cap in `caps.py`), the *real* Pydantic error is extracted — which field, which constraint — and sent back to the model as a specific, named correction, then retried once. This is what actually reads the caps described above, and it's why keeping the prompt and schema in sync matters even with a retry safety net: the retry can only fix a genuine one-off deviation, not a case where the prompt itself is telling the model the wrong number.

If a case still fails after its relevant retry, the user sees a calm, generic error — the raw exception is only ever shown in Render's logs, never to the user.

---

## Frontend notes (`app/static/index.html`)

Single-page app, no build step, no framework — plain HTML/JS in one file, intentionally. It never hardcodes an expected count for any structured field; every table and list renders however many items actually come back, from zero up to whatever `caps.py` allows. This means the frontend was never part of the cap-mismatch bug class and needs no changes when a cap in `caps.py` changes.

Two things worth knowing if you're new to this file:
- **Progress polling** (`pollRealStatus`): the backend writes a real `reasoning` status to the database the moment that stage starts; the frontend polls it every second so the loading screen reflects genuine backend state, not a simulated timer.
- **`waitForHeaders`**: on a cold start (Render's free tier sleeping), the session-setup call can be slow. Any action that needs the session waits up to 8 seconds for it, rather than firing an API call with a broken/empty session and producing a confusing raw error.

---

## What's deliberately not built yet

- Real authentication (private-link workspace model is intentional for the pilot stage, not an oversight).
- OCR / scanned-PDF support (a genuinely different technical undertaking — a paid service or heavy dependency — deferred until real demand justifies the decision).
- A dedicated multi-document synthesis AI call (tested and found unnecessary so far — the existing classifier already handles multi-file input well; see `benchmark/cases.py` for the proof case).
- Payment/billing infrastructure (correctly waiting on real pilot evidence before building).
- **Evidence-completeness indicator** on the "I found this" checklist (e.g. "Evidence completeness: 88%" or "Ready analyses: 4 of 5"). A real, well-reasoned suggestion, deliberately held for after the pilot, not because it's hard — because the "found" checklist itself is brand new and unproven with real users first. Two real design questions worth resolving with actual pilot behavior in hand, not guessed at now: (1) is the right denominator the fixed required-field count for that content type, or something that also reflects how much *optional* evidence (region, Incoterm, currency) was picked up — the second is more honest about full understanding, but the first is simpler and less likely to feel arbitrary to a user; (2) does a percentage read as reassuring or as an implicit grade that quietly discourages someone whose case is genuinely just sparse. Both are answerable by watching real reactions to the plain checklist first, not by deciding in the abstract.
- **Dynamic, BATNA-framed follow-up question** for the alternative-supplier evidence prompt — instead of the current fixed wording, explicitly name the concept ("to judge your negotiating leverage, I need to understand your BATNA") while asking for price/quality/lead-time/switching-cost, teaching a real negotiation term while collecting the evidence. Genuinely good, but held deliberately, for a real reason worth stating plainly: this would be the first time a specific negotiation term gets surfaced directly in the live UI, not just used internally in reasoning. Kraljic and TCO earned real, code-enforced contracts tonight because they have objective, checkable evidence; BATNA was explicitly placed in the *other* category — judgment-based, a spectrum, not suited to hard enforcement. Teaching the term to a user without also being able to rigorously apply it the same way risks implying a precision the system doesn't structurally have. Sequence this after seeing how real users respond to the sharper, jargon-free wording already shipped tonight — if that alone lands well, the BATNA framing is a safe, well-earned addition on top; building the more ambitious version first would mean never knowing which part actually mattered.
- **Confidence should become a system-owned decision attribute, not an LLM-owned opinion.** Right now (post Guarantee #5), the model still writes its own `confidence.level` in prose, and a deterministic ceiling *corrects* it downward when the evidence doesn't support it — proven, tested, working. But this is explicitly a transitional design, not the destination: it means two independent things can disagree (the model's opinion, and the real evidence-quality computation), and the system currently resolves that disagreement after the fact rather than never allowing it to exist. The architecturally cleaner end-state: confidence is computed *first*, deterministically, from the same evidence-quality signals already built (Checks A–E in `confidence_gate.py`), and the model is given that already-decided value as an input, generating only the *prose explanation* of it — never independently asserting a level of its own. This removes the correction step entirely, because there is no longer a competing opinion to correct. Deliberately not built now: it changes the reasoning call's contract (confidence becomes an input, not an output), which is a real, non-trivial restructuring worth its own careful pass, not a rushed addition onto Guarantee #5's proven, working correction mechanism.

---

## Where to look for more

- `benchmark/README.md` — how to run the structural regression suite against a live API key.
- `PILOT_DASHBOARD_QUERIES.md` — ready SQL queries for checking real pilot demand data.
- `tests/` — every test here reflects a real, previously-live bug, not a speculative edge case. Reading the test names is a reasonable way to learn the project's history.
## Release 24 — Outcome Intelligence
R24 closes the decision loop without mutating the immutable commercial position. The read-time outcome layer compares the deterministic expected financial impact with an explicitly structured actual value, preserves the user's outcome narrative, distinguishes reasoning failure from execution failure, and withholds historical realization metrics until at least three structured outcome pairs exist. Free-text outcome descriptions are never parsed into financial numbers.

