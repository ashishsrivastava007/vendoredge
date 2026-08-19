# VendorEdge R27 — 90-Second Buyer Experience

## Mission
Turn the existing VendorEdge intelligence stack into a decision-first buyer experience without deleting the underlying evidence, economics, negotiation, risk, memory, or audit capabilities.

## Buyer-first default
The default decision screen answers five questions:

1. **What should I do?** — the commercial position and decision mode.
2. **Why?** — the few evidence-backed reasons that drive the recommendation.
3. **What is the money?** — the canonical commercial result, with unknowns preserved.
4. **How do I negotiate?** — opening position, target/protection point, and usable talking points.
5. **What could change it?** — decision changers, material risks, and the next missing answer when applicable.

## Progressive disclosure
Supporting evidence is collapsed by default behind:

- Why
- Money
- Negotiation
- Risk & decision changers
- Show me the evidence

Internal R19–R25 engineering layer names are not presented in the default buyer experience.

## Safety / truth rules
- The UI consumes the deterministic decision, canonical economics, uncertainty state, negotiation playbook, audit evidence, and decision boundaries already produced by the pipeline.
- The UI does not calculate commercial numbers.
- Unknown economics remain unknown.
- Supplier statements are not promoted to facts by presentation.
- Uncertainty can reduce confidence; it cannot create evidence.

## Validation
Focused R27 + canonical economics + uncertainty + cockpit regression tests: **18 passed, 0 failed** in the dependency-light environment.

Full application-suite execution still requires the production database/LLM dependencies and is a release gate before production deployment.
