import logging
import httpx
import os
import sys

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

for _p in (_ROOT, _KAVACH_AUTH, _ENGINEER):
    if _p in sys.path: sys.path.remove(_p)
    sys.path.insert(0, _p)

from coder.tools.shell_exec import shell_exec

logger = logging.getLogger("Engineer.CoderAI.DeployTool")
RISHI_URL = os.getenv("RISHI_BASE_URL", "http://127.0.0.1:8000")
AGENT_ID = "AGENT_ENGINEER_CODER"

async def deploy(cwd: str, workspace_id: str) -> dict:
    """
    Execute the deploy_command pre-configured in the workspace record.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{RISHI_URL}/engineer/workspaces/{workspace_id}")
            resp.raise_for_status()
            record = resp.json()
    except Exception as exc:
        logger.error(f"[DeployTool] Could not fetch workspace record: {exc}")
        return {"status": "ERROR", "result": f"Could not fetch workspace record from RISHI: {exc}"}
        
    deploy_command = record.get("deploy_command")
    if not deploy_command or not isinstance(deploy_command, list):
        logger.error(f"[DeployTool] Workspace {workspace_id} has no valid deploy_command configured.")
        return {"status": "ERROR", "result": "DEPLOY_NOT_CONFIGURED: Workspace does not have a valid deploy_command list configured."}
        
    logger.info(f"[DeployTool] Executing pre-authorized deploy command: {' '.join(deploy_command)}")
    result = await shell_exec(deploy_command, cwd=cwd, timeout=600, agent_id=AGENT_ID)
    
    return {
        "status": "OK" if result.success else "ERROR",
        "result": result.stdout + result.stderr
    }
