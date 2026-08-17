# VendorEdge Release 23 — Procurement Memory

## Mission
Turn VendorEdge from a one-case decision engine into an institutional procurement memory without turning sparse history into false intelligence.

## Product capability
R23 adds a deterministic **Procurement Memory** layer after R22. It surfaces:
- supplier-specific prior cases when a reliable supplier history exists;
- organization history for the current case type;
- recorded outcomes and decision alignment;
- unexpected insights recorded by users;
- prior misses that should be checked before repeating an approach;
- historical pattern signals only when the real sample is sufficient;
- explicit warnings when history exists without an outcome.

## Important distinction
R23 stores and presents **decision memory**, not conversation transcripts. The current commercial decision remains immutable. Memory is context, not proof of future supplier behavior.

## Honesty thresholds
- 0 prior cases: no pattern claim.
- 1 prior case: direct context only; explicitly not a pattern.
- 2 prior cases: emerging context; no stable pattern label.
- 3+ cases with fewer than 3 recorded outcomes: no outcome pattern claim.
- 3+ recorded outcomes: historical pattern language is permitted, still explicitly labelled as historical evidence rather than a prediction.

## Safety / architecture
- No LLM call.
- No embeddings or similarity score presented as fact.
- No supplier psychology inference.
- No recommendation mutation.
- No confidence inflation.
- No conversion of missing outcomes into success.
- Uses the same persisted decision and feedback records already protected by organization-level RLS.

## User experience
A new **Procurement Memory** card appears between the Commercial War Room and Commercial Decision Cockpit. It answers:
1. What does VendorEdge remember?
2. What happened in prior cases?
3. Is there enough history to call a pattern?
4. What lessons or prior misses should affect today's attention?
5. What should we *not* assume from the history?

## Validation
- R23 targeted tests: 5 passed.
- R23 + R18–R22 targeted/dependency-free regression set: 54 passed.
- Python `compileall`: passed.
- Frontend JavaScript extracted from `index.html` and checked with Node: passed.
- Full repository collection was attempted but remains blocked by the environment's missing `anthropic` and `psycopg2` dependencies. Those environment-dependent tests are not represented as passed.
