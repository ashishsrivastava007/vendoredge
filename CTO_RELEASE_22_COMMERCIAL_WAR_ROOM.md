# VendorEdge Release 22 — Commercial War Room

## Mission
Turn the validated commercial decision into an evidence-backed negotiation theatre: buyer vs supplier vs market vs stakeholders, with adversarial challenge and negotiation scenarios.

## Product contract
- R22 never changes the recommendation or confidence.
- R22 does not invent supplier psychology, hidden motives, market facts, leverage, or negotiation outcomes.
- Supplier responses are explicitly represented as `NOT_PREDICTED` until an actual response is observed.
- Hypothetical negotiation moves are labelled as scenarios, not forecasts.
- All supplier facts remain supplier-specific.
- Stakeholder views remain attributed opinions/evidence, not objective facts.
- Market signals are only shown when already validated upstream.
- No LLM call is added by the R22 war-room layer.

## New capability
`app/pipeline/commercial_war_room.py` assembles:

1. Buyer position and evidence-backed leverage
2. Supplier-specific facts and defensible constraints
3. Market signals and verified cost-driver comparisons
4. Stakeholder positions with role/type/basis
5. Evidence-backed negotiation scenarios
6. Red-team/adversarial challenges
7. Open blockers and red lines
8. Explicit simulation disclaimer

## UI
A native R22 Commercial War Room is rendered immediately after the R21 Decision Flip Map and before the Commercial Decision Cockpit.

## Validation
Targeted R22 + R21/R19/R18/currency regression tests: **21 passed**.

Frontend JavaScript extracted from the HTML and validated with `node --check`: **PASS**.

Python compilation/import validation: **PASS**.

Known environment limitation inherited from earlier releases: the complete repository suite cannot be collected in this environment because some legacy integration tests import optional runtime dependencies (`anthropic`, database driver `psycopg2`) that are not installed. This is not represented as a passing full-suite result.
