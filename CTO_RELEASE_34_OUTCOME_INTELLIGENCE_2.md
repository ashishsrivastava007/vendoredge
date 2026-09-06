# VendorEdge Release 34 — Outcome Intelligence 2.0

## Mission
Turn recorded outcomes into a safer closed-loop learning layer without rewriting the original decision or pretending that sparse outcomes prove causality.

## Product capability
R34 extends R24 with:
- **realization status** — no expectation / actual not recorded / close to expectation / below expectation / above expectation;
- **learning status** — awaiting outcome / unresolved / measurable / recorded but limited;
- **attribution level** — higher attribution, partial attribution, no direct attribution, diagnostic only, or unresolved;
- **next-time controls** — deterministic process controls based on the recorded verdict and decision alignment;
- **historical calibration** after at least three structured expected-vs-actual pairs:
  - mean signed variance %;
  - mean absolute variance %;
  - share within ±10% of expected;
  - conservative direction signal (generally aligned / over-estimated / under-estimated).

## Integrity rules
- Free text is never parsed into financial values.
- Structured actual value must be recorded on the same annual-impact basis to calculate variance.
- A modified or rejected recommendation is never presented as wholly attributable to VendorEdge.
- Historical calibration is descriptive, not predictive.
- Minimum sample size remains three; sparse history does not create a performance claim.
- Original `commercial_position` remains immutable.
- No LLM call is made by the R34 layer.

## User experience
The Outcome Intelligence card now shows the realization/learning state, attribution treatment, next-time process control, and historical calibration when evidence is sufficient.

## Validation
- R24 + R34 targeted outcome tests: passed.
- R33 supplier memory, R31 decision engine and R30 organisation format regression: passed.
- Python compileall: passed.
- Frontend JavaScript syntax check: passed.
- Live Render/Postgres/Anthropic validation is not claimed in this environment.
