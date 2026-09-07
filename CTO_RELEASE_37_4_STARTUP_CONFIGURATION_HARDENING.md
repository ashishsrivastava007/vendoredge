# VendorEdge R37.4 — Startup Configuration Hardening

## Purpose
Fail fast on mandatory production configuration/database connectivity problems instead of allowing a healthy-looking HTTP service to accept requests and fail later at workspace bootstrap.

## Changes
- Validate `DATABASE_URL` during application lifespan startup.
- In production, require `MIGRATION_DATABASE_URL` as well.
- Open each configured DSN with a bounded 10-second connection timeout and run `SELECT 1`; values are never logged.
- Keep authentication secret validation before serving traffic.
- If demo-organisation initialization still fails after its bounded retries, abort application startup instead of starting a service known to fail database-backed requests.
- Keep Render Blueprint wiring for `DATABASE_URL`, `MIGRATION_DATABASE_URL`, `VENDOREDGE_AUTH_SECRET`, and production environment explicit.

## Operational effect
A missing database URL or unreachable database should now make deployment/startup fail visibly rather than producing the user-facing workspace 500 later.

## Validation
- Python compile: PASS
- JavaScript syntax: PASS
- Startup/configuration tests: PASS
- Release tests available in the sandbox: PASS
- Live Render validation: NOT AVAILABLE from the sandbox
