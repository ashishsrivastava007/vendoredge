# VendorEdge R25 — Final World-Class Hardening Audit

## Scope

This audit starts from the cumulative R25 package and incorporates the final R25.1 hardening pass. The goal is not feature completeness alone; it is to make the product safer, more deterministic, more maintainable and more honest before real pilot use.

## Hardening completed

### 1. Evidence firewall
- Supplier emails, contracts, quotes, spreadsheets, OCR/PDF text, stakeholder notes and other case material are explicitly treated as untrusted data.
- Evidence is escaped before entering model prompts so it cannot manufacture control tags.
- Injection-like wording is detected as an auditable signal without deleting or rewriting the underlying evidence.
- The classifier, decomposed extraction path and reasoning path all receive the firewall rule.
- Added adversarial regression coverage.

### 2. Tenant isolation
- All tenant-bearing tables now have `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`.
- Added RLS to organisations, workspace invitations, interest signals, fallback events, pilot leads and general feedback in addition to the existing decision/user/feedback tables.
- Telemetry writes now carry organisation identity and use the same scoped connection path.
- Application routes no longer open raw PostgreSQL connections.

### 3. Connection pooling
- Replaced per-request PostgreSQL connections with a bounded `ThreadedConnectionPool`.
- Tenant identity is applied using `SET LOCAL`, making it transaction-scoped.
- Connections are rolled back before reuse.
- Broken PostgreSQL connections are discarded rather than returned to the pool.
- Pool bounds are deployment-configurable.

### 4. Invitation security
- A teammate invite is no longer a copy of the inviter's live session token.
- Invites are single-use, 24-hour bearer secrets.
- Only a SHA-256 hash is stored in PostgreSQL.
- Redemption creates a new user and a new signed session.
- Added unauthenticated invite redemption endpoint with rate limiting.
- Frontend now uses `#invite=` rather than `#session=` for invitations.

### 5. Quota enforcement
- Removed the `STRESS_TEST_ORG_ID` production quota bypass entirely.
- Validation uses its own explicitly provisioned workspace limit.
- Regression tests now prove that a legacy environment variable cannot loosen a customer quota.

### 6. Model routing
- Classification/market verification default to `claude-sonnet-4-6`.
- Final commercial reasoning defaults to `claude-opus-4-8`.
- Stage-specific environment overrides are supported.
- The old retired Sonnet 4 snapshot is no longer the production default.
- No sampling parameters are hard-coded, preserving compatibility with current frontier model requirements.

### 7. Document safety
- ZIP bundles have entry-count, per-member and cumulative expansion limits.
- XLSX files are checked as nested ZIP containers before openpyxl processes them.
- Upload size limits remain enforced at the API boundary.

### 8. Browser security
- Added COOP/CORP and production-only HSTS in addition to the existing CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy and no-cache controls.
- Model-controlled frontend fields continue to use `escapeHtml` before HTML insertion.

### 9. CI / validation architecture
- GitHub CI now creates a non-superuser `vendoredge_app` role for tests.
- The schema is loaded using the migration role; the application test suite runs as the non-superuser role.
- This prevents RLS tests from accidentally passing because a PostgreSQL superuser bypassed row-level security.
- Final-package compilation and JavaScript syntax checks remain part of the release gate.

## Validation performed in this environment

- Python compilation: **PASS**
- JavaScript syntax validation: **PASS**
- YAML parsing: **PASS**
- Dependency-light regression tests: **34/34 PASS**
- Final-release + hardening tests: **11 PASS, 3 SKIPPED**
- The skipped tests require the Anthropic SDK or a live PostgreSQL database that is not available in this isolated execution environment.

## Deliberate non-claims

This environment cannot honestly certify:

- a live Anthropic API call using the production key;
- a real PostgreSQL RLS run against the final Render database;
- real Render deployment health;
- real-world Holy Shit Test performance on external procurement cases.

GitHub CI is configured to execute the full database-backed suite, and Render configuration is included for deployment.

## Remaining product-level proof

The product's largest remaining uncertainty is not another feature. It is empirical differentiation:

> Can VendorEdge consistently discover commercially material facts, dependencies, reversal conditions and negotiation leverage that an excellent procurement professional using a strong general-purpose model would miss?

That must be demonstrated with deliberately messy, high-value procurement cases after deployment.

## R25.2 UX + Invite Exposure Hardening

A final product-surface pass was applied after the independent Claude review.

### UX
- Reframed the landing experience around a decision-first promise rather than generic AI chat.
- Added a restrained Commercial Intelligence Journey: Evidence → Truth → Economics → Flip → War Room → Memory → DNA.
- Added evidence-grounded / deterministic-economics / decision-traceable proof cues.
- Upgraded responsive typography, spacing, cards, controls, focus states, and mobile behavior without changing the underlying decision logic or API contract.
- Preserved the existing information architecture and IDs to minimize regression risk.

### Invite endpoint review
- Unauthenticated redemption returns only a generic invalid/expired/used invitation message.
- No workspace-existence error is emitted from the redemption path.
- Invite acceptance rate limiting executes before database access.
- Single-use, hashed, expiring bearer-token design remains unchanged.

### Validation
- R25.2 UX/invite hardening tests: 4 passed.
- R25 world-class hardening regression: 6 passed, 2 skipped for environment-dependent live DB/provider checks.
- Frontend JavaScript syntax check: passed.
- The local environment does not provide PostgreSQL/Anthropic packages, so the complete DB/provider suite was not runnable here; CI remains the authoritative full-suite environment.
