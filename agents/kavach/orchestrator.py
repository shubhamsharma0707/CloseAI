import asyncio
import logging
import json
import os
import sys

# ── Locate project root and load .env ──────────────
_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"), override=False)

# Import sub-agents
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

class KavachOrchestrator:
    def __init__(self):
        logger.info("🛡️ Initializing Kavach Master Security Orchestrator...")
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
            return

        # PHASE 1: RECONNAISSANCE
        logger.info("\n>>> PHASE 1: RECONNAISSANCE")
        recon_data = await self.agent_recon.execute_recon(target)
        
        if scan_type == "RECON_ONLY":
            logger.info("Workflow complete. Scan type was RECON_ONLY.")
            return

        # PHASE 2: VULNERABILITY SCANNING
        logger.info("\n>>> PHASE 2: VULNERABILITY SCANNING")
        vuln_data = await self.agent_vuln_scan.scan_vulnerabilities(recon_data)
        
        pentest_data = {"status": "SKIPPED", "exploited": []}

        # PHASE 3: PENETRATION TESTING (with Human Approval lock)
        if scan_type == "FULL_PENTEST":
            logger.info("\n>>> PHASE 3: PENETRATION TESTING")
            pentest_data = await self.agent_pentest.run_exploit_simulation(
                vulnerabilities=vuln_data.get("vulnerabilities", []),
                auto_approve=auto_approve
            )

        # PHASE 4: REPORTING
        logger.info("\n>>> PHASE 4: REPORTING")
        report_data = await self.agent_reporting.generate_report(target, recon_data, vuln_data, pentest_data)

        # PHASE 5: RETESTING
        logger.info("\n>>> PHASE 5: CONTINUOUS MONITORING & RETESTING")
        await self.agent_retest.verify_fixes(report_data.get("report_path", "unknown"))

        logger.info("\n==================================================")
        logger.info("✅ KAVACH SECURITY WORKFLOW COMPLETE")
        logger.info("==================================================")

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
