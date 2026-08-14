"""Approval-gated outbound integration adapter.

The URL and secret are deployment configuration, never user-supplied. A caller
must explicitly request dispatch for a completed decision. The payload is a
stable, minimal decision event rather than the entire internal object.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


def build_event(decision_id: str, position) -> dict:
    return {
        "event": "commercial_decision.completed",
        "version": "1",
        "decision_id": str(decision_id),
        "recommendation": position.recommendation,
        "confidence": position.confidence.level,
        "evidence_integrity": position.decision_audit.evidence_integrity_status if position.decision_audit else "UNKNOWN",
        "financial_impact": position.financial_impact.model_dump(mode="json") if position.financial_impact else None,
    }


def dispatch_event(decision_id: str, position) -> dict:
    url = os.environ.get("VENDOREDGE_WEBHOOK_URL")
    secret = os.environ.get("VENDOREDGE_WEBHOOK_SECRET")
    if not url or not secret:
        return {"sent": False, "reason": "Webhook integration is not configured."}
    event = build_event(decision_id, position)
    body = json.dumps(event, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    req = Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "X-VendorEdge-Signature": signature,
        "X-VendorEdge-Event": event["event"],
    })
    try:
        with urlopen(req, timeout=8) as resp:
            status = int(resp.status)
        return {"sent": 200 <= status < 300, "http_status": status, "event": event}
    except (HTTPError, URLError, TimeoutError) as exc:
        return {"sent": False, "reason": f"Webhook delivery failed: {type(exc).__name__}"}
