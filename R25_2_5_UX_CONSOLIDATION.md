# VendorEdge R25.2.5 — Decision UX Consolidation

## Purpose
Remove repeated decision content and make the buyer experience decision-first.

## User-facing changes
- One open decision view: **Position → Why → Risk → Action**.
- Removed the duplicate Decision Passport and Decision Snapshot from the live decision page.
- Internal R19–R25 release names are not presented as buyer-facing sections.
- Supporting intelligence is grouped into six collapsed areas:
  - Numbers & commercial evidence
  - Negotiation strategy
  - Risks & decision safeguards
  - Execution
  - History & learning
  - Evidence trail & trust checks
- Each supporting area has a distinct purpose and is opened only on demand.
- Supplier facts remain in the commercial evidence area; the negotiation area focuses on leverage, market/stakeholder context, scenarios and actions rather than repeating supplier tables.
- Decision changers/unknowns are kept in the risk area rather than repeated in commercial facts.
- Assumptions and walk-away conditions are grouped under decision safeguards instead of appearing as standalone duplicate callouts.
- Trust certification no longer exposes an internal release number in its headline.
- Existing font, visual language and restrained styling are preserved.

## Validation
- JavaScript syntax check: passed.
- Focused deterministic regression suite: **33 passed, 0 failed**.
- Full suite could not be executed in the build environment because `psycopg2-binary` is unavailable offline; no claim is made that the full suite passed.
