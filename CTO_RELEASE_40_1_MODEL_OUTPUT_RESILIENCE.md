# VendorEdge R40.1 — Model Output Resilience

## Incident fixed
A real end-to-end "Something I noticed" case caused the generic commercial triage path to return HTTP 500 because the model produced 4 `commercial_insights` while the deterministic `CommercialPosition` contract allows at most 3.

## Root cause
The generic triage path parsed the model JSON and sent it directly into Pydantic validation. Unlike the primary reasoning path, it had no deterministic preflight for bounded list outputs. Prompt instructions are not a guarantee that an LLM will respect a schema cap.

## Fix
Added `app/pipeline/position_contract.py` with a single deterministic `normalize_bounded_position_lists()` safety boundary. It enforces every explicit `CommercialPosition` list cap before validation while preserving model ordering and never inventing content.

The helper is now used by both:
- generic commercial triage
- primary reasoning validation/retry path

This converts a harmless one-item model overflow into a valid bounded response rather than a user-facing 500.

## Regression coverage
Added `tests/test_release40_position_contract.py` covering:
- commercial-insight overflow recovery
- every explicit bounded-list cap
- preservation of uncapped fields

## Validation performed
- Focused regression + generic triage + cap consistency + R38 tests: 23 passed
- Python compilation: PASS
- Frontend JavaScript syntax: PASS
- ZIP contents audited after packaging

## Known validation limitation
The sandbox does not contain the production Anthropic/PostgreSQL dependencies, so full environment integration tests cannot be claimed from this environment. Production verification remains required after deployment.
