"""
file_io.py — WorkspaceGuard-gated file I/O for CoderAI
=======================================================
Every file read/write goes through WorkspaceGuard before touching the disk.
Writes are also logged to RISHI's /engineer/audit ledger.
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

from authorization.workspace_guard import WorkspaceGuard
from audit_client import log_audit_event

logger = logging.getLogger("Engineer.CoderAI.FileIO")

_guard = WorkspaceGuard()


def read_file(path: str, agent_id: str = "AGENT_ENGINEER_CODER") -> str:
    """
    Read a file within the workspace. Fail-closed if path is outside workspace.
    Returns file contents as a string, or raises PermissionError / FileNotFoundError.
    """
    result = _guard.check("read", path)
    if not result.allowed:
        logger.warning(f"[FileIO] READ DENIED: {result.reason} → {path}")
        raise PermissionError(f"WorkspaceGuard: {result.reason} for path: {path}")

    with open(result.path, "r", encoding="utf-8") as f:
        content = f.read()

    logger.info(f"[FileIO] READ OK: {result.path} ({len(content)} chars)")
    return content


def write_file(
    path: str,
    content: str,
    agent_id: str = "AGENT_ENGINEER_CODER",
    overwrite: bool = True,
) -> str:
    """
    Write content to path within the workspace.
    Logs the write action to RISHI audit ledger before writing.
    Returns the real path written.
    """
    result = _guard.check("write", path)
    if not result.allowed:
        logger.warning(f"[FileIO] WRITE DENIED: {result.reason} → {path}")
        log_audit_event(agent_id, "FILE_WRITE_DENIED", {
            "path": path, "reason": result.reason,
        })
        raise PermissionError(f"WorkspaceGuard: {result.reason} for path: {path}")

    if not overwrite and os.path.exists(result.path):
        raise FileExistsError(f"File already exists and overwrite=False: {result.path}")

    # Log before writing — reproducibility of "what was written from what prompt"
    log_audit_event(agent_id, "FILE_WRITE_START", {
        "path": result.path,
        "content_bytes": len(content.encode()),
    })

    os.makedirs(os.path.dirname(result.path), exist_ok=True)
    with open(result.path, "w", encoding="utf-8") as f:
        f.write(content)

    log_audit_event(agent_id, "FILE_WRITE_END", {
        "path": result.path,
        "content_bytes": len(content.encode()),
        "status": "OK",
    })
    logger.info(f"[FileIO] WRITE OK: {result.path}")
    return result.path
