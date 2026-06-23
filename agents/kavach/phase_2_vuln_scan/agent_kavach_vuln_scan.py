import logging
import asyncio
import subprocess
import shutil
import json

logger = logging.getLogger("Kavach.VulnScanAgent")

class VulnScanAgent:
    def __init__(self):
        self.name = "AGENT_KAVACH_VULNSCAN"

    async def scan_vulnerabilities(self, recon_data: dict) -> dict:
        """
        Assesses vulnerabilities on the discovered assets using nuclei or mock data.
        """
        target = recon_data.get("target", "unknown")
        logger.info(f"[{self.name}] Starting vulnerability scan on target: {target}")
        
        vulnerabilities = []
        
        if shutil.which("nuclei"):
            logger.info(f"[{self.name}] Running nuclei on {target}...")
            try:
                proc = await asyncio.create_subprocess_exec(
                    "nuclei", "-u", target, "-jsonl", "-silent",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, _ = await proc.communicate()
                if stdout:
                    for line in stdout.decode().split('\n'):
                        if not line.strip(): continue
                        try:
                            finding = json.loads(line)
                            vuln = {
                                "type": finding.get("info", {}).get("name", "Unknown"),
                                "severity": finding.get("info", {}).get("severity", "info").upper(),
                                "description": finding.get("info", {}).get("description", ""),
                                "asset": finding.get("host", target)
                            }
                            # Only keep interesting severities
                            if vuln["severity"] in ["MEDIUM", "HIGH", "CRITICAL"]:
                                vulnerabilities.append(vuln)
                                logger.warning(f"[{self.name}] Nuclei found {vuln['severity']} vuln: {vuln['type']}")
                        except json.JSONDecodeError:
                            pass
            except Exception as e:
                logger.error(f"[{self.name}] nuclei failed: {e}")
        else:
            logger.info(f"[{self.name}] nuclei not found, falling back to mock data.")
            await asyncio.sleep(1.5)
            if 3306 in recon_data.get("open_ports", []):
                logger.warning(f"[{self.name}] Exposed Database Port Detected: 3306")
                vulnerabilities.append({
                    "type": "EXPOSED_SERVICE",
                    "severity": "HIGH",
                    "description": "MySQL port 3306 is exposed to the public internet.",
                    "asset": target
                })
                
            for sub in recon_data.get("discovered_assets", []):
                if "admin" in sub:
                    logger.warning(f"[{self.name}] Exposed Admin Panel: {sub}")
                    vulnerabilities.append({
                        "type": "WEAK_CONFIG",
                        "severity": "CRITICAL",
                        "description": f"Admin panel exposed without IP restrictions on {sub}.",
                        "asset": sub
                    })

        if not vulnerabilities:
            logger.info(f"[{self.name}] No critical vulnerabilities found in initial scan.")
            
        return {
            "status": "COMPLETED",
            "vulnerabilities": vulnerabilities,
            "scan_depth": "Standard"
        }
