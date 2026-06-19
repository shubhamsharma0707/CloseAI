"""
Phase 3 — Output: Communication Agent
Reads the strategic plan from the blackboard and generates a
human-readable executive summary via the RISHI server.
"""
import asyncio
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

logger = logging.getLogger("Chanakya.Agent05_Communication")


class CommunicationAgent:
    def __init__(self, server_url: str = "http://127.0.0.1:8000/sse"):
        self.server_url = server_url
        self.agent_id = "agent_chanakya_communication"
        self.token = os.getenv("AGENT_TOKEN_AGENT_CHANAKYA_COMMUNICATION", "")
        self.headers = {
            "x-agent-id": self.agent_id,
            "x-agent-token": f"Bearer {self.token}",
        }

    def _safe_text(self, result) -> str:
        if not result.content:
            return "Error: Empty server response."
        return result.content[0].text

    async def generate_executive_summary(self) -> str | None:
        """
        Reads the strategic plan from the blackboard and calls
        `generate_executive_summary` to produce a formatted report.
        Persists the summary back to the blackboard.

        Note: method name is `generate_executive_summary` (matches the
        orchestrator call).  The server-side tool has the same name.
        """
        logger.info("Generating executive summary...")

        try:
            async with async_timeout(20.0):
                async with sse_client(url=self.server_url, headers=self.headers) as (r, w):
                    async with ClientSession(r, w) as session:
                        await session.initialize()
                        logger.info("Communication channel established.")

                        plan_result = await session.call_tool(
                            "read_blackboard",
                            {"key": "latest_strategic_plan"},
                        )
                        raw_plan = self._safe_text(plan_result)

                        if "Error" in raw_plan or not raw_plan.strip():
                            logger.error("No strategic plan on blackboard. Run Phase 2 first.")
                            return None

                        summary_result = await session.call_tool(
                            "generate_executive_summary",
                            {"data_payload": raw_plan},
                        )
                        summary = self._safe_text(summary_result)

                        logger.info("\n" + "=" * 46)
                        logger.info(summary)
                        logger.info("=" * 46)

                        await session.call_tool(
                            "write_blackboard",
                            {"key": "latest_executive_summary", "data": summary},
                        )
                        logger.info("Executive summary written to blackboard.")

                        return summary

        except TimeoutError:
            logger.error("Timeout during summary generation.")
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

    # Alias so both orchestrator call styles work
    draft_executive_summary = generate_executive_summary


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from utils.logger_config import configure_logging
    configure_logging()

    agent = CommunicationAgent()
    asyncio.run(agent.generate_executive_summary())