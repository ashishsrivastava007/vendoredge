# VendorEdge CTO Release 6 — Decision Sensitivity Engine

## Purpose
Turn a completed commercial position into a deterministic, auditable what-if analysis without asking the LLM to perform arithmetic.

## Changes
- Added `app/pipeline/sensitivity.py`.
- Added `CommercialPosition.sensitivity_analysis`.
- Sensitivity is computed from `NormalizedEvidence` only.
- Price-increase cases show deterministic annual impact at 0%, 5%, 10%, requested change, and 15% (deduplicated).
- Quote-comparison cases show 0/25/50/75/100 allocation scenarios for the two lowest explicitly priced suppliers when annual volume and USD supplier prices are genuinely available.
- No FX, freight, duty, capacity, or savings-target assumptions are invented.
- Added a compact UI section: “Decision sensitivity — deterministic what-if analysis”.

## Safety contract
The sensitivity engine is informational. It does not alter the recommendation, confidence, claim-integrity checks, or evidence gate. If safe numeric evidence is insufficient, the section is omitted rather than estimated.

## Validation
- Dedicated sensitivity tests: **4/4 PASS**.
- Targeted regression: **33/33 PASS**.
- Full suite was attempted but collection is blocked in this container because production dependencies `psycopg2` and `anthropic` are not installed. This is an environment limitation, not reported as a green regression result.
- Python compilation of changed modules: PASS.

## Deployment
No database migration is required for Release 6.

Deploy the complete ZIP as a unit. Do not cherry-pick individual files.
