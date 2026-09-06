# VendorEdge R37.2 — Authenticated API Boundary & Cold-Start Hardening

## Purpose

Eliminate the class of browser-side failures where an authenticated application request can be constructed before the workspace session headers exist.

## Root cause addressed

R37.0/R37.1 had a real startup race: `HEADERS` begins as `null`, and individual UI actions relied on readiness guards. A new or cold-starting page could still expose paths where an authenticated `fetch()` was constructed with `headers: null`, producing a browser `RequestInit` TypeError before the request reached the server.

## Changes

- Added a single `authenticatedFetch()` boundary for normal authenticated application API calls.
- The boundary waits for workspace readiness before constructing `RequestInit`.
- Header merging uses the browser `Headers` API, so callers can safely add/override headers without ever spreading a null value.
- FormData uploads remain supported without forcing a JSON `Content-Type`.
- Workspace bootstrap endpoints remain raw by design because they create/redeem the session itself.
- The in-bootstrap workspace-age check remains raw because it runs from inside `ensureWorkspace()` after headers are created; routing it through the authenticated boundary would self-await the bootstrap promise.
- `waitForWorkspaceReady()` now has a bounded 10-second wait for an individual user action. Workspace bootstrap continues independently and the user can retry safely.

## Adversarial regression coverage

- Verifies the authenticated API boundary exists and requires readiness.
- Verifies only the four intended raw workspace/bootstrap API calls remain.
- Verifies application API calls no longer call raw `fetch()` directly.
- Verifies readiness waiting is bounded for user actions.
- Verifies bootstrap remains the single source of workspace setup.

## Release standard

The invariant for this release is:

> No normal authenticated application request may be constructed while `HEADERS` is null.

This release is intentionally a reliability hardening release, not a new commercial-intelligence feature.
