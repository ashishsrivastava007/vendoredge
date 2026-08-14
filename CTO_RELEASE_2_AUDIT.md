# VendorEdge CTO Release 2 — Evidence & Stakeholder Hardening

## Scope

This release builds on the P0 security release and hardens the evidence boundary for real procurement decisions.

### Changes

1. **Stakeholder evidence ledger**
   - Added an attributed `StakeholderView` structure.
   - Captures objective, preference, risk concern, constraint, experience, rumor, and recommendation views.
   - Preserves stakeholder attribution instead of converting opinions into facts.
   - Conflicting stakeholder views remain separate.
   - Capped at 8 views per case to keep extraction bounded.

2. **Supplier-claim firewall compatibility**
   - Stakeholder views are passed to reasoning separately from commercial evidence.
   - The reasoner is explicitly instructed not to treat stakeholder preference, anecdote, rumor, or experience as independently verified supplier evidence.
   - Hard constraints receive greater weight only when the evidence identifies a genuine policy, contractual, regulatory, safety, or operational constraint.

3. **Round-trip persistence**
   - Stakeholder views are stored in the existing JSON evidence payload under an internal reserved key.
   - `/respond` and continuation paths restore them.
   - The generic internal-key filter prevents these bookkeeping objects from leaking through the user-facing API.

4. **Classifier output resilience**
   - The classifier uses a bounded 2048 -> 4096 -> 8192 token ladder when the model actually hits `max_tokens`.
   - This is intentionally bounded; it is not an unbounded "just keep increasing tokens" strategy.
   - The larger budget is used only when the previous response was genuinely truncated.

## Verification performed in this environment

- Python syntax compilation across application modules: PASS.
- Classifier prompt evaluation with a stubbed Anthropic module: PASS.
- Classifier mock integration: PASS.
- Stakeholder evidence tests: PASS.
- Supplier claim taxonomy tests: PASS.
- Multi-supplier evidence tests: PASS.
- Currency safety tests: PASS.
- Combined selected regression set: 35 PASS.

## Environment limitation

The complete application regression suite could not be executed in this isolated build environment because the runtime image does not contain `anthropic` and `psycopg2`, and outbound package installation is unavailable. No green full-suite number is claimed here.

The existing application test suite remains in the package for execution in the real development/Render environment.

## Important product rule

VendorEdge should never decide that a stakeholder is "right" merely because the stakeholder is senior, confident, or appears to have insider information. Instead it should distinguish:

- **Fact** — supported by evidence.
- **Stakeholder view** — explicitly attributed preference, experience, concern, or recommendation.
- **Hard constraint** — independently supported policy/contract/regulation/safety/operational requirement.
- **Rumor / insider signal** — potentially useful lead, but explicitly unverified.

When material stakeholder views conflict, the commercial recommendation should surface the conflict and explain what each party is optimizing for rather than manufacturing consensus.
