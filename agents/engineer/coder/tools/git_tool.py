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

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
_KAVACH_AUTH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "kavach", "authorization")
for _p in (_ROOT, _KAVACH_AUTH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools.shell_exec import shell_exec, ShellExecResult
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
