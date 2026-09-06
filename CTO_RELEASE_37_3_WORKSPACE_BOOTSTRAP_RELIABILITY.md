# VendorEdge R37.3 — Workspace Bootstrap Reliability

## Purpose
R37.3 hardens the browser/session bootstrap path after R37/R37.2 exposed two distinct failure modes: authenticated requests being constructed before session headers existed, and workspace bootstrap itself remaining unresolved while user actions timed out.

## Changes

### 1. Bootstrap network timeouts
All workspace bootstrap HTTP calls use an AbortController-backed timeout (15 seconds by default). This includes invite redemption, legacy-session exchange, workspace creation, and workspace validation.

### 2. Bounded retry
Bootstrap makes at most two attempts with a short backoff. There is no infinite client-side bootstrap loop.

### 3. Retry-safe workspace creation
The browser generates a high-entropy bootstrap key and sends it as `X-Workspace-Bootstrap-Key`. The `/workspaces` endpoint deterministically maps that key to the workspace/user UUIDs and uses conflict-safe inserts. A timed-out browser POST that actually completed on the server therefore cannot create a duplicate workspace when the same bootstrap is retried.

### 4. Session validation before application unlock
A persisted or newly created session is validated through `/workspaces/me` before the authenticated application session is exposed to the rest of the UI. Invalid sessions are discarded; transient validation failures do not silently masquerade as valid sessions.

### 5. Explicit bootstrap state machine
The UI now has explicit starting, retrying, ready, and failed states. A failed bootstrap presents a real retry action. The retry cancels the previous bootstrap run, creates a fresh controller/run, and restarts setup cleanly.

### 6. Stale-run protection
Bootstrap runs use a run identifier and a captured AbortController rather than consulting the mutable global controller from an older run. A cancelled/obsolete run cannot overwrite the current run's session/error state.

### 7. Fresh-workspace reset corrected
`Start a fresh workspace` now clears both the persisted session and bootstrap identity before navigation, so it genuinely creates a new isolated workspace.

### 8. Authenticated API boundary retained
Normal application API calls continue to use `authenticatedFetch()`. Only the deliberate bootstrap/validation endpoints bypass that boundary.

## Validation
- Python compile: PASS
- Frontend JavaScript syntax: PASS
- Release test suite: **122 passed**
- No live Render/Postgres/email-provider validation was performed in the sandbox.

## Scope
This release is a reliability/hardening release only. It does not alter the commercial reasoning, evidence, trust engine, negotiation logic, model orchestration, or supplier-response execution logic.
