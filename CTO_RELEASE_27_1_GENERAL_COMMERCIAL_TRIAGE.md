# VendorEdge R27.1 — General Commercial Decision Triage

## Problem found in real pilot use
A genuine ValveCo-style commercial question was classified correctly as an out-of-scope category, but VendorEdge stopped with an error telling the buyer to rephrase around the two supported case types.

That was a product failure: the system understood the user's commercial problem but made the user leave instead of helping safely.

## Fix
VendorEdge now has a **general commercial decision triage** path for questions that do not fit a specialist engine yet.

The specialist classifier remains honest and still refuses to force-fit the case. Instead of rejecting the buyer, the case is handed to a separate triage engine that:

- identifies the decision the buyer is actually facing;
- gives a safest-defensible action now;
- separates known facts from unknowns;
- identifies the one missing question most likely to change the decision;
- protects the buyer against irreversible commercial commitments when evidence is incomplete;
- provides an actionable supplier/stakeholder position;
- explicitly states when TCO, market verification, legal, or specialist analysis was not performed;
- never invents financial exposure, savings, duty, freight, liability, contract rights, or market facts;
- caps confidence at **medium** because specialist deterministic engines were not run.

## Decision-under-uncertainty behavior
The triage path uses the same core philosophy as the R26 engine:

- **ASK** — one missing answer is likely to materially change the decision.
- **PROTECT** — the buyer can act now, but should keep the commitment small/reversible.
- **DECIDE** — the available evidence is sufficient for the stated action even without specialist module coverage.

Missing information therefore reduces confidence without automatically making VendorEdge useless.

## Architecture
This is deliberately **not** a list of new specialist modules. It is a general safety net in front of future specialist coverage.

Specialist paths remain responsible for deterministic TCO, market verification, quote normalization, price-increase analysis, and other domain-specific calculations. The triage path cannot claim those calculations.

## Validation
Focused regression suite used for this change:

- 18 passed, 0 failed.
- Python compilation passed for the new triage engine and modified API route.

The full dependency-heavy suite was not claimed as green in this isolated build environment because required external Python packages are unavailable and network access is disabled.
