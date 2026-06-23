import logging
import asyncio
import json
import os
from datetime import datetime, timezone

logger = logging.getLogger("Kavach.ReportingAgent")

class ReportingAgent:
    def __init__(self):
        self.name = "AGENT_KAVACH_REPORTING"
        self.reports_dir = os.path.join(os.path.dirname(__file__), "reports")
        if not os.path.exists(self.reports_dir):
            os.makedirs(self.reports_dir)

    async def generate_report(self, target: str, recon_data: dict, vuln_data: dict, pentest_data: dict) -> dict:
        """
        Compiles the findings from Phase 1-3 into a clear, actionable security report.
        """
        logger.info(f"[{self.name}] Generating final security report for {target}...")
        
        await asyncio.sleep(1) # Simulate generation time
        
        report = {
            "report_id": f"KAVACH-{int(datetime.now(timezone.utc).timestamp())}",
            "target": target,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "executive_summary": "Security assessment completed. Please review critical findings.",
            "reconnaissance_summary": recon_data,
            "vulnerabilities_found": vuln_data.get("vulnerabilities", []),
            "exploitation_results": pentest_data.get("exploited", []),
            "remediation_recommendations": []
        }
        
        # Simple rule-based recommendations
        for vuln in report["vulnerabilities_found"]:
            if vuln["type"] == "EXPOSED_SERVICE":
                report["remediation_recommendations"].append(
                    f"Restrict access to {vuln['asset']} using security groups/firewall rules. Implement VPN/Zero Trust access."
                )
            if vuln["type"] == "WEAK_CONFIG":
                report["remediation_recommendations"].append(
                    f"Audit configuration on {vuln['asset']}. Enforce MFA and IP whitelisting for admin interfaces."
                )
                
        # Save report to disk
        report_path = os.path.join(self.reports_dir, f"{report['report_id']}.json")
        try:
            with open(report_path, "w") as f:
                json.dump(report, f, indent=2)
            logger.info(f"[{self.name}] Report saved securely to {report_path}")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to save report: {e}")
            
        return {
            "status": "COMPLETED",
            "report_id": report["report_id"],
            "report_path": report_path
        }
