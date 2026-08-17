# CTO Release 17 — Decision Integrity + Decision Passport

## Purpose
Release 17 hardens the exact defects found during the first real deployed acceptance case and introduces VendorEdge's native answer-first presentation format.

## Stop-ship fixes
- **One confidence authority:** the final confidence gate now starts from the pre-reasoning evidence ceiling and applies post-reasoning checks. A material stakeholder conflict can no longer disappear and become HIGH at the final output.
- **Supplier-specific attribution:** stakeholder conflict detection now requires an explicit directional preference/recommendation/comparison. Merely mentioning two suppliers is not treated as a conflict.
- **Short-form supplier names:** confidence reliance checks recognize safe supplier aliases, so `EuroMotion` can be attributed to `EuroMotion Poland` without requiring the legal name verbatim.
- **Financial presentation:** the native Decision Passport reports deterministic direct economics when available. For quote comparisons it calculates same-currency annual price opportunity from explicit supplier prices and annual volume, without FX/freight/duty assumptions.
- **Alternative/stress isolation:** stress-test and alternative-path construction now fail independently; one presentation module cannot erase the other.
- **Currency safety:** quote alternatives refuse to compare suppliers across currencies without an explicit FX rate.

## New VendorEdge-native format: Decision Passport
The first screen is now designed around **Answer → Money → Confidence → Evidence → Next Move**.

The Passport contains:
1. Decision / recommendation
2. Readiness: READY / CONDITIONAL / HOLD
3. Confidence and its system-owned derivation
4. Direct economics when safely calculable
5. Top reasons
6. Critical items before action
7. Next move
8. Decision-changing conditions
9. Material unknowns
10. Number of alternative commercial paths and stress-test status

This is a presentation layer over the validated decision. It adds no facts and makes no new LLM call.

## Bring Your Own Format
The existing deterministic template renderer is retained and expanded with `{{decision_passport}}`. The UI now exposes it directly alongside the Decision Pack instead of hiding it as a secondary capability.

## Testing intent
New regression coverage specifically targets:
- stakeholder mention vs. stakeholder preference
- comparative supplier statements
- final confidence respecting the pre-reasoning cap
- same-currency quote economics
- Decision Passport construction

Environment note: this build was syntax-compiled locally. Full pytest execution requires the pinned dependencies and PostgreSQL environment defined by `requirements.txt` / `docker-compose.yml`; this execution environment has no network access and did not have those dependencies preinstalled.
