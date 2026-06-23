import os
import json
import hmac
import hashlib
from datetime import datetime, timezone
import httpx
import logging

logger = logging.getLogger("Kavach.Audit")

RISHI_URL = os.getenv("RISHI_AUDIT_URL", "http://127.0.0.1:8000/kavach/audit")

def log_audit_event(agent_id: str, phase: str, event_data: dict) -> str | None:
    """
    Computes an HMAC over (payload + timestamp) and sends it to RISHI
    for immutable hash-chained persistence.
    """
    secret = os.getenv("AGENT_TOKEN_KAVACH_CORE", "default_kavach_secret").encode()
    
    # Include phase info in payload
    payload_dict = {
        "phase": phase,
        "event_data": event_data
    }
    payload_str = json.dumps(payload_dict, sort_keys=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    
    message = f"{payload_str}|{timestamp}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    
    try:
        resp = httpx.post(RISHI_URL, json={
            "agent_id": agent_id,
            "payload": payload_str,
            "timestamp": timestamp,
            "signature": signature
        }, timeout=5.0)
        
        resp.raise_for_status()
        hash_val = resp.json().get("hash")
        logger.info(f"🔒 [AUDIT] Event cryptographically logged to RISHI. Hash: {hash_val[:16]}...")
        return hash_val
    except Exception as e:
        logger.error(f"❌ [AUDIT] Failed to write to RISHI audit ledger: {e}")
        return None
