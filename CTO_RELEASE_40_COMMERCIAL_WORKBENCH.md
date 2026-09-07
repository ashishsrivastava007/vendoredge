# VendorEdge R40 — Commercial Workbench

R40 turns the product front door into a daily commercial workbench rather than a supplier-request-only form. It supports three entry modes: supplier requests, observations the buyer notices proactively, and category/strategy questions.

## Buyer experience
- Default authenticated landing surface is a lightweight Commercial Workbench.
- One-click entry into supplier request, proactive observation, or category/strategy analysis.
- Shows only actionable in-progress work as work needing attention.
- Completed cases without outcomes are not treated as overdue work; the dashboard gives a quiet learning reminder instead.
- Shows deterministic counts from recorded case activity and clearly labels repeated activity as observation, not forecast.
- Recent decisions remain one click away.

## Guardrails
- No new model call, prediction, urgency score, or commercial fact is created by the workbench.
- Dashboard metrics are derived only from tenant-scoped case records already returned by the existing authenticated cases endpoint.
- Proactive entry prompts are prompts for analysis; they do not assert that a pattern exists.
- Existing case reasoning, trust, memory, supplier response, and execution modules remain unchanged.

## Validation
- Python compile: PASS
- Frontend JavaScript syntax: PASS
- R40 focused regression tests: PASS
- Existing release tests rerun: PASS
- Final package reopened and structurally inspected after packaging.
