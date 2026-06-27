"""
orchestrator.py — Engineer: The Third Orchestrator
====================================================
Engineer follows the same RISHI-centric pattern as Chanakya and Kavach.
It sits at agents/engineer/ with three phase-equivalent sub-agent directories.

Responsibilities (from the plan):
  1. Parse NL intent via Ollama (same pattern as Chanakya/Kavach).
  2. Classify each resulting action's risk tier before dispatch.
  3. Route to CoderAI, DesignerAI, GenerativeAI, or a sequence of them.
  4. Hold the SINGLE audit/approval relationship with RISHI —
     sub-agents do NOT talk to RISHI approvals directly.
  5. For Tier 2+ actions: call request_human_approval(), poll for decision,
     then re-dispatch only if APPROVED.
  6. Aggregate multi-step task results into one coherent response/report.

Intent routing logic:
  "Build a login form"      → DesignerAI (component) + CoderAI (logic write)
  "Fix the NPE in auth.py"  → CoderAI only
  "Generate a hero image"   → GenerativeAI
  "Run tests"               → CoderAI (test runner)

Risk enforcement:
  Tier 0 → auto-proceed (logged)
  Tier 1 → auto-proceed (logged)
  Tier 2 → request_human_approval → poll → APPROVED only
  Tier 3 → always requires approval, dual-control checked server-side
"""

import asyncio
import json
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
from approval_client import request_human_approval, poll_for_decision
from kill_switch_client import check_kill_switch_async
from risk_tier import RiskTier, classify_action, describe_tier

from coder.agent_engineer_coder import CoderAI, NeedsApprovalError
from designer.agent_engineer_designer import DesignerAI
from generative.agent_engineer_generative import GenerativeAI

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - [%(levelname)s] - %(message)s",
)
logger = logging.getLogger("Engineer.Orchestrator")

AGENT_ID   = "AGENT_ENGINEER_ORCHESTRATOR"
RISHI_BASE = os.getenv("RISHI_BASE_URL", "http://127.0.0.1:8000")


# ---------------------------------------------------------------------------
# Intent model
# ---------------------------------------------------------------------------

class EngineerIntent:
    """Parsed intent from the human request."""
    def __init__(self, data: dict):
        self.task_type: str       = data.get("task_type", "CODE")
        self.description: str     = data.get("description", "")
        self.target_files: list   = data.get("target_files", [])
        self.component_name: str  = data.get("component_name", "")
        self.output_path: str     = data.get("output_path", "")
        self.language: str        = data.get("language", "python")
        self.run_tests: bool      = data.get("run_tests", False)
        self.commit: bool         = data.get("commit", False)
        self.commit_message: str  = data.get("commit_message", "")
        self.push: bool           = data.get("push", False)
        self.deploy: bool         = data.get("deploy", False)

    def to_dict(self) -> dict:
        return self.__dict__


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class EngineerOrchestrator:
    """
    Engineer: The Third Orchestrator.
    Manages CoderAI, DesignerAI, and GenerativeAI as ordered sub-tasks.
    """

    def __init__(self):
        logger.info("🛠️  Initializing Engineer Orchestrator...")
        self.coder     = CoderAI()
        self.designer  = DesignerAI()
        self.generative = GenerativeAI()
        logger.info("✅ Engineer Orchestrator ready.")

    # ------------------------------------------------------------------
    # Intent Parsing (same Ollama pattern as Chanakya/Kavach)
    # ------------------------------------------------------------------

    async def parse_intent(self, user_prompt: str) -> EngineerIntent | None:
        """
        Uses Ollama (llama3.1:8b) to translate human text into structured
        engineering intent. Reuses the existing Ollama connection — no new
        LLM client dependency.
        """
        logger.info(f"\n🗣️  Human Request: '{user_prompt}'")
        logger.info("🧠 Parsing engineering intent via Ollama (llama3.1:8b)...")

        system_prompt = """
You are Engineer, an AI engineering orchestrator.
Parse the user's request and return ONLY a valid JSON object with these keys:
- "task_type": one of ["CODE", "DESIGN", "GENERATE_ASSET", "TEST", "BUILD", "COMMIT", "PUSH", "DEPLOY", "MULTI"]
- "description": what the user wants in plain English
- "target_files": list of file paths mentioned (empty list if none)
- "component_name": PascalCase component name if designing a UI component (empty string if none)
- "output_path": output file path for asset generation (empty string if none)
- "language": programming language (default "python")
- "run_tests": true if user wants tests run after code is written
- "commit": true if user wants changes committed to git
- "commit_message": git commit message (empty string if commit is false)
- "push": true if user wants changes pushed to git remote
- "deploy": true if user wants to deploy the workspace
"""

        try:
            from ollama import AsyncClient
            response = await AsyncClient().chat(
                model="llama3.1:8b",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                format="json",
            )
            msg = response.get("message", {}) if isinstance(response, dict) else None
            if msg is not None:
                content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            else:
                content = getattr(getattr(response, "message", None), "content", "")

            data = json.loads(content)
            intent = EngineerIntent(data)
            logger.info(f"✅ Intent parsed: {json.dumps(intent.to_dict(), indent=2)}")
            return intent

        except Exception as exc:
            logger.error(f"❌ Intent parsing failed: {exc}")
            logger.error("Ensure Ollama is running ('ollama serve') and llama3.1:8b is pulled.")
            return None

    # ------------------------------------------------------------------
    # Approval helper (Engineer owns the RISHI approval relationship)
    # ------------------------------------------------------------------

    async def _get_approval(self, action_type: str, context: dict, workspace_id: str) -> bool:
        """
        Request and poll for human approval for a Tier 2+ action.
        Returns True if APPROVED, False otherwise (fail-closed).
        """
        tier = classify_action(action_type)
        logger.info(f"⏳ Requesting approval for Tier 2 action: {action_type}")
        log_audit_event(AGENT_ID, "APPROVAL_REQUESTED", {
            "action_type": action_type,
            "tier": describe_tier(tier),
            "context": context,
        })

        severity = "CRITICAL" if tier.requires_dual_control() else "HIGH"
        approval_id = await request_human_approval(
            vuln={"type": action_type},
            asset=context.get("cwd", workspace_id),
            severity=severity,
            engagement_id=workspace_id,
            requesting_agent=AGENT_ID,
        )

        if not approval_id:
            logger.error(f"[Engineer] Could not create approval record — denying {action_type}.")
            return False

        decision = await poll_for_decision(approval_id, timeout_seconds=600)
        approved = decision.status == "APPROVED"
        log_audit_event(AGENT_ID, "APPROVAL_DECISION", {
            "approval_id": approval_id,
            "action_type": action_type,
            "decision": decision.status,
        })
        logger.info(f"{'✅' if approved else '🛑'} Approval decision for {action_type}: {decision.status}")
        return approved

    # ------------------------------------------------------------------
    # Main workflow
    # ------------------------------------------------------------------

    async def run(self, user_prompt: str, workspace_id: str | None = None) -> dict:
        """
        Full Engineer workflow:
          parse intent → classify tier → dispatch sub-agents → aggregate results.
        """
        logger.info("=" * 60)
        logger.info("🛠️  ENGINEER ORCHESTRATOR — START")
        logger.info("=" * 60)

        # ── Kill switch ────────────────────────────────────────────────────
        if await check_kill_switch_async():
            logger.error("[Engineer] Kill switch ACTIVE — aborting all work.")
            return {"status": "ERROR", "result": "Kill switch active.", "steps": []}

        # ── Parse intent ───────────────────────────────────────────────────
        intent = await self.parse_intent(user_prompt)
        if not intent:
            return {"status": "ERROR", "result": "Intent parsing failed.", "steps": []}

        log_audit_event(AGENT_ID, "WORKFLOW_START", {
            "workspace_id": workspace_id,
            "task_type": intent.task_type,
            "description": intent.description,
        })

        results: list[dict] = []
        cwd = _PROJECT_ROOT  # default CWD — orchestrator can override per-task
        
        # Default workspace for non-critical actions if none provided
        effective_workspace_id = workspace_id or "ENG-WORKSPACE-001"

        # ── Route by task type ─────────────────────────────────────────────

        # DESIGN: DesignerAI generates component/page, CoderAI writes it
        if intent.task_type in ("DESIGN", "MULTI") and intent.component_name:
            logger.info(f"\n>>> DESIGN: Generating component '{intent.component_name}'")
            design_result = await self.designer.generate_component(
                component_name=intent.component_name,
                description=intent.description,
            )
            results.append({"step": "design_component", **design_result})

            if design_result["status"] == "OK":
                try:
                    write_result = await self.coder.write_code_to_file(
                        path=design_result.get("suggested_path", ""),
                        content=design_result["result"],
                        workspace_id=effective_workspace_id,
                        approval_id=None,
                    )
                except NeedsApprovalError as exc:
                    approved = await self._get_approval(exc.action_type, exc.context, effective_workspace_id)
                    if approved:
                        write_result = await self.coder.write_code_to_file(
                            path=design_result.get("suggested_path", ""),
                            content=design_result["result"],
                            workspace_id=effective_workspace_id,
                            approval_id="OVERWRITE_APPROVED"
                        )
                    else:
                        write_result = {"status": "ERROR", "result": "Approval denied for overwrite"}
                results.append({"step": "write_component", **write_result})

        # GENERATE_ASSET: GenerativeAI makes an image
        if intent.task_type == "GENERATE_ASSET" and intent.output_path:
            logger.info(f"\n>>> GENERATE_ASSET: {intent.description}")
            gen_result = await self.generative.generate_asset(
                prompt=intent.description,
                output_path=intent.output_path,
                workspace_id=effective_workspace_id,
            )
            results.append({"step": "generate_asset", **gen_result})

        # CODE: CoderAI generates and writes code
        if intent.task_type in ("CODE", "MULTI"):
            logger.info(f"\n>>> CODE: Generating {intent.language} code")
            code_result = await self.coder.generate_code(
                prompt=intent.description,
                language=intent.language,
                context_files=intent.target_files or None,
                workspace_id=effective_workspace_id,
            )
            results.append({"step": "generate_code", **code_result})

            # Write to file if output path specified
            if code_result["status"] == "OK" and intent.output_path:
                try:
                    write_result = await self.coder.write_code_to_file(
                        path=intent.output_path or "output.py",
                        content=code_result["result"],
                        workspace_id=effective_workspace_id,
                        approval_id=None,
                    )
                except NeedsApprovalError as exc:
                    approved = await self._get_approval(exc.action_type, exc.context, effective_workspace_id)
                    if approved:
                        write_result = await self.coder.write_code_to_file(
                            path=intent.output_path or "output.py",
                            content=code_result["result"],
                            workspace_id=effective_workspace_id,
                            approval_id="OVERWRITE_APPROVED"
                        )
                    else:
                        write_result = {"status": "ERROR", "result": "Approval denied for overwrite"}
                results.append({"step": "write_code", **write_result})

        # TEST: Run test suite after code changes
        if intent.run_tests:
            logger.info("\n>>> TEST: Running test suite")
            test_result = await self.coder.run_tests(cwd)
            results.append({"step": "run_tests", **test_result})

        # BUILD: Run build pipeline
        if intent.task_type == "BUILD":
            logger.info("\n>>> BUILD: Running build pipeline")
            build_result = await self.coder.run_build_pipeline(cwd)
            results.append({"step": "run_build", **build_result})

        # COMMIT: Tier 2 — requires approval
        if intent.commit and intent.commit_message:
            logger.info(f"\n>>> COMMIT (Tier 2): '{intent.commit_message}'")
            try:
                commit_result = await self.coder.commit_changes(
                    cwd=cwd,
                    message=intent.commit_message,
                    approval_id=None,  # Will trigger NeedsApprovalError
                )
                results.append({"step": "git_commit", **commit_result})
            except NeedsApprovalError as exc:
                approved = await self._get_approval(
                    action_type=exc.action_type,
                    context=exc.context,
                    workspace_id=workspace_id,
                )
                if approved:
                    commit_result = await self.coder.commit_changes(
                        cwd=cwd,
                        message=intent.commit_message,
                        approval_id="HUMAN_APPROVED",
                    )
                    results.append({"step": "git_commit", **commit_result})
                else:
                    results.append({
                        "step": "git_commit",
                        "status": "BLOCKED",
                        "result": "Commit denied by human reviewer.",
                        "tier": 2,
                    })

        # PUSH: Tier 2 — requires approval
        if intent.task_type == "PUSH" or intent.push:
            if not workspace_id:
                logger.error("[Engineer] PUSH requires an explicit workspace_id. Default fallback not allowed.")
                return {"status": "ERROR", "result": "PUSH requires an explicit workspace_id.", "steps": results}
                
            logger.info("\n>>> PUSH (Tier 2): pushing to remote")
            try:
                push_result = await self.coder.push_changes(
                    cwd=cwd,
                    workspace_id=workspace_id,
                    approval_id=None,
                )
                results.append({"step": "git_push", **push_result})
            except NeedsApprovalError as exc:
                approved = await self._get_approval(
                    action_type=exc.action_type,
                    context=exc.context,
                    workspace_id=workspace_id,
                )
                if approved:
                    push_result = await self.coder.push_changes(
                        cwd=cwd,
                        workspace_id=workspace_id,
                        approval_id="HUMAN_APPROVED",
                    )
                    results.append({"step": "git_push", **push_result})
                else:
                    results.append({
                        "step": "git_push",
                        "status": "BLOCKED",
                        "result": "Push denied by human reviewer.",
                        "tier": 2,
                    })

        # DEPLOY: Tier 3 — requires dual-control approval
        if intent.task_type == "DEPLOY" or intent.deploy:
            if not workspace_id:
                logger.error("[Engineer] DEPLOY requires an explicit workspace_id. Default fallback not allowed.")
                return {"status": "ERROR", "result": "DEPLOY requires an explicit workspace_id.", "steps": results}
                
            logger.info("\n>>> DEPLOY (Tier 3): Triggering workspace deploy")
            try:
                deploy_result = await self.coder.deploy(
                    cwd=cwd,
                    workspace_id=workspace_id,
                    approval_id=None,
                )
                results.append({"step": "deploy", **deploy_result})
            except NeedsApprovalError as exc:
                approved = await self._get_approval(
                    action_type=exc.action_type,
                    context=exc.context,
                    workspace_id=workspace_id,
                )
                if approved:
                    deploy_result = await self.coder.deploy(
                        cwd=cwd,
                        workspace_id=workspace_id,
                        approval_id="HUMAN_APPROVED",
                    )
                    results.append({"step": "deploy", **deploy_result})
                else:
                    results.append({
                        "step": "deploy",
                        "status": "BLOCKED",
                        "result": "Deploy denied by human reviewer(s).",
                        "tier": 3,
                    })

        # ── Aggregate ──────────────────────────────────────────────────────
        has_blocked = any(r.get("status") == "BLOCKED" for r in results)
        has_error = any(r.get("status") not in ("OK", "BLOCKED") for r in results)

        if has_error:
            overall_status = "ERROR"
        elif has_blocked:
            overall_status = "BLOCKED"
        else:
            overall_status = "OK"
            
        log_audit_event(AGENT_ID, "WORKFLOW_END", {
            "workspace_id": workspace_id,
            "steps_completed": len(results),
            "overall_status": overall_status,
        })

        logger.info("\n" + "=" * 60)
        logger.info(f"✅ ENGINEER WORKFLOW COMPLETE — {len(results)} steps, status={overall_status}")
        logger.info("=" * 60)

        return {
            "status":          overall_status,
            "summary":         f"Engineer workflow completed with status: {overall_status}. {len(results)} steps executed.",
            "steps":           results,
            "workspace_id":    workspace_id,
            "details":         intent.to_dict(),
            "orchestrator":    "engineer"
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    orchestrator = EngineerOrchestrator()

    human_input = (
        "Generate a Python function that validates JWT tokens, "
        "write it to utils/jwt_validator.py, and run pytest afterwards."
    )

    result = await orchestrator.run(human_input, workspace_id="ENG-DEV-001")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
