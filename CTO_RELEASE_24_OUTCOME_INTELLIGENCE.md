# VendorEdge Release 24 — Outcome Intelligence

## Mission
Close the loop between a commercial decision and what actually happened, without rewriting history or pretending that one outcome proves causality.

## Product capability
R24 adds a deterministic **Outcome Intelligence** layer at read time. It compares:
- the original deterministic financial expectation, when one exists;
- a user-recorded actual annual financial impact, only when explicitly entered as a structured USD value on the same basis;
- decision alignment (followed / modified / different direction);
- validation verdict (held / wrong assumption / wrong execution / unresolved);
- recorded outcome narrative and unexpected insight;
- historical realization accuracy only after at least three structured outcome pairs exist.

## Critical integrity rules
- **Free text is never parsed into financial numbers.** If a user writes "$121k" in the narrative but leaves the structured actual field blank, R24 does not score a financial variance.
- **The original commercial position is immutable.** Outcome Intelligence is computed when the case is read and is not written into `commercial_position`.
- **Attribution is explicit.** If the buyer modified or rejected the recommendation, realized value is not presented as wholly caused by VendorEdge.
- **Unknown remains unknown.** No actual financial value means no financial variance score.
- **Historical accuracy requires 3+ structured outcomes.** Two cases are context, not a reliable organizational metric.
- **No LLM call.** R24 is deterministic.

## Structured outcome capture
The feedback record now optionally accepts:
- `actual_financial_impact_usd`
- `actual_measurement_basis`

These fields are intentionally optional. Users should only provide a measured value that uses the same annual-impact basis as VendorEdge's original deterministic estimate.

## User experience
A new **R24 · Outcome Intelligence** card appears after Procurement Memory. It shows:
1. expected impact;
2. actual recorded impact;
3. financial variance when safely calculable;
4. recorded outcome;
5. learning signals;
6. historical realization accuracy only when the sample is sufficient;
7. attribution and honesty notes.

## Validation
- R24 targeted tests: **5 passed**.
- R24 + R18–R23 dependency-free regression set: **36 passed**.
- Python `compileall`: passed.
- Frontend JavaScript extraction + Node syntax check: passed.
- Full repository tests are not claimed where the environment lacks the existing `psycopg2` / `anthropic` dependencies.
