# VendorEdge CTO Release 8 — Commercial Alternative Paths

## Purpose
Release 8 adds a deterministic alternative-path layer. VendorEdge now presents distinct commercial paths around the primary recommendation without pretending that one hidden risk score or stakeholder weighting exists.

## Product behavior
The new **Commercial alternatives** section can present up to three evidence-backed paths such as:
- incumbent continuity / accept the requested change;
- negotiate and protect the current baseline;
- develop a named alternative / dual-source;
- cost-led supplier selection, continuity-led selection, and an explicit dual-source path for quote comparisons.

Each path states:
- what the path is;
- deterministic annual spend only when safe evidence supports it;
- what is gained;
- what is given up or constrained;
- stakeholder views explicitly tied to the named supplier;
- evidence strength;
- evidence still required before the path can be treated as fully actionable.

## Guarantees
- No additional LLM call.
- No invented allocation percentages.
- No invented FX, freight, duty, capacity, quality, qualification, or stakeholder preferences.
- Stakeholder views are attributed, never converted into objective supplier facts.
- A missing qualification/production-history fact remains an open item, not a negative fact.
- Dual-source paths do not claim a blended annual spend unless an explicit allocation is already evidenced.
- The alternatives layer does not override the primary recommendation; it exposes decision choices around it.

## Testing
- 7/7 Release-8 focused tests pass.
- Python compilation passes for all touched backend files.
- Browser JavaScript syntax check passes for the static bundle.
- Full suite attempted but cannot be collected in this sandbox because production dependencies `psycopg2` and `anthropic` are unavailable and outbound package installation is unavailable. No full-suite pass is claimed.

## Deployment
No database migration is required for Release 8.
