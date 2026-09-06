# VendorEdge Phase 8 — Bounded Agentic Procurement Workflow

## Objective
Move VendorEdge from decision intelligence into execution preparation without crossing the consequential-action boundary.

## What changed
- Added `app/pipeline/agentic_workflow.py`.
- Builds a deterministic, execution-ready work queue from the validated `CommercialPosition`.
- Prepares a negotiation package and supplier-response draft from already captured commercial terms.
- Surfaces pre-commit blockers before approval.
- Added `GET /api/v1/commercial-decisions/{decision_id}/agent-workflow`.
- Added `POST /api/v1/commercial-decisions/{decision_id}/agent-workflow/{action_id}/approve`.
- Added tenant-scoped `workflow_action_approvals` audit table with RLS.
- Approval records human intent only; it does not send email, modify contracts, create POs, or commit spend.
- Added execution UI under the existing Execution section.

## Safety boundary
The agent can organize work and prepare drafts. Human approval remains required for supplier contact and commercial commitment. External integrations must perform their own authorization and safety checks before executing an approved action.

## Trust boundary
Prepared drafts are not evidence. No new facts, calculations, market claims, or supplier psychology are introduced by this phase. The primary validated recommendation remains the source of truth.

## Validation
- Phase 8 tests: 3/3 passed.
- Combined R30/R31/R35 model-orchestration regression: 11/11 passed.
- Full deterministic `tests/test_release*.py`: 93/93 passed.
- Python compilation: PASS.
- Frontend JavaScript syntax: PASS.
- Live Render/Postgres/Anthropic execution was not available in this build environment and is not claimed.
