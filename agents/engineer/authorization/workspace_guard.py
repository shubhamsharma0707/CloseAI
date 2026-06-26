"""
workspace_guard.py — Engineer WorkspaceGuard
=============================================
Enforces file-write boundaries for CoderAI and GenerativeAI.

Mirrors Kavach's ScopeGuard pattern exactly:
  • WorkspaceGuard.check(action, str, path) → GuardResult
  • Fail-closed: anything not explicitly in the allowlist is denied.
  • Protected patterns are hard-coded and not configurable per-task —
    .env, .git/config, secrets/ cannot be widened by any LLM output or flag.

Usage:
    from authorization.workspace_guard import WorkspaceGuard
    guard = WorkspaceGuard(project_root="/path/to/repo")
    result = guard.check(action="write", path="/path/to/repo/src/foo.py")
    if not result.allowed:
        raise PermissionError(result.reason)
"""

import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("Engineer.WorkspaceGuard")

# ── Protected path patterns (hard-coded, cannot be widened) ───────────────
_PROTECTED_PATTERNS: list[str] = [
    r"\.env$",
    r"\.env\.",          # .env.local, .env.production, etc.
    r"\.git/config$",
    r"\.git/hooks/",
    r"secrets/",
    r"\.ssh/",
    r"credentials",
    r"private_key",
    r"id_rsa",
    r"\.pem$",
    r"\.key$",
]

_COMPILED_PATTERNS = [re.compile(p) for p in _PROTECTED_PATTERNS]


@dataclass
class GuardResult:
    """Mirrors Kavach's GuardResult shape so callers can use the same pattern."""
    allowed: bool
    reason: str
    path: Optional[str] = None
    action: Optional[str] = None


class WorkspaceGuard:
    """
    Path-allowlist guard for Engineer sub-agents.

    Rules:
    1. The target path must be within project_root (or configured workspace).
    2. The target path must NOT match any _PROTECTED_PATTERNS.
    3. If either check fails → GuardResult(allowed=False).
    4. No engagement record needed — workspace boundary is set at init time
       from setup_dev.py / env var, not from agent runtime input.
    """

    def __init__(self, project_root: Optional[str] = None):
        # Default: two levels up from this file = CloseAI repo root
        self._root = os.path.realpath(
            project_root
            or os.getenv(
                "ENGINEER_PROJECT_ROOT",
                os.path.join(os.path.dirname(__file__), "..", "..", ".."),
            )
        )
        logger.info(f"[WorkspaceGuard] Initialized. Root: {self._root}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, action: str, path: str) -> GuardResult:
        """
        Returns GuardResult(allowed=True) iff path is safe to act on.

        Parameters
        ----------
        action : str
            Human-readable action name, e.g. "write", "read", "delete".
        path : str
            Absolute or relative file-system path the agent wants to touch.
        """
        real_path = os.path.realpath(os.path.abspath(path))

        # 1. Must be within workspace root
        if not real_path.startswith(self._root + os.sep) and real_path != self._root:
            logger.warning(
                f"[WorkspaceGuard] DENIED {action} → PATH_OUTSIDE_WORKSPACE: {real_path}"
            )
            return GuardResult(
                allowed=False,
                reason="PATH_OUTSIDE_WORKSPACE",
                path=real_path,
                action=action,
            )

        # 2. Must not match any protected pattern
        rel_path = os.path.relpath(real_path, self._root)
        for pattern in _COMPILED_PATTERNS:
            if pattern.search(rel_path):
                logger.warning(
                    f"[WorkspaceGuard] DENIED {action} → PROTECTED_PATH ({pattern.pattern}): {rel_path}"
                )
                return GuardResult(
                    allowed=False,
                    reason=f"PROTECTED_PATH ({pattern.pattern})",
                    path=real_path,
                    action=action,
                )

        logger.info(f"[WorkspaceGuard] ALLOWED {action} → {rel_path}")
        return GuardResult(allowed=True, reason="ALLOWED", path=real_path, action=action)
