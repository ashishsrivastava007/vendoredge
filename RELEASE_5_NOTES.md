# VendorEdge CTO Release 5 — Decision Evidence & Reversal Layer

## Objective

Make the recommendation auditable without turning VendorEdge into a wall of AI jargon. A user should be able to answer four questions:

1. What evidence materially supports this decision?
2. What is an inference rather than a fact?
3. What remains uncertain or conflicted?
4. What specific change would make VendorEdge reconsider?

## What changed

### 1. Deterministic Decision Audit

Added `app/pipeline/decision_audit.py` and a bounded `DecisionAudit` response object.

The audit is built from `NormalizedEvidence`, not from the model's recommendation. It therefore cannot manufacture support for a recommendation after the fact.

Each material evidence item is assigned one of four states:
- `PROVEN` — directly represented in the normalized evidence/provenance.
- `INFERRED` — explicitly presented by the reasoning as an inference/hypothesis, never silently promoted to fact.
- `UNKNOWN` — not supplied or not resolved.
- `CONTRADICTED` — the evidence/provenance contains a genuine conflict.

### 2. Stakeholder trade-off visibility

Stakeholder views remain separately attributed. The audit surfaces the views and deterministic conflict detection rather than collapsing Finance/Operations/Engineering preferences into a fake consensus.

### 3. Reversal logic

The existing `disconfirming_condition` is now surfaced alongside deterministic unresolved evidence. The result is a practical "what would make us reconsider?" section rather than a generic disclaimer.

### 4. UI

Added a collapsed **Decision evidence & reversal logic** section to the result page. It stays out of the main recommendation flow unless the user opens it, preserving a clean executive view while making the audit available to a serious procurement user.

## Validation performed in this environment

- 4 new decision-audit tests: PASS.
- Existing decision-integrity / confidence / generalized-claim / supplier-claim tests selected for regression: 54 PASS.
- Python compileall: PASS.
- Browser JavaScript syntax check: PASS.

The complete project suite was attempted but cannot be truthfully reported here because this working environment does not contain the production PostgreSQL/Anthropic dependencies (`psycopg2`, `anthropic`). Those failures are environment/dependency collection failures, not test assertions against Release 5. The full suite must therefore be run in the real VendorEdge development environment before deployment.

## Deliberate non-goals

- No new LLM call was added for the audit.
- No new database migration is required; the audit is stored inside the existing commercial-position JSON.
- The model is not allowed to redefine evidence status.
- No automatic recommendation reversal is performed. VendorEdge exposes the reversal condition; the user remains the decision owner.

## Next direction

The next major layer should be **Decision Scenario / Sensitivity Engine**: let a procurement user change a small number of verified assumptions (price, volume, allocation, freight, savings target) and see which recommendation changes, by how much, and where the break-even point is — using deterministic arithmetic, never another free-form model calculation.
