# VendorEdge CTO Release 3 — Reliability Boundary & Auth Hardening

## Objective

Make the current pilot architecture resilient to two classes of failure found during real use:

1. information-dense questions exhausting the classifier's single JSON output budget;
2. protected pilot endpoints relying on browser-supplied organisation/user headers instead of making the signed session the sole authority.

## Changes

### 1. Bounded classifier decomposition

The normal classifier path remains the low-latency path. If the combined classification/evidence response genuinely exhausts 2,048, then 4,096, then 8,192 output tokens, VendorEdge no longer fails merely because the schema grew.

It switches once to three bounded contracts:

- classification only — 768 tokens;
- case/numeric evidence — 2,048 tokens;
- supplier/stakeholder evidence — 4,096 tokens.

This is a finite decomposition, not an unbounded token escalation. The important architectural rule is now explicit: schema growth must not turn one JSON object into the reliability bottleneck.

### 2. Retry telemetry is now truthful

Classifier retries and reasoning retries are recorded with explicit call types. The validation dashboard no longer infers "retry" from total API-call count, which became invalid once decomposition was introduced.

### 3. Protected endpoint identity hardening

Protected pilot endpoints now derive organisation/user identity from the signed bearer session and perform a live membership check. Compatibility headers may remain for the existing frontend but are not the authority.

Protected paths include decision creation, listing, reading, response/continuation, feedback, workspace information/invitation, file extraction, pilot lead/feedback signals, and validation execution.

Workspace creation and the explicitly gated legacy-session migration endpoint remain public by design.

### 4. Validation cost-abuse control

The live validation endpoint remains explicitly disabled unless `VALIDATION_ENABLED=true`, now additionally requires an authenticated workspace session, and is rate-limited to two runs per workspace per hour.

### 5. Frontend compatibility

All frontend calls to newly protected endpoints now send the signed session headers. File upload deliberately sends only authentication metadata and lets the browser set multipart Content-Type correctly.

## Verification performed

- `python3 -m compileall -q app tests benchmark`: PASS.
- JavaScript syntax check for all script blocks: PASS.
- `tests/test_auth_security.py`: 4 PASS.
- `tests/test_supplier_claim_taxonomy.py`, `tests/test_stakeholder_evidence.py`, `tests/test_currency_safety.py`: 29 PASS.
- Direct decomposition fallback simulation with a mocked Anthropic response: PASS.

The full database-backed regression suite is not claimed from this isolated environment because `psycopg2` is unavailable here. No fabricated full-suite number is reported.

## Release principle

Do not deploy this release until the real development/Render environment runs the complete regression suite and the five browser lifecycle checks. This ZIP is an internal release candidate, not the final customer build.
