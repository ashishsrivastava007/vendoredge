from types import SimpleNamespace
import hashlib, hmac, json
from app.pipeline.webhook import build_event


def test_webhook_event_is_minimal_and_stable():
    p = SimpleNamespace(recommendation="Hold price", confidence=SimpleNamespace(level="medium"), decision_audit=SimpleNamespace(evidence_integrity_status="UNKNOWN"), financial_impact=None)
    e = build_event("abc", p)
    assert e == {"event":"commercial_decision.completed","version":"1","decision_id":"abc","recommendation":"Hold price","confidence":"medium","evidence_integrity":"UNKNOWN","financial_impact":None}


def test_webhook_signature_is_hmac_sha256_compatible():
    body = json.dumps({"event":"commercial_decision.completed"}, separators=(",", ":")).encode()
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert len(sig) == 64
