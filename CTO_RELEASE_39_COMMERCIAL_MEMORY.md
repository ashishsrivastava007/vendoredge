# VendorEdge R39 — Commercial Memory

R39 adds a compact buyer-first Commercial Memory layer that unifies supplier precedent, organizational history, recorded outcomes, and current-year observed activity. It supports both supplier-triggered decisions and proactive questions about patterns/category concerns.

## Guarantees
- Deterministic, read-only memory; no LLM call, embeddings, prediction, or supplier psychology.
- Memory never mutates the current recommendation.
- Prior recommendations remain historical context, not supplier facts.
- Current-year repeated activity is explicitly labelled as observation, not forecast.
- Pattern labels require real repeated observations: 2+ = emerging, 3+ = observed.
- One primary buyer-facing Commercial Memory surface; legacy memory modules remain available for compatibility but are not grouped as competing primary summaries.

## Validation
- R39-focused regression tests.
- Existing R38/R38.1/R36.2 release suites rerun.
- Python compilation and frontend JavaScript syntax validation.
- Final ZIP reopened and structurally audited after packaging.
