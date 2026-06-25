"""
agent_kavach_retest.py — Phase 5: Remediation Verification with Stable Finding IDs
====================================================================================
Feature Set C.2 (Remediation Tracking) upgrade.

Changes from the original implementation:
  - Each vulnerability being retested is identified by a stable finding_id
    (sha256 prefix of the normalized asset+type key) imported from the triage
    engine's stable_finding_id() — the same scheme used by the reporting agent,
    so finding timelines are consistent across all phases.
  - Retest result status per finding: RESOLVED | STILL_PRESENT | REGRESSED
      RESOLVED     : was OPEN, now confirmed fixed
      STILL_PRESENT: was OPEN, still open after retest
      REGRESSED    : was RESOLVED in a previous scan, now open again
  - Delta report is appended to the engagement's history JSONL alongside
    regular scan reports (append-only; reads previous history to detect
    REGRESSED status).
  - audit_client.log_audit_event called for start, per-finding result, and end.

Tool behavior (unchanged from original):
  - EXPOSED_SERVICE: nmap retest if available, mock sleep otherwise
  - Other types: nuclei retest if available, mock sleep otherwise
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone

logger = logging.getLogger("Kavach.RetestAgent")

# Shared stable_finding_id from triage engine
try:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from triage.triage_engine import stable_finding_id
    from authorization.audit_client import log_audit_event
except ImportError:
    def stable_finding_id(asset: str, vuln_type: str) -> str:
        import hashlib
        key = f"{asset.strip().lower()}::{vuln_type.strip().upper()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]
    def log_audit_event(*a, **kw): pass


def _load_engagement_history(history_dir: str, engagement_id: str) -> list[dict]:
    """
    Read all previous history records for an engagement from JSONL.
    Returns list of report history records (most recent last).
    """
    history_path = os.path.join(history_dir, f"{engagement_id}_history.jsonl")
    records = []
    if not os.path.exists(history_path):
        return records
    try:
        with open(history_path, "r") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception as exc:
        logger.error(f"[RetestAgent] Failed to read history: {exc}")
    return records


def _previously_resolved(history: list[dict], finding_id: str) -> bool:
    """
    Returns True if finding_id was marked RESOLVED in any prior report.
    Scans history in reverse (most recent first) to find the last known status.
    """
    for record in reversed(history):
        for f in record.get("findings", []):
            if f.get("finding_id") == finding_id:
                if f.get("status") == "RESOLVED":
                    return True
                break  # found in this report; status not RESOLVED; stop
    return False


class RetestAgent:
    def __init__(self):
        self.name = "AGENT_KAVACH_RETEST"
        self.reports_dir = os.path.join(os.path.dirname(__file__), "..", "phase_4_reporting", "reports")
        self.history_dir = os.path.join(self.reports_dir, "history")

    async def _retest_finding(self, vuln: dict) -> bool:
        """
        Returns True if the finding is STILL OPEN (not fixed), False if fixed.
        Uses real tools when available; falls back to pessimistic mock (assumes open).
        """
        asset = vuln.get("asset", "unknown")
        vuln_type = vuln.get("type", "")

        if vuln_type == "EXPOSED_SERVICE":
            if shutil.which("nmap"):
                proc = await asyncio.create_subprocess_exec(
                    "nmap", "-p", "3306", asset, "-oG", "-",
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                stdout, _ = await proc.communicate()
                return "open" in stdout.decode().lower()
            else:
                logger.info(f"[{self.name}] nmap not found — pessimistic: {asset} assumed STILL_PRESENT")
                await asyncio.sleep(0.5)
                return True  # pessimistic fallback

        else:
            if shutil.which("nuclei"):
                proc = await asyncio.create_subprocess_exec(
                    "nuclei", "-u", asset, "-jsonl", "-silent",
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                stdout, _ = await proc.communicate()
                for line in stdout.decode().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        finding = json.loads(line)
                        if finding.get("info", {}).get("name") == vuln_type:
                            return True  # still open
                    except Exception:
                        pass
                return False  # nuclei found nothing → assume resolved
            else:
                logger.info(f"[{self.name}] nuclei not found — pessimistic: {asset} assumed STILL_PRESENT")
                await asyncio.sleep(0.5)
                return True  # pessimistic fallback

    async def verify_fixes(
        self,
        previous_report_path: str,
        engagement_id: str = "ENG-UNKNOWN",
    ) -> dict:
        """
        Reads the previous JSON report, re-invokes verification tools to
        check if each finding is still open, and writes a delta report.

        Finding status lifecycle:
          OPEN → RESOLVED        (was open, now fixed)
          OPEN → STILL_PRESENT   (was open, still open)
          RESOLVED → REGRESSED   (was resolved in a prior scan, now open again)
        """
        log_audit_event(self.name, "PHASE_5_RETEST_START", {
            "report_path": previous_report_path,
            "engagement_id": engagement_id,
        })

        logger.info(f"[{self.name}] Initiating retest phase on: {previous_report_path}")

        if not os.path.exists(previous_report_path):
            logger.error(f"[{self.name}] Previous report not found: {previous_report_path}")
            return {"status": "ERROR", "message": "Report not found"}

        with open(previous_report_path, "r") as f:
            try:
                report = json.load(f)
            except json.JSONDecodeError:
                return {"status": "ERROR", "message": "Invalid JSON report"}

        # Infer engagement_id from report if not passed
        if engagement_id == "ENG-UNKNOWN":
            engagement_id = report.get("engagement_id", "ENG-UNKNOWN")

        # Load history for REGRESSED detection
        history = _load_engagement_history(self.history_dir, engagement_id)

        vulns = report.get("vulnerabilities_found", [])
        still_open = []
        fixed = []
        regressed = []

        for vuln in vulns:
            asset = vuln.get("asset", "unknown")
            vuln_type = vuln.get("type", "")
            fid = vuln.get("finding_id") or stable_finding_id(asset, vuln_type)
            was_previously_resolved = _previously_resolved(history, fid)

            logger.info(f"[{self.name}] Retesting [{vuln_type}] on {asset} (id={fid})…")
            is_still_open = await self._retest_finding(vuln)

            finding_with_id = {**vuln, "finding_id": fid}

            if is_still_open:
                if was_previously_resolved:
                    finding_with_id["status"] = "REGRESSED"
                    regressed.append(finding_with_id)
                    logger.warning(f"[{self.name}] 🔴 REGRESSED: {fid} ({vuln_type} on {asset})")
                else:
                    finding_with_id["status"] = "STILL_PRESENT"
                    still_open.append(finding_with_id)
                    logger.warning(f"[{self.name}] 🟡 STILL_PRESENT: {fid} ({vuln_type} on {asset})")
            else:
                finding_with_id["status"] = "RESOLVED"
                fixed.append(finding_with_id)
                logger.info(f"[{self.name}] ✅ RESOLVED: {fid} ({vuln_type} on {asset})")

            log_audit_event(self.name, "RETEST_FINDING_RESULT", {
                "finding_id": fid,
                "vuln_type": vuln_type,
                "asset": asset,
                "status": finding_with_id["status"],
                "engagement_id": engagement_id,
            })

        now = datetime.now(timezone.utc).isoformat()
        delta_report = {
            "report_type": "RETEST_DELTA",
            "original_report_id": report.get("report_id"),
            "engagement_id": engagement_id,
            "retest_time": now,
            "summary": {
                "resolved": len(fixed),
                "still_present": len(still_open),
                "regressed": len(regressed),
                "total_retested": len(vulns),
            },
            "fixed": fixed,
            "still_open": still_open,
            "regressed": regressed,
        }

        # Save delta report JSON
        delta_path = previous_report_path.replace(".json", "_retest_delta.json")
        try:
            with open(delta_path, "w") as f:
                json.dump(delta_report, f, indent=2)
            logger.info(f"[{self.name}] Delta report saved to {delta_path}")
        except Exception as exc:
            logger.error(f"[{self.name}] Failed to save delta report: {exc}")

        # Append delta to engagement history JSONL for trend analysis (C.3)
        history_record = {
            "report_id": f"{report.get('report_id')}_retest",
            "engagement_id": engagement_id,
            "generated_at": now,
            "report_type": "RETEST_DELTA",
            "findings": (
                [{**f, "status": "RESOLVED"}  for f in fixed] +
                [{**f, "status": "STILL_PRESENT"} for f in still_open] +
                [{**f, "status": "REGRESSED"} for f in regressed]
            ),
        }
        history_path = os.path.join(self.history_dir, f"{engagement_id}_history.jsonl")
        try:
            with open(history_path, "a") as fh:
                fh.write(json.dumps(history_record) + "\n")
        except Exception as exc:
            logger.error(f"[{self.name}] Failed to append retest to history: {exc}")

        log_audit_event(self.name, "PHASE_5_RETEST_END", {
            "engagement_id": engagement_id,
            "resolved": len(fixed),
            "still_present": len(still_open),
            "regressed": len(regressed),
        })

        return delta_report
