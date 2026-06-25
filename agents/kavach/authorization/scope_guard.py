"""
scope_guard.py — Kavach Authorization & Scope Enforcement (Gap 3 upgrade)
==========================================================================
ScopeGuard.check() is now an authenticated HTTP call to RISHI's
GET /kavach/engagements/{id} endpoint rather than a local flat-file read.

Why this matters:
  • A REVOKED engagement takes effect immediately on the next Kavach action —
    no process restart, no file swap.
  • The scope check itself is now in the same tamper-evident ledger as every
    other Kavach action (ScopeGuard reads from RISHI, RISHI writes the audit
    trail, the audit trail is HMAC-chained).
  • Fail-closed by default: if RISHI is unreachable, the check returns DENIED
    rather than falling through to the local file.

Local engagements.json is still loaded as a warm-up seed on first import
(bootstraps RISHI's engagement store via POST /kavach/engagements if the
store is cold), but it is no longer the authoritative source of truth at
request time.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("Kavach.ScopeGuard")

RISHI_BASE = os.getenv("RISHI_BASE_URL", "http://127.0.0.1:8000")
ENGAGEMENTS_FILE = os.path.join(os.path.dirname(__file__), "engagements.json")


@dataclass
class GuardResult:
    allowed: bool
    reason: str
    engagement_id: Optional[str] = None
    destructive_testing_allowed: bool = False
    authorized_approvers: list = None

    def __post_init__(self):
        if self.authorized_approvers is None:
            self.authorized_approvers = []


class ScopeGuard:
    def __init__(self):
        # Load local file once at startup — used as a seed to warm RISHI's
        # engagement store the first time this process connects.
        self._local_engagements = self._load_local_engagements()
        self._seeded = False   # set True after first successful RISHI seed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_local_engagements(self) -> list:
        """Load engagements.json as a bootstrap seed (not authoritative)."""
        try:
            with open(ENGAGEMENTS_FILE, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning("[SCOPE_GUARD] engagements.json not found — RISHI store is sole authority.")
            return []
        except json.JSONDecodeError as exc:
            logger.error(f"[SCOPE_GUARD] Failed to parse engagements.json: {exc}")
            return []

    async def _seed_rishi_if_cold(self, engagement_id: str) -> None:
        """
        If the RISHI engagement store doesn't know about this engagement yet,
        seed it from the local file.  This is a one-time bootstrap path.
        """
        if self._seeded:
            return
        for eng in self._local_engagements:
            if eng.get("engagement_id") == engagement_id:
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.post(
                            f"{RISHI_BASE}/kavach/engagements",
                            json={
                                "engagement_id": eng["engagement_id"],
                                "client": eng.get("client", "Unknown"),
                                "targets": eng.get("targets", []),
                                "start_time": eng.get("start_time", ""),
                                "end_time": eng.get("end_time", ""),
                                "permitted_techniques": eng.get("permitted_techniques", []),
                                "authorized_approvers": eng.get("authorized_approvers", []),
                                "destructive_testing_allowed": eng.get("destructive_testing_allowed", False),
                            }
                        )
                        if resp.status_code in (201, 409):
                            # 201 = created, 409 = already exists — either is fine
                            self._seeded = True
                            logger.info(f"[SCOPE_GUARD] Seeded engagement {engagement_id} into RISHI.")
                except Exception as exc:
                    logger.warning(f"[SCOPE_GUARD] Could not seed engagement into RISHI: {exc}")
                break

    async def _fetch_from_rishi(self, engagement_id: str) -> Optional[dict]:
        """Query RISHI for a single engagement record. Returns None on error."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{RISHI_BASE}/kavach/engagements/{engagement_id}")
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 404:
                    return None
                logger.warning(f"[SCOPE_GUARD] Unexpected RISHI status {resp.status_code} for {engagement_id}")
                return None
        except Exception as exc:
            logger.error(f"[SCOPE_GUARD] RISHI unreachable for engagement lookup: {exc}")
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, target: str, scan_type: str, engagement_id: Optional[str] = None) -> "GuardResult":
        """
        Synchronous wrapper — runs the async check in a new event loop if
        called from sync context, or delegates to check_async from async code.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Called from within an async context — caller should use check_async
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self.check_async(target, scan_type, engagement_id))
                    return future.result()
            else:
                return loop.run_until_complete(self.check_async(target, scan_type, engagement_id))
        except Exception as exc:
            logger.error(f"[SCOPE_GUARD] check() error: {exc}")
            return GuardResult(allowed=False, reason="SCOPE_CHECK_ERROR")

    async def check_async(
        self, target: str, scan_type: str, engagement_id: Optional[str] = None
    ) -> "GuardResult":
        """
        Async-native scope check.  Primary path used by PentestAgent and
        the Kavach orchestrator when running inside an async context.

        Order of operations:
          1. Identify which engagement covers this target (RISHI-first).
          2. Check engagement status — REVOKED = denied immediately.
          3. Check time window.
          4. Check technique allowlist.
          5. Return GuardResult with authorized_approvers and
             destructive_testing_allowed so callers have everything they need.
        """
        logger.info(f"🛡️  [SCOPE_GUARD] Checking: target={target} | type={scan_type}")
        now = datetime.now(timezone.utc)

        # ── Resolve candidate engagements ─────────────────────────────────
        # If caller already knows the engagement_id, go straight to RISHI.
        # Otherwise fall back to scanning the local seed list for target match.
        candidates: list[dict] = []

        if engagement_id:
            await self._seed_rishi_if_cold(engagement_id)
            rishi_record = await self._fetch_from_rishi(engagement_id)
            if rishi_record:
                candidates = [rishi_record]
        else:
            # Scan local list to find matching engagements, then verify each via RISHI
            for eng in self._local_engagements:
                if (
                    target in eng.get("targets", [])
                    or any(target.endswith("." + t) for t in eng.get("targets", []))
                ):
                    eid = eng["engagement_id"]
                    await self._seed_rishi_if_cold(eid)
                    rishi_record = await self._fetch_from_rishi(eid)
                    if rishi_record:
                        candidates.append(rishi_record)

        # ── Evaluate each candidate ───────────────────────────────────────
        for eng in candidates:
            eid = eng["engagement_id"]

            # Target in scope?
            targets_list = eng.get("targets", [])
            if not (
                target in targets_list
                or any(target.endswith("." + t) for t in targets_list)
            ):
                continue

            # 1. REVOKED check (new — Gap 3)
            if eng.get("status") == "REVOKED":
                reason = eng.get("revocation_reason", "ENGAGEMENT_REVOKED")
                logger.warning(
                    f"🛑 [SCOPE_GUARD] Engagement {eid} is REVOKED: {reason}"
                )
                return GuardResult(allowed=False, reason="ENGAGEMENT_REVOKED",
                                   engagement_id=eid)

            # 2. Time window
            try:
                start = datetime.fromisoformat(eng["start_time"]).replace(tzinfo=timezone.utc) \
                    if "+" not in eng["start_time"] and "Z" not in eng["start_time"] \
                    else datetime.fromisoformat(eng["start_time"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(eng["end_time"]).replace(tzinfo=timezone.utc) \
                    if "+" not in eng["end_time"] and "Z" not in eng["end_time"] \
                    else datetime.fromisoformat(eng["end_time"].replace("Z", "+00:00"))
            except (ValueError, KeyError) as exc:
                logger.error(f"[SCOPE_GUARD] Invalid time window for {eid}: {exc}")
                return GuardResult(allowed=False, reason="INVALID_ENGAGEMENT_TIME_WINDOW",
                                   engagement_id=eid)

            if not (start <= now <= end):
                logger.warning(f"🛑 [SCOPE_GUARD] {eid}: outside authorized window.")
                return GuardResult(allowed=False, reason="OUTSIDE_ENGAGEMENT_WINDOW",
                                   engagement_id=eid)

            # 3. Technique allowlist
            if scan_type not in eng.get("permitted_techniques", []):
                logger.warning(f"🛑 [SCOPE_GUARD] {eid}: technique '{scan_type}' not authorized.")
                return GuardResult(allowed=False, reason="TECHNIQUE_NOT_AUTHORIZED",
                                   engagement_id=eid)

            logger.info(f"✅ [SCOPE_GUARD] Authorization GRANTED (Engagement: {eid})")
            return GuardResult(
                allowed=True,
                reason="AUTHORIZED",
                engagement_id=eid,
                destructive_testing_allowed=eng.get("destructive_testing_allowed", False),
                authorized_approvers=eng.get("authorized_approvers", []),
            )

        # No matching active engagement found
        logger.warning(f"🛑 [SCOPE_GUARD] No active engagement covers target '{target}'.")
        return GuardResult(allowed=False, reason="NO_ACTIVE_ENGAGEMENT")
