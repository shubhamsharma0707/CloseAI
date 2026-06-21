"""
Phase 2 — Qualitative: Ethical Compliance Agent
Evaluates financial proposals against the AML/KYC compliance rule set.
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

logger = logging.getLogger("Chanakya.Agent03_Ethical")


class EthicalComplianceAgent:
    def __init__(self, server_url: str = "http://127.0.0.1:8000/sse"):
        self.server_url = server_url
        self.agent_id = "agent_chanakya_ethical"
        self.token = os.getenv(f"AGENT_TOKEN_AGENT_CHANAKYA_ETHICAL", "")
        self.headers = {
            "x-agent-id": self.agent_id,
            "x-agent-token": f"Bearer {self.token}",
        }

    def _safe_text(self, result) -> str:
        """Guard against empty content lists."""
        if not result.content:
            return "Error: Empty response from server."
        return result.content[0].text

    async def evaluate_proposal(self, proposal: str, jurisdiction: str = "", entity_type: str = "", transaction_amount: str = "0") -> dict | None:
        """
        Connects to the RISHI server, calls the `evaluate_compliance` tool,
        and returns the compliance verdict as a parsed dict.

        Returns:
            dict with 'status' ("APPROVED" | "REJECTED" | "EDD_REQUIRED") and 'reason'.
            None on network / timeout failure.
        """
        logger.info(f"Submitting proposal for compliance evaluation: '{proposal[:80]}'")

        try:
            async with async_timeout(15.0):
                async with sse_client(url=self.server_url, headers=self.headers) as (r, w):
                    async with ClientSession(r, w) as session:
                        await session.initialize()
                        logger.info("Compliance channel established.")

                        result = await session.call_tool(
                            "evaluate_compliance",
                            {
                                "proposal": proposal,
                                "jurisdiction": jurisdiction,
                                "entity_type": entity_type,
                                "transaction_amount": transaction_amount
                            },
                        )

                        raw = self._safe_text(result)
                        verdict = json.loads(raw)

                        status = verdict.get("status", "UNKNOWN")
                        reason = verdict.get("reason", "")

                        if status == "APPROVED":
                            logger.info(f"✅ COMPLIANCE APPROVED — {reason}")
                        elif status == "EDD_REQUIRED":
                            logger.warning(f"⚠️ EDD REQUIRED — {reason}")
                        else:
                            logger.warning(f"🚫 COMPLIANCE REJECTED — {reason}")

                        # Persist verdict to the shared blackboard for downstream agents
                        await session.call_tool(
                            "write_blackboard",
                            {"key": "latest_compliance_verdict", "data": raw},
                        )
                        logger.info("Compliance verdict written to blackboard.")

                        return verdict

        except TimeoutError:
            logger.error("Connection timed out during compliance evaluation.")
            return None
        except json.JSONDecodeError as exc:
            logger.error(f"Malformed compliance response: {exc}")
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

    agent = EthicalComplianceAgent()
    result = asyncio.run(
        agent.evaluate_proposal("Reallocate 15% of Q3 budget to sustainability initiatives.")
    )
    print(f"\nVerdict: {result}")