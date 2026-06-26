"""
test_runner.py — Tier 1 test/lint/build runner for CoderAI
============================================================
Wraps shell_exec for common development workflows:
  • pytest / npm test
  • eslint / prettier
  • npm run build / vite build / tsc

All Tier 1: logged, no approval required.
"""

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

_ROOT        = _project_root()
_ENGINEER    = os.path.join(_ROOT, "agents", "engineer")
_KAVACH_AUTH = os.path.join(_ROOT, "agents", "kavach", "authorization")
# Insert in reverse priority order — last insert(0,...) wins, so _ENGINEER
# ends up at sys.path[0], shadowing Kavach's audit_client correctly.
for _p in (_ROOT, _KAVACH_AUTH, _ENGINEER):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from coder.tools.shell_exec import shell_exec, ShellExecResult
from audit_client import log_audit_event

logger = logging.getLogger("Engineer.CoderAI.TestRunner")
AGENT_ID = "AGENT_ENGINEER_CODER"


async def run_pytest(cwd: str, args: list[str] | None = None) -> ShellExecResult:
    """Run pytest in the given directory. Tier 1."""
    cmd = ["pytest"] + (args or ["-v", "--tb=short"])
    log_audit_event(AGENT_ID, "RUN_PYTEST", {"cwd": cwd, "args": cmd})
    return await shell_exec(cmd, cwd=cwd, timeout=300, agent_id=AGENT_ID)


async def run_npm_test(cwd: str, args: list[str] | None = None) -> ShellExecResult:
    """Run npm test in the given directory. Tier 1."""
    cmd = ["npm", "test"] + (args or [])
    log_audit_event(AGENT_ID, "RUN_NPM_TEST", {"cwd": cwd, "args": cmd})
    return await shell_exec(cmd, cwd=cwd, timeout=300, agent_id=AGENT_ID)


async def run_linter(cwd: str, paths: list[str] | None = None) -> ShellExecResult:
    """Run eslint. Tier 1."""
    cmd = ["eslint"] + (paths or ["."])
    log_audit_event(AGENT_ID, "RUN_LINTER", {"cwd": cwd, "paths": paths})
    return await shell_exec(cmd, cwd=cwd, timeout=120, agent_id=AGENT_ID)


async def run_build(cwd: str, tool: str = "npm") -> ShellExecResult:
    """
    Run a build command. Tier 1.
    tool: 'npm' → `npm run build`, 'vite' → `vite build`, 'tsc' → `tsc`
    """
    if tool == "npm":
        cmd = ["npm", "run", "build"]
    elif tool == "vite":
        cmd = ["vite", "build"]
    elif tool == "tsc":
        cmd = ["tsc"]
    else:
        raise ValueError(f"Unknown build tool: {tool}")

    log_audit_event(AGENT_ID, "RUN_BUILD", {"cwd": cwd, "tool": tool})
    return await shell_exec(cmd, cwd=cwd, timeout=300, agent_id=AGENT_ID)


async def run_prettier(cwd: str, paths: list[str] | None = None) -> ShellExecResult:
    """Run prettier formatter. Tier 1."""
    cmd = ["prettier", "--write"] + (paths or ["."])
    log_audit_event(AGENT_ID, "RUN_PRETTIER", {"cwd": cwd, "paths": paths})
    return await shell_exec(cmd, cwd=cwd, timeout=120, agent_id=AGENT_ID)
