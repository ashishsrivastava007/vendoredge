# VendorEdge CTO Release 10 — End-to-End Decision Integrity

## Purpose

Release 10 is a validation milestone, not a new customer-facing feature. It uses one deliberately difficult procurement case to test whether the deterministic decision stack remains coherent when many evidence types fire at once.

The case contains:

- incumbent price increase
- two named suppliers
- FCA vs DDP
- annual volume and baseline spend
- supplier performance metrics
- capacity ceiling
- qualification and production-history gaps
- Finance vs Operations preference conflict
- Procurement recommendation
- an explicitly attributed but unverified operational rumor
- negotiation logic
- sensitivity analysis
- stress testing
- reversal conditions
- executive Control Tower output

## Master-case contract

The exact test case is stored in `tests/test_release10_master_decision_integrity.py` as `MASTER_CASE`.

The key rule is **do not add facts to the case merely to make a test pass**. If a field is absent, VendorEdge must preserve it as unknown or make the relevant downstream analysis unavailable.

## What the tests prove

1. Supplier evidence stays supplier-specific.
2. Stakeholder preferences are not promoted into facts.
3. Material stakeholder conflict is preserved.
4. Rumor/insider information remains explicitly unverified.
5. Financial impact is calculated deterministically from safe USD evidence.
6. Unsupported supplier-status claims are caught.
7. A metric-anchored reliability statement is not falsely blocked.
8. Decision audit preserves uncertainty and reversal conditions.
9. Sensitivity analysis uses explicit numbers only.
10. Alternative paths do not invent allocation percentages.
11. Stress testing remains deterministic and conservative.
12. Control Tower correctly reports the decision as conditional rather than pretending it is ready with unresolved material evidence.

## What this does NOT prove

This release does **not** prove real Anthropic behaviour, real browser behaviour, Render deployment behaviour, or customer willingness to pay. Those require live validation.

## Release gate

Before calling VendorEdge pilot-ready, run:

- this deterministic master suite
- the complete regression suite in an environment containing the production dependencies
- at least one real-model case through the deployed application
- the five browser lifecycle tests
- the live follow-up/recovery test
- customer usability interviews

No green test number should be reported unless the corresponding environment and test path actually ran.
