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
        - "proposed_action": A summary of what the user wants to do strategically.
        - "jurisdiction": The geographical jurisdiction for the action (e.g., "Europe", "Cayman Islands", "India"). Return "Unknown" if not specified.
        - "entity_type": The type of entity involved (e.g., "Corporation", "Shell Company"). Return "Unknown" if not specified.
        - "reallocation_percentage": The percentage of remaining capital to be reallocated, as a decimal string (e.g., "0.20" for 20%). Return "0" if not specified.
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

            # ── Normalise reallocation_percentage ───────────────────────────────
            raw_alloc = str(parsed_data.get('reallocation_percentage', '0'))
            clean_alloc = raw_alloc.replace('%', '').replace(' ', '').strip()
            try:
                alloc_float = float(clean_alloc)
                if alloc_float >= 1.0:
                    alloc_float /= 100.0
                parsed_data['reallocation_percentage'] = f"{alloc_float:.6f}".rstrip('0').rstrip('.')
            except ValueError:
                parsed_data['reallocation_percentage'] = '0'

            # Set defaults for new fields
            parsed_data.setdefault('jurisdiction', 'Unknown')
            parsed_data.setdefault('entity_type', 'Unknown')

            logger.info("✅ LLM Intent Parsing Successful!")
            logger.info(json.dumps(parsed_data, indent=2))
            
            return parsed_data
            
        except Exception as e:
            logger.error(f"❌ LLM Parsing Failed: {e}")
            logger.error("Make sure Ollama is running in the background ('ollama serve') and 'llama3' is pulled.")
            return None

    async def amend_proposal_with_ollama(self, original_proposal: str, rejection_reason: str) -> str | None:
        """
        Uses Ollama to dynamically amend a non-compliant proposal based on the rejection reason.
        """
        logger.info(f"🧠 Asking Chanakya (Llama3) to amend the proposal to resolve: '{rejection_reason}'")
        
        system_prompt = f"""
        You are Chanakya, a financial compliance expert. 
        A proposed action was rejected by the Ethical Compliance Agent for the following reason:
        "{rejection_reason}"
        
        Original Proposal:
        "{original_proposal}"
        
        Rewrite the proposed action so that it satisfies the compliance requirements while keeping the financial intent as similar as possible. 
        Do not explain yourself or use conversational text. Reply ONLY with the rewritten proposal string.
        """
        
        try:
            from ollama import AsyncClient
            response = await AsyncClient().chat(model='llama3', messages=[
                {'role': 'system', 'content': system_prompt}
            ])
            
            msg = response.get('message', None) if isinstance(response, dict) else None
            if msg is not None:
                content = msg.get('content', '') if isinstance(msg, dict) else getattr(msg, 'content', '')
            else:
                content = getattr(getattr(response, 'message', None), 'content', '')

            amended_proposal = content.strip().strip('"')
            return amended_proposal

        except Exception as e:
            logger.error(f"❌ LLM Amendment Failed: {e}")
            return None

    async def run_full_financial_workflow(self, principal: str, reallocation_percentage: str, proposed_action: str, jurisdiction: str, entity_type: str):
        """
        Executes the complete end-to-end multi-agent financial workflow.
        """
        logger.info("==================================================")
        logger.info("🚀 INITIATING FULL CHANAKYA FINANCIAL WORKFLOW")
        logger.info("==================================================")

        # PHASE 1: QUANTITATIVE & AUDITABILITY (Tax Engine)
        logger.info("\n>>> PHASE 1: QUANTITATIVE EXECUTION (TAX ENGINE)")
        audit_result = await self.agent_deterministic.execute_audit("calculate_tax_liability", [principal])
        
        if audit_result and audit_result.get("status") == "ok":
            await self.agent_auditability.secure_ledger_entry("latest_tax_audit_hash")
            tax_liability = float(audit_result.get("exact_result", "0"))
            remaining_capital = float(principal) - tax_liability
            transaction_amount = remaining_capital * float(reallocation_percentage or "0")
            logger.info(f"Calculated Tax: {tax_liability} | Remaining Capital: {remaining_capital}")
            logger.info(f"Transaction Amount ({float(reallocation_percentage)*100}% allocation): {transaction_amount}")
        else:
            logger.error("Phase 1 Failed: Deterministic math error. Halting workflow.")
            return

        # PHASE 2: QUALITATIVE & STRATEGY
        logger.info("\n>>> PHASE 2: ETHICAL COMPLIANCE & STRATEGY")
        
        max_retries = 3
        attempt = 0
        current_proposal = proposed_action
        compliance_approved = False
        
        while attempt < max_retries and not compliance_approved:
            compliance_result = await self.agent_ethical.evaluate_proposal(
                current_proposal,
                jurisdiction=jurisdiction,
                entity_type=entity_type,
                transaction_amount=str(transaction_amount)
            )
            if compliance_result and compliance_result.get("status") in ["APPROVED", "EDD_REQUIRED"]:
                compliance_approved = True
                if compliance_result.get("status") == "EDD_REQUIRED":
                    logger.warning(f"⚠️ EDD REQUIRED: {compliance_result.get('reason')}")
            else:
                attempt += 1
                reason = compliance_result.get("reason", "Unknown policy violation") if compliance_result else "Unknown Error"
                logger.warning(f"Proposal rejected: {reason}. Attempting to amend (Attempt {attempt}/{max_retries})...")
                
                amended_proposal = await self.amend_proposal_with_ollama(current_proposal, reason)
                if amended_proposal:
                    current_proposal = amended_proposal
                    logger.info(f"Amended proposal: '{current_proposal}'")
                else:
                    logger.error("Failed to amend proposal. Halting workflow.")
                    return

        if compliance_approved:
            await self.agent_critical.analyze_financial_strategy(current_proposal)
        else:
            logger.error(f"Max retries ({max_retries}) reached for compliance. Halting workflow.")
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
    
    # Testing the CA-grade rule engine
    human_input = "We have a core income of ₹2,50,00,000. Calculate our tax liability under the new Indian regime. Next, reallocate 20% of the remaining capital to a green energy fund in India."
    
    # 2. Let the LLM extract the parameters
    intent_data = await ceo.parse_intent_with_ollama(human_input)
    
    # 3. If the LLM successfully understood, run the autonomous workflow
    if intent_data:
        await ceo.run_full_financial_workflow(
            principal=str(intent_data.get("principal", "0")),
            reallocation_percentage=str(intent_data.get("reallocation_percentage", "0")),
            proposed_action=intent_data.get("proposed_action", ""),
            jurisdiction=intent_data.get("jurisdiction", "Unknown"),
            entity_type=intent_data.get("entity_type", "Unknown")
        )

if __name__ == "__main__":
    # Run the orchestrator
    asyncio.run(main())