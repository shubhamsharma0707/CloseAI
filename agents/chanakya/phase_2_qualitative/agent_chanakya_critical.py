"""
Phase 2 — Qualitative: Critical Thinking / Strategy Agent
Reads prior audit and compliance context from the blackboard and
runs strategic analysis via the RISHI `analyze_strategy` tool.
"""
import asyncio
import json
import logging
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..', '..'))
from utils.compat import async_timeout
del _sys, _os

from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger("Chanakya.Agent04_Critical")


class CriticalThinkingAgent:
    def __init__(self, server_url: str = "http://127.0.0.1:8000/sse"):
        self.server_url = server_url
        self.agent_id = "agent_chanakya_critical"
        self.token = os.getenv("AGENT_TOKEN_AGENT_CHANAKYA_CRITICAL", "")
        self.headers = {
            "x-agent-id": self.agent_id,
            "x-agent-token": f"Bearer {self.token}",
        }

    def _safe_text(self, result) -> str:
        if not result.content:
            return "Error: Empty server response."
        return result.content[0].text

    async def analyze_financial_strategy(self, context_data: str) -> dict | None:
        """
        Gathers prior agent outputs from the blackboard, then calls
        `analyze_strategy` to produce strategic insights and risk factors.
        Writes the resulting plan back to the blackboard for Phase 3 agents.

        Returns parsed strategy dict or None on failure.
        """
        logger.info(f"Starting critical analysis for: '{context_data[:80]}'")

        try:
            async with async_timeout(20.0):
                async with sse_client(url=self.server_url, headers=self.headers) as (r, w):
                    async with ClientSession(r, w) as session:
                        await session.initialize()
                        logger.info("Strategy channel established.")

                        # Read context written by Phase 1 agents
                        audit_result = await session.call_tool(
                            "read_blackboard", {"key": "latest_tax_audit_hash"}
                        )
                        compliance_result = await session.call_tool(
                            "read_blackboard", {"key": "latest_compliance_verdict"}
                        )

                        audit_hash = self._safe_text(audit_result)
                        compliance_raw = self._safe_text(compliance_result)

                        logger.info(
                            f"Context: audit_present={('Error' not in audit_hash)}, "
                            f"compliance_present={('Error' not in compliance_raw)}"
                        )

                        analysis_payload = json.dumps({
                            "proposal": context_data,
                            "audit_context": audit_hash,
                            "compliance_context": compliance_raw,
                        })

                        result = await session.call_tool(
                            "analyze_strategy",
                            {"context": analysis_payload},
                        )

                        response_data = json.loads(self._safe_text(result))
                        insights = response_data.get("strategic_insights", [])
                        risks = response_data.get("risk_factors", [])

                        logger.info("─── STRATEGIC ANALYSIS RECORD ─────────────────")
                        for i, insight in enumerate(insights, 1):
                            logger.info(f"  Insight {i}: {insight}")
                        for i, risk in enumerate(risks, 1):
                            logger.warning(f"  Risk    {i}: {risk}")
                        logger.info("───────────────────────────────────────────────")

                        plan_payload = json.dumps({
                            "action": context_data,
                            "insights": insights,
                            "risks": risks,
                        })
                        await session.call_tool(
                            "write_blackboard",
                            {"key": "latest_strategic_plan", "data": plan_payload},
                        )
                        logger.info("Strategic plan written to blackboard.")

                        return response_data

        except TimeoutError:
            logger.error("Timeout during strategic analysis.")
            return None
        except json.JSONDecodeError as exc:
            logger.error(f"Malformed strategy response: {exc}")
            return None
        except TimeoutError:
            # Re-raise already handled above; this silences the linter
            raise
        except Exception as exc:
            # anyio wraps connection errors in an ExceptionGroup on Python <3.11
            cause = str(exc)
            if "refused" in cause or "TaskGroup" in cause or "ExceptionGroup" in cause:
                logger.error(
                    "Cannot reach RISHI server at http://127.0.0.1:8000 — "
                    "is 'python3 RISHI.py' running? (run setup_dev.py first)"
                )
            else:
                logger.error(f"Network or execution failure: {exc}")
            return None
        except BaseException as exc:
            # Safety net: catches anyio ExceptionGroup on Python 3.10 backport
            cause = str(exc)
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if "refused" in cause or "TaskGroup" in cause:
                logger.error(
                    "Cannot reach RISHI server at http://127.0.0.1:8000 — "
                    "is 'python3 RISHI.py' running? (run setup_dev.py first)"
                )
            else:
                logger.error(f"Unhandled exception in agent: {type(exc).__name__}: {exc}")
            return None


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from utils.logger_config import configure_logging
    configure_logging()

    agent = CriticalThinkingAgent()
    asyncio.run(
        agent.analyze_financial_strategy(
            "Reallocate 15% of Q3 budget to sustainability initiatives."
        )
    )