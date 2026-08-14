# VendorEdge CTO Release 7 — Decision Stress Test

## Purpose
Release 7 adds a deterministic commercial stress-test layer. It challenges the recommendation with explicitly labelled hypothetical scenarios using only normalized evidence already present in the case.

## Guarantees
- No additional LLM call.
- No invented FX, freight, duty, quality, capacity, or market facts.
- Hypothetical shocks are labelled as scenarios, never presented as facts.
- Currency-unsafe scenarios refuse to calculate rather than guessing.
- Supplier allocation tests use only two explicitly priced suppliers and never silently optimize across unknown suppliers.
- The model's stated disconfirming condition is surfaced as an evidence-reversal test; it is not converted into a fake numeric result.

## Product behavior
The result appears as **Decision stress test** below deterministic sensitivity analysis.
Possible states:
- **Survives available tests** — no unresolved structural warning was found in the scenarios that can be safely tested.
- **Recommendation is sensitive** — explicit evidence constraints could materially change the decision.
- **Not safely testable** — the required numeric evidence is incomplete or unsafe.

## Validation
- 4/4 Release-7 tests pass.
- 15/15 combined Release-6 sensitivity/audit/stakeholder + Release-7 tests pass.
- 37/37 targeted supplier-claim, stress, sensitivity, audit and stakeholder tests pass.
- Python compilation passes for touched backend files.
- Browser JavaScript syntax check passes for the current static bundle.

A full production dependency/database regression was not claimed from this environment.

## Deployment
No database migration is required for Release 7.
