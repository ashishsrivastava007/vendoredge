# VendorEdge Release 21 — Decision Flip Map

## Mission
Answer: **What would actually change this decision?**

R21 adds a deterministic decision-boundary layer after the validated commercial position and before presentation. It does not create a second model opinion and cannot alter the recommendation.

## Product behavior
- Shows exact numeric supplier-price boundaries only when suppliers are explicitly comparable in the same currency and annual volume is known.
- Preserves qualitative reversal conditions as evidence-required conditions instead of fabricating thresholds.
- Refuses FX conversion when supplier currencies are mixed or missing.
- Separates economic price ordering from the overall award recommendation.
- Provides a conservative fragility review signal; it is explicitly **not** statistical confidence or probability of failure.
- Carries the original recommendation unchanged into the flip map for traceability.

## Example
If Atlas is recommended at EUR 52/unit and EuroMotion is EUR 43/unit, R21 may state that Atlas reaches the direct-price boundary at EUR 43/unit. It must not claim that this alone reverses the full procurement recommendation because quality, capacity, qualification, freight, contract terms and other non-price factors may matter.

## Non-negotiable controls
1. No LLM call.
2. No invented FX.
3. No invented freight, duty, quality, capacity or market thresholds.
4. No recommendation mutation.
5. No statistical claims from the fragility score.
6. Qualitative reversal conditions remain clearly labelled as requiring evidence.

## Validation
Targeted R21 + regression suite: **25 passed**.

Full repository collection is not executable in this environment because the existing project test environment lacks `psycopg2` and `anthropic`; those failures are dependency/collection failures, not R21 test failures.
