# VendorEdge R27.2 — Case Reopen Audit & Hotfix

## Priority incident
Completed cases could not be reopened after refresh with:

`Cannot set properties of null (setting 'innerHTML')`

## Root cause
`organizeDecisionPage()` cleared `#pos-assumption-wrap` with `innerHTML = ""`. That element contains the nested render target `#pos-assumption`. Clearing the wrapper destroyed the nested target. `renderPosition()` later attempted to write to the removed target.

A second lifecycle defect was also found: `organizeDecisionPage()` ran before the final renderers populated several supporting blocks, which caused populated blocks to remain hidden or be omitted from the supporting-intelligence groups.

## Fixes
- Never clear supporting DOM wrappers during organization.
- Run page organization only after all case-position renderers have completed.
- Add null guards to position renderers so optional/legacy DOM differences cannot crash the completed-case page.
- Normalize the minimum persisted `commercial_position` shape before rendering.
- Guard the completed-case thread and feedback elements.
- Handle non-2xx responses explicitly in `openCase()` instead of trying to render an error payload.
- Make legacy Decision Passport / Snapshot renderers safe if invoked.

## Validation performed
- JavaScript syntax check: PASS
- Python `compileall`: PASS
- Frontend smoke test reproducing the nested-wrapper failure: PASS
- Selected deterministic pipeline tests: 37 PASS

The full test suite could not be executed in this isolated environment because production dependencies such as PostgreSQL/Anthropic are not installed locally. No claim is made that a live Render/API integration test was performed here.
