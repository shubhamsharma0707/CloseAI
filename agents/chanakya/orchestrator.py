import asyncio
import logging
import json
import os
import sys

# ── Locate project root (agents/chanakya → ../../) and load .env ──────────────
_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"), override=False)

# Import all sub-agents from their respective phases
from phase_1_quantitative.agent_chanakya_deterministic import DeterministicAuditAgent
from phase_1_quantitative.agent_chanakya_auditability import AuditabilityAgent
from phase_2_qualitative.agent_chanakya_ethical import EthicalComplianceAgent
from phase_2_qualitative.agent_chanakya_critical import CriticalThinkingAgent
from phase_3_output.agent_chanakya_communication import CommunicationAgent
from phase_3_output.agent_chanakya_visualization import VisualizationAgent
from phase_3_output.agent_chanakya_esg import ESGAgent
from phase_4_evolution.agent_chanakya_adaptability import AdaptabilityAgent

# --- ENTERPRISE LOGGING CONFIGURATION ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger("Chanakya.CEO_Orchestrator")

class ChanakyaOrchestrator:
    def __init__(self):
        logger.info("Initializing Chanakya Master Orchestrator...")
        self.agent_deterministic = DeterministicAuditAgent()
        self.agent_auditability = AuditabilityAgent()
        self.agent_ethical = EthicalComplianceAgent()
        self.agent_critical = CriticalThinkingAgent()
        self.agent_communication = CommunicationAgent()
        self.agent_visualization = VisualizationAgent()
        self.agent_esg = ESGAgent()
        self.agent_adaptability = AdaptabilityAgent()

    async def parse_intent_with_ollama(self, user_prompt: str) -> dict | None:
        """
        Uses a local Ollama model to translate human text into structured data.
        Forces the output into JSON format for safe extraction.
        """
        logger.info(f"\n🗣️ Human Prompt Received: '{user_prompt}'")
        logger.info("🧠 Waking up Chanakya (Local Ollama: Llama3) to parse intent...")
        
        system_prompt = """
        You are Chanakya, a master financial AI orchestrator. 
        Your job is to read the user's prompt and extract three specific variables to feed into your sub-agents.
        You MUST respond ONLY with a valid JSON object. Do not include markdown code blocks or conversational text.
        
        Required JSON keys:
        - "principal": The main monetary amount as a string (e.g., "1500000.00"). Remove currency symbols and commas.
        - "tax_rate": The tax rate or percentage as a decimal string (e.g., "0.05" for 5%).
        - "proposed_action": A summary of what the user wants to do strategically.
        """
        
        try:
            # We import here to keep the rest of the script clean if ollama isn't installed
            from ollama import AsyncClient
            
            # Using format='json' forces the model to output valid JSON
            response = await AsyncClient().chat(model='llama3', messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt}
            ], format='json')
            
            # Newer ollama SDK uses attribute access; older used dict — handle both
            msg = response.get('message', None) if isinstance(response, dict) else None
            if msg is not None:
                content = msg.get('content', '') if isinstance(msg, dict) else getattr(msg, 'content', '')
            else:
                content = getattr(getattr(response, 'message', None), 'content', '')

            parsed_data = json.loads(content)
            
            # ── Sanitise principal ──────────────────────────────────────────
            # Strip currency symbols, commas, whitespace the LLM may have left in
            raw_principal = str(parsed_data.get('principal', '0'))
            clean_principal = raw_principal.replace('$', '').replace(',', '').replace(' ', '').strip()
            parsed_data['principal'] = clean_principal

            # ── Normalise tax_rate ──────────────────────────────────────────
            # LLMs often return "12.5" when they mean "0.125".  If the value
            # is >= 1.0 we treat it as a percentage and convert to decimal.
            raw_rate = str(parsed_data.get('tax_rate', '0'))
            clean_rate = raw_rate.replace('%', '').replace(' ', '').strip()
            try:
                rate_float = float(clean_rate)
                if rate_float >= 1.0:
                    rate_float /= 100.0
                    logger.info(f"  tax_rate normalised: '{raw_rate}' → '{rate_float}'")
                parsed_data['tax_rate'] = f"{rate_float:.6f}".rstrip('0').rstrip('.')
            except ValueError:
                logger.warning(f"  tax_rate '{raw_rate}' not numeric — defaulting to 0")
                parsed_data['tax_rate'] = '0'

            logger.info("✅ LLM Intent Parsing Successful!")
            logger.info(json.dumps(parsed_data, indent=2))
            
            return parsed_data
            
        except Exception as e:
            logger.error(f"❌ LLM Parsing Failed: {e}")
            logger.error("Make sure Ollama is running in the background ('ollama serve') and 'llama3' is pulled.")
            return None

    async def run_full_financial_workflow(self, principal: str, tax_rate: str, proposed_action: str):
        """
        Executes the complete end-to-end multi-agent financial workflow.
        """
        logger.info("==================================================")
        logger.info("🚀 INITIATING FULL CHANAKYA FINANCIAL WORKFLOW")
        logger.info("==================================================")

        # PHASE 1: QUANTITATIVE & AUDITABILITY
        logger.info("\n>>> PHASE 1: QUANTITATIVE EXECUTION")
        audit_result = await self.agent_deterministic.execute_audit("multiply", [principal, tax_rate])
        
        if audit_result:
            await self.agent_auditability.secure_ledger_entry("latest_tax_audit_hash")
        else:
            logger.error("Phase 1 Failed: Deterministic math error. Halting workflow.")
            return

        # PHASE 2: QUALITATIVE & STRATEGY
        logger.info("\n>>> PHASE 2: ETHICAL COMPLIANCE & STRATEGY")
        compliance_result = await self.agent_ethical.evaluate_proposal(proposed_action)
        
        if compliance_result and compliance_result.get("status") == "APPROVED":
            await self.agent_critical.analyze_financial_strategy(proposed_action)
        else:
            logger.warning(f"Proposal rejected by Compliance. Halting further execution.")
            return

        # PHASE 3: OUTPUT, VISUALIZATION & ESG
        logger.info("\n>>> PHASE 3: REPORTING & OUTPUT GENERATION")
        logger.info("Triggering Communication, Visualization, and ESG Agents concurrently...")
        await asyncio.gather(
            self.agent_communication.draft_executive_summary(),
            self.agent_visualization.generate_dashboards(),
            self.agent_esg.generate_sustainability_report()
        )

        # PHASE 4: EVOLUTION & LEARNING
        logger.info("\n>>> PHASE 4: SYSTEM ADAPTABILITY")
        await self.agent_adaptability.research_regulatory_updates("2026 global tax and ESG compliance updates")

        logger.info("\n==================================================")
        logger.info("✅ CHANAKYA WORKFLOW COMPLETE")
        logger.info("==================================================")

async def main():
    ceo = ChanakyaOrchestrator()
    
    # 1. Provide a natural language prompt instead of hardcoded variables
    human_input = "We have a core fund of $25,400,500. Calculate an estimated 12.5% tax provision on this. Next, I want to evaluate if we can reallocate 20% of the remaining capital to aggressive green-energy acquisitions in Europe to lower our carbon footprint."
    
    # 2. Let the LLM extract the parameters
    intent_data = await ceo.parse_intent_with_ollama(human_input)
    
    # 3. If the LLM successfully understood, run the autonomous workflow
    if intent_data:
        await ceo.run_full_financial_workflow(
            principal=str(intent_data.get("principal", "0")),
            tax_rate=str(intent_data.get("tax_rate", "0")),
            proposed_action=intent_data.get("proposed_action", "")
        )

if __name__ == "__main__":
    # Run the orchestrator
    asyncio.run(main())