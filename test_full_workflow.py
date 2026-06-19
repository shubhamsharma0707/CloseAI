"""
test_full_workflow.py
=====================
Integration test for the Ollama-powered CloseAI / RISHI multi-agent system.

What it does:
  1. Generates a fresh cryptographically-secure token for every agent.
  2. Raises CRITICAL_RAM_PERCENT to 92% to accommodate Ollama's VRAM usage.
  3. Starts RISHI.py as a subprocess with those tokens injected via env vars.
  4. Polls /health until the server is ready (max 12 s).
  5. Runs the orchestrator (with Ollama LLM intent parsing) as a subprocess.
  6. Prints live output from the orchestrator.
  7. Checks that every workflow milestone appeared in the output.
  8. Tears down the server cleanly.

Run from the project root:
    python3 test_full_workflow.py
"""

import os
import secrets
import subprocess
import sys
import time
import urllib.request
import urllib.error

# ── Project paths ────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER_SCRIPT = os.path.join(ROOT, "RISHI.py")
ORCHESTRATOR_DIR = os.path.join(ROOT, "agents", "chanakya")
ORCHESTRATOR_SCRIPT = os.path.join(ORCHESTRATOR_DIR, "orchestrator.py")
HEALTH_URL = "http://127.0.0.1:8000/health"

# ── Agent IDs that need tokens ────────────────────────────────────────────────
AGENT_IDS = [
    "RISHI_CORE_NODE",
    "AGENT_CHANAKYA_DETERMINISTIC",
    "AGENT_CHANAKYA_AUDITABILITY",
    "AGENT_CHANAKYA_ETHICAL",
    "AGENT_CHANAKYA_CRITICAL",
    "AGENT_CHANAKYA_COMMUNICATION",
    "AGENT_CHANAKYA_VISUALIZATION",
    "AGENT_CHANAKYA_ESG",
    "AGENT_CHANAKYA_ADAPTABILITY",
]


def generate_env() -> dict[str, str]:
    """Create a full environment with fresh random tokens for every agent.
    Also raises the RAM threshold to 92% to accommodate Ollama's memory footprint.
    """
    env = os.environ.copy()
    for agent_id in AGENT_IDS:
        key = f"AGENT_TOKEN_{agent_id}"
        env[key] = secrets.token_hex(32)
    # Ollama + llama3 uses ~5-6 GB RAM; without this the server returns 503
    env["CRITICAL_RAM_PERCENT"] = "92.0"
    return env


def wait_for_server(timeout: float = 12.0, interval: float = 0.4) -> bool:
    """Poll /health until the server responds 200 or timeout expires."""
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


def main() -> int:
    print("=" * 62)
    print("  CloseAI — Ollama LLM + Full Multi-Agent Integration Test")
    print("=" * 62)

    # Step 1 — Generate tokens
    print("\n[1/4] Generating fresh agent tokens (RAM threshold → 92%)...")
    env = generate_env()
    for agent_id in AGENT_IDS:
        key = f"AGENT_TOKEN_{agent_id}"
        print(f"  {key}... ✅")

    # Step 2 — Start RISHI server
    print("\n[2/4] Starting RISHI server (RISHI.py)...")
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

    print("[3/4] Waiting for server to become healthy...")
    if not wait_for_server(timeout=12.0):
        print("  ❌  Server did not become healthy within 12 seconds.")
        server_proc.terminate()
        remaining, _ = server_proc.communicate(timeout=3)
        print(remaining)
        return 1
    print("  ✅  Server healthy.\n")

    # Step 3 — Run orchestrator (includes Ollama LLM call)
    print("[4/4] Running Chanakya Orchestrator with Ollama intent parsing...\n")
    print("─" * 62)
    print("  ⏳  Waiting for LLM to parse: '$25,400,500 at 12.5% tax ...'")
    print("─" * 62)

    orch_proc = subprocess.Popen(
        [sys.executable, ORCHESTRATOR_SCRIPT],
        env=env,
        cwd=ORCHESTRATOR_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    orchestrator_lines = []
    if orch_proc.stdout:
        for line in orch_proc.stdout:
            print(line, end="", flush=True)
            orchestrator_lines.append(line)

    orch_exit = orch_proc.wait(timeout=180)  # 3 min — LLM can be slow
    print("─" * 62)

    # Step 4 — Tear down server
    print("\n[Cleanup] Stopping RISHI server...")
    server_proc.terminate()
    try:
        server_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server_proc.kill()

    # ── Milestone checks ──────────────────────────────────────────────────────
    print()
    if orch_exit == 0:
        output = "".join(orchestrator_lines)
        milestones = [
            ("LLM intent parsed",        "LLM Intent Parsing Successful"),
            ("Principal extracted",       "principal"),
            ("Tax rate normalised",       "tax_rate"),
            ("Phase 1 math audit",        "CRYPTOGRAPHIC AUDIT RECORD"),
            ("Phase 1 ledger",            "IMMUTABLE LEDGER UPDATED"),
            ("Phase 2 compliance",        "COMPLIANCE APPROVED"),
            ("Phase 2 strategy",          "STRATEGIC ANALYSIS RECORD"),
            ("Phase 3 exec summary",      "EXECUTIVE SUMMARY"),
            ("Phase 3 charts",            "VISUALIZATION COMPLETE"),
            ("Phase 3 ESG report",        "ESG REPORT"),
            ("Phase 4 regulatory",        "REGULATORY RESEARCH COMPLETE"),
            ("Workflow complete",         "CHANAKYA WORKFLOW COMPLETE"),
        ]
        print("  Milestone checks:")
        all_passed = True
        for label, marker in milestones:
            found = marker in output
            icon = "✅" if found else "❌"
            print(f"    {icon}  {label}")
            if not found:
                all_passed = False

        print()
        if all_passed:
            print("=" * 62)
            print("  ✅  ALL 12 MILESTONES PASSED")
            print("  LLM → Decimal math → Compliance → Strategy → ESG → Done")
            print("=" * 62)
            return 0
        else:
            print("=" * 62)
            print("  ⚠️   Some milestones missing — check output above.")
            print("=" * 62)
            return 1
    else:
        print(f"  ❌  Orchestrator exited with code {orch_exit}.")
        return orch_exit


if __name__ == "__main__":
    sys.exit(main())
