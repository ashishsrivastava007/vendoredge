# VendorEdge R26.1 — Commercial Truth Foundation

## Mission
Make incomplete commercial comparisons useful without turning unknown costs into invented savings.

## What changed
- Known buyer-borne components are credited independently.
- An unknown duty/tax component no longer discards known freight.
- A partial landed-cost difference is clearly labelled **not confirmed savings**.
- A deterministic decision boundary shows how large the missing component would need to be to eliminate the known advantage.
- A raw FCA/DDP price gap is never annualized as savings when the landed basis is not defensible.
- The quote comparison path remains the single source for customer-facing commercial economics.

## Example
Atlas: EUR 52/unit DDP.
EuroMotion: EUR 45.50/unit FCA + EUR 2.20/unit explicitly evidenced freight.
Annual volume: 8,000 units.

Known landed comparison:
- Atlas known cost: EUR 52.00/unit
- EuroMotion known cost: EUR 47.70/unit
- Known difference: EUR 4.30/unit
- Known annual difference: EUR 34,400/year
- Unknown: buyer-borne import duty/tax
- Decision boundary: EUR 4.30/unit

The output is intentionally **not** called confirmed savings.

## Release gate
The dependency-free regression suite is green: 264 passed, 1 skipped, 0 failed. The complete suite cannot be executed in this isolated build environment because `psycopg2-binary` and `anthropic` are unavailable and network access is disabled. This is explicitly recorded rather than hidden.
