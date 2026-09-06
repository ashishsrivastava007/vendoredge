# VendorEdge R36.1 — Phase 9.1 Execution Hardening

## Purpose
Harden the Phase 9 supplier-response execution path before any real supplier email is sent. This release deliberately adds no new product capability.

## Fixes

### S-2: Duplicate-send race condition
Supplier-response sends are now serialized per commercial decision using a PostgreSQL transaction-scoped advisory lock before the existing sent/idempotency check. This closes the two-tab/double-click race where two requests could both observe that a payload had not yet been sent and both invoke the external webhook.

The existing payload hash and unique delivery constraint remain in place as defense in depth.

### S-1: Production legacy-auth guard
Production startup now fails if `ALLOW_LEGACY_WORKSPACE_LINKS=true`. Render production configuration explicitly sets `ENVIRONMENT=production` while keeping the legacy path disabled.

The legacy compatibility path remains available for controlled test environments only; it is not accepted as a production authentication mechanism.

## Validation
- Python compile: PASS
- Frontend JavaScript syntax: PASS
- Release regression suite: 94 passed
- Phase 9 supplier-response concurrency guard: structural regression test added
- Production legacy-auth guard: regression test added
- Live Render/Postgres/email connector execution: NOT available in this environment

## Product scope decision
No Phase 10 capability is added in R36.1. The next step after deployment is workflow instrumentation and real-user validation, not additional intelligence modules.


## Post-release startup hotfix

Render startup exposed a pre-existing route/model contract defect: the organisation-format endpoints referenced `OrganisationFormatResponse` and `OrganisationFormatRenderRequest` without defining them in `app.models` or importing them into `app.routes.decisions`. The hardened package now defines both Pydantic contracts and imports them, and also imports `IngestionArtifactResponse`, which was the next missing response-model import on the same route module. A static regression test now verifies that every `response_model` used by this route module is both imported and defined.
