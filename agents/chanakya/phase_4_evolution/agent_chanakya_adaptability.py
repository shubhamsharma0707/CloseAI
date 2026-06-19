"""
Phase 4 — Evolution: Adaptability / Regulatory Research Agent
Fetches current regulatory and ESG compliance updates via RISHI.
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

logger = logging.getLogger("Chanakya.Agent08_Adaptability")


class AdaptabilityAgent:
    def __init__(self, server_url: str = "http://127.0.0.1:8000/sse"):
        self.server_url = server_url
        self.agent_id = "agent_chanakya_adaptability"
        self.token = os.getenv("AGENT_TOKEN_AGENT_CHANAKYA_ADAPTABILITY", "")
        self.headers = {
            "x-agent-id": self.agent_id,
            "x-agent-token": f"Bearer {self.token}",
        }

    def _safe_text(self, result) -> str:
        if not result.content:
            return '{"status": "error", "message": "Empty server response."}'
        return result.content[0].text

    async def research_regulatory_updates(
        self,
        query_context: str = "2026 global tax and ESG compliance updates",
    ) -> dict | None:
        """
        Calls `fetch_regulatory_updates` on RISHI and persists the returned
        regulatory changes and risk alerts to the blackboard.
        """
        logger.info(f"Research query: '{query_context}'")

        try:
            async with async_timeout(20.0):
                async with sse_client(url=self.server_url, headers=self.headers) as (r, w):
                    async with ClientSession(r, w) as session:
                        await session.initialize()
                        logger.info("Research channel established.")

                        research_result = await session.call_tool(
                            "fetch_regulatory_updates",
                            {"query": query_context},
                        )
                        research_data = json.loads(self._safe_text(research_result))

                        timestamp = research_data.get("timestamp", "Unknown")
                        key_changes = research_data.get("key_regulatory_changes", [])
                        risk_alerts = research_data.get("new_risk_alerts", [])

                        logger.info("─── 🧠  REGULATORY RESEARCH COMPLETE ──────────")
                        logger.info(f"  Timestamp : {timestamp}")
                        for change in key_changes:
                            logger.info(f"  [UPDATE]  : {change}")
                        for alert in risk_alerts:
                            logger.warning(f"  [ALERT]   : {alert}")
                        logger.info("───────────────────────────────────────────────")

                        await session.call_tool(
                            "write_blackboard",
                            {
                                "key": "latest_regulatory_updates",
                                "data": json.dumps(research_data),
                            },
                        )
                        logger.info("Regulatory updates written to blackboard.")

                        return research_data

        except TimeoutError:
            logger.error("Timeout during regulatory research.")
            return None
        except json.JSONDecodeError as exc:
            logger.error(f"Malformed research response: {exc}")
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

    agent = AdaptabilityAgent()
    asyncio.run(agent.research_regulatory_updates())