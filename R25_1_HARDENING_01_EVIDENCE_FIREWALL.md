# VendorEdge R25.1 — Hardening 01: Evidence Firewall

## Objective

Make the Evidence Firewall an implemented security boundary rather than a documentation-only principle.

## What changed

- Added `app/pipeline/evidence_firewall.py`.
- All classifier inputs are wrapped as escaped `<untrusted_evidence>` data.
- All decomposed classifier stages receive the same firewall system rule.
- The reasoning payload is wrapped as one untrusted case-data envelope so raw questions, extracted evidence, stakeholder views, market text, continuation context, and historical notes cannot create a new instruction boundary.
- XML control characters are escaped so evidence cannot manufacture its own `<untrusted_evidence>` or control tags.
- Added deterministic prompt-injection signals for audit/telemetry. Signals never delete or rewrite evidence.
- Added dedicated regression tests for boundary escaping, signal detection, normal commercial text, and source-level integration contracts.

## Security model

Evidence remains visible to the model because it may contain commercially material information. The model is explicitly instructed that evidence is data, not instructions. Supplier/stakeholder text cannot override the system prompt or request system/developer secrets.

This is a defense-in-depth control, not a mathematical guarantee against model compromise. Live-provider adversarial testing remains required before claiming production-grade resistance.

## Validation

- Evidence firewall tests: **5 passed**.
- Dependency-light cumulative release regression selected for R19–R25: **76 passed**.
- Python compilation: **passed**.
- Full application/API tests were not claimed in this environment because `psycopg2` and `anthropic` are not installed locally.

## Explicit non-goals in this hardening step

This release does **not** yet address connection pooling, RLS consistency, route decomposition, invite/session lifecycle, model benchmarking, or broader UX changes. Those are separate hardening steps and must not be silently mixed into this release.
