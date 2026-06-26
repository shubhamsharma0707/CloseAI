import os
import secrets
import subprocess
import sys
import time
import urllib.request
import urllib.error
import json
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER_SCRIPT = os.path.join(ROOT, "RISHI.py")
ORCHESTRATOR_DIR = os.path.join(ROOT, "agents", "engineer")
ORCHESTRATOR_SCRIPT = os.path.join(ORCHESTRATOR_DIR, "orchestrator.py")
HEALTH_URL = "http://127.0.0.1:8000/health"
WORKSPACE_URL = "http://127.0.0.1:8000/engineer/workspaces"
LEDGER_FILE = os.path.join(ROOT, "engineer_audit_ledger.jsonl")

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

def create_workspace(workspace_id: str, root_path: str):
    req = urllib.request.Request(
        WORKSPACE_URL,
        data=json.dumps({
            "workspace_id": workspace_id,
            "project_name": "Test Project",
            "root_path": root_path,
            "authorized_agents": ["AGENT_ENGINEER_CODER", "AGENT_ENGINEER_DESIGNER", "AGENT_ENGINEER_GENERATIVE"]
        }).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return resp.read()

def main() -> int:
    print("=" * 62)
    print("  CloseAI — Engineer Orchestrator Integration Test")
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

    print("[1/4] Waiting for server to become healthy...")
    if not wait_for_server():
        print("  ❌  Server did not become healthy within 12 seconds.")
        server_proc.terminate()
        return 1
    print("  ✅  Server healthy.\n")

    with tempfile.TemporaryDirectory(dir=ROOT) as tmpdir:
        tmpdir = os.path.realpath(tmpdir)
        workspace_id = f"ENG-TEST-{secrets.token_hex(4).upper()}"
        print(f"[2/4] Creating test workspace {workspace_id} at {tmpdir}...")
        create_workspace(workspace_id, tmpdir)
        print("  ✅  Workspace created.\n")

        target_file = os.path.join(tmpdir, "utils", "jwt_validator.py")
        
        # Modify the orchestrator.py human_input to point to the tmp workspace
        # actually, the orchestrator.py is hardcoded with human_input:
        # "Generate a Python function that validates JWT tokens, write it to utils/jwt_validator.py, and run pytest afterwards."
        # And it uses workspace_id="ENG-DEV-001".
        # We should overwrite the last lines of orchestrator.py or run it differently.
        # Let's write a wrapper script to run the orchestrator with our workspace_id and human_input.
        
        wrapper_script = os.path.join(tmpdir, "run_orch.py")
        with open(wrapper_script, "w") as f:
            f.write(f'''
import asyncio
import sys
import json
sys.path.insert(0, "{ORCHESTRATOR_DIR}")
from orchestrator import EngineerOrchestrator
async def main():
    orc = EngineerOrchestrator()
    res = await orc.run(
        "Write a Python script for JWT validation. You MUST set task_type to 'CODE'. You MUST set output_path to '{target_file}'. Do NOT use GENERATE_ASSET.",
        workspace_id="{workspace_id}"
    )
    print(json.dumps(res, indent=2, default=str))
asyncio.run(main())
''')

        print("[3/4] Running Engineer Orchestrator...")
        orch_proc = subprocess.Popen(
            [sys.executable, wrapper_script],
            env=env,
            cwd=ORCHESTRATOR_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        if orch_proc.stdout:
            for line in orch_proc.stdout:
                print(line, end="", flush=True)

        orch_exit = orch_proc.wait(timeout=180)

        print("\n[Cleanup] Stopping RISHI server...")
        server_proc.terminate()
        try:
            server_proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
            server_proc.communicate()

        print("\n[4/4] Asserting results...")
        if orch_exit != 0:
            print(f"  ❌  Orchestrator exited with code {orch_exit}")
            return orch_exit

        # 1. Assert file exists and is non-empty
        if not os.path.exists(target_file):
            print(f"  ❌  File not found on disk: {target_file}")
            return 1
        
        with open(target_file, "r") as f:
            content = f.read()
        if not content.strip():
            print(f"  ❌  File is empty: {target_file}")
            return 1
        print("  ✅  Target file exists and is non-empty.")

        # 2. Assert ledger entry
        found_ledger_entry = False
        if os.path.exists(LEDGER_FILE):
            with open(LEDGER_FILE, "r") as f:
                lines = f.readlines()
                # Check last 20 lines
                for line in lines[-20:]:
                    if not line.strip(): continue
                    try:
                        record = json.loads(line.strip())
                        payload = json.loads(record.get("payload", "{}"))
                        if payload.get("event_type") == "FILE_WRITE_END":
                            data = payload.get("data", {})
                            if data.get("path") == target_file and data.get("status") == "OK":
                                found_ledger_entry = True
                                break
                    except:
                        pass
        
        if not found_ledger_entry:
            print("  ❌  FILE_WRITE_END event not found in ledger for target file.")
            return 1
        print("  ✅  FILE_WRITE_END event confirmed in ledger.")

        print("=" * 62)
        print("  ✅  ALL TESTS PASSED")
        print("=" * 62)
        return 0

if __name__ == "__main__":
    sys.exit(main())
