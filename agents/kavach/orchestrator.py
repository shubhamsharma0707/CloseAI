import asyncio
import logging
import json
import os
import sys
import httpx

# ── Locate project root and load .env ──────────────
_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"), override=False)

_KAVACH_ROOT = os.path.dirname(os.path.abspath(__file__))
if _KAVACH_ROOT not in sys.path:
    sys.path.insert(0, _KAVACH_ROOT)

# Import sub-agents
from authorization.scope_guard import ScopeGuard
from authorization.audit_client import log_audit_event
from triage.triage_engine import TriageEngine
from phase_1_recon.agent_kavach_recon import ReconAgent
from phase_2_vuln_scan.agent_kavach_vuln_scan import VulnScanAgent
from phase_3_pentest.agent_kavach_pentest import PentestAgent
from phase_4_reporting.agent_kavach_reporting import ReportingAgent
from phase_5_retest.agent_kavach_retest import RetestAgent

# --- ENTERPRISE LOGGING CONFIGURATION ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger("Kavach.CISO_Orchestrator")

RISHI_BASE = os.getenv("RISHI_BASE_URL", "http://127.0.0.1:8000")

async def _check_rate_limit(engagement_id: str, action_type: str) -> bool:
    """
    Returns True if the action is allowed, False if rate-limited.
    Fail-closed: RISHI unreachable or unexpected error → deny.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{RISHI_BASE}/kavach/rate-limit/check",
                json={"engagement_id": engagement_id, "action_type": action_type},
            )
            if resp.status_code == 200:
                return True
            if resp.status_code == 429:
                logger.warning(f"[⛔️ RATE_LIMIT] {action_type} for {engagement_id}: {resp.json().get('detail', 'limit exceeded')}")
                log_audit_event("KavachOrchestrator", "RATE_LIMIT_DENIED", {
                    "engagement_id": engagement_id, "action_type": action_type,
                })
                return False
            logger.warning(f"[RATE_LIMIT] Unexpected {resp.status_code} — denying (fail-closed).")
            return False
    except Exception as exc:
        logger.error(f"[RATE_LIMIT] RISHI unreachable: {exc} — denying (fail-closed).")
        log_audit_event("KavachOrchestrator", "RATE_LIMIT_RISHI_UNREACHABLE", {
            "engagement_id": engagement_id, "action_type": action_type,
        })
        return False

class KavachOrchestrator:
    def __init__(self):
        logger.info("🛡️ Initializing Kavach Master Security Orchestrator...")
        self.scope_guard = ScopeGuard()
        self.triage_engine = TriageEngine()
        self.agent_recon = ReconAgent()
        self.agent_vuln_scan = VulnScanAgent()
        self.agent_pentest = PentestAgent()
        self.agent_reporting = ReportingAgent()
        self.agent_retest = RetestAgent()

    async def parse_intent_with_ollama(self, user_prompt: str) -> dict | None:
        """
        Uses a local Ollama model to translate human text into structured security intent.
        """
        logger.info(f"\n🗣️ Human Request Received: '{user_prompt}'")
        logger.info("🧠 Waking up Kavach (Local Ollama: Llama3.1:8b) to parse security intent...")
        
        system_prompt = """
        You are Kavach, a Master Cybersecurity AI Orchestrator (CISO).
        Your job is to read the user's prompt and extract specific variables to feed into your security sub-agents.
        You MUST respond ONLY with a valid JSON object. Do not include markdown code blocks or conversational text.
        
        Required JSON keys:
        - "target": The domain, IP, or application to be tested (e.g., "example.com", "192.168.1.5"). Return "Unknown" if not specified.
        - "scan_type": The type of scan requested. Must be one of ["RECON_ONLY", "VULN_SCAN", "FULL_PENTEST"]. Default to "FULL_PENTEST" if unsure.
        - "auto_approve": Boolean (true/false). Whether the user explicitly granted permission to exploit vulnerabilities. Default to false.
        """
        
        try:
            from ollama import AsyncClient
            
            response = await AsyncClient().chat(model='llama3.1:8b', messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt}
            ], format='json')
            
            msg = response.get('message', None) if isinstance(response, dict) else None
            if msg is not None:
                content = msg.get('content', '') if isinstance(msg, dict) else getattr(msg, 'content', '')
            else:
                content = getattr(getattr(response, 'message', None), 'content', '')

            parsed_data = json.loads(content)
            
            parsed_data.setdefault('target', 'Unknown')
            parsed_data.setdefault('scan_type', 'FULL_PENTEST')
            
            if isinstance(parsed_data.get('auto_approve'), str):
                parsed_data['auto_approve'] = parsed_data['auto_approve'].lower() == 'true'
            else:
                parsed_data.setdefault('auto_approve', False)

            logger.info("✅ Security Intent Parsing Successful!")
            logger.info(json.dumps(parsed_data, indent=2))
            
            return parsed_data
            
        except Exception as e:
            logger.error(f"❌ LLM Parsing Failed: {e}")
            logger.error("Make sure Ollama is running in the background ('ollama serve') and 'llama3.1:8b' is pulled.")
            return None

    async def run_full_security_workflow(self, target: str, scan_type: str, auto_approve: bool):
        """
        Executes the ethical hacking workflow based on the extracted intent.
        """
        logger.info("==================================================")
        logger.info(f"🛡️ INITIATING KAVACH SECURITY WORKFLOW ON: {target}")
        logger.info(f"Mode: {scan_type} | Auto-Approve Exploits: {auto_approve}")
        logger.info("==================================================")

        if target == "Unknown":
            logger.error("🛑 Cannot proceed without a valid target. Aborting workflow.")
            return {"status": "ERROR", "summary": "No target specified."}

        # PHASE 0: AUTHORIZATION & SCOPE GUARD
        logger.info("\n>>> PHASE 0: AUTHORIZATION & SCOPE GUARD")
        guard_result = self.scope_guard.check(target, scan_type)
        
        log_audit_event("KavachOrchestrator", "PHASE_0_AUTH", {
            "target": target,
            "scan_type": scan_type,
            "allowed": guard_result.allowed,
            "reason": guard_result.reason
        })
        
        if not guard_result.allowed:
            logger.error(f"🛑 Workflow aborted by Scope Guard. Reason: {guard_result.reason}")
            return {"status": "BLOCKED", "summary": f"ScopeGuard blocked: {guard_result.reason}"}

        # PHASE 1: RECONNAISSANCE
        if not await _check_rate_limit(guard_result.engagement_id or "ENG-UNKNOWN", "RECON"):
            logger.error("⛔️ RECON rate limit exceeded — aborting workflow.")
            return {"status": "ERROR", "summary": "RECON rate limit exceeded."}
        log_audit_event("KavachOrchestrator", "PHASE_1_RECON_START", {"target": target})
        logger.info("\n>>> PHASE 1: RECONNAISSANCE")
        recon_data = await self.agent_recon.execute_recon(target)
        log_audit_event("KavachOrchestrator", "PHASE_1_RECON_END", {"recon_data": recon_data})
        
        if scan_type == "RECON_ONLY":
            logger.info("Workflow complete. Scan type was RECON_ONLY.")
            return {"status": "OK", "summary": "RECON_ONLY workflow complete."}

        # PHASE 2: VULNERABILITY SCANNING
        if not await _check_rate_limit(guard_result.engagement_id or "ENG-UNKNOWN", "VULN_SCAN"):
            logger.error("⛔️ VULN_SCAN rate limit exceeded — aborting workflow.")
            return {"status": "ERROR", "summary": "VULN_SCAN rate limit exceeded."}
        log_audit_event("KavachOrchestrator", "PHASE_2_VULNSCAN_START", {"target": target})
        logger.info("\n>>> PHASE 2: VULNERABILITY SCANNING")
        vuln_data = await self.agent_vuln_scan.scan_vulnerabilities(recon_data)
        log_audit_event("KavachOrchestrator", "PHASE_2_VULNSCAN_END", {"vuln_data": vuln_data})

        # PHASE 2.5: TRIAGE
        log_audit_event("KavachOrchestrator", "PHASE_2_5_TRIAGE_START", {"target": target})
        logger.info("\n>>> PHASE 2.5: TRIAGE & DEDUPLICATION")
        triaged_findings = self.triage_engine.run(vuln_data)
        triaged_dicts = [f.to_dict() for f in triaged_findings]
        log_audit_event("KavachOrchestrator", "PHASE_2_5_TRIAGE_END", {
            "finding_count": len(triaged_findings),
            "severities": [f.severity for f in triaged_findings],
        })
        logger.info(f">>> TRIAGE: {len(triaged_findings)} findings after dedup/enrichment")

        pentest_data = {"status": "SKIPPED", "exploited": []}

        # PHASE 3: PENETRATION TESTING (with Human Approval lock)
        if scan_type == "FULL_PENTEST":
            if not await _check_rate_limit(guard_result.engagement_id or "ENG-UNKNOWN", "EXPLOIT"):
                logger.error("⛔️ EXPLOIT rate limit exceeded — skipping pentest phase.")
            else:
                log_audit_event("KavachOrchestrator", "PHASE_3_PENTEST_START", {"target": target})
                logger.info("\n>>> PHASE 3: PENETRATION TESTING")
                pentest_data = await self.agent_pentest.run_exploit_simulation(
                    vulnerabilities=triaged_dicts,
                    auto_approve=auto_approve,
                    engagement_id=guard_result.engagement_id or "ENG-UNKNOWN",
                    destructive_testing_allowed=guard_result.destructive_testing_allowed,
                )
                log_audit_event("KavachOrchestrator", "PHASE_3_PENTEST_END", {"pentest_data": pentest_data})

        # PHASE 4: REPORTING
        log_audit_event("KavachOrchestrator", "PHASE_4_REPORTING_START", {"target": target})
        logger.info("\n>>> PHASE 4: REPORTING")
        report_data = await self.agent_reporting.generate_report(
            target=target,
            recon_data=recon_data,
            vuln_data={**vuln_data, "vulnerabilities": triaged_dicts},
            pentest_data=pentest_data,
            engagement_id=guard_result.engagement_id or "ENG-UNKNOWN",
        )
        log_audit_event("KavachOrchestrator", "PHASE_4_REPORTING_END", {"report_data": report_data})

        # PHASE 5: RETESTING
        log_audit_event("KavachOrchestrator", "PHASE_5_RETEST_START", {"target": target})
        logger.info("\n>>> PHASE 5: CONTINUOUS MONITORING & RETESTING")
        await self.agent_retest.verify_fixes(
            previous_report_path=report_data.get("report_path", "unknown"),
            engagement_id=guard_result.engagement_id or "ENG-UNKNOWN",
        )
        log_audit_event("KavachOrchestrator", "PHASE_5_RETEST_END", {"target": target})

        logger.info("\n==================================================")
        logger.info("✅ KAVACH SECURITY WORKFLOW COMPLETE")
        logger.info("==================================================")
        
        # Check if pentest_data had any blocked exploits (e.g. NEEDS_APPROVAL or EXPLOIT_BLOCKED)
        if isinstance(pentest_data, dict):
            # If pentest_data status is KILL_SWITCH_ACTIVE or similar we could map it
            # But PentestAgent also handles approvals. If approval was denied, it doesn't halt the whole workflow 
            # unless we want it to. Wait, PentestAgent just logs EXPLOIT_BLOCKED and continues.
            pass

        return {"status": "OK", "summary": "Security workflow complete."}

    async def run(self, user_prompt: str, engagement_id: str | None = None) -> dict:
        """
        Thin wrapper to provide a standardized agentic interface for RISHI Central Router.
        """
        intent = await self.parse_intent_with_ollama(user_prompt)
        if not intent:
            return {
                "status": "ERROR",
                "summary": "Failed to parse intent.",
                "details": {},
                "orchestrator": "kavach"
            }
            
        result = await self.run_full_security_workflow(
            target=intent.get("target", "Unknown"),
            scan_type=intent.get("scan_type", "FULL_PENTEST"),
            auto_approve=intent.get("auto_approve", False)
        )
        
        # In case the workflow returned None by accident, default to OK
        if not result:
            result = {"status": "OK", "summary": "Workflow completed (no status returned)."}
            
        return {
            "status": result.get("status", "OK"),
            "summary": result.get("summary", ""),
            "details": intent,
            "orchestrator": "kavach"
        }

async def main():
    ciso = KavachOrchestrator()
    
    # Testing the orchestrator
    human_input = "I need you to run a full penetration test against internal-portal.corp.closeai.com. Do not auto-approve exploits, I want to review them first."
    
    intent_data = await ciso.parse_intent_with_ollama(human_input)
    
    if intent_data:
        await ciso.run_full_security_workflow(
            target=intent_data.get("target", "Unknown"),
            scan_type=intent_data.get("scan_type", "FULL_PENTEST"),
            auto_approve=intent_data.get("auto_approve", False)
        )

if __name__ == "__main__":
    asyncio.run(main())
