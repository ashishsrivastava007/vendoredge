# VendorEdge R26.1.1 — Canonical Economics Everywhere

## Purpose
Close the remaining R26.1 architecture gap: customer-facing quote economics and monetary flip boundaries must come from the canonical `build_quote_tco()` result.

## Changes
- `decision_flip_map.py` no longer computes quote price × volume independently.
- Quote Flip Map consumes monetary boundaries from `build_quote_tco()`.
- Partial landed-cost cases prefer the known landed-cost decision boundary (for example, EUR 4.30/unit) and do not surface the raw EUR 6.50/unit annualized gap.
- A raw quoted-price boundary is exposed by the canonical TCO engine only when landed economics are unavailable, and is explicitly labelled as quote-basis rather than savings.
- Added regression coverage proving the partial FCA/DDP case cannot reintroduce the raw annualized gap in Flip Map.

## Release gate
Focused regression set: 16 passed, 0 failed.

Full-suite execution remains environment-dependent where database/LLM packages are unavailable; no full-suite result is claimed from this isolated build environment.
