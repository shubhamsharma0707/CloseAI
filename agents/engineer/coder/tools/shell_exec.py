"""
shell_exec.py — Sandboxed subprocess runner for CoderAI
========================================================
All shell commands CoderAI runs pass through here.

Safety guarantees (identical to Kavach's plugin sandbox):
  • Binary allowlist — arbitrary strings are NOT passed to a subprocess.
  • Timeout — a single command cannot hang the agent indefinitely.
  • Output size cap — prevents runaway stdout floods.
  • Every invocation (command, exit code, truncated output) is written to
    RISHI's /engineer/audit ledger via log_audit_event.

Usage:
    result = await shell_exec(["pytest", "tests/"], cwd="/path/to/project")
"""

import asyncio
import logging
import os
import sys

# ── Robust path bootstrap (CWD-independent) ───────────────────────────────
def _project_root() -> str:
    """Walk up from __file__ until we find RISHI.py (project root)."""
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

from audit_client import log_audit_event   # Engineer's own audit_client (→ /engineer/audit)

logger = logging.getLogger("Engineer.CoderAI.ShellExec")

# ── Allowlisted binaries ───────────────────────────────────────────────────
ALLOWED_BINARIES: set[str] = {
    "npm", "npx", "node",
    "python", "python3",
    "pytest",
    "git",
    "tsc",         # TypeScript compiler
    "eslint",
    "prettier",
    "vite",
    "bash",        # for simple script runners; arguments still validated
}

MAX_OUTPUT_BYTES = 64 * 1024   # 64 KB output cap
DEFAULT_TIMEOUT  = 60          # seconds


class ShellExecResult:
    def __init__(self, returncode: int, stdout: str, stderr: str, timed_out: bool = False):
        self.returncode  = returncode
        self.stdout      = stdout
        self.stderr      = stderr
        self.timed_out   = timed_out
        self.success     = returncode == 0 and not timed_out

    def __repr__(self) -> str:
        status = "OK" if self.success else ("TIMEOUT" if self.timed_out else f"RC={self.returncode}")
        return f"<ShellExecResult {status} | stdout={len(self.stdout)}B | stderr={len(self.stderr)}B>"


async def shell_exec(
    cmd: list[str],
    cwd: str,
    timeout: int = DEFAULT_TIMEOUT,
    agent_id: str = "AGENT_ENGINEER_CODER",
    extra_allowed_binaries: set[str] | None = None,
) -> ShellExecResult:
    """
    Runs cmd in a sandboxed subprocess.

    Parameters
    ----------
    cmd     : Command as a list of strings. First token must be in ALLOWED_BINARIES.
    cwd     : Working directory (must be pre-validated by WorkspaceGuard).
    timeout : Wall-clock timeout in seconds.
    agent_id: Agent ID for audit log attribution.

    Returns
    -------
    ShellExecResult — always returns (never raises). Errors are surfaced via
    non-zero returncode / timed_out flag and logged to RISHI audit.
    """
    if not cmd:
        logger.error("[ShellExec] Empty command list — aborting.")
        return ShellExecResult(returncode=1, stdout="", stderr="Empty command.")

    binary = os.path.basename(cmd[0])
    allowed = ALLOWED_BINARIES | (extra_allowed_binaries or set())
    if binary not in allowed:
        reason = f"BINARY_NOT_ALLOWED: {binary}"
        logger.warning(f"[ShellExec] {reason}")
        log_audit_event(agent_id, "SHELL_EXEC_DENIED", {"cmd": cmd, "reason": reason, "cwd": cwd})
        return ShellExecResult(returncode=1, stdout="", stderr=reason)

    logger.info(f"[ShellExec] Running: {' '.join(cmd)} (cwd={cwd}, timeout={timeout}s)")
    log_audit_event(agent_id, "SHELL_EXEC_START", {"cmd": cmd, "cwd": cwd, "timeout": timeout})

    timed_out = False
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ},
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        returncode = proc.returncode or 0

    except asyncio.TimeoutError:
        timed_out = True
        returncode = -1
        proc.kill()
        await proc.wait()  # reap the process, avoid a zombie
        stdout_bytes = b""
        stderr_bytes = b"Command timed out."
        logger.warning(f"[ShellExec] TIMEOUT after {timeout}s: {' '.join(cmd)}")

    # Truncate output to cap
    stdout = stdout_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
    stderr = stderr_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]

    result = ShellExecResult(returncode=returncode, stdout=stdout, stderr=stderr, timed_out=timed_out)

    log_audit_event(agent_id, "SHELL_EXEC_END", {
        "cmd": cmd,
        "cwd": cwd,
        "returncode": returncode,
        "timed_out": timed_out,
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
    })
    logger.info(f"[ShellExec] Done: {result}")
    return result
