# VendorEdge R40.4 — Runtime Import Hotfix

## Defect fixed
The reasoning worker called `normalize_bounded_position_lists()` in `app/pipeline/reasoner.py` without importing it. This caused a live `NameError` during Step D and prevented commercial reasoning from completing.

## Change
Added the explicit import from `app.pipeline.position_contract`.

## Validation
- Python `compileall`: PASS
- R40.2 static audit tests: PASS (8)
- Case-mode boundary tests: PASS (2)
- Runtime-import regression test: PASS (1)

The full test suite was not executable in this environment because the required third-party packages (`anthropic`, `psycopg2`) are unavailable locally and network access is disabled. Render deployment/smoke testing is therefore still required before treating this as production-verified.
