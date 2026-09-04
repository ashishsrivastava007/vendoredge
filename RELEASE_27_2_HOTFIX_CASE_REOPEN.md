# VendorEdge R27.2 Hotfix — Persisted Case Reopen

## Fix
- Hardened the decision-page renderers against missing DOM targets so a saved/completed case cannot fail with `Cannot set properties of null (setting 'innerHTML')`.
- Added a guard for the case thread indicator during reopen.
- Added defensive handling for partially populated/legacy decision records (confidence factors, assumptions, commercial insights, financial impact, walk-away, and feedback elements).
- Kept the existing buyer-facing decision flow and commercial logic unchanged.

## Observed failure
After refreshing a completed case, the UI displayed:
`Could not open this case. Details: Cannot set properties of null (setting 'innerHTML')`

## Validation
- Extracted frontend JavaScript and passed `node --check`.
- Verified all renderer target IDs used by the active render path exist in the HTML, with defensive guards added for optional/legacy targets.
