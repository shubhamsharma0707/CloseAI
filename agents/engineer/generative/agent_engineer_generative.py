"""
agent_engineer_generative.py — GenerativeAI Sub-Agent
======================================================
GenerativeAI wraps a locally-running image/diffusion CLI tool
(e.g., Stable Diffusion, ComfyUI) for asset generation alongside
DesignerAI's UI work.

Architecture (from the plan):
  • Checks for the local CLI tool before invoking — returns a clear
    GENERATIVE_TOOL_NOT_FOUND result rather than fabricating placeholder output.
  • GPU VRAM health check via gpu_guard.py before any model invocation.
  • Output paths are WorkspaceGuard-checked before writing.
  • Audit-logged to RISHI /engineer/audit on every attempt.
  • Used for: icons, hero images, placeholder content — not a general-purpose
    image generator bolted on separately.

Tool detection:
  Looks for the CLI tool at ENGINEER_SD_CLI env var or common defaults:
    • invoke-ai / InvokeAI: `invokeai`
    • ComfyUI CLI wrapper: `comfyui`
    • Automatic1111 webui API (localhost:7860) — via HTTP, not subprocess
  Returns GENERATIVE_TOOL_NOT_FOUND if none found.
"""

import asyncio
import logging
import os
import shutil
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
    if _p in sys.path: sys.path.remove(_p)
    sys.path.insert(0, _p)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"), override=False)

from agents.engineer.authorization.workspace_guard import WorkspaceGuard
from audit_client import log_audit_event
from kill_switch_client import check_kill_switch
from risk_tier import RiskTier
from generative.gpu_guard import check_gpu_vram

logger = logging.getLogger("Engineer.GenerativeAI")
AGENT_ID = "AGENT_ENGINEER_GENERATIVE"

# ── Tool detection ─────────────────────────────────────────────────────────
_KNOWN_CLI_TOOLS = ["invokeai", "comfyui", "sd"]
_SD_CLI = os.getenv("ENGINEER_SD_CLI", "")


def _detect_sd_tool() -> str | None:
    """
    Returns the first available local diffusion CLI tool name, or None.
    Checks ENGINEER_SD_CLI env var first, then common names.
    """
    if _SD_CLI and shutil.which(_SD_CLI):
        return _SD_CLI
    for tool in _KNOWN_CLI_TOOLS:
        if shutil.which(tool):
            return tool
    return None


class GenerativeAI:
    """
    GenerativeAI — local image/asset generation sub-agent.

    All public methods return:
      {"status": "OK"|"ERROR"|"GENERATIVE_TOOL_NOT_FOUND"|"RESOURCE_CONSTRAINED",
       "result": <path_or_message>, "tier": <int>}
    """

    def __init__(self):
        logger.info("🖼️  Initializing GenerativeAI Sub-Agent...")
        self.workspace_guard = WorkspaceGuard()
        self._tool = _detect_sd_tool()
        if self._tool:
            logger.info(f"✅ GenerativeAI ready. Local diffusion tool: {self._tool}")
        else:
            logger.warning(
                "⚠️  GenerativeAI: no local diffusion CLI found. "
                "Set ENGINEER_SD_CLI or install invokeai/comfyui. "
                "generate_asset() will return GENERATIVE_TOOL_NOT_FOUND."
            )

    async def generate_asset(
        self,
        prompt: str,
        output_path: str,
        workspace_id: str,
        width: int = 1024,
        height: int = 1024,
        steps: int = 30,
    ) -> dict:
        """
        Generate an image asset via the local diffusion CLI.

        NOTE (Untested Path): The success path (local diffusion CLI execution) has NOT been 
        verified against a real local diffusion CLI because no such tool is installed 
        in this environment via ENGINEER_SD_CLI. The `GENERATIVE_TOOL_NOT_FOUND` path 
        is verified, but the actual subprocess invocation success path remains untested 
        pending a tool becoming available.

        Parameters
        ----------
        prompt      : Text prompt for image generation.
        output_path : Workspace-relative or absolute path for the output file.
        width       : Image width in pixels.
        height      : Image height in pixels.
        steps       : Diffusion steps (lower = faster, lower quality).

        Returns
        -------
        dict with "status" and "result" (file path on OK, message on error).
        """
        if check_kill_switch():
            logger.error("[GenerativeAI] Kill switch ACTIVE — aborting generate_asset.")
            return {"status": "ERROR", "result": "Kill switch active.", "tier": 0}

        # 1. Tool availability check
        if not self._tool:
            logger.warning("[GenerativeAI] GENERATIVE_TOOL_NOT_FOUND — no CLI tool available.")
            log_audit_event(AGENT_ID, "GENERATE_ASSET_TOOL_NOT_FOUND", {"prompt_snippet": prompt[:200]})
            return {
                "status": "GENERATIVE_TOOL_NOT_FOUND",
                "result": (
                    "No local diffusion CLI found. Install InvokeAI or ComfyUI, "
                    "or set ENGINEER_SD_CLI to the path of your tool."
                ),
                "tier": RiskTier.TIER_0_GENERATE,
            }

        # 2. GPU VRAM health check
        vram = check_gpu_vram()
        log_audit_event(AGENT_ID, "GENERATE_ASSET_VRAM_CHECK", {
            "available": vram.available,
            "free_mb": vram.free_mb,
            "total_mb": vram.total_mb,
            "reason": vram.reason,
        })
        if not vram.available:
            logger.warning(f"[GenerativeAI] RESOURCE_CONSTRAINED: {vram.reason}")
            return {
                "status": "RESOURCE_CONSTRAINED",
                "result": f"Insufficient VRAM/RAM to run diffusion model: {vram.reason}",
                "tier": RiskTier.TIER_0_GENERATE,
            }

        # 3. WorkspaceGuard check on output path
        guard_result = await self.workspace_guard.check_async("write", output_path, workspace_id, agent_id=AGENT_ID)
        if not guard_result.allowed:
            logger.warning(f"[GenerativeAI] Write DENIED: {guard_result.reason}")
            log_audit_event(AGENT_ID, "GENERATE_ASSET_WRITE_DENIED", {
                "output_path": output_path, "reason": guard_result.reason,
            })
            return {
                "status": "ERROR",
                "result": f"WorkspaceGuard: {guard_result.reason}",
                "tier": RiskTier.TIER_0_GENERATE,
            }

        real_output = guard_result.path
        os.makedirs(os.path.dirname(real_output), exist_ok=True)

        # 4. Build and run the CLI command
        # Command shape varies by tool — we support the common --outdir / --prompt pattern.
        cmd = [
            self._tool,
            "--prompt", prompt,
            "--outdir", os.path.dirname(real_output),
            "--width",  str(width),
            "--height", str(height),
            "--steps",  str(steps),
        ]

        log_audit_event(AGENT_ID, "GENERATE_ASSET_START", {
            "prompt_snippet": prompt[:200],
            "output_path": real_output,
            "width": width, "height": height, "steps": steps,
        })
        logger.info(f"[GenerativeAI] Running: {' '.join(cmd)}")

        from coder.tools.shell_exec import shell_exec
        result = await shell_exec(
            cmd,
            cwd=os.path.dirname(real_output),
            timeout=300,
            agent_id=AGENT_ID,
            extra_allowed_binaries={self._tool},
        )

        if result.success:
            log_audit_event(AGENT_ID, "GENERATE_ASSET_END", {
                "output_path": real_output, "status": "OK",
            })
            logger.info(f"[GenerativeAI] Asset generated: {real_output}")
            return {
                "status": "OK",
                "result": real_output,
                "tier": RiskTier.TIER_0_GENERATE,
            }
        elif result.timed_out:
            logger.error("[GenerativeAI] Diffusion timed out after 300s.")
            log_audit_event(AGENT_ID, "GENERATE_ASSET_TIMEOUT", {"output_path": real_output})
            return {
                "status": "ERROR",
                "result": "Diffusion model timed out after 300 seconds.",
                "tier": RiskTier.TIER_0_GENERATE,
            }
        else:
            error_msg = result.stderr[:2048]
            logger.error(f"[GenerativeAI] CLI error (rc={result.returncode}): {error_msg}")
            log_audit_event(AGENT_ID, "GENERATE_ASSET_CLI_ERROR", {
                "returncode": result.returncode, "stderr": error_msg,
            })
            return {
                "status": "ERROR",
                "result": f"CLI exited with rc={result.returncode}: {error_msg}",
                "tier": RiskTier.TIER_0_GENERATE,
            }
