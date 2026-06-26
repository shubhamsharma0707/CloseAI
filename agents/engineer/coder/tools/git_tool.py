"""
git_tool.py — Tier 1/2 Git operations for CoderAI
===================================================
`git add`  → Tier 1 (logged, no approval)
`git commit` → Tier 2 (logged, requires approval via RISHI)

`git push` is also Tier 2 — approval must be obtained before calling push().
The orchestrator is responsible for calling request_human_approval() and
verifying the decision before dispatching any Tier 2 git action.
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
    if _p in sys.path: sys.path.remove(_p)
    sys.path.insert(0, _p)

from coder.tools.shell_exec import shell_exec, ShellExecResult
from audit_client import log_audit_event

logger = logging.getLogger("Engineer.CoderAI.GitTool")

AGENT_ID = "AGENT_ENGINEER_CODER"


async def git_add(cwd: str, paths: list[str] | None = None) -> ShellExecResult:
    """
    Stage files for commit. Defaults to `git add -A` if paths is None/empty.
    Tier 1 — logged, no approval required.
    """
    args = paths if paths else ["-A"]
    cmd = ["git", "add"] + args
    log_audit_event(AGENT_ID, "GIT_ADD", {"cwd": cwd, "args": args})
    return await shell_exec(cmd, cwd=cwd, agent_id=AGENT_ID)


async def git_commit(cwd: str, message: str) -> ShellExecResult:
    """
    Create a local commit. Tier 2 — caller MUST have obtained approval before
    calling this function. The approval_id should be embedded in the message.
    """
    if not message or len(message.strip()) < 3:
        raise ValueError("Commit message must be at least 3 characters.")

    cmd = ["git", "commit", "-m", message]
    log_audit_event(AGENT_ID, "GIT_COMMIT", {"cwd": cwd, "message": message})
    return await shell_exec(cmd, cwd=cwd, agent_id=AGENT_ID)


async def git_push(cwd: str, remote: str = "origin", branch: str = "HEAD") -> ShellExecResult:
    """
    Push to remote. Tier 2 — caller MUST have obtained approval before calling.
    """
    cmd = ["git", "push", remote, branch]
    log_audit_event(AGENT_ID, "GIT_PUSH", {"cwd": cwd, "remote": remote, "branch": branch})
    return await shell_exec(cmd, cwd=cwd, timeout=120, agent_id=AGENT_ID)


async def git_status(cwd: str) -> ShellExecResult:
    """Read-only status check. Tier 0."""
    return await shell_exec(["git", "status", "--short"], cwd=cwd, agent_id=AGENT_ID)
