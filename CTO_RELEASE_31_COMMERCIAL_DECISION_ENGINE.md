# VendorEdge R31 — Commercial Decision Engine

## Purpose
Phase 3 turns the validated VendorEdge layers into one deterministic operational decision spine for daily procurement use.

The engine does not replace the LLM reasoner. It compresses already validated outputs into:
- decision mode: DECIDE / PROTECT / ASK / REVIEW
- recommendation and decision type
- evidence posture and trust integrity
- quantified economics when safely available
- available commercial alternatives
- immediate next move and action items
- blockers, unknowns and change/reversal conditions
- negotiation objective, target and walk-away when available

## Design rule
No new facts, calculations, thresholds or LLM inference are introduced by this layer. Existing Trust Engine, Commercial Truth Model, Decision-under-Uncertainty, alternatives, negotiation playbook and financial calculation remain authoritative for their respective domains.

## Why this matters for daily use
The buyer should not have to assemble the answer by opening six analytical panels. R31 creates a single "what do I do now?" layer while preserving the deeper evidence and trust layers underneath.

## Validation
- Python compile: PASS
- Browser JavaScript syntax: PASS
- Phase 3 focused tests: 3/3 PASS
- Phase 1/2 regression subset: PASS
- Full DB/LLM integration suite not runnable in this environment because `psycopg2` and `anthropic` are unavailable; no live Render validation claimed.
