# VendorEdge R25.2.4 — Decision-first UX & Economics Integrity

## Purpose
This release simplifies the buyer experience without weakening the underlying intelligence layers.

## Buyer experience
- The first screen answers four questions only: **What is my position? What is the confidence? What should I do next? What could change it?**
- Technical release labels (R19–R25) are removed from the buyer-facing sections.
- Decision Passport and Decision Snapshot duplicates are removed from the visible decision page.
- Supporting intelligence is grouped into collapsible areas: Commercial facts, Negotiation plan, What could change the decision, Execution, History & learning, and Trust & evidence trail.
- Repeated legacy rationale blocks are hidden from the decision page; detailed evidence remains available on demand.
- Existing typography and visual language are retained.

## Economics integrity
- Quote-comparison economics now require a comparable commercial basis before presenting a monetary opportunity.
- FCA/EXW/FAS/FOB buyer-borne freight is added only when explicitly quantified for that supplier.
- If a buyer-borne logistics cost is missing, VendorEdge fails closed and shows that the landed comparison is incomplete instead of annualizing the raw unit-price gap.
- Quote comparison currency is preserved; no FX is invented.
- The commercial-facts annual spend card now uses the incumbent quote currency for multi-supplier quote cases instead of hardcoding USD.

## Validation
- Focused regression suite: **20 passed, 0 failed**.
- Added regression tests for FCA/DDP quote comparisons and fail-closed behavior when freight is missing.
- JavaScript bundle syntax check: passed with Node.js `--check`.
- Full suite was not runnable in the build sandbox because external Python dependencies (including FastAPI/psycopg2/Anthropic) were not installed and the sandbox has no package-network access. This is an environment limitation, not a claimed test pass.
