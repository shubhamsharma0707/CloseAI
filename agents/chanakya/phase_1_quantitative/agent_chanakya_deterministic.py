"""
Phase 1 — Quantitative: Deterministic Audit Agent
Executes exact-precision financial arithmetic via the RISHI server's
`tamper_proof_audit_math` tool and records the resulting SHA-256 hash.
"""
import asyncio
import json
import logging
import os
from decimal import Decimal, InvalidOperation

import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..', '..'))
from utils.compat import async_timeout
del _sys, _os

from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger("Chanakya.Agent01_Deterministic")


class DeterministicAuditAgent:
    def __init__(self, server_url: str = "http://127.0.0.1:8000/sse"):
        self.server_url = server_url
        self.agent_id = "agent_chanakya_deterministic"
        self.token = os.getenv("AGENT_TOKEN_AGENT_CHANAKYA_DETERMINISTIC", "")
        self.headers = {
            "x-agent-id": self.agent_id,
            "x-agent-token": f"Bearer {self.token}",
        }

    def _safe_text(self, result) -> str:
        """Guard against empty content lists returned by the server."""
        if not result.content:
            return '{"status": "error", "message": "Empty server response."}'
        return result.content[0].text

    def _local_pre_validation(self, operands: list[str]) -> bool:
        """
        Validate operands locally before opening a network connection.
        Prevents malformed LLM output from wasting server cycles.
        """
        if not operands:
            logger.error("Operand list is empty.")
            return False
        try:
            for op in operands:
                Decimal(op)
            return True
        except InvalidOperation:
            logger.error(f"Pre-validation failed — invalid operand in: {operands}")
            return False

    async def execute_audit(self, operation: str, operands: list[str]) -> dict | None:
        """
        Connects to RISHI, executes tamper-proof math, and writes the
        resulting audit hash to the shared blackboard.

        Args:
            operation: One of 'add', 'subtract', 'multiply', 'divide'.
            operands:  List of numeric strings (use strings to avoid float errors).

        Returns:
            Parsed response dict, or None on validation/network failure.
        """
        if not self._local_pre_validation(operands):
            return None

        logger.info(f"Initiating audited calculation: '{operation}' on {operands}")

        try:
            async with async_timeout(15.0):
                async with sse_client(url=self.server_url, headers=self.headers) as (r, w):
                    async with ClientSession(r, w) as session:
                        await session.initialize()
                        logger.info("Secure channel established.")

                        if operation == "calculate_tax_liability":
                            result = await session.call_tool(
                                "calculate_tax_liability",
                                {"principal": operands[0]},
                            )
                        else:
                            result = await session.call_tool(
                                "tamper_proof_audit_math",
                                {"operation": operation, "operands": operands},
                            )

                        response_data = json.loads(self._safe_text(result))

                        if response_data.get("status") == "error":
                            logger.error(f"Server error: {response_data.get('message')}")
                            return None

                        logger.info("─── 🛡️  CRYPTOGRAPHIC AUDIT RECORD ───────────")
                        logger.info(f"  Operation  : {response_data['operation'].upper()}")
                        logger.info(f"  Exact Value: {response_data['exact_result']}")
                        logger.info(f"  SHA-256    : {response_data['audit_hash']}")
                        logger.info(f"  Timestamp  : {response_data.get('timestamp_utc', 'N/A')}")
                        logger.info("───────────────────────────────────────────────")

                        # Write audit hash to blackboard for downstream agents
                        write_result = await session.call_tool(
                            "write_blackboard",
                            {"key": "latest_tax_audit_hash", "data": response_data["audit_hash"]},
                        )
                        logger.info(f"Blackboard write: {self._safe_text(write_result)}")

                        return response_data

        except TimeoutError:
            logger.error("Connection timed out — RISHI server may be at capacity.")
            return None
        except json.JSONDecodeError as exc:
            logger.error(f"Malformed server response: {exc}")
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

    agent = DeterministicAuditAgent()
    # Passed as strings — avoids IEEE 754 floating-point rounding errors.
    asyncio.run(agent.execute_audit("multiply", ["15438290.4552", "0.0875"]))