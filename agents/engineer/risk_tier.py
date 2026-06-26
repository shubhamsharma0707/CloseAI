"""
risk_tier.py — Shared Risk Tier Definitions for Engineer
=========================================================
Defines once, used by all three sub-agents and the orchestrator.

Risk Tiers (mirrors Kavach's severity model):
  Tier 0 — Generate / read only. No approval required by default.
            Logged for reproducibility (what was generated, from what prompt).
  Tier 1 — Write files within workspace or run tests/linters/builds.
            Logged, no approval required. Auto-proceeds.
  Tier 2 — Git commit (local), git push, install/update a dependency.
            Approval required. request_human_approval() is called.
  Tier 3 — Deploy to any environment. Always requires approval + dual-control.
            Never auto-proceeds regardless of agent settings.

The classify_action() helper maps common action strings to their default tier.
Sub-agents may escalate (but not de-escalate) based on context.
"""

from enum import IntEnum
from typing import Optional


class RiskTier(IntEnum):
    """Lower = safer. Tier 3 is the highest risk, always requires human approval."""
    TIER_0_GENERATE = 0   # read / generate only — no mutation
    TIER_1_WRITE    = 1   # write files, run tests, lint, build
    TIER_2_COMMIT   = 2   # git commit, push, install dependency
    TIER_3_DEPLOY   = 3   # deploy to any environment — dual control required

    def requires_approval(self) -> bool:
        """Returns True if this tier requires explicit human approval."""
        return self >= RiskTier.TIER_2_COMMIT

    def requires_dual_control(self) -> bool:
        """Returns True if this tier requires two distinct approvers."""
        return self >= RiskTier.TIER_3_DEPLOY

    def __str__(self) -> str:
        labels = {
            0: "Tier 0 — Generate (no write)",
            1: "Tier 1 — Write / Run (logged, no approval)",
            2: "Tier 2 — Commit / Push / Install (approval required)",
            3: "Tier 3 — Deploy (approval + dual control)",
        }
        return labels[self.value]


# ── Action → Default Tier mapping ─────────────────────────────────────────
_ACTION_TIER_MAP: dict[str, RiskTier] = {
    # Tier 0
    "generate_code":         RiskTier.TIER_0_GENERATE,
    "generate_component":    RiskTier.TIER_0_GENERATE,
    "generate_image":        RiskTier.TIER_0_GENERATE,
    "read_file":             RiskTier.TIER_0_GENERATE,
    "list_directory":        RiskTier.TIER_0_GENERATE,
    # Tier 1
    "write_file":            RiskTier.TIER_1_WRITE,
    "run_tests":             RiskTier.TIER_1_WRITE,
    "run_linter":            RiskTier.TIER_1_WRITE,
    "run_build":             RiskTier.TIER_1_WRITE,
    "git_add":               RiskTier.TIER_1_WRITE,
    # Tier 2
    "git_commit":            RiskTier.TIER_2_COMMIT,
    "git_push":              RiskTier.TIER_2_COMMIT,
    "install_dependency":    RiskTier.TIER_2_COMMIT,
    "update_dependency":     RiskTier.TIER_2_COMMIT,
    # Tier 3
    "deploy":                RiskTier.TIER_3_DEPLOY,
    "deploy_production":     RiskTier.TIER_3_DEPLOY,
    "deploy_staging":        RiskTier.TIER_3_DEPLOY,
}


def classify_action(action_type: str) -> RiskTier:
    """
    Returns the default RiskTier for the given action_type string.
    Unknown actions default to Tier 2 (approval required) — fail-safe.

    Sub-agents may escalate the returned tier but must not de-escalate it.
    """
    action_lower = action_type.lower().strip()
    tier = _ACTION_TIER_MAP.get(action_lower)
    if tier is None:
        # Unknown action — conservative default
        return RiskTier.TIER_2_COMMIT
    return tier


def describe_tier(tier: RiskTier) -> dict:
    """Returns a human-readable dict suitable for audit logs."""
    return {
        "tier": tier.value,
        "label": str(tier),
        "requires_approval": tier.requires_approval(),
        "requires_dual_control": tier.requires_dual_control(),
    }
