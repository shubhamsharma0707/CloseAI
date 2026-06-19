"""
Phase 3 — Output: ESG Agent
Reads strategic plan data from the blackboard and calculates
carbon footprint and ESG compliance metrics via RISHI.
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

logger = logging.getLogger("Chanakya.Agent07_ESG")


class ESGAgent:
    def __init__(self, server_url: str = "http://127.0.0.1:8000/sse"):
        self.server_url = server_url
        self.agent_id = "agent_chanakya_esg"
        self.token = os.getenv("AGENT_TOKEN_AGENT_CHANAKYA_ESG", "")
        self.headers = {
            "x-agent-id": self.agent_id,
            "x-agent-token": f"Bearer {self.token}",
        }

    def _safe_text(self, result) -> str:
        if not result.content:
            return '{"status": "error", "message": "Empty server response."}'
        return result.content[0].text

    async def generate_sustainability_report(self) -> dict | None:
        """
        Reads the strategic plan, calls `calculate_esg_metrics`, logs the
        sustainability report, and persists results to the blackboard.
        """
        logger.info("Starting ESG and carbon footprint analysis...")

        try:
            async with async_timeout(20.0):
                async with sse_client(url=self.server_url, headers=self.headers) as (r, w):
                    async with ClientSession(r, w) as session:
                        await session.initialize()
                        logger.info("ESG channel established.")

                        plan_result = await session.call_tool(
                            "read_blackboard",
                            {"key": "latest_strategic_plan"},
                        )
                        raw_plan = self._safe_text(plan_result)

                        if "Error" in raw_plan or not raw_plan.strip():
                            logger.error("No strategic plan on blackboard. Run Phase 2 first.")
                            return None

                        esg_result = await session.call_tool(
                            "calculate_esg_metrics",
                            {"financial_data": raw_plan},
                        )
                        esg_data = json.loads(self._safe_text(esg_result))

                        carbon = esg_data.get("estimated_carbon_tons", 0)
                        compliance = esg_data.get("esg_compliance", "Unknown")
                        recommendations = esg_data.get("sustainability_recommendations", [])

                        logger.info("─── 🌍  ESG REPORT ─────────────────────────────")
                        logger.info(f"  Carbon Footprint : {carbon} Metric Tons CO2e")
                        logger.info(f"  ESG Compliance   : {compliance}")
                        for rec in recommendations:
                            logger.info(f"  Recommendation   : {rec}")
                        logger.info("───────────────────────────────────────────────")

                        await session.call_tool(
                            "write_blackboard",
                            {"key": "latest_esg_report", "data": json.dumps(esg_data)},
                        )
                        logger.info("ESG report written to blackboard.")

                        return esg_data

        except TimeoutError:
            logger.error("Timeout during ESG analysis.")
            return None
        except json.JSONDecodeError as exc:
            logger.error(f"Malformed ESG response: {exc}")
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

    agent = ESGAgent()
    asyncio.run(agent.generate_sustainability_report())