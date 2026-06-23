import logging
import asyncio
import json
import os
from datetime import datetime, timezone

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

logger = logging.getLogger("Kavach.ReportingAgent")

class ReportingAgent:
    def __init__(self):
        self.name = "AGENT_KAVACH_REPORTING"
        self.reports_dir = os.path.join(os.path.dirname(__file__), "reports")
        if not os.path.exists(self.reports_dir):
            os.makedirs(self.reports_dir)

    def _generate_pdf(self, report: dict, pdf_path: str):
        if not REPORTLAB_AVAILABLE:
            logger.warning(f"[{self.name}] reportlab not installed. Skipping PDF generation.")
            return

        doc = SimpleDocTemplate(pdf_path, pagesize=letter)
        styles = getSampleStyleSheet()
        flowables = []

        flowables.append(Paragraph(f"Kavach Security Report: {report['target']}", styles['Title']))
        flowables.append(Spacer(1, 12))
        
        flowables.append(Paragraph(f"<b>Report ID:</b> {report['report_id']}", styles['Normal']))
        flowables.append(Paragraph(f"<b>Generated At:</b> {report['generated_at']}", styles['Normal']))
        flowables.append(Spacer(1, 12))
        
        flowables.append(Paragraph("Executive Summary", styles['Heading2']))
        flowables.append(Paragraph(report['executive_summary'], styles['Normal']))
        flowables.append(Spacer(1, 12))

        flowables.append(Paragraph("Reconnaissance", styles['Heading2']))
        recon = report.get("reconnaissance_summary", {})
        flowables.append(Paragraph(f"<b>Discovered Assets:</b> {', '.join(recon.get('discovered_assets', []))}", styles['Normal']))
        flowables.append(Paragraph(f"<b>Open Ports:</b> {', '.join(map(str, recon.get('open_ports', [])))}", styles['Normal']))
        flowables.append(Spacer(1, 12))

        flowables.append(Paragraph("Vulnerabilities Found", styles['Heading2']))
        for vuln in report.get("vulnerabilities_found", []):
            flowables.append(Paragraph(f"• <b>[{vuln.get('severity', 'INFO')}]</b> {vuln.get('type', 'Unknown')} on {vuln.get('asset', 'Unknown')}", styles['Normal']))
            flowables.append(Paragraph(f"  <i>{vuln.get('description', '')}</i>", styles['Normal']))
            flowables.append(Spacer(1, 6))

        flowables.append(Spacer(1, 12))
        flowables.append(Paragraph("Remediation Recommendations", styles['Heading2']))
        for rec in report.get("remediation_recommendations", []):
            flowables.append(Paragraph(f"• {rec}", styles['Normal']))

        try:
            doc.build(flowables)
            logger.info(f"[{self.name}] PDF report saved securely to {pdf_path}")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to build PDF: {e}")

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
                
        # Save JSON report to disk
        json_path = os.path.join(self.reports_dir, f"{report['report_id']}.json")
        try:
            with open(json_path, "w") as f:
                json.dump(report, f, indent=2)
            logger.info(f"[{self.name}] JSON report saved securely to {json_path}")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to save JSON report: {e}")

        # Save PDF report to disk
        pdf_path = os.path.join(self.reports_dir, f"{report['report_id']}.pdf")
        self._generate_pdf(report, pdf_path)
            
        return {
            "status": "COMPLETED",
            "report_id": report["report_id"],
            "report_path": json_path,
            "pdf_report_path": pdf_path
        }
