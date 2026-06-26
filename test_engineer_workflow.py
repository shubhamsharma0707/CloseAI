import os
import secrets
import subprocess
import sys
import time
import urllib.request
import urllib.error
import json
import tempfile
import asyncio

ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER_SCRIPT = os.path.join(ROOT, "RISHI.py")
ORCHESTRATOR_DIR = os.path.join(ROOT, "agents", "engineer")
HEALTH_URL = "http://127.0.0.1:8000/health"
WORKSPACE_URL = "http://127.0.0.1:8000/engineer/workspaces"
LEDGER_FILE = os.path.join(ROOT, "engineer_audit_ledger.jsonl")

# Insert ORCHESTRATOR_DIR to sys.path so we can import orchestrator and tools directly
if ORCHESTRATOR_DIR not in sys.path:
    sys.path.insert(0, ORCHESTRATOR_DIR)

from orchestrator import EngineerOrchestrator
from coder.agent_engineer_coder import NeedsApprovalError, CoderAI
from coder.tools.shell_exec import ALLOWED_BINARIES, shell_exec
from authorization.workspace_guard import WorkspaceGuard

def generate_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CRITICAL_RAM_PERCENT"] = "92.0"
    return env

def wait_for_server(timeout: float = 12.0, interval: float = 0.4) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(interval)
    return False

def create_workspace(workspace_id: str, root_path: str, allow_deploy: bool = False, deploy_command: list[str] = None):
    req = urllib.request.Request(
        WORKSPACE_URL,
        data=json.dumps({
            "workspace_id": workspace_id,
            "project_name": "Test Project",
            "root_path": root_path,
            "authorized_agents": ["AGENT_ENGINEER_CODER", "AGENT_ENGINEER_DESIGNER", "AGENT_ENGINEER_GENERATIVE"],
            "allow_deploy": allow_deploy,
            "deploy_command": deploy_command or []
        }).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def revoke_workspace(workspace_id: str):
    req = urllib.request.Request(
        f"{WORKSPACE_URL}/{workspace_id}/revoke",
        data=json.dumps({
            "revocation_reason": "Test Revocation",
            "revoking_admin": "TEST_ADMIN"
        }).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def create_approval_in_rishi(action_type: str, workspace_id: str, severity: str = "HIGH") -> str:
    req = urllib.request.Request(
        "http://127.0.0.1:8000/engineer/approvals",
        data=json.dumps({
            "vuln_type": action_type,
            "asset": workspace_id,
            "severity": severity,
            "engagement_id": workspace_id,
            "requesting_agent": "AGENT_ENGINEER_CODER"
        }).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["approval_id"]

def get_approval_from_rishi(approval_id: str) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:8000/engineer/approvals/{approval_id}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

import hmac
import hashlib
from datetime import datetime, timezone

def submit_approval_decision(approval_id: str, reviewer: str, status: str = "APPROVED"):
    app_record = get_approval_from_rishi(approval_id)
    payload = app_record["payload"]
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # RISHI uses REVIEWER_TOKEN_<ID> or AGENT_TOKEN_KAVACH_CORE (default "default_kavach_secret")
    env_key = f"REVIEWER_TOKEN_{reviewer.upper().replace('-', '_')}"
    secret = (os.getenv(env_key) or os.getenv("AGENT_TOKEN_KAVACH_CORE", "default_kavach_secret")).encode()
    message = f"{payload}|{timestamp}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()

    req = urllib.request.Request(
        f"http://127.0.0.1:8000/engineer/approvals/{approval_id}/decide",
        method="POST",
        data=json.dumps({
            "reviewer_id": reviewer,
            "decision": status,
            "payload": payload,
            "timestamp": timestamp,
            "signature": signature
        }).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

async def run_happy_path(tmpdir: str) -> bool:
    print("[Test 1/5] Running happy-path write...")
    workspace_id = f"ENG-TEST-{secrets.token_hex(4).upper()}"
    create_workspace(workspace_id, tmpdir)
    target_file = os.path.join(tmpdir, "utils", "jwt_validator.py")
    
    orc = EngineerOrchestrator()
    res = await orc.run(
        f"Write a Python script for JWT validation. You MUST set task_type to 'CODE'. You MUST set output_path to '{target_file}'. Do NOT use GENERATE_ASSET. Do NOT commit. Do NOT push. Do NOT deploy.",
        workspace_id=workspace_id
    )
    if res.get("status") != "OK":
        print(f"  ❌  Orchestrator failed: {res}")
        return False
        
    if not os.path.exists(target_file):
        print(f"  ❌  File not found on disk: {target_file}")
        return False
        
    with open(target_file, "r") as f:
        content = f.read()
    if not content.strip():
        print(f"  ❌  File is empty: {target_file}")
        return False
        
    print("  ✅  Happy path passed.")
    return True

async def test_overwrite_requires_approval(tmpdir: str) -> bool:
    print("[Test 2/5] Testing overwrite requires approval...")
    workspace_id = f"ENG-TEST-{secrets.token_hex(4).upper()}"
    create_workspace(workspace_id, tmpdir)
    target_file = os.path.join(tmpdir, "test_overwrite.txt")
    
    coder = CoderAI()
    
    # First write (should succeed)
    res1 = await coder.write_code_to_file(target_file, "initial content", workspace_id)
    if res1["status"] != "OK":
        print(f"  ❌  First write failed: {res1}")
        return False
        
    with open(target_file, "r") as f:
        content_before = f.read()
        
    # Second write without approval_id (should raise NeedsApprovalError)
    try:
        await coder.write_code_to_file(target_file, "new content", workspace_id, approval_id=None)
        print("  ❌  Overwrite succeeded without approval!")
        return False
    except NeedsApprovalError:
        pass
    except Exception as e:
        print(f"  ❌  Unexpected exception on overwrite: {e}")
        return False
        
    with open(target_file, "r") as f:
        content_after = f.read()
        
    if content_before != content_after:
        print("  ❌  File content changed despite NeedsApprovalError!")
        return False
        
    print("  ✅  Overwrite safely blocked.")
    return True

async def test_bash_is_excluded(tmpdir: str) -> bool:
    print("[Test 3/5] Testing bash exclusion...")
    if "bash" in ALLOWED_BINARIES:
        print("  ❌  'bash' is in ALLOWED_BINARIES!")
        return False
    if "sh" in ALLOWED_BINARIES:
        print("  ❌  'sh' is in ALLOWED_BINARIES!")
        return False
        
    try:
        res = await shell_exec(["bash", "-c", "echo hi"], cwd=tmpdir, timeout=2)
        if res.success:
            print("  ❌  bash execution succeeded!")
            return False
    except Exception as e:
        # shell_exec raises ValueError if binary not in allowlist
        pass
        
    print("  ✅  bash is excluded.")
    return True

async def test_deploy_requires_dual_control(tmpdir: str) -> bool:
    print("[Test 4/5] Testing deploy requires dual control...")
    workspace_id = f"ENG-TEST-{secrets.token_hex(4).upper()}"
    create_workspace(
        workspace_id, tmpdir, 
        allow_deploy=True, 
        deploy_command=[sys.executable, "-c", "print('deployed')"]
    )
    
    coder = CoderAI()
    
    # Trigger deploy without approval
    try:
        await coder.deploy(tmpdir, workspace_id, approval_id=None)
        print("  ❌  Deploy succeeded without approval!")
        return False
    except NeedsApprovalError:
        pass
        
    # Create approval in RISHI as the orchestrator would
    approval_id = create_approval_in_rishi("deploy", workspace_id, severity="CRITICAL")
    
    app_record = get_approval_from_rishi(approval_id)
    if app_record.get("required_approvers") != 2:
        print(f"  ❌  required_approvers is {app_record.get('required_approvers')}, expected 2")
        return False
        
    # Submit one approval
    updated_record = submit_approval_decision(approval_id, reviewer="user1", status="APPROVED")
    if updated_record.get("status") != "PENDING":
        print(f"  ❌  Approval status is {updated_record.get('status')} with only 1 approver!")
        return False
        
    print("  ✅  Deploy dual control verified.")
    return True

async def test_workspace_revocation_blocks_in_flight_actions(tmpdir: str) -> bool:
    print("[Test 5/5] Testing workspace revocation blocks actions...")
    workspace_id = f"ENG-TEST-{secrets.token_hex(4).upper()}"
    create_workspace(workspace_id, tmpdir)
    target_file = os.path.join(tmpdir, "test_revoke.txt")
    
    revoke_workspace(workspace_id)
    
    guard = WorkspaceGuard()
    res = await guard.check_async("write", target_file, workspace_id, agent_id="AGENT_ENGINEER_CODER")
    
    if res.allowed:
        print("  ❌  WorkspaceGuard allowed action on revoked workspace!")
        return False
    if "WORKSPACE_REVOKED" not in res.reason:
        print(f"  ❌  Guard denied for wrong reason: {res.reason}")
        return False
        
    print("  ✅  Revocation safely blocked actions.")
    return True

async def run_all_tests(tmpdir: str) -> int:
    tests = [
        run_happy_path,
        test_overwrite_requires_approval,
        test_bash_is_excluded,
        test_deploy_requires_dual_control,
        test_workspace_revocation_blocks_in_flight_actions
    ]
    
    failed = False
    for t in tests:
        success = await t(tmpdir)
        if not success:
            failed = True
            
    return 1 if failed else 0

def main() -> int:
    print("=" * 62)
    print("  CloseAI — Engineer Orchestrator Regression Tests")
    print("=" * 62)

    env = generate_env()

    server_proc = subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        env=env,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    time.sleep(1.0)

    print("[0/5] Waiting for server to become healthy...")
    if not wait_for_server():
        print("  ❌  Server did not become healthy within 12 seconds.")
        server_proc.terminate()
        return 1
    print("  ✅  Server healthy.\n")

    exit_code = 1
    try:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmpdir:
            tmpdir = os.path.realpath(tmpdir)
            exit_code = asyncio.run(run_all_tests(tmpdir))
    finally:
        print("\n[Cleanup] Stopping RISHI server...")
        server_proc.terminate()
        try:
            server_proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
            server_proc.communicate()

        print("\n==============================================================")
        if exit_code == 0:
            print("  ✅  ALL TESTS PASSED")
        else:
            print("  ❌  SOME TESTS FAILED")
        print("==============================================================")
        
    return exit_code

if __name__ == "__main__":
    sys.exit(main())
