import logging
import asyncio
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

logger = logging.getLogger("Kavach.RetestAgent")

class RetestAgent:
    def __init__(self):
        self.name = "AGENT_KAVACH_RETEST"

    async def verify_fixes(self, previous_report_path: str) -> dict:
        """
        Reads the previous JSON report, re-invokes tools to check if vulns are open,
        and writes a delta report.
        """
        logger.info(f"[{self.name}] Initiating retest phase based on report: {previous_report_path}")
        
        if not os.path.exists(previous_report_path):
            logger.error(f"[{self.name}] Previous report not found at {previous_report_path}")
            return {"status": "ERROR", "message": "Report not found"}
            
        with open(previous_report_path, "r") as f:
            try:
                report = json.load(f)
            except json.JSONDecodeError:
                return {"status": "ERROR", "message": "Invalid JSON report"}
                
        vulns = report.get("vulnerabilities_found", [])
        still_open = []
        fixed = []
        
        for vuln in vulns:
            asset = vuln.get("asset", "unknown")
            vuln_type = vuln.get("type", "")
            
            logger.info(f"[{self.name}] Retesting {vuln_type} on {asset}...")
            
            if vuln_type == "EXPOSED_SERVICE":
                if shutil.which("nmap"):
                    proc = await asyncio.create_subprocess_exec(
                        "nmap", "-p", "3306", asset, "-oG", "-",
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    stdout, _ = await proc.communicate()
                    if "open" in stdout.decode().lower():
                        still_open.append(vuln)
                    else:
                        fixed.append(vuln)
                else:
                    await asyncio.sleep(1)
                    still_open.append(vuln)
            else:
                if shutil.which("nuclei"):
                    proc = await asyncio.create_subprocess_exec(
                        "nuclei", "-u", asset, "-jsonl", "-silent",
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    stdout, _ = await proc.communicate()
                    is_open = False
                    for line in stdout.decode().split("\n"):
                        if not line.strip(): continue
                        try:
                            finding = json.loads(line)
                            if finding.get("info", {}).get("name") == vuln_type:
                                is_open = True
                        except Exception:
                            pass
                    if is_open:
                        still_open.append(vuln)
                    else:
                        fixed.append(vuln)
                else:
                    await asyncio.sleep(1)
                    still_open.append(vuln)
                    
        delta_report = {
            "original_report_id": report.get("report_id"),
            "retest_time": datetime.now(timezone.utc).isoformat(),
            "fixed": fixed,
            "still_open": still_open
        }
        
        delta_path = previous_report_path.replace(".json", "_retest_delta.json")
        try:
            with open(delta_path, "w") as f:
                json.dump(delta_report, f, indent=2)
            logger.info(f"[{self.name}] Retest complete. Delta report saved to {delta_path}")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to save delta report: {e}")
            
        return delta_report
