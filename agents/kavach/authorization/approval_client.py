"""
approval_client.py — Kavach Gap 1 agent-side helpers
=====================================================
Provides two async functions consumed by PentestAgent:

  request_human_approval(vuln, asset, severity, engagement_id)
      → calls POST /kavach/approvals on RISHI, returns approval_id

  poll_for_decision(approval_id, timeout_seconds)
      → polls GET /kavach/approvals/{id} every POLL_INTERVAL_SECONDS
        until status leaves PENDING or the wall-clock timeout expires.
        Returns a DecisionRecord (a simple namespace with .status,
        .payload, .timestamp, .signature) or None on timeout.

Fail-closed: any network error or unexpected response is treated as
TIMEOUT_NO_RESPONSE so the pentest agent stays safe without a live RISHI.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("Kavach.ApprovalClient")

RISHI_BASE = os.getenv("RISHI_BASE_URL", "http://127.0.0.1:8000")
POLL_INTERVAL_SECONDS = int(os.getenv("APPROVAL_POLL_INTERVAL", "10"))


@dataclass
class DecisionRecord:
    """Immutable snapshot of a resolved approval decision."""
    status: str          # APPROVED | DENIED | TIMEOUT_NO_RESPONSE
    payload: str         # canonical payload that was HMAC-signed
    timestamp: str       # ISO-8601 UTC from the reviewer's decide call
    signature: str       # HMAC signature from the reviewer's decide call


async def request_human_approval(
    vuln: dict,
    asset: str,
    severity: str,
    engagement_id: str,
    requesting_agent: str = "AGENT_KAVACH_PENTEST",
) -> Optional[str]:
    """
    Registers a HIGH/CRITICAL finding with RISHI for human sign-off.
    Returns the approval_id string, or None if RISHI is unreachable.
    """
    body = {
        "vuln_type": vuln.get("type", "UNKNOWN"),
        "asset": asset,
        "severity": severity,
        "engagement_id": engagement_id,
        "requesting_agent": requesting_agent,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{RISHI_BASE}/kavach/approvals", json=body)
            resp.raise_for_status()
            approval_id = resp.json()["approval_id"]
            required = resp.json().get("required_approvers", 1)
            logger.info(
                f"[APPROVAL_CLIENT] Approval {approval_id} created for {asset} "
                f"({severity}). Requires {required} reviewer(s)."
            )
            return approval_id
    except Exception as exc:
        logger.error(f"[APPROVAL_CLIENT] Failed to create approval record: {exc}")
        return None


async def poll_for_decision(
    approval_id: str,
    timeout_seconds: int = 900,
) -> DecisionRecord:
    """
    Polls RISHI every POLL_INTERVAL_SECONDS until the approval record
    leaves PENDING state or the timeout elapses.

    Returns a DecisionRecord.  Status will be TIMEOUT_NO_RESPONSE if
    the polling window expires without a human decision — the pentest
    agent must treat this as BLOCKED (fail-closed).
    """
    if not approval_id:
        logger.error("[APPROVAL_CLIENT] No approval_id to poll — returning TIMEOUT.")
        return DecisionRecord(
            status="TIMEOUT_NO_RESPONSE", payload="", timestamp="", signature=""
        )

    deadline = asyncio.get_event_loop().time() + timeout_seconds
    url = f"{RISHI_BASE}/kavach/approvals/{approval_id}"

    logger.info(
        f"[APPROVAL_CLIENT] Polling {approval_id} "
        f"(timeout={timeout_seconds}s, interval={POLL_INTERVAL_SECONDS}s)…"
    )

    while asyncio.get_event_loop().time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "PENDING")

                if status != "PENDING":
                    logger.info(
                        f"[APPROVAL_CLIENT] {approval_id} resolved → {status}"
                    )
                    return DecisionRecord(
                        status=status,
                        payload=data.get("payload", ""),
                        timestamp=data.get("timestamp", ""),
                        signature=data.get("signature", ""),
                    )
        except Exception as exc:
            logger.warning(f"[APPROVAL_CLIENT] Poll error for {approval_id}: {exc}")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    logger.warning(
        f"[APPROVAL_CLIENT] {approval_id} timed out after {timeout_seconds}s — "
        "treating as TIMEOUT_NO_RESPONSE (fail-closed)."
    )
    return DecisionRecord(
        status="TIMEOUT_NO_RESPONSE",
        payload="",
        timestamp=datetime.now(timezone.utc).isoformat(),
        signature="",
    )
