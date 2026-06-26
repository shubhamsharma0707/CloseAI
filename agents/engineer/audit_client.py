"""
audit_client.py — Engineer's own audit client
==============================================
Posts audit events to RISHI's /engineer/audit endpoint (NOT /kavach/audit).
Signs with AGENT_TOKEN_AGENT_ENGINEER_CODER — the same env var that
setup_dev.py generates and RISHI's _load_token("agent_engineer_coder")
looks up (AGENT_TOKEN_ + "agent_engineer_coder".upper() =
AGENT_TOKEN_AGENT_ENGINEER_CODER).

Drop-in replacement for Kavach's audit_client.log_audit_event().
All Engineer sub-agents import from here, not from Kavach's audit_client.
"""

import hashlib
import hmac
import json
import logging
import os
import time

import requests

logger = logging.getLogger("Engineer.AuditClient")

RISHI_AUDIT_URL: str = os.getenv(
    "ENGINEER_AUDIT_URL",
    "http://127.0.0.1:8000/engineer/audit",
)

# This token name matches:
#   setup_dev.py:  AGENT_IDS includes "AGENT_ENGINEER_CODER"
#                  → writes AGENT_TOKEN_AGENT_ENGINEER_CODER=<token>
#   RISHI.py:      _load_token("agent_engineer_coder")
#                  → env_key = "AGENT_TOKEN_AGENT_ENGINEER_CODER"
_AGENT_TOKEN_KEY = "AGENT_TOKEN_AGENT_ENGINEER_CODER"
AGENT_ID = "AGENT_ENGINEER_CODER"


def log_audit_event(agent_id: str, event_type: str, data: dict) -> bool:
    """
    Post one HMAC-signed audit event to RISHI /engineer/audit.

    Parameters
    ----------
    agent_id   : The reporting sub-agent ID.
    event_type : Short label for the event (e.g. "FILE_WRITE", "GIT_COMMIT").
    data       : Arbitrary dict of event metadata.

    Returns True on success, False if RISHI is unreachable (fail-open for
    audit — we log the error but do NOT block the calling operation).
    """
    secret = os.getenv(_AGENT_TOKEN_KEY, "default_engineer_secret").encode()
    payload = json.dumps(
        {"agent_id": agent_id, "event_type": event_type, "data": data},
        sort_keys=True,
    )
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    message = f"{payload}|{timestamp}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()

    try:
        resp = requests.post(
            RISHI_AUDIT_URL,
            json={
                "agent_id": agent_id,
                "payload": payload,
                "timestamp": timestamp,
                "signature": signature,
            },
            timeout=5,
        )
        if resp.status_code == 200:
            return True
        logger.warning(
            f"[EngineerAudit] RISHI returned {resp.status_code}: {resp.text[:200]}"
        )
        return False
    except Exception as exc:
        logger.warning(f"[EngineerAudit] RISHI unreachable — audit event dropped: {exc}")
        return False
