from dataclasses import dataclass
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger("Kavach.ScopeGuard")

@dataclass
class GuardResult:
    allowed: bool
    reason: str
    engagement_id: Optional[str] = None

class ScopeGuard:
    def __init__(self):
        # Simulated database of authorized engagements
        self.engagements = self._load_engagements()

    def _load_engagements(self):
        # A hardcoded engagement representing a valid signed Rules of Engagement (RoE)
        # In a production setting, this would be fetched from an authorization database.
        return [
            {
                "engagement_id": "ENG-2026-001",
                "client": "CloseAI Internal",
                "targets": [
                    "internal-portal.corp.closeai.com",
                    "api.internal-portal.corp.closeai.com",
                    "dev.internal-portal.corp.closeai.com",
                    "admin.internal-portal.corp.closeai.com"
                ],
                "start_time": "2026-01-01T00:00:00",
                "end_time": "2026-12-31T23:59:59",
                "permitted_techniques": ["RECON", "VULN_SCAN", "FULL_PENTEST"]
            }
        ]

    def check(self, target: str, scan_type: str) -> GuardResult:
        logger.info(f"🛡️  [SCOPE_GUARD] Checking authorization for target: {target} | type: {scan_type}")
        now = datetime.utcnow()

        for eng in self.engagements:
            # 1. Target-in-scope check
            if target in eng["targets"] or any(target.endswith("." + t) for t in eng["targets"]):
                # 2. Engagement window check
                start = datetime.fromisoformat(eng["start_time"])
                end = datetime.fromisoformat(eng["end_time"])
                if not (start <= now <= end):
                    logger.warning(f"🛑 [SCOPE_GUARD] Target in scope, but outside authorized engagement window.")
                    return GuardResult(allowed=False, reason="OUTSIDE_ENGAGEMENT_WINDOW")
                
                # 3. Technique allowlist check
                if scan_type not in eng["permitted_techniques"]:
                    logger.warning(f"🛑 [SCOPE_GUARD] Technique '{scan_type}' exceeds authorized level.")
                    return GuardResult(allowed=False, reason="TECHNIQUE_NOT_AUTHORIZED")
                
                logger.info(f"✅ [SCOPE_GUARD] Authorization GRANTED (Engagement: {eng['engagement_id']})")
                return GuardResult(allowed=True, reason="AUTHORIZED", engagement_id=eng["engagement_id"])
        
        logger.warning(f"🛑 [SCOPE_GUARD] Target '{target}' is NOT covered by any active engagement.")
        return GuardResult(allowed=False, reason="NO_ACTIVE_ENGAGEMENT")
