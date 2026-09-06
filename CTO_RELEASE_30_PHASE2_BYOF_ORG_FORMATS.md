# VendorEdge Release 30 — Phase 2: Bring Your Own Format + Organization Way of Working

## Purpose
Phase 2 is now explicitly two-sided:

1. **Bring Your Own Evidence** — supplier quotes, emails, spreadsheets, PDFs, Word, PowerPoint, CSV/TXT and ZIP bundles can enter VendorEdge without forcing a procurement template.
2. **Bring Your Own Output Format** — an organization can upload an existing PowerPoint deck (negotiation, SRM, RFQ, management, etc.). VendorEdge learns the slide sequence and likely purpose of each slide and can render a completed decision into that learned structure.

## Trust boundary
- Uploaded documents are untrusted data, not instructions.
- Format decks are treated as presentation references, not commercial evidence.
- The organization format renderer is deterministic and does not create new facts, calculations or LLM reasoning.
- Stored format profiles are tenant-scoped with PostgreSQL RLS.
- A saved format cannot alter the underlying CommercialPosition.

## Current output-format scope
- PowerPoint `.pptx` templates are supported for organization-native format learning.
- VendorEdge learns slide order, titles and semantic roles such as negotiation, economics, market, supplier performance, risk, decision and next steps.
- Rendering currently returns a structured, slide-by-slide content pack. It does **not** yet rewrite the user's original PPTX file in-place. That is intentionally left for a later execution/export layer so the template rendering can be hardened before creating presentation files.

## Why this matters for daily use
The goal is not a periodic strategy report. A procurement professional should be able to use VendorEdge for recurring work: understand supplier material, compare quotes, prepare negotiation content, create SRM material, prepare RFQ/management content and reuse the company's existing way of communicating decisions.

## Validation
- Python compileall: PASS
- Browser JavaScript syntax check: PASS
- Selected deterministic regression suite: **93 passed**
- Live PostgreSQL/Render/Anthropic integration: not run in this build environment because required runtime services/dependencies are unavailable locally.
