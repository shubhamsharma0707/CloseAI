"""
agent_kavach_reporting.py — Phase 4: Risk-Prioritized Reporting & Remediation Tracking
========================================================================================
Feature Set C.1 (Risk-Prioritized Output) and C.2 (Remediation Tracking).

Changes from the original:
  - generate_report() now accepts engagement_id and persists report history per
    engagement as append-only JSONL (parallel to RISHI's audit ledger pattern).
  - Findings sorted and grouped by severity (CRITICAL → HIGH → MEDIUM → LOW → INFO)
    then by confidence descending — triage engine already computes both values,
    reporting just surfaces them.
  - Executive summary is computed from the actual findings (counts by severity,
    top CRITICAL/HIGH named, overall risk posture statement) instead of the
    static placeholder string.
  - Each finding in the report carries its full triage metadata: confidence,
    cve_id, cvss_score, severity_adjusted, notes, finding_id.
  - Each finding gets a stable finding_id = stable_finding_id(asset, type) from
    the triage engine's key function — the same identifier scheme used by the
    retest agent in Phase 5 so remediation timelines are per-finding, not
    per-report.
  - Remediation recommendations are now keyed to canonical type categories.
  - generate_trend_summary(engagement_id) is added in Commit 9 (C.3).
"""

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# Shared stable_finding_id from triage engine — single source of truth
try:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from triage.triage_engine import stable_finding_id, SEVERITY_ORDER
except ImportError:
    def stable_finding_id(asset: str, vuln_type: str) -> str:
        import hashlib
        key = f"{asset.strip().lower()}::{vuln_type.strip().upper()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]
    SEVERITY_ORDER = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

logger = logging.getLogger("Kavach.ReportingAgent")

# ---------------------------------------------------------------------------
# Remediation recommendations — keyed to canonical triage category keys.
# Add new entries here when new plugin categories are added.
# ---------------------------------------------------------------------------
_REMEDIATION_MAP = {
    "EXPOSED_SERVICE": (
        "Restrict access using security groups/firewall rules. "
        "Implement VPN/Zero Trust access for sensitive services."
    ),
    "WEAK_CONFIG": (
        "Audit configuration. Enforce MFA and IP whitelisting for admin interfaces. "
        "Review firewall rules and disable unnecessary features."
    ),
    "SQL_INJECTION": (
        "Use parameterized queries / prepared statements throughout the codebase. "
        "Apply least-privilege database accounts. Enable WAF rules for SQLi patterns."
    ),
    "XSS": (
        "Apply output encoding (HTML-escape) on all user-controlled data. "
        "Implement Content-Security-Policy (CSP) headers. Use framework-native XSS mitigations."
    ),
    "SSRF": (
        "Validate and allowlist outbound destinations server-side. "
        "Block cloud metadata endpoints (169.254.169.254) at the network layer. "
        "Reject private/loopback IP ranges in user-supplied URLs."
    ),
    "AUTH_BYPASS": (
        "Enforce authentication middleware consistently on all protected routes. "
        "Rotate any compromised credentials. "
        "Implement proper JWT validation including algorithm pinning."
    ),
}

# Overall risk posture thresholds
_POSTURE_CRITICAL_THRESHOLD = 1
_POSTURE_HIGH_THRESHOLD = 3


def _compute_executive_summary(findings: list[dict]) -> str:
    """
    Compute an executive summary string from actual findings.
    Never returns a static placeholder — always reflects real data.
    """
    if not findings:
        return (
            "Security assessment completed. No medium/high/critical findings identified. "
            "The target appears well-hardened for the scope assessed."
        )

    counts: dict[str, int] = defaultdict(int)
    for f in findings:
        counts[f.get("severity", "INFO")] += 1

    total = len(findings)
    crit_count = counts.get("CRITICAL", 0)
    high_count = counts.get("HIGH", 0)

    # Severity summary line
    parts = []
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
        if counts[sev]:
            parts.append(f"{counts[sev]} {sev}")
    severity_summary = ", ".join(parts)

    # Name top CRITICAL/HIGH findings explicitly
    top_named = []
    for f in findings:
        if f.get("severity") in ("CRITICAL", "HIGH") and len(top_named) < 3:
            top_named.append(f"{f.get('type', 'Unknown')} on {f.get('asset', 'unknown')}")
    top_str = "; ".join(top_named) if top_named else "none"

    # Overall posture
    if crit_count >= _POSTURE_CRITICAL_THRESHOLD:
        posture = "CRITICAL — immediate remediation required before further use."
    elif high_count >= _POSTURE_HIGH_THRESHOLD:
        posture = "HIGH — significant vulnerabilities present; remediation required."
    elif high_count > 0:
        posture = "MODERATE-HIGH — actionable vulnerabilities require prompt remediation."
    elif counts["MEDIUM"] > 0:
        posture = "MODERATE — medium-severity issues require scheduled remediation."
    else:
        posture = "LOW — minor issues only; monitor and remediate in next cycle."

    return (
        f"Assessment identified {total} finding(s): {severity_summary}. "
        f"Key findings: {top_str}. "
        f"Overall risk posture: {posture}"
    )


class ReportingAgent:
    def __init__(self):
        self.name = "AGENT_KAVACH_REPORTING"
        self.reports_dir = os.path.join(os.path.dirname(__file__), "reports")
        self.history_dir = os.path.join(os.path.dirname(__file__), "reports", "history")
        os.makedirs(self.reports_dir, exist_ok=True)
        os.makedirs(self.history_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal: findings preparation
    # ------------------------------------------------------------------

    def _prepare_findings(self, raw_findings: list[dict]) -> list[dict]:
        """
        Sort by severity (highest first) then confidence descending.
        Attach stable finding_id and initialise remediation tracking status.
        """
        enriched = []
        for f in raw_findings:
            asset = f.get("asset", "unknown")
            vuln_type = f.get("type", "UNKNOWN")
            fid = f.get("finding_id") or stable_finding_id(asset, vuln_type)
            entry = {
                **f,
                "finding_id": fid,
                "status": "OPEN",           # Initial status; updated by RetestAgent
                "remediation_status": "OPEN",
            }
            enriched.append(entry)

        enriched.sort(key=lambda f: (
            -SEVERITY_ORDER.get(f.get("severity", "INFO"), 0),
            -f.get("confidence", 0.5),
        ))
        return enriched

    def _build_recommendations(self, findings: list[dict]) -> list[str]:
        """Generate deduplicated remediation recommendations."""
        seen = set()
        recs = []
        for f in findings:
            canon_type = f.get("type", "UNKNOWN")
            if canon_type not in seen:
                rec = _REMEDIATION_MAP.get(canon_type)
                if rec:
                    recs.append(f"[{canon_type}] {rec}")
                    seen.add(canon_type)
        return recs

    # ------------------------------------------------------------------
    # PDF generation (upgraded to reflect grouped/enriched structure)
    # ------------------------------------------------------------------

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
        flowables.append(Paragraph(f"<b>Engagement:</b> {report.get('engagement_id', 'N/A')}", styles['Normal']))
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

        # Group by severity
        by_severity: dict[str, list[dict]] = defaultdict(list)
        for f in report.get("vulnerabilities_found", []):
            by_severity[f.get("severity", "INFO")].append(f)

        flowables.append(Paragraph("Vulnerabilities Found (Risk-Prioritized)", styles['Heading2']))
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            if sev not in by_severity:
                continue
            flowables.append(Paragraph(f"— {sev} —", styles['Heading3']))
            for vuln in by_severity[sev]:
                conf = vuln.get("confidence", "")
                cve  = f" | CVE: {vuln['cve_id']}" if vuln.get("cve_id") else ""
                cvss = f" | CVSS: {vuln['cvss_score']}" if vuln.get("cvss_score") else ""
                adj  = " [severity adjusted from CVSS]" if vuln.get("severity_adjusted") else ""
                fid  = vuln.get("finding_id", "")
                flowables.append(Paragraph(
                    f"• <b>[{vuln.get('severity', 'INFO')}]</b> {vuln.get('type', 'Unknown')} "
                    f"on {vuln.get('asset', 'Unknown')}"
                    f" (conf={conf}{cve}{cvss}{adj}) [ID: {fid}]",
                    styles['Normal']
                ))
                flowables.append(Paragraph(f"  <i>{vuln.get('description', '')}</i>", styles['Normal']))
                if vuln.get("notes"):
                    for note in vuln["notes"]:
                        flowables.append(Paragraph(f"  ↳ {note}", styles['Normal']))
                flowables.append(Spacer(1, 4))

        flowables.append(Spacer(1, 12))
        flowables.append(Paragraph("Remediation Recommendations", styles['Heading2']))
        for rec in report.get("remediation_recommendations", []):
            flowables.append(Paragraph(f"• {rec}", styles['Normal']))

        try:
            doc.build(flowables)
            logger.info(f"[{self.name}] PDF report saved to {pdf_path}")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to build PDF: {e}")

    # ------------------------------------------------------------------
    # Remediation history (C.2) — append-only JSONL per engagement
    # ------------------------------------------------------------------

    def _persist_report_history(self, engagement_id: str, report: dict, findings: list[dict]):
        """
        Append a compact history record to {engagement_id}_history.jsonl.
        Used by generate_trend_summary() and RetestAgent for remediation tracking.
        """
        history_record = {
            "report_id": report["report_id"],
            "engagement_id": engagement_id,
            "generated_at": report["generated_at"],
            "findings": [
                {
                    "finding_id": f.get("finding_id"),
                    "type": f.get("type"),
                    "severity": f.get("severity"),
                    "asset": f.get("asset"),
                    "confidence": f.get("confidence"),
                    "cve_id": f.get("cve_id", ""),
                    "cvss_score": f.get("cvss_score"),
                    "status": f.get("status", "OPEN"),
                }
                for f in findings
            ],
        }
        history_path = os.path.join(self.history_dir, f"{engagement_id}_history.jsonl")
        try:
            with open(history_path, "a") as fh:
                fh.write(json.dumps(history_record) + "\n")
            logger.info(f"[{self.name}] Report history appended for engagement {engagement_id}")
        except Exception as exc:
            logger.error(f"[{self.name}] Failed to persist report history: {exc}")

    # ------------------------------------------------------------------
    # Main generate_report (C.1 + C.2)
    # ------------------------------------------------------------------

    async def generate_report(
        self,
        target: str,
        recon_data: dict,
        vuln_data: dict,
        pentest_data: dict,
        engagement_id: str = "ENG-UNKNOWN",
    ) -> dict:
        """
        Compiles findings from Phase 1–3 into a risk-prioritized security report.

        Changes from original:
          - Findings sorted by severity (CRITICAL first) then confidence descending
          - Executive summary computed from actual findings (not a static string)
          - Full triage metadata surfaced per finding (confidence, cve_id, cvss_score,
            severity_adjusted, notes, finding_id)
          - Report history persisted to {engagement_id}_history.jsonl (append-only)
        """
        logger.info(f"[{self.name}] Generating report for {target} (engagement: {engagement_id})…")
        await asyncio.sleep(0)  # yield control; remove asyncio.sleep(1) simulation

        raw_findings = vuln_data.get("vulnerabilities", [])
        findings = self._prepare_findings(raw_findings)
        recommendations = self._build_recommendations(findings)
        executive_summary = _compute_executive_summary(findings)

        report = {
            "report_id": f"KAVACH-{int(datetime.now(timezone.utc).timestamp())}",
            "target": target,
            "engagement_id": engagement_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "executive_summary": executive_summary,
            "risk_posture": {
                "critical": sum(1 for f in findings if f.get("severity") == "CRITICAL"),
                "high":     sum(1 for f in findings if f.get("severity") == "HIGH"),
                "medium":   sum(1 for f in findings if f.get("severity") == "MEDIUM"),
                "low":      sum(1 for f in findings if f.get("severity") == "LOW"),
                "info":     sum(1 for f in findings if f.get("severity") == "INFO"),
                "total":    len(findings),
            },
            "reconnaissance_summary": recon_data,
            "vulnerabilities_found": findings,
            "exploitation_results": pentest_data.get("exploited", []),
            "remediation_recommendations": recommendations,
        }

        # Save JSON report
        json_path = os.path.join(self.reports_dir, f"{report['report_id']}.json")
        try:
            with open(json_path, "w") as f:
                json.dump(report, f, indent=2)
            logger.info(f"[{self.name}] JSON report saved to {json_path}")
        except Exception as exc:
            logger.error(f"[{self.name}] Failed to save JSON report: {exc}")

        # Save PDF
        pdf_path = os.path.join(self.reports_dir, f"{report['report_id']}.pdf")
        self._generate_pdf(report, pdf_path)

        # Persist engagement history (C.2)
        self._persist_report_history(engagement_id, report, findings)

        return {
            "status": "COMPLETED",
            "report_id": report["report_id"],
            "report_path": json_path,
            "pdf_report_path": pdf_path,
            "engagement_id": engagement_id,
            "risk_posture": report["risk_posture"],
        }

    # ------------------------------------------------------------------
    # C.3 Trend Analysis — computed purely from persisted history,
    #     no re-scanning required.
    # ------------------------------------------------------------------

    def generate_trend_summary(self, engagement_id: str) -> dict:
        """
        Read the engagement's report history JSONL and compute:
          1. Open findings over time (timeline of total OPEN counts per report)
          2. Mean time to remediation (MTTR) by severity
          3. Recurrence rate (findings with status REGRESSED in any delta report)

        All data comes from {engagement_id}_history.jsonl written by:
          - ReportingAgent._persist_report_history()   (scan reports)
          - RetestAgent.verify_fixes()                  (retest deltas)

        Returns a dict suitable for logging / API response / embedding in a
        management dashboard.  Does not require any network calls or re-scans.
        """
        history_path = os.path.join(self.history_dir, f"{engagement_id}_history.jsonl")
        if not os.path.exists(history_path):
            return {
                "engagement_id": engagement_id,
                "error": f"No history found for engagement {engagement_id}",
            }

        records: list[dict] = []
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
            logger.error(f"[{self.name}] generate_trend_summary read error: {exc}")
            return {"engagement_id": engagement_id, "error": str(exc)}

        if not records:
            return {"engagement_id": engagement_id, "error": "History file is empty"}

        # ── 1. Open findings timeline ──────────────────────────────────────
        timeline: list[dict] = []
        for record in records:
            if record.get("report_type") == "RETEST_DELTA":
                continue   # Use scan reports for the timeline, not delta reports
            open_count = sum(
                1 for f in record.get("findings", [])
                if f.get("status", "OPEN") == "OPEN"
            )
            timeline.append({
                "report_id": record.get("report_id"),
                "generated_at": record.get("generated_at"),
                "open_findings": open_count,
                "total_findings": len(record.get("findings", [])),
            })

        # ── 2. Mean time to remediation (MTTR) by severity ───────────────
        # Match RESOLVED findings in delta reports back to their original
        # scan timestamp to compute the time delta.
        # Build: finding_id → {severity, first_seen_at}
        finding_first_seen: dict[str, dict] = {}
        for record in records:
            if record.get("report_type") == "RETEST_DELTA":
                continue
            seen_at = record.get("generated_at", "")
            for f in record.get("findings", []):
                fid = f.get("finding_id")
                if fid and fid not in finding_first_seen:
                    finding_first_seen[fid] = {
                        "severity": f.get("severity", "INFO"),
                        "first_seen_at": seen_at,
                    }

        # Collect resolution times from delta reports
        mttr_by_severity: dict[str, list[float]] = defaultdict(list)
        for record in records:
            if record.get("report_type") != "RETEST_DELTA":
                continue
            resolved_at = record.get("generated_at", "")
            for f in record.get("findings", []):
                if f.get("status") != "RESOLVED":
                    continue
                fid = f.get("finding_id")
                if not fid or fid not in finding_first_seen:
                    continue
                first_info = finding_first_seen[fid]
                try:
                    t0 = datetime.fromisoformat(first_info["first_seen_at"].replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(resolved_at.replace("Z", "+00:00"))
                    delta_hours = (t1 - t0).total_seconds() / 3600.0
                    if delta_hours >= 0:
                        mttr_by_severity[first_info["severity"]].append(delta_hours)
                except (ValueError, TypeError):
                    pass

        mttr_summary: dict[str, float | None] = {}
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            times = mttr_by_severity.get(sev, [])
            mttr_summary[sev] = round(sum(times) / len(times), 2) if times else None

        # ── 3. Recurrence rate ────────────────────────────────────────────
        regressed_ids: set[str] = set()
        for record in records:
            if record.get("report_type") != "RETEST_DELTA":
                continue
            for f in record.get("findings", []):
                if f.get("status") == "REGRESSED" and f.get("finding_id"):
                    regressed_ids.add(f["finding_id"])

        total_unique_findings = len(finding_first_seen)
        recurrence_rate = (
            round(len(regressed_ids) / total_unique_findings, 3)
            if total_unique_findings > 0 else 0.0
        )

        summary = {
            "engagement_id": engagement_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_reports_in_history": len(records),
            "open_findings_timeline": timeline,
            "mean_time_to_remediation_hours_by_severity": mttr_summary,
            "recurrence": {
                "regressed_finding_ids": sorted(regressed_ids),
                "regressed_count": len(regressed_ids),
                "total_unique_findings": total_unique_findings,
                "recurrence_rate": recurrence_rate,
            },
        }

        logger.info(
            f"[{self.name}] Trend summary for {engagement_id}: "
            f"{len(timeline)} scan reports, "
            f"{len(regressed_ids)} regressions, "
            f"CRITICAL MTTR={mttr_summary.get('CRITICAL')}h"
        )
        return summary

