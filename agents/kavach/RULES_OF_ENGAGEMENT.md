# Kavach — Rules of Engagement (RoE)

## 1. Introduction
Kavach is the Chief Information Security Officer (CISO) orchestrator within the CloseAI Multi-Agent System. It executes continuous security monitoring, vulnerability scanning, and ethical penetration testing. To ensure the safety, legality, and stability of CloseAI's infrastructure, Kavach adheres to strict Rules of Engagement (RoE).

## 2. Strict Sandboxing & Scope Guard
Kavach is constrained by the **Scope Guard** middleware (`agents/kavach/authorization/scope_guard.py`).
- **Target Allowlist**: Kavach will immediately abort any workflow targeting a domain or IP not explicitly listed in an active, digitally signed engagement.
- **Time Windows**: Security scanning is strictly bound by start and end timestamps. Scans attempted outside these windows are automatically rejected.
- **Technique Constraints**: Operations are tiered (e.g., RECON_ONLY, VULN_SCAN, FULL_PENTEST). Kavach cannot escalate its techniques beyond the engagement's permitted level.

## 3. Human-Approval Locks
To prevent unintended disruption or data modification during Phase 3 (Penetration Testing):
- **High-Risk Actions**: Any exploit simulation targeting vulnerabilities classified as `HIGH` or `CRITICAL` severity automatically pauses execution.
- **Explicit Authorization**: Resuming the workflow requires an explicit human override (`auto_approve`).
- **Cryptographic Verification**: In production, approval decisions are transmitted via HMAC-signed payloads, which Kavach verifies before proceeding (`_verify_hmac_approval`).

## 4. Cryptographic Auditing
Every significant state change, phase transition, and tool execution within the Kavach workflow is immutably logged to the **RISHI Central Node**.
- **HMAC Signatures**: Kavach signs every audit payload with an HMAC-SHA256 signature using a shared secret.
- **Hash-Chaining**: The RISHI server persists each event with a hash chain. Each entry includes the SHA-256 hash of the previous entry, making the entire audit ledger tamper-evident.
- **Transparency**: This ensures that every action taken by the AI agent can be mathematically proven and audited by compliance officers.

## 5. Tool Integration
Kavach relies on established, open-source security tooling (`nmap`, `subfinder`, `nuclei`, `sqlmap`).
- Tools are invoked securely via subprocesses.
- If a tool is unavailable, Kavach degrades gracefully to safe, mocked simulations.
- Outputs are parsed and integrated into unified JSON and PDF reports via `ReportLab`.

## 6. Continuous Retesting
Following remediation, the Retest Agent automatically re-evaluates previously identified vulnerabilities using delta reporting, ensuring patches are effective without requiring a full manual rescan.
