"""
Phase 1 — Quantitative: Auditability Agent
Reads the cryptographic audit hash from the shared blackboard and
writes it to an append-only immutable ledger file.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..', '..'))
from utils.compat import async_timeout
del _sys, _os

from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger("Chanakya.Agent02_Auditability")

# Ledger file is anchored to this source file's directory — not CWD.
_LEDGER_PATH = Path(__file__).parent / "chanakya_immutable_ledger.log"


class AuditabilityAgent:
    def __init__(self, server_url: str = "http://127.0.0.1:8000/sse"):
        self.server_url = server_url
        self.agent_id = "agent_chanakya_auditability"
        self.token = os.getenv("AGENT_TOKEN_AGENT_CHANAKYA_AUDITABILITY", "")
        self.headers = {
            "x-agent-id": self.agent_id,
            "x-agent-token": f"Bearer {self.token}",
        }
        self.ledger_path = _LEDGER_PATH

    def _safe_text(self, result) -> str:
        if not result.content:
            return "Error: Empty server response."
        return result.content[0].text

    def _write_to_ledger(self, data_key: str, hash_value: str) -> None:
        """
        Appends one tamper-evident line to the immutable ledger.
        Uses UTC timestamps so the log is timezone-agnostic and portable.
        In production, consider WORM storage or a hash-chained ledger.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = f"[{timestamp}] SOURCE_KEY: {data_key} | CRYPTO_HASH: {hash_value}\n"
        with self.ledger_path.open("a", encoding="utf-8") as f:
            f.write(entry)

    async def secure_ledger_entry(self, target_key: str) -> bool:
        """
        Reads *target_key* from the RISHI blackboard and permanently records
        its value in the local immutable ledger.

        Returns True on success, False on any failure.
        """
        logger.info(f"Auditing blackboard key: '{target_key}'")

        try:
            async with async_timeout(15.0):
                async with sse_client(url=self.server_url, headers=self.headers) as (r, w):
                    async with ClientSession(r, w) as session:
                        await session.initialize()
                        logger.info("Audit channel established.")

                        result = await session.call_tool(
                            "read_blackboard",
                            {"key": target_key},
                        )

                        value = self._safe_text(result)
                        if value.startswith("Error:"):
                            logger.error(f"Blackboard read failed: {value}")
                            return False

                        self._write_to_ledger(target_key, value)

                        logger.info("─── 🔒  IMMUTABLE LEDGER UPDATED ──────────────")
                        logger.info(f"  File  : {self.ledger_path}")
                        logger.info(f"  Key   : {target_key}")
                        logger.info(f"  Hash  : {value}")
                        logger.info("───────────────────────────────────────────────")

                        return True

        except TimeoutError:
            logger.error("Connection timed out during ledger audit.")
            return False
        except Exception as exc:
            cause = str(exc)
            if "refused" in cause or "TaskGroup" in cause or "ExceptionGroup" in cause:
                logger.error(
                    "Cannot reach RISHI server at http://127.0.0.1:8000 — "
                    "is 'python3 RISHI.py' running? (run setup_dev.py first)"
                )
            else:
                logger.error(f"Ledger audit failure: {exc}")
            return False
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            logger.error(
                "Cannot reach RISHI server — "
                "is 'python3 RISHI.py' running? (run setup_dev.py first)"
            )
            return False


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from utils.logger_config import configure_logging
    configure_logging()

    agent = AuditabilityAgent()
    asyncio.run(agent.secure_ledger_entry("latest_tax_audit_hash"))