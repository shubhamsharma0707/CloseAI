"""
agents/engineer/authorization/__init__.py
==========================================
Thin re-export layer so Engineer sub-agents import from a single location.
The actual implementations live in Kavach's authorization/ directory —
same signing scheme, same RISHI endpoints, same audit trail.

This is intentional: the plan specifies "import, don't reimplement".
"""

import sys
import os

# ── Ensure Kavach's authorization package is on the path ──────────────────
_KAVACH_AUTH = os.path.join(
    os.path.dirname(__file__), "..", "..", "kavach", "authorization"
)
if _KAVACH_AUTH not in sys.path:
    sys.path.insert(0, _KAVACH_AUTH)

# Re-export the Kavach authorization modules for Engineer's use.
from scope_guard import ScopeGuard, GuardResult          # noqa: F401
from audit_client import log_audit_event                  # noqa: F401
from approval_client import (                             # noqa: F401
    request_human_approval,
    poll_for_decision,
    DecisionRecord,
)
from kill_switch_client import (                          # noqa: F401
    check_kill_switch,
    check_kill_switch_async,
)

__all__ = [
    "ScopeGuard",
    "GuardResult",
    "log_audit_event",
    "request_human_approval",
    "poll_for_decision",
    "DecisionRecord",
    "check_kill_switch",
    "check_kill_switch_async",
]
