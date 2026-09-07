# VendorEdge R38 — Commercial Answer Engine

## Purpose
Turn the existing evidence, deterministic economics, decision controls,
negotiation layers, and outcome safeguards into one buyer-first commercial answer.
R38 is a compression and integrity release, not a new intelligence engine.

## Buyer experience
The first completed-case surface now answers, in order:
1. What should I do?
2. What is the money?
3. Why?
4. What do I do next?
5. What should I negotiate / trade?
6. What is the strongest counter-case?
7. What would change the decision?
8. What can I send the supplier?

The same answer surface is available to general commercial triage, so VendorEdge
is not framed only as a reaction to supplier requests. Users can bring a pattern,
forecast concern, category question, or observed commercial risk and still get a
single actionable answer with specialist limitations made explicit.

## Commercial-truth guarantees
- Deterministic price-change exposure is calculated in code whenever the normalized
  annual spend and requested percentage are safely available.
- Explicit `from X% to Y%` scenarios in the user's case text are recognized only
  when the wording is unambiguous; no arbitrary percentage is promoted into a target.
- Unsupported negotiation numbers detected by the existing claim-integrity contract
  are withheld from the buyer-facing answer.
- Supplier statements are displayed as supplier claims, not verified facts.
- Stakeholder views remain separate from verified facts.
- Unknowns remain visible without being converted into negative facts.
- No new supplier economics, thresholds, savings, or market claims are created.

## Daily-use direction
The front door explicitly supports supplier requests, observed patterns, category
strategy questions, and emerging commercial concerns. This makes R38 the first step
toward the broader VendorEdge loop: observe → ask → decide → act → learn.

## Supplier response
For price-increase cases, R38 generates an editable supplier-response draft from
existing case facts and the validated position. It does not send the message and
does not invent a commercial target.

## UI hardening
The buyer evidence renderer now safely renders structured evidence objects instead
of coercing them to `[object Object]`.

## Validation
- Python compile: PASS
- Frontend JavaScript syntax: PASS
- R38 focused tests: 7 PASS
- All release tests: 129 PASS (sandbox environment)
- ZIP integrity: checked after packaging
- Full live Render/Postgres/provider validation: not available in the sandbox

## R38.1 — Answer consolidation / repetition hardening

R38.1 makes the Commercial Answer the single owner of the buyer-facing decision summary. The legacy Decision Cockpit is suppressed for positions that have a consolidated answer; the reasoning loop retains only reasoning trace and counter-case; decision-critical unknowns are surfaced once in the answer; and the audit view filters answer-owned unknowns/reversal conditions to reduce repetition. The Control Tower is collapsed by default. Added focused regression tests for these ownership/consolidation invariants.
