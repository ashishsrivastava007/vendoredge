# VendorEdge Release 25 — Commercial DNA

## Mission
Combine trust, commercial structure, flip conditions, negotiation context, procurement memory and measured outcomes into a conservative organization-level intelligence layer.

## Product capability
R25 adds a deterministic **Commercial DNA** view at read time. It reports:
- organization decision and recorded-outcome counts;
- outcome mix (held / assumption miss / execution miss / unresolved);
- decision alignment (followed / modified / different direction);
- measured expected-vs-actual financial realization when at least three structured outcome pairs exist;
- repeated, evidence-backed organizational signals;
- one evidence-backed behavior to change when a material signal is strong enough.

## Critical integrity rules
- No LLM call.
- No mutation of the current commercial recommendation.
- No free-text financial parsing.
- No causal claims from outcome data alone.
- No behavioral pattern claim from fewer than five recorded outcomes.
- No financial realization metric from fewer than three structured expected/actual outcome pairs.
- "Leakage" means measured shortfall against positive expected value only; the module does not claim the root cause.
- All history is scoped to the authenticated organization.

## Why this is R25
R19 establishes trust; R20 structures the commercial truth; R21 identifies decision flips; R22 adds the commercial war room; R23 preserves institutional memory; R24 closes the expected-vs-actual loop. R25 connects those layers into an organizational view of repeated commercial behavior and realized value.

## Validation
- Targeted R25 tests: see `tests/test_release25_commercial_dna.py`.
- Dependency-free regression: R25 + prior deterministic pipeline tests.
- Full repository tests remain explicitly unclaimed if the environment lacks the existing external database/LLM dependencies.
