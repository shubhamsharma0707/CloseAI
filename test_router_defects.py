import sys
import os
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import RISHI
from agents.kavach.orchestrator import KavachOrchestrator
from agents.engineer.orchestrator import EngineerOrchestrator
from RISHI import rishi_ask, AskRequest, RouterDecision, router_sessions

ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINEER_ROOT = os.path.join(ROOT, "agents", "engineer")
if ENGINEER_ROOT not in sys.path:
    sys.path.insert(0, ENGINEER_ROOT)

from coder.agent_engineer_coder import NeedsApprovalError

def test_kavach_blocked_status():
    async def run_test():
        ciso = KavachOrchestrator()
        ciso.scope_guard.check = MagicMock(return_value=MagicMock(allowed=True, reason="OK", engagement_id="ENG-123", destructive_testing_allowed=False))
        ciso.agent_recon.execute_recon = AsyncMock(return_value={"status": "COMPLETED"})
        ciso.agent_vuln_scan.scan_vulnerabilities = AsyncMock(return_value={"status": "COMPLETED"})
        ciso.triage_engine.run = MagicMock(return_value=[])
        
        ciso.agent_pentest.run_exploit_simulation = AsyncMock(return_value={
            "status": "COMPLETED",
            "exploited": [{"status": "BLOCKED_BY_POLICY"}]
        })
        ciso.agent_reporting.generate_report = AsyncMock(return_value={"status": "COMPLETED"})
        ciso.agent_retest.verify_fixes = AsyncMock(return_value={"status": "COMPLETED"})
        
        with patch('agents.kavach.orchestrator._check_rate_limit', new_callable=AsyncMock) as mock_rate_limit:
            mock_rate_limit.return_value = True
            result = await ciso.run_full_security_workflow("test.com", "FULL_PENTEST", auto_approve=False)
            assert result["status"] == "BLOCKED"
    asyncio.run(run_test())

def test_engineer_blocked_status():
    async def run_test():
        orc = EngineerOrchestrator()
        intent = MagicMock(task_type="DEPLOY", deploy=True, component_name=None, output_path=None, run_tests=False, commit=False, push=False, description="deploy task", language="python", target_files=None)
        orc.parse_intent = AsyncMock(return_value=intent)
        
        orc.coder.deploy = AsyncMock(side_effect=NeedsApprovalError("DEPLOY", "test"))
        orc._get_approval = AsyncMock(return_value=False)
        
        with patch('agents.engineer.orchestrator.check_kill_switch_async', new_callable=AsyncMock) as mock_kill_switch:
            mock_kill_switch.return_value = False
            result = await orc.run("deploy this", workspace_id="ENG-123")
            assert result["status"] == "BLOCKED"
            assert any(step.get("status") == "BLOCKED" for step in result["steps"])
    asyncio.run(run_test())

def test_router_halts_on_blocked():
    async def run_test():
        req = AskRequest(user_prompt="do security test", session_id="test_session")
        
        with patch('RISHI.classify_intent', new_callable=AsyncMock) as mock_classify:
            mock_classify.return_value = RouterDecision(orchestrators=["kavach", "engineer"], sequence="sequential", reasoning="test")
            
            with patch('agents.kavach.orchestrator.KavachOrchestrator.run', new_callable=AsyncMock) as mock_kavach_run:
                mock_kavach_run.return_value = {"orchestrator": "kavach", "status": "BLOCKED", "summary": "Blocked by policy"}
                
                with patch('RISHI._write_router_audit', new_callable=AsyncMock):
                    result = await rishi_ask(req)
                    
                    assert result["status"] == "BLOCKED"
                    assert len(result["results"]) == 1
                    assert result["results"][0]["orchestrator"] == "kavach"
    asyncio.run(run_test())

def test_router_classification_failure():
    async def run_test():
        req = AskRequest(user_prompt="hello", session_id="test_session_2")
        
        with patch('RISHI.classify_intent', new_callable=AsyncMock) as mock_classify:
            mock_classify.return_value = RouterDecision(orchestrators=["ERROR"], sequence="single", reasoning="Classification error")
            
            with patch('RISHI._write_router_audit', new_callable=AsyncMock):
                result = await rishi_ask(req)
                assert result["status"] == "ERROR"
                assert result["summary"] == "The request could not be classified. Please retry or be more specific."
                assert len(result["results"]) == 0
    asyncio.run(run_test())
