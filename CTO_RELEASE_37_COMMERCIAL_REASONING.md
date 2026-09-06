# VendorEdge R37 — Commercial Reasoning Loop

## Purpose

R37 is a focused intelligence upgrade built on the existing trust, decision,
negotiation, memory and model-orchestration layers. It does not attempt to make
VendorEdge's foundation model "smarter" than frontier models. Instead it makes
VendorEdge reason as a procurement decision system rather than exposing a pile
of independent AI outputs.

## What changed

### 1. Commercial Reasoning Loop

`app/pipeline/commercial_reasoning.py` deterministically reconciles:

- the primary recommendation;
- deterministic financial exposure;
- strongest validated evidence;
- commercial trade-offs;
- independent challenger view;
- decision stability;
- decision-changing conditions.

It cannot create facts, calculations, thresholds or recommendations.

### 2. Independent counter-case becomes visible

The existing model challenger remains independent and advisory. R37 now
surfaces its strongest counterargument directly in the buyer-facing reasoning
loop and clearly labels it as a challenger view rather than evidence.

### 3. Smarter challenge routing

Material price-increase exposure can now trigger the independent challenger at
a lower, configurable model-cost gate (`VENDOREDGE_PRICE_INCREASE_CHALLENGE_EXPOSURE_USD`,
default USD 100,000). This is a routing policy only; it is not a commercial
approval threshold.

### 4. Answer-first UX

The primary decision page now shows:

**Commercial Decision → Reasoning Loop → Action**

with the evidence, detailed analysis and advanced review still progressively
disclosed.

## Safety contract

- Challenger cannot mutate the primary recommendation.
- Market context remains separate from supplier-specific evidence.
- Unsupported strategy numbers remain blocked by R36.2 controls.
- The reasoning loop does not manufacture negotiation targets or walk-away
  values.
- Missing information is not converted into false certainty.

## Validation

- Python compilation: PASS
- R37 focused tests: PASS
- R36.2 trust/UX tests: PASS
- R36 route-contract tests: PASS
- R36 supplier-response tests: PASS
- Full release suite: run separately in the deployment/CI environment where
  PostgreSQL and provider dependencies are available.
