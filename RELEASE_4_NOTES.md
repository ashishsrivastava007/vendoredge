# VendorEdge CTO Release 4 — Decision Integrity & Stakeholder Discipline

## Objective

Move VendorEdge from a strong evidence/guardrail engine toward a decision engine that distinguishes facts, stakeholder signals, and system-owned confidence.

## Changes

### 1. System-owned confidence

Confidence level is no longer authoritative from the LLM. The model still supplies explanatory confidence factors and a derivation narrative, but the final `confidence.level` is assigned deterministically by VendorEdge after the reasoning and integrity checks.

The pre-reasoning stage also computes an evidence-only confidence ceiling and passes that boundary into the reasoning call. This prevents the model from being asked to decide its own confidence without knowing the system's evidence boundary.

### 2. Stakeholder decision protocol

Stakeholder views remain attributed evidence rather than being promoted to objective facts.

The reasoning engine now receives a deterministic protocol that explicitly distinguishes:
- objective statements;
- preferences/recommendations;
- risk concerns and experience reports;
- genuine hard constraints;
- rumors / insider information.

A preference is never silently converted into a hard constraint. Rumors are never presented as verified facts. Conflicting stakeholder supplier choices are explicitly detected and surfaced to the reasoning model rather than averaged into a fake consensus.

### 3. Material stakeholder conflict affects confidence

When different stakeholders explicitly point toward different suppliers, the deterministic pre-reasoning layer caps the case at MEDIUM before the LLM reasons. This is conservative by design: the system acknowledges that the decision contains an unresolved human trade-off.

### 4. No premature qualification penalty

An incomplete alternative supplier does not automatically reduce pre-reasoning confidence merely because it exists. Before the recommendation is known, VendorEdge cannot know whether the recommendation will rely on that supplier. The existing post-reasoning qualification-dependency check remains responsible for that decision-specific confidence reduction.

## Tests

- 24 focused decision-integrity / normalization / confidence tests: PASS.
- 35 supplier-claim / generalized claim-firewall tests: PASS.
- `python3 -m compileall -q app tests benchmark`: PASS.

The full application regression suite and browser/real-model validation were **not** claimed in this environment because the working container does not have the production Python dependencies / PostgreSQL environment available. No fabricated full-suite number is reported.

## Important deployment principle

This is an internal Release 4 candidate. Do not deploy it to Render until the complete project regression suite passes in the real development environment and the live browser lifecycle tests are repeated.

## Next direction

The next hardening layer should make the decision itself more auditable: expose the material evidence that drove the recommendation, distinguish PROVEN / INFERRED / UNKNOWN / CONTRADICTED claims, and make the recommendation's reversal conditions explicit without turning the UI into a wall of AI jargon.
