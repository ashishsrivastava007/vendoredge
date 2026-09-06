# VendorEdge Release 33 — Phase 5 Supplier Memory 2.0

## Mission
Move from generic institutional case history to a supplier-centric commercial memory that a buyer can use every time the same supplier appears.

## What changed
R33 adds a deterministic **Supplier Memory** layer built from the authenticated organization's completed decision records and recorded outcomes.

It provides:
- a current captured supplier baseline (terms, performance, qualification/certification fields when present);
- prior supplier case count and recorded-outcome count;
- held-vs-missed outcome counts when real feedback exists;
- deterministic changes between the latest historical supplier snapshot and the current captured snapshot;
- prior VendorEdge commercial positions for context;
- explicit fields that are still unknown in the current case.

## Integrity rules
- No LLM call.
- No embeddings or similarity scores presented as facts.
- No supplier psychology or behavior prediction.
- No recommendation mutation.
- A prior VendorEdge opening/walk-away is labelled as historical context, not supplier behavior.
- Missing fields remain unknown.
- Sparse history is never promoted to "established" memory.
- Historical outcomes are only counted when explicit feedback exists.
- Tenant isolation continues through the existing organization-scoped database connection/RLS.

## Architecture
The new `app/pipeline/supplier_memory.py` module is a deterministic presentation/learning layer above the existing normalized evidence and Commercial Truth Model.

During reasoning, the layer reads up to 200 recent completed cases from the authenticated organization and matches the named supplier against the structured Commercial Truth Model. It then stores the resulting supplier-memory view with the immutable commercial position.

The read path also has a non-blocking reconstruction path for older completed cases where the new field was not previously persisted.

## User experience
A new **Supplier Memory** card appears at the top of History & Learning. It answers:
1. Which supplier is VendorEdge remembering?
2. What is the latest captured commercial baseline?
3. What changed since the last captured baseline?
4. What prior positions/outcomes exist?
5. What information is still missing?

This is deliberately different from the existing Procurement Memory card: Procurement Memory answers "what happened in prior cases?" while Supplier Memory answers "what do we know about this supplier's commercial relationship, and what changed?"

## Validation
- R33 Supplier Memory targeted tests: **5 passed**.
- R33 + R29/R30/R31/R32 deterministic regression set: **16 passed**.
- Full `tests/test_release*.py`: **83 passed**.
- Python `compileall`: passed.
- Frontend JavaScript extracted from `index.html` and checked with Node: passed.
- Full repository collection is not claimed because the current environment lacks existing `psycopg2` and `anthropic` dependencies; DB-backed/live Render/Postgres/Anthropic validation was not performed.

## Deliberate non-goals
R33 does not create a supplier master-data system, fuzzy supplier identity resolution, external supplier intelligence, autonomous outreach, or supplier-behavior prediction. Those belong in later phases only when evidence, permissions, and audit controls are strong enough.
