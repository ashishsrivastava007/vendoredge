# VendorEdge Quality Scorecard
**Last verified build**: this session, full 120-test suite passing from a clean state, PostgreSQL 16, real RLS enforcement confirmed.

---

## Guarantees 1–6

| # | Guarantee | Tests | Deliberate-Break Proven | Status |
|---|---|---|---|---|
| 1 | Evidence Provenance | 4 | ✅ (nonexistent-decision query returns honest `None`) | **PASS** |
| 2 | Multi-Supplier Evidence Model | 6 + 4 (findings) | ✅ (simulated pre-fix state loses NordicMetals' Incoterm entirely) | **PASS** |
| 3 | No Internal Contradiction | 4 | ✅ (live-endpoint retry proven, real Case 5 reconstruction) | **PASS** |
| 4 | Evidence → Claim Integrity | 5 | ✅ (live-endpoint retry proven, real BioSyn reconstruction) | **PASS** |
| 5 | Decision Integrity / Confidence Gate | 10 | ✅ (removing Check C lets a real case wrongly reach HIGH) | **PASS** |
| 6 | Adversarial Reliability Framework | 4 new + 116 consolidated | ✅ (2 new real bugs found and fixed live during this guarantee) | **PASS** |

**Total: 120 tests, 0 failing, run from a clean database state.**

---

## Known limitations — stated plainly, not hidden

1. **Confidence is still model-owned prose, corrected after the fact**, not system-owned from the start. On the roadmap (`ARCHITECTURE.md`), deliberately deferred — a real architectural restructuring, not a quick fix.
2. **The claim-integrity gate (#4) only checks qualification-status language.** "Approved supplier," "verified price," and other claim-strength patterns named in the original Quality Gate request are not yet built — the mechanism generalizes cleanly, but only one instance is implemented and proven.
3. **The confidence gate's five checks are real but not exhaustive.** They cover the five adversarial cases specified and the false-high/false-low tests, not every conceivable evidence-quality signal.
4. **BATNA and Anchoring remain deliberately unenforced** as hard contracts, per the explicit, preserved decision earlier tonight — judgment-based, not suited to binary pass/fail.
5. **Every guarantee is proven with mocked LLM calls.** Nothing tonight has been proven against a real, live Anthropic API response — the deterministic logic is genuinely tested; the model's actual real-world text output interacting with these gates has not been.
6. **Zero of this has been tested at real user volume.** All 120 tests are deterministic, single-case proofs. Whether these guarantees hold under real, messy, concurrent production traffic is unverified.

---

## Unresolved risks

**P1 — real, not yet fixed:**
- Claim-integrity coverage is narrow (see limitation #2). A real user could still receive an overstated "verified price" or "approved supplier" claim that the qualification-specific check doesn't catch.
- Confidence-gate Check E (sole-fallback reliance) uses a >50% threshold on load-bearing fields — not independently stress-tested against unusual field-count distributions (e.g., a case with only one load-bearing field present).

**P2 — real, lower urgency:**
- The Incoterm full-name normalization list is not exhaustive — a supplier document using an unusual but valid phrasing could still fail to normalize and correctly fall back to `None` (a safe failure, not a silent one, but still a missed opportunity to help).
- Methodology contracts (#12) exist only for Kraljic and TCO — Anchoring, Reciprocity, Concession Planning have no contract at all, by design, but this means a response could still name them without any evidence check whatsoever.

---

## Deploy note

This build requires the schema to be **re-applied**, not just the code redeployed — the `evidence_provenance` column and the `fallback_events.is_conflict` column are both real, additive schema changes from tonight's Phase 1 work.
