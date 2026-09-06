# VendorEdge R36.2 — Commercial Truth & Decision UX Hardening

## Purpose

R36.2 is a quality correction, not a new intelligence phase. It addresses issues found in the first real ABC Marine case test:

- external market context could be written as if it were supplier-specific fact;
- the reasoner could invent precise negotiation targets or durations not supported by the case;
- absent supplier attributes were being surfaced as repeated blockers even when not decision-relevant;
- the decision page exposed too many overlapping decision surfaces at once.

## Controls added

1. **External market attribution**
   - Market verification is persisted separately from supplier evidence.
   - The reasoner is explicitly forbidden from treating market movement as proof of supplier cost.
   - Market-derived statements must be labelled as external market context.
   - Market-check source metadata is retained when returned by the provider.

2. **Unsupported strategy-number gate**
   - Negotiation percentages and contract durations must be grounded in supplied evidence.
   - Unsupported numeric targets/boundaries trigger a correction attempt.
   - If the model still returns unsupported strategy numbers, a deterministic fallback removes false precision from the affected strategy fields.

3. **Decision-audit noise reduction**
   - Qualification is surfaced only when the current recommendation actually relies on an alternative supplier.
   - Certification and production-history silence is not automatically turned into a blocker.
   - Duplicate uncertainty/reversal entries are removed.

4. **Answer-first UX**
   - The Commercial Decision Cockpit is the single primary decision surface.
   - Evidence/trust, commercial analysis, negotiation detail, memory/learning and advanced review are progressively disclosed.
   - Duplicate supplier-comparison markup was removed.

## Validation

- `python -m py_compile` — PASS
- Frontend JavaScript syntax check — PASS
- R36.2 focused tests — 8/8 PASS
- All deterministic release tests — **102/102 PASS**
- Full environment test collection could not run because the sandbox has no network access and required runtime packages are not installed; Render deployment remains the production validation environment.

## Product rule

R36.2 deliberately does **not** add another intelligence module. The next step is real user validation and workflow instrumentation, not Phase 10 feature expansion.
