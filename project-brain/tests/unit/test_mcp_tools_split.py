"""
H-02 拆分驗收測試：驗證 mcp_server.py 拆分至 mcp_tools/ 後的正確性。

驗收項目：
1. mcp_server.py 行數 ≤ 600（含 backward-compat）
2. 所有 tool modules 可獨立 import 且有 register()
3. register_all_tools() 成功執行不拋例外
4. 所有 18 個 MCP tools 在 FastMCP 實例中註冊
5. 公開 API（create_server, BrainServer）不變
6. Backward-compat 模組層級變數存在
"""

from __future__ import annotations

import inspect
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestModuleStructure(unittest.TestCase):
    """H-02 模組結構驗證。"""

    def test_mcp_server_line_count(self):
        """mcp_server.py 不超過 600 行。"""
        root = Path(__file__).parent.parent.parent
        mcp_path = root / "project_brain" / "interfaces" / "mcp_server.py"
        lines = mcp_path.read_text().count("\n")
        self.assertLessEqual(lines, 600,
                             f"mcp_server.py is {lines} lines, should be ≤600")

    def test_tool_modules_exist(self):
        """6 個 tool modules 都存在。"""
        root = Path(__file__).parent.parent.parent
        tools_dir = root / "project_brain" / "interfaces" / "mcp_tools"
        expected = [
            "knowledge_tools.py",
            "feedback_tools.py",
            "admin_tools.py",
            "pipeline_tools.py",
            "federation_tools.py",
            "reasoning_tools.py",
        ]
        for name in expected:
            self.assertTrue(
                (tools_dir / name).exists(),
                f"Missing tool module: {name}",
            )

    def test_tool_modules_have_register(self):
        """每個 tool module 都有 register(mcp, srv, helpers) 函式。"""
        modules = [
            "project_brain.interfaces.mcp_tools.knowledge_tools",
            "project_brain.interfaces.mcp_tools.feedback_tools",
            "project_brain.interfaces.mcp_tools.admin_tools",
            "project_brain.interfaces.mcp_tools.pipeline_tools",
            "project_brain.interfaces.mcp_tools.federation_tools",
            "project_brain.interfaces.mcp_tools.reasoning_tools",
        ]
        import importlib
        for mod_path in modules:
            mod = importlib.import_module(mod_path)
            self.assertTrue(
                hasattr(mod, "register") and callable(mod.register),
                f"{mod_path} missing register() function",
            )

    def test_tool_module_line_counts(self):
        """每個 tool module ≤ 500 行。"""
        root = Path(__file__).parent.parent.parent
        tools_dir = root / "project_brain" / "interfaces" / "mcp_tools"
        for f in tools_dir.glob("*_tools.py"):
            lines = f.read_text().count("\n")
            self.assertLessEqual(
                lines, 500,
                f"{f.name} is {lines} lines, should be ≤500",
            )


class TestBackwardCompat(unittest.TestCase):
    """公開 API 和 backward-compat 不變。"""

    def test_create_server_importable(self):
        """create_server 仍可從 mcp_server import。"""
        from project_brain.interfaces.mcp_server import create_server
        self.assertTrue(callable(create_server))

    def test_brain_server_importable(self):
        """BrainServer class 仍可從 mcp_server import。"""
        from project_brain.interfaces.mcp_server import BrainServer
        self.assertTrue(inspect.isclass(BrainServer))

    def test_module_compat_functions(self):
        """Module-level 函式（_rate_check, _safe_str 等）仍存在。"""
        from project_brain.interfaces import mcp_server as ms
        for name in ("_rate_check", "_safe_str", "_validate_workdir",
                     "_find_brain_root", "_cleanup_expired_sessions",
                     "_run_maintenance_cycle", "_adjust_signal_confidence"):
            self.assertTrue(
                callable(getattr(ms, name, None)),
                f"Missing backward-compat function: {name}",
            )

    def test_module_compat_variables(self):
        """Module-level 變數仍存在。"""
        from project_brain.interfaces import mcp_server as ms
        for name in ("_call_times", "_rate_lock", "_session_nodes",
                     "_snodes_lock", "_session_served", "_sserved_lock",
                     "_brain_cache", "_cache_lock",
                     "_cleanup_daemon_started", "_decay_daemon_started",
                     "_pipeline_worker_started"):
            self.assertTrue(
                hasattr(ms, name),
                f"Missing backward-compat variable: {name}",
            )


class TestToolRegistration(unittest.TestCase):
    """驗證 register_all_tools 正確註冊所有 tools。"""

    def test_register_all_tools_creates_tools(self):
        """register_all_tools 在 FastMCP mock 上註冊 18 個 tools。"""
        from project_brain.interfaces.mcp_tools import register_all_tools

        # Build a mock MCP and srv
        mcp = MagicMock()
        # Make @mcp.tool() return a passthrough decorator
        mcp.tool.return_value = lambda fn: fn
        mcp.resource.return_value = lambda fn: fn

        srv = MagicMock()
        srv.rate_check = MagicMock()
        srv.resolve_brain = MagicMock(return_value=MagicMock())
        srv._sserved_lock = threading.Lock()
        srv._snodes_lock = threading.Lock()
        srv._cache_lock = threading.Lock()
        srv._session_served = {}
        srv._session_served_ts = {}
        srv._session_nodes = {}
        srv._brain_cache = {}

        helpers = {
            "_safe_str": lambda v, m, f: str(v)[:m],
            "_check_permission": lambda t: None,
            "_get_central_client": lambda: (None, None),
            "_find_brain_root": lambda s: None,
            "_now_iso": lambda: "2026-01-01T00:00:00Z",
            "_FORBIDDEN_ROOTS": (),
            "_MAX_BRAIN_CACHE": 32,
            "work_path": Path("/tmp"),
            "brain": MagicMock(),
            "MAX_QUERY_LEN": 500,
            "MAX_CONTENT_LEN": 2000,
            "MAX_TITLE_LEN": 200,
            "MAX_TAGS_COUNT": 10,
        }

        # Should not raise
        register_all_tools(mcp, srv, helpers)

        # Verify tools were registered (18 tools + 1 resource)
        tool_calls = mcp.tool.call_count
        resource_calls = mcp.resource.call_count
        self.assertGreaterEqual(tool_calls, 18,
                                f"Expected ≥18 tool registrations, got {tool_calls}")
        self.assertGreaterEqual(resource_calls, 1,
                                f"Expected ≥1 resource registration, got {resource_calls}")


if __name__ == "__main__":
    unittest.main()
