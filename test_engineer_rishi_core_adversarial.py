import pytest
import os
import asyncio
from agents.engineer.authorization.workspace_guard import WorkspaceGuard, GuardResult
from agents.engineer.coder.agent_engineer_coder import CoderAI, NeedsApprovalError

class MockResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code
    def json(self):
        return self._json_data
    def raise_for_status(self):
        pass

class MockAsyncClient:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def get(self, url):
        return MockResponse({
            "workspace_id": "ENG-WORKSPACE-RISHI-CORE",
            "status": "ACTIVE",
            "authorized_agents": ["AGENT_ENGINEER_CODER"],
            "allow_git_push": True,
            "allow_deploy": True
        })

@pytest.mark.asyncio
async def test_engineer_modifying_rishi_core_is_blocked(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: MockAsyncClient())
    
    # Mock kill switch to allow execution
    import agents.engineer.coder.agent_engineer_coder as coder_module
    monkeypatch.setattr(coder_module, "check_kill_switch", lambda: False)
    
    # Path to modify
    root = os.path.dirname(os.path.abspath(__file__))
    target_path = os.path.join(root, "RISHI.py")
    
    # 1. Test WorkspaceGuard directly
    guard = WorkspaceGuard(project_root=root)
    result = await guard.check_async("write", target_path, "ENG-WORKSPACE-RISHI-CORE")
    
    assert not result.allowed
    assert result.reason == "CORE_FILE_REQUIRES_TIER3"
    
    # 2. Test CoderAI write_code_to_file directly
    coder = CoderAI()
    try:
        import agents.engineer.coder.tools.file_io as file_io
        monkeypatch.setattr(file_io, "_guard", guard)
        
        await coder.write_code_to_file(
            path=target_path,
            content="# Exploit logic",
            workspace_id="ENG-WORKSPACE-RISHI-CORE"
        )
        pytest.fail("NeedsApprovalError should have been raised for CORE_FILE_REQUIRES_TIER3")
    except NeedsApprovalError as exc:
        assert exc.action_type == "write_core_file"
        assert exc.context["path"] == target_path
