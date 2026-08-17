# VendorEdge R25.2.2 — LLM Extraction Contract Hardening

## Incident

The first live Holy Shit Test exposed a production 500 when the classifier returned
`number_of_suppliers_being_compared` as JSON number `2` while the normalized schema
represented that human-readable field as `Optional[str]`.

## Root cause

The model-to-typed-evidence boundary trusted the shape of model-generated JSON too
much. Pydantic correctly rejected the mismatched value, but the application exposed
the validation failure as a generic 500 instead of degrading safely to missing evidence.

## Fix

The normalization boundary now treats classifier JSON as an untrusted typed contract:

- Numeric scalar representation drift (`2` vs `"2"`) is accepted only where safe.
- Numeric fields accept real numeric scalars and strictly numeric strings only.
- Percent fields may additionally accept a numeric string with a trailing `%`.
- Prose such as `"35 weeks"`, `"EUR 52"`, booleans, arrays and objects are never
  reinterpreted as numbers; they become missing evidence with a normalization warning.
- Human-readable text fields only coerce numeric scalars where a number-shaped answer
  is semantically plausible.
- Invalid enum values degrade to the explicit `unknown` state.
- Malformed top-level extraction objects/arrays and malformed per-entry objects are
  downgraded rather than allowed to crash the request.
- Normalization warnings are preserved on `NormalizedEvidence` so the degradation is
  auditable instead of silent.

## Scope audited

The complete LLM -> normalized-evidence boundary was reviewed across:

- numeric facts
- common evidence
- price-increase evidence
- quote-comparison evidence
- per-supplier evidence
- stakeholder views
- enum/status fields
- top-level extraction container shapes

## Validation

- Dedicated LLM extraction-contract tests: **6 passed**
- Existing quote/normalization/multi-supplier/currency/claim/firewall/UX suite:
  **52 passed**
- Dependency-light cumulative regression: **259 passed, 3 skipped**
- Python compilation: **PASS**
- Fresh-package extraction validation: required before release packaging

## Safety principle

A model output is never allowed to turn a representation mismatch into a fabricated
commercial value. When the system cannot safely interpret the value, VendorEdge keeps
the evidence gap visible and lets the evidence gate request clarification.
