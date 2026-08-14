# VendorEdge Release 16 — Customer-Grade Launch Layer

## Implemented

- **Bring Your Own Format v2:** users can paste an allow-listed template and render the already-validated decision into it. No new LLM call, facts, calculations or assumptions are introduced.
- **Approval-gated action plan:** every completed decision can produce explicit Decide / Validate / Negotiate / Learn actions. External side effects remain disabled until a human approves them through a separately authenticated integration.
- **Integration surface:** deterministic CSV export plus an explicit, deployment-configured HMAC-signed webhook dispatch endpoint. Webhook URLs/secrets are never user supplied.
- **Decision workspace UX:** completed decisions expose decision brief, custom format, CSV export and action plan from the same screen.
- **Fail-closed migration:** schema migration errors now abort startup rather than allowing the API to run against an unknown schema.

## Hard boundary

VendorEdge is **not** allowed to send supplier messages, alter contracts, create purchase orders or commit spend autonomously in this release. The product prepares and validates actions; an external action requires explicit approval and a separately authenticated integration.

That boundary is deliberate. It is safer than pretending that a recommendation engine is an autonomous procurement agent before customer controls, permissions, audit trails and integrations are proven.

## Verification

- 188 dependency-available automated tests passed.
- Same suite passed **three consecutive clean runs**.
- JavaScript syntax check passed.
- Python compilation passed.
- No temporary/bytecode artifacts included in the package.
- No real API keys/private keys/known placeholder production passwords detected in the packaged source.

Full live PostgreSQL/Anthropic execution remains an environment-dependent verification step and is not represented as locally proven here.
