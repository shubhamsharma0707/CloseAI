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


# ---------------------------------------------------------------------------
# MEMORY — same HMAC scheme as log_audit_event above, posted to RISHI's
# /kavach/memory/* endpoints instead of /kavach/audit. Kavach has no MCP
# connection to RISHI (see RISHI.py's AGENT_REGISTRY comment), so memory
# access has to travel over this same REST+HMAC channel as everything else.
# ---------------------------------------------------------------------------
_RISHI_BASE = RISHI_URL.rsplit("/kavach/audit", 1)[0]  # http://127.0.0.1:8000


def _signed_post(path: str, agent_id: str, payload_dict: dict) -> dict | None:
    secret = os.getenv("AGENT_TOKEN_KAVACH_CORE", "default_kavach_secret").encode()
    payload_str = json.dumps(payload_dict, sort_keys=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    message = f"{payload_str}|{timestamp}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()

    try:
        resp = httpx.post(f"{_RISHI_BASE}{path}", json={
            "agent_id": agent_id,
            "payload": payload_str,
            "timestamp": timestamp,
            "signature": signature,
        }, timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"❌ [MEMORY] Failed to reach RISHI at {path}: {e}")
        return None


def remember(agent_id: str, key: str, value: str, category: str = "kavach") -> bool:
    """Store/reinforce a durable fact. Mirrors memory_store.remember() over REST."""
    result = _signed_post("/kavach/memory/remember", agent_id, {"key": key, "value": value, "category": category})
    return result is not None


def record_episode(agent_id: str, task_summary: str, outcome: str, detail: str = "", duration_ms: int | None = None) -> int | None:
    """Record a completed task attempt. Mirrors memory_store.record_episode() over REST."""
    result = _signed_post("/kavach/memory/episode", agent_id, {
        "task_summary": task_summary, "outcome": outcome, "detail": detail, "duration_ms": duration_ms,
    })
    return result.get("episode_id") if result else None


def recall(agent_id: str, query: str, category: str | None = None) -> list[dict]:
    """Search stored facts. Mirrors memory_store.recall() over REST."""
    result = _signed_post("/kavach/memory/recall", agent_id, {"query": query, "category": category})
    return result.get("facts", []) if result else []


def recall_recent_episodes(agent_id: str, n: int = 10, outcome: str | None = None) -> list[dict]:
    """Check precedent before retrying a task. Mirrors memory_store.recall_recent_episodes() over REST."""
    result = _signed_post("/kavach/memory/recent-episodes", agent_id, {"agent_id": agent_id, "n": n, "outcome": outcome})
    return result.get("episodes", []) if result else []
