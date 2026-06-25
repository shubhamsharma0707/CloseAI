"""
triage_engine.py — Kavach Phase 2.5: Finding Deduplication & Triage
====================================================================
Sits between Phase 2 (VulnScan) and Phase 3 (Pentest) in the orchestrator
pipeline. Responsibilities:

  1. Deduplicate: findings with the same (asset, normalized_type) key are
     merged into one TriagedFinding with a duplicate_count > 1.
  2. Severity re-derivation: if a finding carries a CVSS score, recompute
     severity from it (CVSS → CRITICAL/HIGH/MEDIUM/LOW) rather than trusting
     the scanner's raw label, which varies by tool.
  3. Confidence scoring: a simple 0.0–1.0 score based on whether the finding
     came from a real tool invocation vs. mock fallback and how many distinct
     observations contributed to it.
  4. Category normalization: maps free-form vuln type strings to canonical
     keys that the Phase 3 plugin registry uses for dispatch. This is the
     single place where scanner output strings map to plugin keys — do not
     duplicate this logic elsewhere.

Output shape — TriagedFinding.to_dict() keys (consumed by Phase 3, Phase 4,
Phase 5, and the reporting/remediation subsystems):
  type                str   canonical category key (e.g. "SQL_INJECTION")
  severity            str   final severity after CVSS re-derivation
  original_severity   str   scanner's raw severity label
  asset               str   target URL / host
  description         str   human-readable description
  confidence          float 0.0–1.0
  cve_id              str   CVE identifier or ""
  cvss_score          float or None
  duplicate_count     int   number of raw findings merged into this one
  severity_adjusted   bool  True if CVSS re-derivation changed the severity
  notes               list  extra context strings appended during triage

Stable dedup key:
  _normalize_key(asset, vuln_type) → deterministic string shared with the
  reporting / remediation subsystem (Phase 4 uses it to generate finding_id).
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("Kavach.TriageEngine")

# ---------------------------------------------------------------------------
# Severity ordering (higher index = higher severity)
# ---------------------------------------------------------------------------
SEVERITY_ORDER = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

# ---------------------------------------------------------------------------
# CVSS v3 → severity mapping (standard NVD breakpoints)
# ---------------------------------------------------------------------------
def _cvss_to_severity(score: float) -> str:
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    if score > 0.0:
        return "LOW"
    return "INFO"


# ---------------------------------------------------------------------------
# Category normalization
# ---------------------------------------------------------------------------
# Maps raw vuln type strings (scanner output) → canonical plugin-registry keys.
# Add entries here when new scanner templates are introduced; do NOT duplicate
# this mapping in individual plugins or the pentest agent.
_CATEGORY_MAP: dict[str, str] = {
    # SQL injection variants
    "sql_injection": "SQL_INJECTION",
    "sqli": "SQL_INJECTION",
    "sql injection": "SQL_INJECTION",
    "sql-injection": "SQL_INJECTION",
    "exposed_service": "EXPOSED_SERVICE",
    "exposed service": "EXPOSED_SERVICE",
    # XSS variants
    "xss": "XSS",
    "cross-site scripting": "XSS",
    "cross_site_scripting": "XSS",
    "reflected xss": "XSS",
    "stored xss": "XSS",
    # SSRF variants
    "ssrf": "SSRF",
    "server-side request forgery": "SSRF",
    "server_side_request_forgery": "SSRF",
    # Auth bypass / weak config
    "auth_bypass": "AUTH_BYPASS",
    "auth bypass": "AUTH_BYPASS",
    "authentication bypass": "AUTH_BYPASS",
    "weak_config": "WEAK_CONFIG",
    "weak config": "WEAK_CONFIG",
    "weak_configuration": "WEAK_CONFIG",
    "misconfiguration": "WEAK_CONFIG",
}


def _category_key(vuln_type: str) -> str:
    """
    Normalize a raw vuln type string to a canonical plugin-registry key.
    Unknown types are passed through as upper-cased strings so they can
    still be stored in a report even if no plugin handles them.
    """
    normalized = vuln_type.strip().lower()
    return _CATEGORY_MAP.get(normalized, vuln_type.strip().upper())


# ---------------------------------------------------------------------------
# Always-surface set: categories that should never be filtered out regardless
# of severity, because they indicate structural authorization / configuration
# failures that a human reviewer must always see.
# ---------------------------------------------------------------------------
ALWAYS_SURFACE: frozenset[str] = frozenset({
    "AUTH_BYPASS",
    "WEAK_CONFIG",
    "EXPOSED_SERVICE",
})


# ---------------------------------------------------------------------------
# Stable dedup / finding identifier
# ---------------------------------------------------------------------------
def _normalize_key(asset: str, vuln_type: str) -> str:
    """
    Build a deterministic, stable string key that uniquely identifies a
    (asset, vuln_category) pair.  Used for:
      - Deduplication within a single triage run
      - Generating stable finding_id across reports (sha256 prefix of this)

    The key is deliberately lowercase and stripped of protocol/port noise so
    'https://admin.corp:443/login' and 'admin.corp' for the same vuln type
    produce the same key.
    """
    # Strip protocol, port, trailing slash from asset
    clean_asset = re.sub(r"^https?://", "", asset.strip().lower())
    clean_asset = re.sub(r":\d+", "", clean_asset)
    clean_asset = clean_asset.rstrip("/")
    canon_type = _category_key(vuln_type)
    return f"{clean_asset}::{canon_type}"


def stable_finding_id(asset: str, vuln_type: str) -> str:
    """
    16-hex-char stable identifier for a (asset, vuln_type) pair.
    Used by Phase 4 and Phase 5 for remediation tracking.
    """
    key = _normalize_key(asset, vuln_type)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# TriagedFinding dataclass
# ---------------------------------------------------------------------------
@dataclass
class TriagedFinding:
    type: str                          # canonical category key
    severity: str                      # final severity
    original_severity: str             # raw scanner label
    asset: str                         # target URL / host
    description: str
    confidence: float                  # 0.0–1.0
    cve_id: str = ""
    cvss_score: Optional[float] = None
    duplicate_count: int = 1
    severity_adjusted: bool = False    # True if CVSS re-derivation changed severity
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "severity": self.severity,
            "original_severity": self.original_severity,
            "asset": self.asset,
            "description": self.description,
            "confidence": self.confidence,
            "cve_id": self.cve_id,
            "cvss_score": self.cvss_score,
            "duplicate_count": self.duplicate_count,
            "severity_adjusted": self.severity_adjusted,
            "notes": self.notes,
            "finding_id": stable_finding_id(self.asset, self.type),
        }


# ---------------------------------------------------------------------------
# TriageEngine
# ---------------------------------------------------------------------------
class TriageEngine:
    """
    Phase 2.5 triage processor.  Stateless — construct once, call run() per
    workflow.  Thread-safe (no mutable state outside run()).
    """

    def __init__(self):
        self.name = "TRIAGE_ENGINE"

    def run(self, vuln_data: dict) -> list[TriagedFinding]:
        """
        Accept the raw vuln_data dict from Phase 2 (VulnScanAgent) and return
        a list of deduplicated, enriched TriagedFinding objects ready for
        Phase 3 consumption.

        vuln_data expected shape:
          {"vulnerabilities": [...], "scan_depth": str, ...}

        Each vulnerability dict is expected to have at least:
          type, severity, asset, description
        Optional: cve_id, cvss_score
        """
        raw_vulns: list[dict] = vuln_data.get("vulnerabilities", [])
        logger.info(f"[{self.name}] Starting triage on {len(raw_vulns)} raw findings…")

        # ── Pass 1: Normalize + deduplicate ──────────────────────────────
        seen: dict[str, TriagedFinding] = {}

        for raw in raw_vulns:
            raw_type = raw.get("type", "UNKNOWN")
            asset = raw.get("asset", "unknown")
            raw_severity = raw.get("severity", "INFO").upper()
            description = raw.get("description", "")
            cve_id = raw.get("cve_id", "")
            cvss_score = raw.get("cvss_score", None)
            try:
                cvss_score = float(cvss_score) if cvss_score is not None else None
            except (ValueError, TypeError):
                cvss_score = None

            canon_type = _category_key(raw_type)
            key = _normalize_key(asset, raw_type)

            if key in seen:
                # Merge duplicate — keep higher severity, accumulate count
                existing = seen[key]
                existing.duplicate_count += 1
                if SEVERITY_ORDER.get(raw_severity, 0) > SEVERITY_ORDER.get(existing.severity, 0):
                    existing.notes.append(
                        f"Severity upgraded {existing.severity}→{raw_severity} "
                        f"due to duplicate observation."
                    )
                    existing.original_severity = raw_severity
                # Improve CVSS if new observation has a score and we don't
                if cvss_score and not existing.cvss_score:
                    existing.cvss_score = cvss_score
                if cve_id and not existing.cve_id:
                    existing.cve_id = cve_id
                logger.debug(f"[{self.name}] Merged duplicate: {key}")
                continue

            finding = TriagedFinding(
                type=canon_type,
                severity=raw_severity,
                original_severity=raw_severity,
                asset=asset,
                description=description,
                confidence=0.7,      # base confidence; adjusted below
                cve_id=cve_id,
                cvss_score=cvss_score,
                duplicate_count=1,
                severity_adjusted=False,
                notes=[],
            )
            seen[key] = finding

        # ── Pass 2: CVSS re-derivation + confidence scoring ───────────────
        results: list[TriagedFinding] = []

        for finding in seen.values():
            # CVSS re-derivation
            if finding.cvss_score is not None:
                cvss_sev = _cvss_to_severity(finding.cvss_score)
                if cvss_sev != finding.severity:
                    finding.notes.append(
                        f"Severity re-derived from CVSS {finding.cvss_score:.1f}: "
                        f"{finding.severity} → {cvss_sev}"
                    )
                    finding.severity = cvss_sev
                    finding.severity_adjusted = True

            # Confidence scoring heuristics
            confidence = 0.6  # base for a single scanner report
            if finding.cvss_score:
                confidence += 0.15   # CVSS score → more authoritative
            if finding.cve_id:
                confidence += 0.10   # known CVE → higher confidence
            if finding.duplicate_count > 1:
                confidence += min(0.10 * (finding.duplicate_count - 1), 0.15)
            if finding.type in ALWAYS_SURFACE:
                confidence = max(confidence, 0.75)  # structural issues always high-confidence
            finding.confidence = round(min(confidence, 1.0), 2)

            # Filter: drop INFO severity unless in ALWAYS_SURFACE set
            if finding.severity == "INFO" and finding.type not in ALWAYS_SURFACE:
                logger.debug(f"[{self.name}] Suppressed INFO finding: {finding.type} on {finding.asset}")
                continue

            results.append(finding)

        # Sort: CRITICAL first, then by confidence descending
        results.sort(
            key=lambda f: (
                -SEVERITY_ORDER.get(f.severity, 0),
                -f.confidence,
            )
        )

        logger.info(
            f"[{self.name}] Triage complete: {len(results)} findings "
            f"(from {len(raw_vulns)} raw, {len(seen) - len(results)} suppressed)"
        )
        return results
