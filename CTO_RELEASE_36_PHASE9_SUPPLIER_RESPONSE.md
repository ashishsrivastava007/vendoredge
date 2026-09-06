# VendorEdge R36.1 — Phase 9: Supplier Response Execution

## Product decision
Phase 9 deliberately stays **thin**. It turns the Phase 8 prepared supplier message into a real buyer workflow without building a full email platform.

**Draft → Review → Approve → Execute → Confirm → Audit**

## User-testable flow
1. Complete a commercial case.
2. Open **Supplier Response Center**.
3. Enter the supplier email address and edit the proposed subject/body.
4. Save the exact draft.
5. Explicitly approve the response. Any subsequent edit automatically invalidates the prior approval.
6. If `VENDOREDGE_EMAIL_WEBHOOK_URL` + `VENDOREDGE_EMAIL_WEBHOOK_SECRET` are configured, send through the deployment-owned email connector.
7. If no connector is configured, use the safe **Open in email client** handoff. VendorEdge records the handoff but never claims the email was sent.
8. Paste the supplier reply back into the case and record it as captured supplier evidence.

## Safety / trust
- No send is possible without explicit approval.
- Approval is tied to the current edited draft state.
- Delivery payloads are hashed and idempotent to prevent duplicate sends of the same draft.
- Outbound delivery is durably audited with recipient, subject, body, draft version, approver, approval time and delivery result.
- Supplier replies are stored verbatim and linked to the commercial decision; this phase does not silently reinterpret them into the existing recommendation.
- Tenant RLS applies to drafts, deliveries and captured replies.

## Deliberately NOT built
- No mailbox polling / IMAP / Microsoft Graph / Gmail integration.
- No autonomous supplier outreach.
- No automatic commitment, contract, PO or ERP change.
- No automatic reinterpretation of a supplier reply into the current decision.

Those are separate product decisions and should only be added when they create enough recurring user value to justify the added integration and operational complexity.

## Validation
- Python compile: PASS
- Frontend JavaScript syntax: PASS
- Deterministic release suite: 94 passed
- Live Render/Postgres/email-provider execution: NOT validated in this environment.
