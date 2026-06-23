import logging
import asyncio

logger = logging.getLogger("Kavach.VulnScanAgent")

class VulnScanAgent:
    def __init__(self):
        self.name = "AGENT_KAVACH_VULNSCAN"

    async def scan_vulnerabilities(self, recon_data: dict) -> dict:
        """
        Simulates assessing vulnerabilities on the discovered assets.
        """
        target = recon_data.get("target", "unknown")
        logger.info(f"[{self.name}] Starting vulnerability scan on target: {target}")
        
        await asyncio.sleep(1.5)
        
        vulnerabilities = []
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
