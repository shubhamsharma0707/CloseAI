"""
kill_switch_client.py — Kavach Kill Switch Client (Feature Set B.2)
====================================================================
Provides check_kill_switch() used by all Phase 3 plugins and PentestAgent
before any real work (subprocess invocation, HTTP calls).

Fail-closed: if RISHI is unreachable, the kill switch is treated as ACTIVE
and the caller must abort. This is intentional — a missing safety check is
itself unsafe.

The RISHI-side kill switch endpoints (POST /kavach/kill-switch/activate,
POST /kavach/kill-switch/deactivate, GET /kavach/kill-switch/status) are
added in Commit 5. Until then, GET /kavach/kill-switch/status returns 404
and this client treats 404 as INACTIVE (safe default for startup).
"""

import logging
import os

import httpx

logger = logging.getLogger("Kavach.KillSwitchClient")

RISHI_BASE = os.getenv("RISHI_BASE_URL", "http://127.0.0.1:8000")
_STATUS_URL = f"{RISHI_BASE}/kavach/kill-switch/status"


def check_kill_switch() -> bool:
    """
    Synchronous kill switch check.  Returns True if the kill switch is
    ACTIVE (caller must abort), False if INACTIVE (safe to proceed).

    Fail-closed: any error other than 404 (endpoint not yet deployed) is
    treated as ACTIVE.  404 is treated as INACTIVE to allow the system to
    start before the kill switch endpoint is deployed.
    """
    try:
        resp = httpx.get(_STATUS_URL, timeout=3.0)
        if resp.status_code == 404:
            # Kill switch endpoint not yet deployed — treat as inactive
            return False
        if resp.status_code == 200:
            return resp.json().get("active", False)
        # Any other status → fail closed
        logger.warning(
            f"[KillSwitch] Unexpected status {resp.status_code} from RISHI — "
            "treating kill switch as ACTIVE (fail-closed)."
        )
        return True
    except httpx.ConnectError:
        # RISHI unreachable → fail closed
        logger.error(
            "[KillSwitch] RISHI unreachable — treating kill switch as ACTIVE (fail-closed)."
        )
        return True
    except Exception as exc:
        logger.error(f"[KillSwitch] Unexpected error: {exc} — fail-closed.")
        return True


async def check_kill_switch_async() -> bool:
    """
    Async version for use inside async contexts.  Same fail-closed semantics.
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(_STATUS_URL)
            if resp.status_code == 404:
                return False
            if resp.status_code == 200:
                return resp.json().get("active", False)
            logger.warning(
                f"[KillSwitch] Unexpected status {resp.status_code} — "
                "treating as ACTIVE (fail-closed)."
            )
            return True
    except httpx.ConnectError:
        logger.error("[KillSwitch] RISHI unreachable — treating kill switch as ACTIVE.")
        return True
    except Exception as exc:
        logger.error(f"[KillSwitch] Error: {exc} — fail-closed.")
        return True
