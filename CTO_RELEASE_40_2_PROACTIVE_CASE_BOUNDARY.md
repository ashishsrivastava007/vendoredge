# VendorEdge R40.2 — Proactive Case Contract & Recovery Boundary

## Purpose
Close the R40 regression where proactive/general-commercial cases (the Workbench's "Something I noticed" / category-strategy path) were later re-routed into the specialist `NormalizedEvidence` schema and failed with `content_type=None`.

## Root cause
The specialist normalizer accepts only `price_increase` and `quote_comparison`. R40 introduced a broader general-commercial triage path, but `/respond` and `/continue` still assumed every case could be re-normalized by the specialist pipeline.

## Fix
- General/proactive cases carry explicit private routing metadata: `__workflow_mode__=general_commercial_triage` plus the category.
- A single route helper identifies specialist vs general cases.
- Recovery (`/respond`), background dispatch, and continuation (`/continue`) keep general cases on the general triage engine and never call specialist normalization.
- Specialist routes remain unchanged and continue using the existing NormalizedEvidence contract.
- Commercial Memory retains general case category/mode so proactive activity is not lost from observed-history signals.

## Invariants
1. No general/proactive case can enter `normalize_evidence()`.
2. Reopening or retrying a general case remains recoverable.
3. Continuing a general case preserves the original observation as context.
4. Specialist calculations and trust contracts are not weakened to accommodate general cases.

## Verification
- Static boundary regression tests pass.
- Python compilation passes.
- Existing release tests that can run without external provider/database dependencies remain the validation baseline; full provider/DB suite requires the production dependency environment.
