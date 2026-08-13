# VendorEdge Adversarial Reliability Framework

This is the permanent reference for what VendorEdge is proven to survive, and how. Every category below follows the same required structure: **EXPECTED FAILURE → SYSTEM DETECTS IT → SAFE RESPONSE → NO SILENT CORRUPTION.**

**Quality Gate Rule, in effect from this point forward**: no future production change is considered complete unless the relevant adversarial test(s) below pass **and** the full regression suite passes. A change that breaks any of these, even while adding something new and valuable, is not done — it is broken.

---

### 1. Missing critical evidence
- **Expected failure**: a case is submitted without a load-bearing fact (e.g. no annual spend).
- **Detected by**: `check_missing_evidence()`, deterministic, runs before any reasoning call.
- **Safe response**: the case stops at `awaiting_user_input`, asking specifically for what's missing — never guessed.
- **Proof**: `tests/test_pipeline.py`, `tests/test_evidence_gate_backfill.py`.

### 2. Conflicting evidence (LLM vs. deterministic disagreement)
- **Expected failure**: two independent extraction methods produce different values for the same fact.
- **Detected by**: `_resolve_field()` in `normalize.py`.
- **Safe response**: both values retained in provenance, `conflicting=True`, surfaced explicitly into the reasoning prompt — never silently resolved.
- **Proof**: `tests/test_normalize_evidence.py::test_scenario_g_conflict_detected_and_both_values_retained`.

### 3. Multi-supplier ambiguity
- **Expected failure**: two real suppliers genuinely have different Incoterms/regions in one case.
- **Detected by**: the multi-supplier evidence model (Guarantee #2) — differing per-supplier values are recognized as legitimate, not forced into a single case-wide field.
- **Safe response**: zero false conflict; both suppliers' real data represented independently.
- **Proof**: `tests/test_multi_supplier_evidence.py`, using the real, verbatim Case 5 text.

### 4. Wrong supplier attribution
- **Expected failure**: data from one supplier bleeds into another's record.
- **Detected by**: direct, adversarial testing with three deliberately similar-sounding supplier names.
- **Safe response**: each supplier's Incoterm and price stay independently correct.
- **Proof**: `tests/test_adversarial_new_findings.py::test_no_cross_attribution_across_similarly_named_suppliers`.

### 5. Wrong currency/Incoterm (malformed, not just missing)
- **Expected failure**: the LLM extracts a full name ("Free On Board") or a genuinely invalid value instead of the real code.
- **Detected by**: **found live during this guarantee's adversarial pass, then fixed** — `normalize_incoterm()`, validated against the real Incoterms 2020 standard.
- **Safe response**: recognized full names are normalized to their code; genuinely invalid values become `None`, never silently accepted as real.
- **Proof**: `tests/test_adversarial_new_findings.py` (3 tests, including the real fix's regression).

### 6. Malformed numeric inputs
- **Expected failure**: a value that looks numeric but isn't ("not-a-number" as a duty rate).
- **Detected by**: Pydantic's own strict typing at the `NormalizedEvidence` construction boundary.
- **Safe response**: rejected at construction, never silently coerced or defaulted to zero.
- **Proof**: `tests/test_cross_border.py::test_malformed_duty_rate_is_now_rejected_earlier_by_pydantic`.

### 7. Unsupported claims (general)
- **Expected failure**: a response asserts something stronger than the evidence justifies.
- **Detected by**: the claim-integrity gate (Guarantee #4).
- **Safe response**: retried with a specific correction naming the real evidence gap.
- **Proof**: see #8 below — the concrete, proven instance of this general category.

### 8. Qualification-status overstatement
- **Expected failure**: a supplier at 70% qualification gets called "a qualified supplier."
- **Detected by**: `check_qualification_overstatement()`, checked against the real, structured `qualification_status` field.
- **Safe response**: retried once; the corrected response uses honestly hedged language.
- **Proof**: `tests/test_claim_integrity.py`, including a full live-endpoint deliberate-break proof.

### 9. Internal financial contradictions
- **Expected failure**: the headline says "not calculable" while a real scenario table shows a computed figure.
- **Detected by**: `check_all_contradictions()` — the exact, confirmed real Case 5 finding.
- **Safe response**: retried once, correction references the real guaranteed number.
- **Proof**: `tests/test_no_contradiction.py`, full live-endpoint deliberate-break proof.

### 10. Follow-up data loss
- **Expected failure**: per-supplier evidence disappears across a `/respond` or `continue_case` round-trip.
- **Detected by**: **found and fixed twice during this build** — a real ordering bug where data was stripped before being saved.
- **Safe response**: a direct database query confirms supplier data survives the round-trip.
- **Proof**: `tests/test_claim_integrity.py::test_supplier_data_survives_a_followup_respond_call`.

### 11. Confidence manipulation
- **Expected failure**: the model claims HIGH confidence despite a real structural gap (false-high), or the system tries to "help" a genuinely cautious model by raising a real LOW claim (false-low).
- **Detected by**: `apply_confidence_ceiling()` (Guarantee #5).
- **Safe response**: false-high is genuinely overridden downward; false-low is left alone — the ceiling only ever lowers, never raises.
- **Proof**: `tests/test_confidence_gate.py` — 10 tests, including both required false-high/false-low tests and a deliberate-break proof.

### 12. Methodology misuse
- **Expected failure**: "Kraljic" or "TCO" is named without the real prerequisites (both risk axes; complete cost components) being genuinely evidenced.
- **Detected by**: `check_kraljic_reasoning_coverage()`, `check_tco_coverage()`.
- **Safe response**: retried with a correction naming exactly what's missing.
- **Proof**: `tests/test_kraljic_contract.py`, `tests/test_methodology_consistency.py`.

### 13. Tenant/data-isolation failures
- **Expected failure**: one organization's data becomes visible to another.
- **Detected by**: real, adversarial, DB-level RLS testing — not assumed, tested directly against a second real organization for every new sensitive query added tonight (provenance, confidence calibration).
- **Safe response**: every cross-org query genuinely returns nothing.
- **Proof**: `tests/test_tenant_isolation.py`, `tests/test_evidence_provenance.py::test_tenant_isolation_protects_the_provenance_query`, `tests/test_confidence_calibration.py`.

### 14. LLM vs. deterministic extraction disagreement
- Same underlying mechanism as #2, listed separately because the *instrumentation* is a distinct, real guarantee (Guarantee #1): every conflict is logged as real telemetry (`fallback_events`, `is_conflict=True`), not just silently resolved in memory.
- **Proof**: `tests/test_normalize_evidence.py`, `tests/test_evidence_provenance.py`.

---

## What this framework deliberately does not claim

This proves VendorEdge survives these **specific, real, previously-found failure modes** — most discovered from genuine live incidents tonight, not invented in the abstract. It does not prove VendorEdge is immune to failure modes nobody has found yet. Section "What could still fool VendorEdge" in the final Phase 1 audit names several of these honestly.
