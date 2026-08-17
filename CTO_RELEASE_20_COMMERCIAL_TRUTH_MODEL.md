# VendorEdge Release 20 — Commercial Truth Model

## Mission
Turn the validated procurement case into a deterministic structural model of the commercial situation.

R20 is **not** another LLM summary. It is the internal contract that later releases consume:

- R21 Decision Flip Engine
- R22 Commercial War Room
- R23 Procurement Memory
- R24 Outcome Loop
- R25 Commercial DNA

## Design guarantees

1. One source of truth: `NormalizedEvidence` remains the only evidence-normalization boundary.
2. No second extraction pass.
3. No hidden FX conversion.
4. Same-currency supplier prices may be compared deterministically; mixed currencies remain non-comparable.
5. Supplier-specific attributes remain supplier-specific (including Incoterm, region and qualification).
6. Unknown is never converted into a negative fact.
7. Stakeholder views remain attributed and are not promoted to commercial facts.
8. The model cannot change the recommendation or confidence.
9. No LLM call is used to build R20.
10. The model is persisted inside the immutable completed `commercial_position` JSON.

## Model sections

- Situation
- Parties / suppliers
- Economics and exposure
- Commercial dimensions
- Dependencies
- Stakeholder views
- Decision changers and unknowns
- Evidence posture and provenance links
- Traceability to R19 controls

## Product intent

The user should be able to inspect the situation as a structured commercial system rather than a block of AI prose. R20 is the foundation for the later question: **what exactly would have to change for the decision to change?**
