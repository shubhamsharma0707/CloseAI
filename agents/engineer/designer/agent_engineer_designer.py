"""
agent_engineer_designer.py — DesignerAI Sub-Agent
==================================================
DesignerAI generates UI components and design specs for Engineer.

Architecture (from the plan):
  • Reads design tokens from frontend/src/style.css — single source of truth,
    not invented per-request.
  • Scaffolds new pages/components into the existing frontend/src/components/
    structure (doesn't introduce a parallel directory convention).
  • Tier 0 output — a generated component spec (JS string or JSX content).
    The output becomes Tier 1 only when CoderAI writes it to disk.
  • DesignerAI does NOT write files or run shell commands itself —
    it produces output that CoderAI's file_io writes.

Relationship to Engineer Orchestrator:
  • Multi-part requests (e.g., "build a login form") → Orchestrator dispatches
    DesignerAI for the component, CoderAI for the logic, as ordered sub-tasks.
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

from audit_client import log_audit_event
from kill_switch_client import check_kill_switch
from risk_tier import RiskTier

logger = logging.getLogger("Engineer.DesignerAI")
AGENT_ID = "AGENT_ENGINEER_DESIGNER"

# ── Paths ──────────────────────────────────────────────────────────────────
_FRONTEND_SRC       = os.path.join(_PROJECT_ROOT, "frontend", "src")
_DESIGN_TOKENS_FILE = os.path.join(_FRONTEND_SRC, "style.css")
_COMPONENTS_DIR     = os.path.join(_FRONTEND_SRC, "components")


def _load_design_tokens() -> str:
    """
    Load design tokens from the project's existing style.css.
    Returns the CSS content, or an empty string with a warning if not found.
    """
    if not os.path.exists(_DESIGN_TOKENS_FILE):
        logger.warning(f"[DesignerAI] style.css not found at {_DESIGN_TOKENS_FILE} — using empty tokens.")
        return ""
    with open(_DESIGN_TOKENS_FILE, "r", encoding="utf-8") as f:
        return f.read()


class DesignerAI:
    """
    DesignerAI — UI/UX component generation sub-agent.

    All public methods return a dict:
      {"status": "OK"|"ERROR", "result": <spec_string>, "tier": 0,
       "suggested_path": <where CoderAI should write it>}

    DesignerAI never writes files directly.
    """

    def __init__(self):
        logger.info("🎨 Initializing DesignerAI Sub-Agent...")
        self._design_tokens = _load_design_tokens()
        logger.info(f"✅ DesignerAI ready. Design tokens: {len(self._design_tokens)} chars.")

    def _build_system_prompt(self) -> str:
        tokens_snippet = self._design_tokens[:3000] if self._design_tokens else "(none loaded)"
        return f"""You are DesignerAI, a senior UI/UX engineer.
Apply design tokens consistently from the project's existing style.css — do not invent new color values.
Scaffold components into frontend/src/components/ — do not introduce new directories.
Respond ONLY with valid JavaScript/JSX code. No explanations, no markdown preamble.

--- Design Tokens (from style.css) ---
{tokens_snippet}
"""

    async def generate_component(
        self,
        component_name: str,
        description: str,
        props: list[str] | None = None,
    ) -> dict:
        """
        Generate a JS/JSX component spec. Tier 0.

        Parameters
        ----------
        component_name : PascalCase component name (e.g., "LoginForm")
        description    : Natural language description of the component's purpose
        props          : Optional list of prop names the component should accept
        """
        if check_kill_switch():
            logger.error("[DesignerAI] Kill switch ACTIVE — aborting generate_component.")
            return {"status": "ERROR", "result": "Kill switch active.", "tier": 0}

        import re
        if not re.match(r"^[A-Za-z][A-Za-z0-9]*$", component_name):
            logger.error(f"[DesignerAI] Invalid component_name: {component_name}")
            return {"status": "ERROR", "result": "Invalid component_name. Must be PascalCase alphanumeric.", "tier": 0}

        log_audit_event(AGENT_ID, "GENERATE_COMPONENT_START", {
            "component_name": component_name,
            "description_snippet": description[:200],
            "props": props or [],
        })

        props_hint = ""
        if props:
            props_hint = f"\nThe component must accept these props: {', '.join(props)}"

        user_message = (
            f"Generate a React component named '{component_name}'.\n"
            f"Purpose: {description}{props_hint}\n"
            "Use only the design tokens from style.css. No inline styles. "
            "Use CSS class names that match the existing project conventions."
        )

        try:
            from ollama import AsyncClient
            response = await AsyncClient().chat(
                model="llama3.1:8b",
                messages=[
                    {"role": "system", "content": self._build_system_prompt()},
                    {"role": "user",   "content": user_message},
                ],
            )
            msg = response.get("message", {}) if isinstance(response, dict) else None
            if msg is not None:
                generated = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            else:
                generated = getattr(getattr(response, "message", None), "content", "")

            suggested_path = os.path.join(
                _COMPONENTS_DIR, f"{component_name}.jsx"
            )

            log_audit_event(AGENT_ID, "GENERATE_COMPONENT_END", {
                "component_name": component_name,
                "output_chars": len(generated),
                "suggested_path": suggested_path,
                "status": "OK",
            })
            logger.info(f"[DesignerAI] Generated component '{component_name}' ({len(generated)} chars).")
            return {
                "status":         "OK",
                "result":         generated,
                "tier":           RiskTier.TIER_0_GENERATE,
                "suggested_path": suggested_path,
                "component_name": component_name,
            }

        except Exception as exc:
            logger.error(f"[DesignerAI] Ollama error: {exc}")
            log_audit_event(AGENT_ID, "GENERATE_COMPONENT_ERROR", {"error": str(exc)})
            return {"status": "ERROR", "result": str(exc), "tier": RiskTier.TIER_0_GENERATE}

    async def generate_page(
        self,
        page_name: str,
        description: str,
        route: str | None = None,
    ) -> dict:
        """
        Generate a full page component. Tier 0.
        Suggested path: frontend/src/pages/<PageName>.jsx
        """
        if check_kill_switch():
            return {"status": "ERROR", "result": "Kill switch active.", "tier": 0}

        import re
        if not re.match(r"^[A-Za-z][A-Za-z0-9]*$", page_name):
            logger.error(f"[DesignerAI] Invalid page_name: {page_name}")
            return {"status": "ERROR", "result": "Invalid page_name. Must be PascalCase alphanumeric.", "tier": 0}

        log_audit_event(AGENT_ID, "GENERATE_PAGE_START", {
            "page_name": page_name,
            "route": route,
        })

        route_hint = f"\nThis page is served at route: {route}" if route else ""
        user_message = (
            f"Generate a full React page component named '{page_name}'.\n"
            f"Purpose: {description}{route_hint}\n"
            "Use existing design tokens. Include imports. Follow the existing pages/ convention."
        )

        try:
            from ollama import AsyncClient
            response = await AsyncClient().chat(
                model="llama3.1:8b",
                messages=[
                    {"role": "system", "content": self._build_system_prompt()},
                    {"role": "user",   "content": user_message},
                ],
            )
            msg = response.get("message", {}) if isinstance(response, dict) else None
            if msg is not None:
                generated = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            else:
                generated = getattr(getattr(response, "message", None), "content", "")

            _pages_dir = os.path.join(_FRONTEND_SRC, "pages")
            suggested_path = os.path.join(_pages_dir, f"{page_name}.jsx")

            log_audit_event(AGENT_ID, "GENERATE_PAGE_END", {
                "page_name": page_name,
                "output_chars": len(generated),
                "suggested_path": suggested_path,
            })
            return {
                "status":         "OK",
                "result":         generated,
                "tier":           RiskTier.TIER_0_GENERATE,
                "suggested_path": suggested_path,
                "page_name":      page_name,
            }

        except Exception as exc:
            logger.error(f"[DesignerAI] Ollama error: {exc}")
            log_audit_event(AGENT_ID, "GENERATE_PAGE_ERROR", {"error": str(exc)})
            return {"status": "ERROR", "result": str(exc), "tier": RiskTier.TIER_0_GENERATE}
