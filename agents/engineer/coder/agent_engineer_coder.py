"""
agent_engineer_coder.py — CoderAI Sub-Agent
============================================
CoderAI handles code generation and execution for Engineer.

Architecture (from the plan):
  • Calls Ollama (llama3.1:8b) for code generation — reuses existing connection.
  • WorkspaceGuard.check() before every file write.
  • Shell exec via sandboxed shell_exec (allowlisted binaries only).
  • Every action → RISHI /engineer/audit via log_audit_event.
  • Risk tiers: Tier 0 (generate), Tier 1 (write/run), Tier 2 (commit/push).

Relationship to Engineer Orchestrator:
  • Orchestrator dispatches tasks here; CoderAI does NOT call RISHI approvals
    directly for Tier 2 — it raises NeedsApprovalError and the orchestrator
    holds the single RISHI approval relationship.
"""

import asyncio
import json
import logging
import os
import sys

# ── Robust path bootstrap (CWD-independent) ───────────────────────────────
def _project_root() -> str:
    p = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.exists(os.path.join(p, "RISHI.py")):
            return p
        p = os.path.dirname(p)
    return p

_PROJECT_ROOT  = _project_root()
_ENGINEER_ROOT = os.path.join(_PROJECT_ROOT, "agents", "engineer")
_KAVACH_AUTH   = os.path.join(_PROJECT_ROOT, "agents", "kavach", "authorization")

# Insert in reverse priority order — last insert(0,...) wins, so _ENGINEER_ROOT
# ends up at sys.path[0], shadowing Kavach's audit_client correctly.
for _p in (_PROJECT_ROOT, _KAVACH_AUTH, _ENGINEER_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"), override=False)

from authorization.workspace_guard import WorkspaceGuard
from audit_client import log_audit_event
from kill_switch_client import check_kill_switch
from risk_tier import RiskTier, classify_action

from coder.tools.file_io import write_file, read_file
from coder.tools.shell_exec import shell_exec
from coder.tools.git_tool import git_add, git_commit, git_status
from coder.tools.test_runner import run_pytest, run_npm_test, run_build

logger = logging.getLogger("Engineer.CoderAI")

AGENT_ID   = "AGENT_ENGINEER_CODER"
RISHI_BASE = os.getenv("RISHI_BASE_URL", "http://127.0.0.1:8000")


class NeedsApprovalError(Exception):
    """
    Raised when CoderAI reaches a Tier 2+ action.
    The orchestrator catches this, requests RISHI approval, and re-dispatches.
    """
    def __init__(self, action_type: str, context: dict):
        super().__init__(f"Action '{action_type}' requires human approval.")
        self.action_type = action_type
        self.context     = context


class CoderAI:
    """
    CoderAI — code generation and execution sub-agent.

    All public methods return a dict with at least:
      {"status": "OK"|"ERROR"|"NEEDS_APPROVAL", "result": ..., "tier": <int>}
    """

    def __init__(self):
        logger.info("💻 Initializing CoderAI Sub-Agent...")
        self.workspace_guard = WorkspaceGuard()
        logger.info("✅ CoderAI ready.")

    # ------------------------------------------------------------------
    # Tier 0 — Generate only (no write)
    # ------------------------------------------------------------------

    async def generate_code(
        self,
        prompt: str,
        language: str = "python",
        context_files: list[str] | None = None,
    ) -> dict:
        """
        Ask Ollama to generate code. Returns the generated string — does NOT
        write to disk. Tier 0.
        """
        if check_kill_switch():
            logger.error("[CoderAI] Kill switch ACTIVE — aborting generate_code.")
            return {"status": "ERROR", "result": "Kill switch active.", "tier": 0}

        log_audit_event(AGENT_ID, "GENERATE_CODE_START", {
            "language": language,
            "prompt_snippet": prompt[:200],
        })

        # Build context from files if provided
        file_context = ""
        if context_files:
            for fp in context_files:
                try:
                    content = read_file(fp)
                    file_context += f"\n\n--- {fp} ---\n{content}"
                except Exception as exc:
                    logger.warning(f"[CoderAI] Could not read context file {fp}: {exc}")

        system_prompt = f"""You are CoderAI, a senior software engineer.
Generate clean, well-commented {language} code that solves the user's request.
Respond ONLY with the code block — no explanations, no markdown preamble.
Do not wrap in triple backticks unless asked."""

        user_message = prompt
        if file_context:
            user_message += f"\n\nExisting code context:{file_context}"

        try:
            from ollama import AsyncClient
            response = await AsyncClient().chat(
                model="llama3.1:8b",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
            )
            msg = response.get("message", {}) if isinstance(response, dict) else None
            if msg is not None:
                generated = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            else:
                generated = getattr(getattr(response, "message", None), "content", "")

            log_audit_event(AGENT_ID, "GENERATE_CODE_END", {
                "language": language,
                "output_chars": len(generated),
                "status": "OK",
            })
            logger.info(f"[CoderAI] Generated {len(generated)} chars of {language} code.")
            return {"status": "OK", "result": generated, "tier": RiskTier.TIER_0_GENERATE}

        except Exception as exc:
            logger.error(f"[CoderAI] Ollama error: {exc}")
            log_audit_event(AGENT_ID, "GENERATE_CODE_ERROR", {"error": str(exc)})
            return {"status": "ERROR", "result": str(exc), "tier": RiskTier.TIER_0_GENERATE}

    # ------------------------------------------------------------------
    # Tier 1 — Write file
    # ------------------------------------------------------------------

    async def write_code_to_file(self, path: str, content: str) -> dict:
        """Write generated code to a workspace file. Tier 1."""
        if check_kill_switch():
            return {"status": "ERROR", "result": "Kill switch active.", "tier": 1}

        try:
            real_path = write_file(path, content, agent_id=AGENT_ID)
            return {"status": "OK", "result": real_path, "tier": RiskTier.TIER_1_WRITE}
        except PermissionError as exc:
            return {"status": "ERROR", "result": str(exc), "tier": RiskTier.TIER_1_WRITE}

    # ------------------------------------------------------------------
    # Tier 1 — Run tests / linter / build
    # ------------------------------------------------------------------

    async def run_tests(self, cwd: str, framework: str = "pytest") -> dict:
        """Run test suite. Tier 1."""
        if check_kill_switch():
            return {"status": "ERROR", "result": "Kill switch active.", "tier": 1}

        if framework == "pytest":
            result = await run_pytest(cwd)
        elif framework in ("npm", "jest"):
            result = await run_npm_test(cwd)
        else:
            return {"status": "ERROR", "result": f"Unknown test framework: {framework}", "tier": 1}

        return {
            "status": "OK" if result.success else "ERROR",
            "result": result.stdout + result.stderr,
            "returncode": result.returncode,
            "tier": RiskTier.TIER_1_WRITE,
        }

    async def run_build_pipeline(self, cwd: str, tool: str = "npm") -> dict:
        """Run build. Tier 1."""
        if check_kill_switch():
            return {"status": "ERROR", "result": "Kill switch active.", "tier": 1}

        result = await run_build(cwd, tool=tool)
        return {
            "status": "OK" if result.success else "ERROR",
            "result": result.stdout + result.stderr,
            "tier": RiskTier.TIER_1_WRITE,
        }

    # ------------------------------------------------------------------
    # Tier 2 — Git commit (raises NeedsApprovalError if not pre-approved)
    # ------------------------------------------------------------------

    async def commit_changes(
        self,
        cwd: str,
        message: str,
        approval_id: str | None = None,
    ) -> dict:
        """
        Stage all changes and commit. Tier 2.
        Raises NeedsApprovalError if approval_id is not provided.
        The orchestrator catches this, gets RISHI approval, and re-calls
        with approval_id embedded.
        """
        if check_kill_switch():
            return {"status": "ERROR", "result": "Kill switch active.", "tier": 2}

        if not approval_id:
            raise NeedsApprovalError(
                action_type="git_commit",
                context={"cwd": cwd, "message": message},
            )

        await git_add(cwd)
        result = await git_commit(cwd, message=f"{message} [approval:{approval_id}]")
        return {
            "status": "OK" if result.success else "ERROR",
            "result": result.stdout + result.stderr,
            "tier": RiskTier.TIER_2_COMMIT,
            "approval_id": approval_id,
        }
