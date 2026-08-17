# VendorEdge Release 19 — Trust Certification

## Mission
Make the decision process difficult to fool and make that trust visible to the user.

## New capability
### Deterministic Trust Certification
R19 adds a system-owned trust certificate to every completed CommercialPosition. The certificate evaluates the final decision process without making another model call and without changing the recommendation.

Checks include:
- Evidence provenance on load-bearing fields
- Internal recommendation/evidence consistency
- Claim-strength integrity
- System-owned confidence enforcement
- Decision audit / traceability
- Supplier-specific attribution
- Presence of deterministic challenge layers
- Stakeholder attribution
- Model independence of the certification itself

## Certificate states
- `CERTIFIED` — all R19 structural checks passed
- `CONDITIONAL` — no critical failure, but one or more limitations remain
- `NOT_CERTIFIED` — at least one critical trust check failed

## Important boundary
Trust Certification measures **decision-process integrity**, not commercial outcome accuracy. A certified decision can still be wrong if supplied evidence is wrong or future conditions change.

## UI
The completed decision view now shows an R19 Trust Certification card before the Commercial Decision Cockpit, with pass/warn/fail counts and expandable checks.

## Validation
- R19 targeted tests: 3 passed
- R18 cockpit regression tests: 3 passed
- Python compileall: passed
- Browser JavaScript syntax check with Node: passed
- Existing full-suite dependency limitation remains: the environment used for this release does not have `psycopg2`, so tests importing the database-backed application cannot be collected locally without installing the project's declared dependencies.
