# VendorEdge Release 18 — Commercial Decision Cockpit

## Objective
Turn a completed VendorEdge reasoning result into a materially faster decision experience: less prose, more clarity, with a native executive view and deterministic customer-format rendering.

## New capability
### Commercial Decision Cockpit
A deterministic presentation layer that surfaces, in order:
1. Verdict
2. Readiness
3. Confidence
4. Direct economics (only when safely calculable)
5. Evidence signal
6. Why the position wins
7. Next move
8. Critical blockers before action
9. Decision-flip conditions
10. Material unknowns
11. Stakeholder signals
12. Alternative/stress-test status

It does not call an LLM and cannot alter the stored recommendation.

### Standard output formats
Added a native `decision_cockpit` format alongside:
- Executive 60-Second
- CFO Brief
- Category Review
- Supplier Meeting
- One Page

### Bring Your Own Format
Added `{{decision_cockpit}}` as a supported deterministic token. Existing BYOF tokens remain supported.

## Design principles
- Answer first; proof on demand.
- No new facts in the presentation layer.
- No new calculations in the presentation layer.
- No confidence inflation.
- Unknown remains unknown.
- User's own company format can be rendered without another reasoning call.

## Validation performed
- 196 dependency-free regression tests passed.
- Release 17 + Release 18 targeted tests: 42 passed.
- Python compileall: passed.
- Inline JavaScript syntax check with Node: passed.
- Clean-package artifact scan performed after removing generated caches.
- Full suite was attempted; 14 test modules require unavailable local dependencies (`psycopg2` and/or `anthropic`) and therefore could not be collected in this environment. No claim is made that those environment-dependent tests passed locally.
