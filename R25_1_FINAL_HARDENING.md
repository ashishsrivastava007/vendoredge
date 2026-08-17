# VendorEdge R25.1 — Final Hardening Release

This is a hardening release, not a feature release. It closes the specific risks identified during the external engineering review and adds stronger production safeguards around the cumulative R19–R25 intelligence stack.

## Closed findings

1. **Evidence firewall gap** — evidence is now explicitly untrusted data throughout classification, decomposed extraction and reasoning.
2. **RLS inconsistency** — tenant-bearing telemetry, organisations and invitations now use FORCE RLS.
3. **Per-request DB connections** — replaced with a bounded tenant-scoped connection pool.
4. **Session-sharing invitations** — replaced with 24-hour, single-use invitation secrets that redeem into a new session.
5. **Production quota bypass** — removed `STRESS_TEST_ORG_ID` entirely from production code.
6. **Retired model default** — moved to current Anthropic model routing with Opus 4.8 for final reasoning and Sonnet 4.6 for extraction/market work.
7. **Nested archive expansion** — added XLSX and ZIP expansion safety limits.
8. **Browser hardening** — added COOP/CORP/HSTS (HTTPS only) on top of existing CSP and no-cache controls.
9. **CI RLS validity** — CI now tests using a non-superuser application role rather than accidentally bypassing RLS with `postgres`.
10. **Local deployment role setup** — Docker Compose now creates the app role before loading the schema.

## Release gate

The final package must pass:

- Python compilation
- JavaScript syntax validation
- dependency-light regression tests
- GitHub CI PostgreSQL-backed suite
- security hardening tests
- fresh-package extraction/smoke validation

A live Anthropic API key and a real Render deployment are intentionally outside this offline build environment and remain explicit deployment validation steps.
