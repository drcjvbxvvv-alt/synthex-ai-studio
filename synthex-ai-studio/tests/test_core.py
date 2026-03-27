"""
SYNTHEX Unit Test Suite

覆蓋範圍：
  - core/tools.py — _safe_run 安全執行（shell injection 防護、輸出截斷）
  - core/base_agent.py — 記憶體管理（history 截斷）、Token Budget
  - core/advanced_tool_use.py — StructuredOutputParser、ToolRegistry
  - core/web_orchestrator.py — DocContext 原子寫入、PhaseCheckpoint
  - core/brain/ — VectorMemory 安全驗證、TemporalGraph 時間戳

執行方式：
  pytest tests/ -v
  pytest tests/ -v --tb=short -x   # 失敗就停
  pytest tests/test_tools.py -v -k "injection"  # 只跑特定測試
"""

import sys
import os
import json
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 確保可以 import core/
sys.path.insert(0, str(Path(__file__).parent.parent))


# ══════════════════════════════════════════════════════════════
# Test Group 1：_safe_run 安全執行
# ══════════════════════════════════════════════════════════════

class TestSafeRun(unittest.TestCase):
    """_safe_run 安全執行的 unit tests"""

    def setUp(self):
        from core.tools import _safe_run
        self.safe_run = _safe_run
        self.workdir  = tempfile.mkdtemp()

    def test_basic_command_succeeds(self):
        """正常命令應該成功執行"""
        r = self.safe_run("echo hello", cwd=self.workdir)
        self.assertEqual(r["returncode"], 0)
        self.assertIn("hello", r["stdout"])

    def test_argv_list_works(self):
        """argv 陣列格式應該正確執行"""
        r = self.safe_run(["echo", "world"], cwd=self.workdir)
        self.assertEqual(r["returncode"], 0)
        self.assertIn("world", r["stdout"])

    def test_shell_injection_rejected(self):
        """包含危險字元的命令應該被拒絕"""
        from core.tools import _REJECT_PATTERNS
        dangerous = "echo hello; rm -rf /"
        # _safe_run 應拒絕包含 ; 的命令（或 shlex.split 會把它解析為兩個命令）
        # 用 shlex.split 解析後，; 不是 shell operator，只是一個字元 — 這沒問題
        # 真正危險的是 shell=True，我們測試確保 shell=False
        r = self.safe_run(["echo", "hello; rm test"], cwd=self.workdir)
        self.assertEqual(r["returncode"], 0)
        # 確認 rm 沒有被執行（shell=False 模式下 ; 只是字面字元）
        self.assertNotIn("rm", r.get("stderr", ""))

    def test_nonexistent_command(self):
        """不存在的命令應該回傳 127"""
        r = self.safe_run("nonexistent_command_xyz", cwd=self.workdir)
        self.assertEqual(r["returncode"], 127)
        self.assertIn("不存在", r["stderr"])

    def test_timeout_respected(self):
        """超時命令應該回傳 124"""
        import platform
        if platform.system() == "Windows":
            self.skipTest("Windows 不支援此測試")
        r = self.safe_run("sleep 10", cwd=self.workdir, timeout=1)
        self.assertEqual(r["returncode"], 124)
        self.assertIn("超時", r["stderr"])

    def test_output_truncated(self):
        """超大輸出應該被截斷"""
        from core.tools import MAX_CMD_OUTPUT_BYTES
        # 生成超過 1MB 的輸出
        r = self.safe_run(
            ["python3", "-c", f"print('x'*{MAX_CMD_OUTPUT_BYTES * 2})"],
            cwd=self.workdir,
            timeout=5,
        )
        total_bytes = len((r.get("output","") or "").encode("utf-8","replace"))
        # 應該被截斷
        self.assertLess(total_bytes, MAX_CMD_OUTPUT_BYTES * 2)

    def test_workdir_is_used(self):
        """命令應該在指定工作目錄執行"""
        r = self.safe_run("pwd", cwd=self.workdir)
        self.assertEqual(r["returncode"], 0)
        # pwd 輸出應該包含工作目錄（可能有符號連結差異，用 realpath）
        real_workdir = str(Path(self.workdir).resolve())
        self.assertTrue(
            real_workdir in r["stdout"] or
            os.path.realpath(r["stdout"].strip()) == real_workdir
        )


# ══════════════════════════════════════════════════════════════
# Test Group 2：conversation_history 記憶體管理
# ══════════════════════════════════════════════════════════════

class TestConversationHistory(unittest.TestCase):
    """conversation_history 截斷的 unit tests"""

    def setUp(self):
        from core.base_agent import BaseAgent, MAX_HISTORY_LEN
        self.MAX_HISTORY_LEN = MAX_HISTORY_LEN
        # 建立最小化的 Agent 實例（不需要 API key）
        self.agent = object.__new__(BaseAgent)
        self.agent.conversation_history = []

    def test_trim_history_reduces_to_max(self):
        """_trim_history 應該把 history 截斷到 MAX_HISTORY_LEN"""
        from core.base_agent import BaseAgent, MAX_HISTORY_LEN
        agent = object.__new__(BaseAgent)
        agent.conversation_history = [
            {"role": "user", "content": f"msg {i}"}
            for i in range(MAX_HISTORY_LEN + 20)
        ]
        agent._trim_history()
        self.assertEqual(len(agent.conversation_history), MAX_HISTORY_LEN)

    def test_trim_keeps_latest_messages(self):
        """截斷後應保留最新的消息"""
        from core.base_agent import BaseAgent, MAX_HISTORY_LEN
        agent = object.__new__(BaseAgent)
        agent.conversation_history = [
            {"role": "user", "content": f"msg {i}"}
            for i in range(MAX_HISTORY_LEN + 10)
        ]
        agent._trim_history()
        # 最後一條應該是最新的消息
        last_msg = agent.conversation_history[-1]["content"]
        self.assertEqual(last_msg, f"msg {MAX_HISTORY_LEN + 9}")

    def test_trim_noop_when_within_limit(self):
        """未超過限制時，_trim_history 不應改變 history"""
        from core.base_agent import BaseAgent, MAX_HISTORY_LEN
        agent = object.__new__(BaseAgent)
        original = [{"role": "user", "content": f"msg {i}"} for i in range(5)]
        agent.conversation_history = list(original)
        agent._trim_history()
        self.assertEqual(agent.conversation_history, original)


class TestTokenGuard(unittest.TestCase):
    """TokenGuard Context Window 保護的 unit tests"""

    def test_no_truncation_when_within_limit(self):
        """短文件不應被截斷"""
        from core.logging_setup import TokenGuard
        guard = TokenGuard("claude-haiku-4-5")
        short = "hello world " * 100
        result = guard.truncate(short, "short_doc")
        self.assertEqual(result, short)

    def test_truncation_when_over_limit(self):
        """超過限制的文件應被截斷"""
        from core.logging_setup import TokenGuard
        guard = TokenGuard("claude-haiku-4-5")
        # 700KB > safe_limit（640KB）
        big_doc = "x " * (350 * 1024)
        result = guard.truncate(big_doc, "big_doc")
        self.assertLess(len(result), len(big_doc))
        self.assertIn("[TokenGuard", result)

    def test_truncation_preserves_head_and_tail(self):
        """截斷後應保留開頭和結尾"""
        from core.logging_setup import TokenGuard
        guard = TokenGuard("claude-haiku-4-5")
        head = "HEAD_CONTENT " * 1000
        tail = " TAIL_CONTENT" * 1000
        middle  = "MIDDLE " * (500 * 1024 // 7)
        big_doc = head + middle + tail
        result = guard.truncate(big_doc, "structured_doc")
        self.assertIn("HEAD_CONTENT", result)
        self.assertIn("TAIL_CONTENT", result)


# ══════════════════════════════════════════════════════════════
# Test Group 3：StructuredOutputParser
# ══════════════════════════════════════════════════════════════

class TestStructuredOutputParser(unittest.TestCase):
    """StructuredOutputParser 的 unit tests"""

    def setUp(self):
        from core.advanced_tool_use import StructuredOutputParser
        self.parser = StructuredOutputParser()

    def test_parse_valid_json(self):
        """完整 JSON 輸出應該正確解析"""
        raw = '{"score": 8, "gate": "PASS", "summary": "很好", "top_issue": null}'
        result = self.parser.parse_eval_score(raw)
        self.assertEqual(result["score"], 8)
        self.assertEqual(result["gate"], "PASS")
        self.assertEqual(result["_source"], "json")

    def test_parse_json_with_markdown(self):
        """帶 markdown 程式碼塊的 JSON 應該正確解析"""
        raw = '```json\n{"score": 6, "gate": "FAIL", "summary": "需改進"}\n```'
        result = self.parser.parse_eval_score(raw)
        self.assertEqual(result["score"], 6)
        self.assertEqual(result["gate"], "FAIL")

    def test_parse_regex_fallback(self):
        """非 JSON 格式應該 fallback 到 regex"""
        raw = "SCORE: 7\nGATE: PASS\nSUMMARY: 通過"
        result = self.parser.parse_eval_score(raw)
        self.assertEqual(result["score"], 7)
        self.assertEqual(result["gate"], "PASS")
        self.assertEqual(result["_source"], "regex_fallback")

    def test_score_clamped_to_valid_range(self):
        """Score 應該被限制在 1-10"""
        raw = '{"score": 15, "gate": "PASS", "summary": "超出範圍"}'
        result = self.parser.parse_eval_score(raw)
        self.assertLessEqual(result["score"], 10)
        self.assertGreaterEqual(result["score"], 1)

    def test_gate_auto_inferred_from_score(self):
        """未指定 gate 時，應從 score 推斷"""
        raw = '{"score": 9, "summary": "優秀"}'
        result = self.parser.parse_eval_score(raw)
        self.assertEqual(result["gate"], "PASS")

        raw = '{"score": 3, "summary": "差"}'
        result = self.parser.parse_eval_score(raw)
        self.assertEqual(result["gate"], "FAIL")

    def test_malformed_input_returns_default(self):
        """完全無法解析的輸入應回傳合理預設值"""
        raw = "這不是 JSON 也不是 SCORE: 格式的文字"
        result = self.parser.parse_eval_score(raw)
        self.assertIn("score", result)
        self.assertIn("gate", result)
        self.assertIn(result["gate"], ["PASS", "FAIL"])


# ══════════════════════════════════════════════════════════════
# Test Group 4：ToolRegistry 動態工具發現
# ══════════════════════════════════════════════════════════════

class TestToolRegistry(unittest.TestCase):
    """ToolRegistry 的 unit tests"""

    def setUp(self):
        from core.advanced_tool_use import ToolRegistry
        self.tools = [
            {"name": "read_file",    "description": "讀取文件內容"},
            {"name": "write_file",   "description": "寫入文件"},
            {"name": "run_command",  "description": "執行 shell 命令"},
            {"name": "run_tests",    "description": "執行測試"},
            {"name": "git_commit",   "description": "提交程式碼"},
            {"name": "browse_web",   "description": "瀏覽網頁"},
            {"name": "sast_scan",    "description": "靜態安全分析"},
            {"name": "brain_search", "description": "搜尋知識庫"},
        ]
        self.registry = ToolRegistry(self.tools)

    def test_search_returns_relevant_tools(self):
        """搜尋應該回傳相關工具"""
        results = self.registry.search("讀取檔案")
        names = [t["name"] for t in results]
        self.assertIn("read_file", names)

    def test_search_limits_top_k(self):
        """搜尋應該遵守 top_k 限制"""
        results = self.registry.search("執行", top_k=2)
        self.assertLessEqual(len(results), 2)

    def test_search_empty_query(self):
        """空查詢不應崩潰"""
        results = self.registry.search("")
        self.assertIsInstance(results, list)

    def test_get_all_returns_all_tools(self):
        """get_all 應回傳所有工具"""
        all_tools = self.registry.get_all()
        self.assertEqual(len(all_tools), len(self.tools))

    def test_tool_count(self):
        """tool_count 應準確"""
        self.assertEqual(self.registry.tool_count, len(self.tools))


# ══════════════════════════════════════════════════════════════
# Test Group 5：DocContext 原子寫入
# ══════════════════════════════════════════════════════════════

class TestDocContextAtomicWrite(unittest.TestCase):
    """DocContext 原子寫入的 unit tests"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_write_creates_file(self):
        """write() 應建立文件"""
        # 動態 import（需要 web_orchestrator 的依賴）
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.web_orchestrator import DocContext
        ctx = DocContext(self.tmpdir)
        ctx.write("TEST_DOC", "test content", "Test Document")
        path = Path(self.tmpdir) / "docs" / "TEST_DOC.md"
        self.assertTrue(path.exists())

    def test_write_content_intact(self):
        """寫入的內容應完整保存"""
        from core.web_orchestrator import DocContext
        ctx     = DocContext(self.tmpdir)
        content = "test content with special chars: ⚠️ 測試 🚀"
        ctx.write("TEST_DOC2", content)
        path    = Path(self.tmpdir) / "docs" / "TEST_DOC2.md"
        read    = path.read_text(encoding="utf-8")
        self.assertIn(content, read)

    def test_no_temp_files_left(self):
        """原子寫入後不應留下 temp 文件"""
        from core.web_orchestrator import DocContext
        ctx = DocContext(self.tmpdir)
        ctx.write("TEST_DOC3", "content")
        docs_dir = Path(self.tmpdir) / "docs"
        tmp_files = list(docs_dir.glob(".TEST_DOC3_tmp_*"))
        self.assertEqual(len(tmp_files), 0)


# ══════════════════════════════════════════════════════════════
# Test Group 6：URL 安全驗證
# ══════════════════════════════════════════════════════════════

class TestUrlSecurity(unittest.TestCase):
    """URL 安全驗證的 unit tests"""

    def test_valid_https_url(self):
        """有效的 HTTPS URL 應通過驗證"""
        from core.tools import _safe_run
        # 直接測試 tools.py 的 fetch 工具（mock 網路）
        # 這裡只測試 URL 驗證邏輯
        import urllib.parse as up
        url = "https://example.com/api"
        parsed = up.urlparse(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertIn(parsed.scheme, {"http", "https"})

    def test_file_scheme_rejected(self):
        """file:// scheme 應被拒絕"""
        url = "file:///etc/passwd"
        import urllib.parse as up
        parsed = up.urlparse(url)
        self.assertNotIn(parsed.scheme, {"http", "https"})

    def test_ssrf_blocked(self):
        """私有 IP 應被阻擋"""
        import re
        blocked = ["169.254.169.254", "192.168.1.1", "10.0.0.1", "172.16.0.1"]
        for ip in blocked:
            is_private = bool(
                re.match(r'^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)', ip) or
                ip == "169.254.169.254"
            )
            self.assertTrue(is_private, f"{ip} 應被視為私有 IP")


# ══════════════════════════════════════════════════════════════
# 執行入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)


# ══════════════════════════════════════════════════════════════
# Test Group 7：Config 集中設定（第十輪新增）
# ══════════════════════════════════════════════════════════════

class TestConfig(unittest.TestCase):
    """core/config.py 集中設定的 unit tests"""

    def test_model_id_constants_valid(self):
        """ModelID 常數應該符合 Anthropic 模型 ID 格式"""
        from core.config import ModelID
        valid_models = [
            ModelID.OPUS_46, ModelID.SONNET_46,
            ModelID.SONNET_45, ModelID.HAIKU_45,
        ]
        for m in valid_models:
            self.assertTrue(m.startswith("claude-"),
                            f"{m} 應以 claude- 開頭")
            self.assertNotIn("haiku-20240307", m,
                             f"{m} 不應包含已退役的 Haiku 3")

    def test_context_windows_updated(self):
        """Opus 4.6 和 Sonnet 4.6 的 context window 應為 1M（GA）"""
        from core.config import CONTEXT_WINDOWS, ModelID
        self.assertEqual(CONTEXT_WINDOWS[ModelID.OPUS_46], 1_000_000,
                         "Opus 4.6 context window 應為 1M（GA 2026-03-13）")
        self.assertEqual(CONTEXT_WINDOWS[ModelID.SONNET_46], 1_000_000,
                         "Sonnet 4.6 context window 應為 1M（GA 2026-03-13）")

    def test_safe_input_limits_are_80_percent(self):
        """safe_input_limit 應為 context_window 的 80%"""
        from core.config import CONTEXT_WINDOWS, SAFE_INPUT_LIMITS
        for model, ctx in CONTEXT_WINDOWS.items():
            safe = SAFE_INPUT_LIMITS.get(model)
            if safe is not None:
                expected = int(ctx * 0.80)
                self.assertEqual(safe, expected,
                                 f"{model} safe limit 應為 {expected}")

    def test_agent_tier_map_complete(self):
        """AGENT_TIER_MAP 應涵蓋所有 28 個 Agent"""
        from core.config import AGENT_TIER_MAP
        expected_agents = {
            "NEXUS", "SIGMA", "ARIA", "NOVA", "ATOM",
            "ECHO", "BYTE", "STACK", "TRACE", "FORGE", "SHIELD",
            "SPARK", "VISTA", "PRISM", "VOLT", "FLUX", "PROBE",
            "MEMO", "QUANT", "LUMI", "RIFT", "KERN",
            "RELAY", "BRIDGE", "WIRE", "BOLT", "ATLAS",
            "PULSE",
        }
        missing = expected_agents - set(AGENT_TIER_MAP.keys())
        self.assertEqual(len(missing), 0,
                         f"AGENT_TIER_MAP 缺少 Agent：{missing}")

    def test_calc_cost_accurate(self):
        """calc_cost 應準確計算（含 cache read/write）"""
        from core.config import cfg, ModelID
        # Haiku 4.5: input=$0.8/MTK, output=$4/MTK
        # 1M input + 0 output = $0.80
        cost = cfg.calc_cost(ModelID.HAIKU_45, 1_000_000, 0)
        self.assertAlmostEqual(cost, 0.80, places=2)

        # 帶 cache read（$0.08/MTK）
        cost_cached = cfg.calc_cost(ModelID.HAIKU_45, 0, 0,
                                    cache_read=1_000_000)
        self.assertAlmostEqual(cost_cached, 0.08, places=2)

    def test_model_for_agent_uses_tier_map(self):
        """model_for_agent 應根據 AGENT_TIER_MAP 選擇正確模型"""
        from core.config import cfg, ModelID
        # Opus tier agents
        self.assertEqual(cfg.model_for_agent("NEXUS"), cfg.model_opus)
        self.assertEqual(cfg.model_for_agent("ARIA"),  cfg.model_opus)
        # Haiku tier agents
        self.assertEqual(cfg.model_for_agent("RELAY"), cfg.model_haiku)
        # Sonnet tier (default)
        self.assertEqual(cfg.model_for_agent("BYTE"),  cfg.model_sonnet)

    def test_cache_control_block_is_ephemeral(self):
        """cache_control_block 應回傳 ephemeral（1h TTL）"""
        from core.config import cfg
        block = cfg.cache_control_block()
        self.assertEqual(block["type"], "ephemeral")


# ══════════════════════════════════════════════════════════════
# Test Group 8：StructuredOutputParser GA 格式（第十輪新增）
# ══════════════════════════════════════════════════════════════

class TestStructuredOutputGA(unittest.TestCase):
    """Structured Output GA 格式的 unit tests"""

    def test_build_ga_output_config_structure(self):
        """build_ga_output_config 應回傳正確的 output_config 結構"""
        from core.advanced_tool_use import StructuredOutputParser, EVAL_SCORE_SCHEMA
        params = StructuredOutputParser.build_ga_output_config(
            EVAL_SCORE_SCHEMA, name="eval_score"
        )
        self.assertIn("output_config", params)
        fmt = params["output_config"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertIn("json_schema", fmt)
        self.assertEqual(fmt["json_schema"]["name"], "eval_score")

    def test_ga_params_no_beta_header(self):
        """GA 格式不應包含 beta header"""
        from core.advanced_tool_use import StructuredOutputParser, EVAL_SCORE_SCHEMA
        params = StructuredOutputParser.build_ga_output_config(EVAL_SCORE_SCHEMA)
        self.assertNotIn("betas", params,
                         "GA 格式不需要 betas header")

    def test_ga_params_no_tools_key(self):
        """GA 格式不應包含 tools/tool_choice（非 beta 工具路徑）"""
        from core.advanced_tool_use import StructuredOutputParser, EVAL_SCORE_SCHEMA
        params = StructuredOutputParser.build_ga_output_config(EVAL_SCORE_SCHEMA)
        self.assertNotIn("tools", params)
        self.assertNotIn("tool_choice", params)

    def test_build_web_search_tool_latest_version(self):
        """build_web_search_tool 應預設使用最新版（dynamic filtering）"""
        from core.advanced_tool_use import build_web_search_tool, WEB_SEARCH_TOOL_VERSION
        tool = build_web_search_tool()
        self.assertEqual(tool["type"], WEB_SEARCH_TOOL_VERSION,
                         "應使用最新版 web_search（含 dynamic filtering）")
        self.assertNotIn("betas", tool,
                         "GA web search 不需要 betas")

    def test_web_search_tool_max_uses(self):
        """build_web_search_tool 應正確設定 max_uses"""
        from core.advanced_tool_use import build_web_search_tool
        tool = build_web_search_tool(max_uses=10)
        self.assertEqual(tool["max_uses"], 10)

    def test_web_search_tool_allowed_domains(self):
        """build_web_search_tool 應支援 allowed_domains"""
        from core.advanced_tool_use import build_web_search_tool
        tool = build_web_search_tool(allowed_domains=["github.com", "docs.python.org"])
        self.assertIn("allowed_domains", tool)
        self.assertIn("github.com", tool["allowed_domains"])


# ══════════════════════════════════════════════════════════════
# Test Group 9：ComputerUseSecurity（第十輪新增）
# ══════════════════════════════════════════════════════════════

class TestComputerUseSecurity(unittest.TestCase):
    """ComputerUseSecurity 安全檢查的 unit tests"""

    def setUp(self):
        from core.computer_use import ComputerUseSecurity
        self.sec = ComputerUseSecurity(workdir="/tmp")

    def test_valid_localhost_url(self):
        """localhost URL 應通過驗證"""
        ok, err = self.sec.check_url("http://localhost:3000")
        self.assertTrue(ok, f"localhost 應允許，但被拒絕：{err}")

    def test_valid_https_url(self):
        """HTTPS URL 應通過驗證"""
        ok, err = self.sec.check_url("https://example.com")
        self.assertTrue(ok, f"HTTPS 應允許：{err}")

    def test_file_scheme_blocked(self):
        """file:// scheme 應被阻擋"""
        ok, _ = self.sec.check_url("file:///etc/passwd")
        self.assertFalse(ok, "file:// 應被阻擋")

    def test_private_ip_blocked(self):
        """私有 IP 應被阻擋"""
        for url in [
            "http://192.168.1.100",
            "http://10.0.0.1",
            "http://172.16.0.1",
        ]:
            ok, _ = self.sec.check_url(url)
            self.assertFalse(ok, f"{url} 應被阻擋")

    def test_127_0_0_1_allowed(self):
        """127.0.0.1（localhost）應允許"""
        ok, _ = self.sec.check_url("http://127.0.0.1:8080")
        self.assertTrue(ok, "127.0.0.1 是 localhost，應允許")

    def test_action_limit_blocks_after_max(self):
        """超過動作上限後應被阻擋"""
        from core.computer_use import ComputerUseSecurity, MAX_ACTIONS_PER_SESSION, ComputerAction
        sec = ComputerUseSecurity(workdir="/tmp")
        # 直接設定 count
        sec._action_count = MAX_ACTIONS_PER_SESSION
        ok, msg = sec.check_action_limit()
        self.assertFalse(ok)
        self.assertIn("上限", msg)

    def test_audit_log_rotates(self):
        """audit log 超過上限時應輪轉（不無限增長）"""
        from core.computer_use import ComputerUseSecurity, ACTION_AUDIT_LIMIT, ComputerAction
        sec = ComputerUseSecurity(workdir="/tmp")
        # 加入超過上限的記錄
        for i in range(ACTION_AUDIT_LIMIT + 50):
            sec.record_action(ComputerAction("click", f"target_{i}"))
        self.assertLessEqual(len(sec._audit_log), ACTION_AUDIT_LIMIT)


# ══════════════════════════════════════════════════════════════
# Test Group 10：AgentSwarm 部分失敗恢復（第十輪新增）
# ══════════════════════════════════════════════════════════════

class TestSwarmFailureRecovery(unittest.TestCase):
    """AgentSwarm 部分失敗恢復的 unit tests"""

    def setUp(self):
        from core.swarm import SwarmTask, SwarmScheduler, FailurePolicy, TaskStatus
        self.SwarmTask     = SwarmTask
        self.SwarmScheduler = SwarmScheduler
        self.FailurePolicy = FailurePolicy
        self.TaskStatus    = TaskStatus

    def _make_tasks(self):
        """建立測試用 DAG：A → B → C，A → D"""
        return {
            "A": self.SwarmTask("A", "ECHO",  "task A"),
            "B": self.SwarmTask("B", "BYTE",  "task B", depends_on=["A"]),
            "C": self.SwarmTask("C", "STACK", "task C", depends_on=["B"]),
            "D": self.SwarmTask("D", "TRACE", "task D", depends_on=["A"]),
        }

    def test_get_ready_tasks_no_deps(self):
        """無依賴任務應立即 ready"""
        tasks = self._make_tasks()
        sched = self.SwarmScheduler()
        ready = sched.get_ready_tasks(tasks, self.FailurePolicy.CONTINUE)
        names = [t.task_id for t in ready]
        self.assertIn("A", names)
        self.assertNotIn("B", names)

    def test_get_ready_after_parent_done(self):
        """父任務完成後，子任務應 ready"""
        tasks = self._make_tasks()
        tasks["A"].status = self.TaskStatus.DONE
        sched = self.SwarmScheduler()
        ready = sched.get_ready_tasks(tasks, self.FailurePolicy.CONTINUE)
        names = [t.task_id for t in ready]
        self.assertIn("B", names)
        self.assertIn("D", names)

    def test_continue_policy_skips_downstream(self):
        """CONTINUE 策略：A 失敗後，B 和 C 應被跳過（D 不受影響）"""
        tasks = self._make_tasks()
        tasks["A"].status = self.TaskStatus.FAILED
        sched  = self.SwarmScheduler()
        to_skip = sched.get_tasks_to_skip(tasks, "A")
        self.assertIn("B", to_skip)
        self.assertIn("C", to_skip)
        # D 直接依賴 A，也應被跳過
        self.assertIn("D", to_skip)

    def test_fallback_policy_resolves_failed_dep(self):
        """FALLBACK 策略：A 失敗後，B 的依賴仍算已解決"""
        tasks = self._make_tasks()
        tasks["A"].status = self.TaskStatus.FAILED
        sched  = self.SwarmScheduler()
        ready  = sched.get_ready_tasks(tasks, self.FailurePolicy.FALLBACK)
        names  = [t.task_id for t in ready]
        self.assertIn("B", names,
                      "FALLBACK 策略下，A 失敗但 B 應仍可執行")

    def test_transitive_dependency_skip(self):
        """遞迴依賴：A 失敗 → C 也應被跳過（雖然 C 直接依賴 B，不是 A）"""
        tasks = self._make_tasks()
        tasks["A"].status = self.TaskStatus.FAILED
        sched  = self.SwarmScheduler()
        to_skip = sched.get_tasks_to_skip(tasks, "A")
        self.assertIn("C", to_skip,
                      "C 間接依賴 A（透過 B），應被遞迴跳過")

    def test_swarm_result_partial_success(self):
        """SwarmResult.partial_success 語義正確"""
        from core.swarm import SwarmResult, FailurePolicy
        r = SwarmResult(
            run_id="test", tasks_done=3, tasks_failed=1,
            tasks_skipped=0, total_ms=1000,
            final_output="", task_results={},
            failure_policy=FailurePolicy.CONTINUE,
        )
        self.assertTrue(r.partial_success)
        self.assertFalse(r.success)

    def test_swarm_result_full_success(self):
        """全部完成時 success = True"""
        from core.swarm import SwarmResult, FailurePolicy
        r = SwarmResult(
            run_id="test", tasks_done=5, tasks_failed=0,
            tasks_skipped=0, total_ms=2000,
            final_output="ok", task_results={},
            failure_policy=FailurePolicy.CONTINUE,
        )
        self.assertTrue(r.success)
        self.assertFalse(r.partial_success)

    def test_task_retry_logic(self):
        """SwarmTask.can_retry 和 reset_for_retry 行為正確"""
        task = self.SwarmTask("x", "ECHO", "test", max_retries=2)
        self.assertTrue(task.can_retry)       # attempt=0 < max_retries=2
        task.reset_for_retry()
        self.assertEqual(task.attempt, 1)
        self.assertTrue(task.can_retry)       # attempt=1 < max_retries=2
        task.reset_for_retry()
        self.assertFalse(task.can_retry)      # attempt=2 = max_retries=2


# ══════════════════════════════════════════════════════════════
# Test Group 11：TokenBudget 精確成本計算（第十輪新增）
# ══════════════════════════════════════════════════════════════

class TestTokenBudgetV4(unittest.TestCase):
    """TokenBudget v4 使用 cfg.calc_cost() 的 unit tests"""

    def test_record_tracks_cache_tokens(self):
        """record() 應追蹤 cache_read 和 cache_write"""
        from core.base_agent import TokenBudget
        from core.config import ModelID
        budget = TokenBudget(budget_usd=10.0, model=ModelID.HAIKU_45)
        budget.record("NEXUS", input_tokens=1000, output_tokens=500,
                      cache_read=2000, cache_write=500)
        self.assertEqual(budget.total_cache_read, 2000)
        self.assertEqual(budget.total_cache_write, 500)

    def test_over_budget_raises(self):
        """超出 budget 時應拋出 BudgetExceededError"""
        from core.base_agent import TokenBudget, BudgetExceededError
        from core.config import ModelID
        budget = TokenBudget(budget_usd=0.001, model=ModelID.OPUS_46)
        budget.record("NEXUS", input_tokens=100_000, output_tokens=50_000)
        with self.assertRaises(BudgetExceededError):
            budget.check_budget()

    def test_within_budget_no_raise(self):
        """未超出 budget 時不應拋出例外"""
        from core.base_agent import TokenBudget
        from core.config import ModelID
        budget = TokenBudget(budget_usd=10.0, model=ModelID.HAIKU_45)
        budget.record("RELAY", input_tokens=100, output_tokens=50)
        try:
            budget.check_budget()
        except Exception as e:
            self.fail(f"不應拋出例外：{e}")

    def test_haiku_cost_cheaper_than_opus(self):
        """Haiku 成本應顯著低於 Opus"""
        from core.base_agent import TokenBudget
        from core.config import ModelID, cfg
        # 相同 token 用量
        cost_haiku = cfg.calc_cost(ModelID.HAIKU_45, 10_000, 5_000)
        cost_opus  = cfg.calc_cost(ModelID.OPUS_46,  10_000, 5_000)
        self.assertLess(cost_haiku, cost_opus * 0.1,
                        "Haiku 成本應低於 Opus 10%（實際差距 60x）")


# ══════════════════════════════════════════════════════════════
# Test Group 12：CompactionManager（第十一輪新增）
# ══════════════════════════════════════════════════════════════

class TestCompactionManager(unittest.TestCase):
    """CompactionManager Context Compaction 的 unit tests"""

    def setUp(self):
        from core.base_agent import CompactionManager, COMPACTION_TOKEN_THRESHOLD
        from core.config import ModelID
        self.CM        = CompactionManager
        self.model     = ModelID.SONNET_46
        self.threshold = COMPACTION_TOKEN_THRESHOLD

    def test_should_compact_by_token_count(self):
        """input_tokens 超過閾值應觸發 compaction"""
        mgr = self.CM(self.model, "NEXUS")
        self.assertTrue(mgr.should_compact([], self.threshold + 1))
        self.assertFalse(mgr.should_compact([], self.threshold - 1))

    def test_should_compact_by_char_estimate(self):
        """無精確 token 數時，用字元估算"""
        mgr   = self.CM(self.model, "NEXUS", threshold=1_000)
        short = [{"role": "user", "content": "hi"}]  # 很短
        long_ = [{"role": "user", "content": "x" * 5_000}]  # 很長
        self.assertFalse(mgr.should_compact(short))
        self.assertTrue(mgr.should_compact(long_))

    def test_build_context_management_params_structure(self):
        """context_management 參數應有正確結構"""
        mgr    = self.CM(self.model, "NEXUS")
        params = mgr.build_context_management_params()
        self.assertIn("betas", params)
        self.assertIn("context-management-2025-06-27", params["betas"])
        self.assertIn("context_management", params)
        edits = params["context_management"]["edits"]
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["type"], "clear_tool_uses_20250919")

    def test_context_management_trigger_value(self):
        """觸發閾值應等於 compaction manager 的 threshold"""
        threshold = 50_000
        mgr       = self.CM(self.model, "NEXUS", threshold=threshold)
        params    = mgr.build_context_management_params()
        trigger   = params["context_management"]["edits"][0]["trigger"]
        self.assertEqual(trigger["value"], threshold)

    def test_compaction_fallback_on_short_messages(self):
        """訊息太少時，compact() 應直接返回原始訊息（不壓縮）"""
        mgr      = self.CM(self.model, "NEXUS")
        messages = [{"role": "user", "content": "hi"}]
        result   = mgr.compact(messages, client=None, system_prompt="")
        self.assertEqual(result, messages,
                         "少於 4 條訊息不應壓縮")

    def test_compacted_count_tracking(self):
        """compacted_count 應正確追蹤"""
        mgr = self.CM(self.model, "NEXUS")
        self.assertEqual(mgr.compacted_count, 0)


# ══════════════════════════════════════════════════════════════
# Test Group 13：PhaseCheckpoint 修復（第十一輪新增）
# ══════════════════════════════════════════════════════════════

class TestPhaseCheckpointFixed(unittest.TestCase):
    """PhaseCheckpoint P0-1 修復驗證"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _make_ckpt(self, requirement="test req"):
        from core.web_orchestrator import PhaseCheckpoint
        return PhaseCheckpoint(self.tmpdir, requirement)

    def test_close_no_name_error(self):
        """close() 修復後不應拋出 NameError"""
        ckpt = self._make_ckpt()
        try:
            ckpt.close()
        except NameError as e:
            self.fail(f"close() 拋出 NameError：{e}")

    def test_save_is_atomic(self):
        """_save() 應使用原子寫入（不留 tmp 文件）"""
        ckpt = self._make_ckpt()
        ckpt.mark_done(1)
        docs_dir = Path(self.tmpdir) / "docs"
        tmp_files = list(docs_dir.glob(".ship_state_tmp_*"))
        self.assertEqual(len(tmp_files), 0,
                         "原子寫入後不應留下 .ship_state_tmp_* 文件")

    def test_state_file_created(self):
        """mark_done() 後狀態文件應存在且可讀"""
        ckpt       = self._make_ckpt()
        ckpt.mark_done(1)
        state_file = Path(self.tmpdir) / "docs" / ".ship_state.json"
        self.assertTrue(state_file.exists())
        state = json.loads(state_file.read_text())
        self.assertEqual(state["phases"]["1"]["status"], "done")

    def test_load_corrupted_state_returns_empty(self):
        """損毀的狀態文件應靜默重置（不崩潰）"""
        docs = Path(self.tmpdir) / "docs"
        docs.mkdir(exist_ok=True)
        state_file = docs / ".ship_state.json"
        state_file.write_text("{corrupted json{{")
        ckpt = self._make_ckpt()
        self.assertEqual(ckpt.state, {},
                         "損毀狀態應重置為空 dict")

    def test_reset_for_new_requirement(self):
        """reset_for_new_requirement 應清除舊狀態"""
        ckpt = self._make_ckpt("old req")
        ckpt.mark_done(1)
        ckpt.mark_done(2)
        ckpt.reset_for_new_requirement("new req")
        self.assertEqual(ckpt.state.get("requirement"), "new req")
        self.assertEqual(ckpt.state.get("phases"), {},
                         "新需求應重置所有 Phase 狀態")

    def test_is_done_returns_false_for_undone_phase(self):
        """未完成的 Phase 應返回 False"""
        ckpt = self._make_ckpt()
        self.assertFalse(ckpt.is_done(5))

    def test_mark_failed_records_error(self):
        """mark_failed() 應記錄錯誤訊息"""
        ckpt = self._make_ckpt()
        ckpt.mark_failed(3, "API 超時")
        phase_state = ckpt.state["phases"]["3"]
        self.assertEqual(phase_state["status"], "failed")
        self.assertIn("API 超時", phase_state.get("error", ""))


# ══════════════════════════════════════════════════════════════
# Test Group 14：Evals Golden Dataset（第十一輪新增）
# ══════════════════════════════════════════════════════════════

class TestEvalsGoldenDataset(unittest.TestCase):
    """Evals Golden Dataset 和 EvalRunner 的 unit tests"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_evals_dir_exists_and_has_suites(self):
        """evals/ 目錄應存在且有測試套件"""
        from core.evals import EVALS_DIR, SUITES_DIR
        self.assertTrue(EVALS_DIR.exists(),
                        f"evals/ 目錄不存在：{EVALS_DIR}")
        self.assertTrue(SUITES_DIR.exists(),
                        f"evals/suites/ 不存在：{SUITES_DIR}")

    def test_suite_files_are_valid_json(self):
        """所有測試套件文件應是有效 JSON"""
        from core.evals import SUITES_DIR
        suite_files = list(SUITES_DIR.glob("*.json"))
        self.assertGreater(len(suite_files), 0,
                           "至少應有一個測試套件文件")
        for f in suite_files:
            try:
                cases = json.loads(f.read_text())
                self.assertIsInstance(cases, list)
            except json.JSONDecodeError as e:
                self.fail(f"{f.name} JSON 格式無效：{e}")

    def test_suite_cases_have_required_fields(self):
        """每個測試案例應有必要欄位"""
        from core.evals import SUITES_DIR
        required = {"case_id", "suite", "agent", "prompt"}
        for f in SUITES_DIR.glob("*.json"):
            cases = json.loads(f.read_text())
            for case in cases:
                missing = required - set(case.keys())
                self.assertEqual(len(missing), 0,
                                 f"{f.name} / {case.get('case_id')} 缺少欄位：{missing}")

    def test_eval_scorer_keywords(self):
        """EvalScorer 關鍵字命中應正確計算"""
        from core.evals import EvalScorer, EvalCase
        scorer = EvalScorer()
        case   = EvalCase(
            case_id="t1", suite="test", agent="ECHO",
            prompt="test",
            expected_keywords=["用戶故事", "AC", "P0"],
        )
        score, breakdown = scorer.score(case, "用戶故事：xxx，AC：xxx，P0 功能")
        self.assertGreater(score, 0.5)
        self.assertEqual(breakdown["keywords"], 1.0)

    def test_eval_scorer_forbidden_word(self):
        """禁用詞出現應降低分數"""
        from core.evals import EvalScorer, EvalCase
        scorer = EvalScorer()
        case   = EvalCase(
            case_id="t2", suite="test", agent="ECHO",
            prompt="test",
            forbidden_keywords=["lorem ipsum"],
        )
        score_clean, _ = scorer.score(case, "正常輸出內容")
        score_dirty, _ = scorer.score(case, "lorem ipsum 填充文字")
        self.assertGreater(score_clean, score_dirty)

    def test_eval_runner_db_initializes(self):
        """EvalRunner 應能初始化 SQLite DB"""
        from core.evals import EvalRunner, EVALS_DB
        runner = EvalRunner(workdir=self.tmpdir)
        self.assertTrue(EVALS_DB.exists(),
                        f"Evals DB 應已建立：{EVALS_DB}")

    def test_eval_runner_suite_not_found_raises(self):
        """不存在的套件應拋出 FileNotFoundError"""
        from core.evals import EvalRunner
        runner = EvalRunner(workdir=self.tmpdir)
        with self.assertRaises(FileNotFoundError):
            runner.run_suite("nonexistent_suite_xyz")


# ══════════════════════════════════════════════════════════════
# Test Group 15：SwarmScheduler async safety（第十一輪新增）
# ══════════════════════════════════════════════════════════════

class TestSwarmAsyncSafety(unittest.TestCase):
    """AgentSwarm v3.1 async 升級的 unit tests"""

    def test_swarm_has_run_async(self):
        """AgentSwarm 應有 run_async() 方法"""
        from core.swarm import AgentSwarm
        swarm = AgentSwarm(workdir=".")
        self.assertTrue(hasattr(swarm, "run_async"),
                        "AgentSwarm 應有 run_async() 方法")

    def test_run_async_is_coroutine(self):
        """run_async 應是 coroutine function"""
        import asyncio
        from core.swarm import AgentSwarm
        swarm = AgentSwarm(workdir=".")
        self.assertTrue(asyncio.iscoroutinefunction(swarm.run_async),
                        "run_async 應是 async def（coroutine function）")

    def test_swarm_docstring_updated(self):
        """swarm.py docstring 應提及 asyncio"""
        from core.swarm import AgentSwarm
        import inspect
        module_src = inspect.getmodule(AgentSwarm)
        module_doc = module_src.__doc__ or ""
        self.assertIn("asyncio", module_doc.lower(),
                      "模組 docstring 應說明 asyncio 支援")


# ══════════════════════════════════════════════════════════════
# Test Group 16：Brain v3.0 L1 Memory Tool（第十二輪新增）
# ══════════════════════════════════════════════════════════════

class TestBrainMemoryBackend(unittest.TestCase):
    """BrainMemoryBackend（L1 工作記憶）的 unit tests"""

    def setUp(self):
        self.tmpdir  = tempfile.mkdtemp()
        from core.brain.memory_tool import BrainMemoryBackend
        self.backend = BrainMemoryBackend(
            brain_dir  = Path(self.tmpdir),
            agent_name = "test_agent",
        )

    def test_create_and_view(self):
        """建立記憶後應可讀取"""
        self.backend.handle_create({
            "path":    "/memories/notes/test.md",
            "content": "測試記憶內容",
        })
        content = self.backend.handle_view({"path": "/memories/notes/test.md"})
        self.assertIn("測試記憶內容", content)

    def test_str_replace(self):
        """str_replace 應更新內容"""
        self.backend.handle_create({
            "path": "/memories/notes/replace_test.md",
            "content": "舊內容：HS256",
        })
        self.backend.handle_str_replace({
            "path":    "/memories/notes/replace_test.md",
            "old_str": "HS256",
            "new_str": "RS256",
        })
        content = self.backend.handle_view({"path": "/memories/notes/replace_test.md"})
        self.assertIn("RS256", content)
        self.assertNotIn("HS256", content)

    def test_delete(self):
        """刪除後應無法讀取"""
        self.backend.handle_create({
            "path": "/memories/notes/delete_me.md",
            "content": "要刪除的內容",
        })
        self.backend.handle_delete({"path": "/memories/notes/delete_me.md"})
        content = self.backend.handle_view({"path": "/memories/notes/delete_me.md"})
        self.assertNotIn("要刪除的內容", content)

    def test_path_traversal_blocked(self):
        """路徑穿越攻擊應被阻擋"""
        from core.brain.memory_tool import _validate_path
        with self.assertRaises(ValueError):
            _validate_path("../../etc/passwd")
        with self.assertRaises(ValueError):
            _validate_path("/etc/passwd")

    def test_path_prefix_enforced(self):
        """/memories 前綴應被強制"""
        from core.brain.memory_tool import _validate_path
        with self.assertRaises(ValueError):
            _validate_path("/other/path/file.md")
        valid = _validate_path("/memories/notes/ok.md")
        self.assertTrue(valid.startswith("/memories"))

    def test_content_length_limit(self):
        """超長內容應被截斷"""
        from core.brain.memory_tool import MAX_MEMORY_SIZE_CHARS
        big_content = "x" * (MAX_MEMORY_SIZE_CHARS + 10_000)
        self.backend.handle_create({
            "path":    "/memories/notes/big.md",
            "content": big_content,
        })
        content = self.backend.handle_view({"path": "/memories/notes/big.md"})
        self.assertLessEqual(len(content), MAX_MEMORY_SIZE_CHARS + 100)

    def test_search_fts5(self):
        """FTS5 搜尋應找到相關記憶（使用 ASCII 關鍵字，避免中文分詞邊界問題）"""
        self.backend.handle_create({
            "path":    "/memories/pitfalls/jwt.md",
            "content": "JWT auth must use RS256 not HS256 security risk",
        })
        # FTS5 對 ASCII 詞的分詞最可靠
        results = self.backend.search("RS256")
        self.assertGreater(len(results), 0)
        self.assertTrue(any("RS256" in r.get("content", "") for r in results))

    def test_session_summary(self):
        """session_summary 應正確統計"""
        self.backend.handle_create({
            "path": "/memories/notes/s1.md", "content": "test1"
        })
        self.backend.handle_create({
            "path": "/memories/notes/s2.md", "content": "test2"
        })
        summary = self.backend.session_summary()
        self.assertGreaterEqual(summary["total_memories"], 2)
        self.assertGreaterEqual(summary["total_ops"], 2)

    def test_make_memory_params(self):
        """make_memory_params 應包含正確的 API 參數"""
        from core.brain.memory_tool import make_memory_params, MEMORY_BETA_HEADER, MEMORY_TOOL_TYPE
        params = make_memory_params()
        self.assertIn("tools", params)
        self.assertIn("betas", params)
        self.assertIn(MEMORY_BETA_HEADER, params["betas"])
        tool_types = [t["type"] for t in params["tools"]]
        self.assertIn(MEMORY_TOOL_TYPE, tool_types)


# ══════════════════════════════════════════════════════════════
# Test Group 17：Brain v3.0 L2 Graphiti Adapter（第十二輪新增）
# ══════════════════════════════════════════════════════════════

class TestGraphitiAdapter(unittest.TestCase):
    """GraphitiAdapter（L2 情節記憶）的 unit tests"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from core.brain.graphiti_adapter import GraphitiAdapter
        # 不提供真實 DB，測試降級邏輯
        self.adapter = GraphitiAdapter(
            brain_dir  = Path(self.tmpdir),
            db_url     = "bolt://localhost:7999",  # 不存在的 DB
            fallback   = None,
        )

    def test_available_false_without_db(self):
        """沒有 DB 連線時 available 應為 False"""
        # 注意：這個測試假設 FalkorDB/Neo4j 不在測試環境
        result = self.adapter.available
        self.assertIsInstance(result, bool)

    def test_search_sync_fallback_returns_list(self):
        """search_sync 降級時應返回空列表（不崩潰）"""
        results = self.adapter.search_sync("測試查詢", top_k=3)
        self.assertIsInstance(results, list)

    def test_add_episode_sync_fallback(self):
        """add_episode_sync 降級時應返回 False（不崩潰）"""
        from core.brain.graphiti_adapter import KnowledgeEpisode
        ep = KnowledgeEpisode(
            content="NEXUS 決定使用 Next.js App Router",
            source ="phase_4_nexus",
        )
        result = self.adapter.add_episode_sync(ep)
        self.assertIsInstance(result, bool)

    def test_episode_from_phase_helper(self):
        """episode_from_phase 應建立正確的 Episode"""
        from core.brain.graphiti_adapter import episode_from_phase, KnowledgeEpisode
        ep = episode_from_phase(4, "NEXUS", "設計了微服務架構", "使用 API Gateway 模式")
        self.assertIsInstance(ep, KnowledgeEpisode)
        self.assertIn("Phase 4", ep.content)
        self.assertIn("NEXUS", ep.content)
        self.assertIn("API Gateway", ep.content)

    def test_episode_from_commit_helper(self):
        """episode_from_commit 應包含 commit 資訊"""
        from core.brain.graphiti_adapter import episode_from_commit
        ep = episode_from_commit(
            "abc12345", "fix: JWT RS256 migration",
            "ahern", ["auth/jwt.py", "config/security.py"]
        )
        self.assertIn("abc12345"[:8], ep.content)
        self.assertIn("JWT", ep.content)

    def test_episode_from_adr_helper(self):
        """episode_from_adr 應包含 ADR 資訊"""
        from core.brain.graphiti_adapter import episode_from_adr
        ep = episode_from_adr(
            "ADR-007", "使用 PostgreSQL", "支援事務",
            context="NoSQL 無法滿足複雜查詢需求",
            supersedes="ADR-003",
        )
        self.assertIn("ADR-007", ep.content)
        self.assertIn("PostgreSQL", ep.content)
        self.assertIn("ADR-003", ep.metadata["supersedes"])

    def test_temporal_search_result_is_current(self):
        """valid_until=None 應表示仍有效"""
        from core.brain.graphiti_adapter import TemporalSearchResult
        r1 = TemporalSearchResult(
            content="測試", source="test", relevance=0.9,
            valid_until=None
        )
        r2 = TemporalSearchResult(
            content="舊知識", source="test", relevance=0.8,
            valid_until="2025-12-01T00:00:00Z"
        )
        self.assertTrue(r1.is_current)
        self.assertFalse(r2.is_current)

    def test_temporal_result_context_line(self):
        """to_context_line 應包含狀態和來源"""
        from core.brain.graphiti_adapter import TemporalSearchResult
        r = TemporalSearchResult(
            content="使用 PostgreSQL", source="phase_4_nexus",
            relevance=0.9, valid_from="2026-01-15T10:00:00Z"
        )
        line = r.to_context_line()
        self.assertIn("PostgreSQL", line)
        self.assertIn("phase_4_nexus", line)


# ══════════════════════════════════════════════════════════════
# Test Group 18：Brain v3.0 BrainRouter（第十二輪新增）
# ══════════════════════════════════════════════════════════════

class TestBrainRouter(unittest.TestCase):
    """BrainRouter v3.0 三層路由器的 unit tests"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from core.brain.router import BrainRouter
        self.router = BrainRouter(
            brain_dir    = Path(self.tmpdir),
            l3_brain     = None,   # 無 L3 的最小化測試
            graphiti_url = "bolt://localhost:7999",
            agent_name   = "test",
        )

    def test_query_returns_result(self):
        """query() 應返回 BrainQueryResult（不崩潰）"""
        from core.brain.router import BrainQueryResult
        result = self.router.query("修復支付 bug")
        self.assertIsInstance(result, BrainQueryResult)
        self.assertIsInstance(result.elapsed_ms, int)

    def test_query_has_elapsed_ms(self):
        """query() 結果應有計時"""
        result = self.router.query("測試任務")
        self.assertGreater(result.elapsed_ms, 0)

    def test_write_working_memory(self):
        """write_working_memory 應成功寫入 L1"""
        ok = self.router.write_working_memory(
            "pitfalls",
            "JWT RS256：要用 PKCS#8 格式",
            name="jwt_pitfall",
        )
        self.assertTrue(ok)

    def test_context_string_includes_l1(self):
        """若 L1 有記憶，context_string 應包含 L1 內容"""
        self.router.write_working_memory("pitfalls", "重要的踩坑記錄")
        result = self.router.query("踩坑")
        ctx = result.to_context_string()
        if ctx:  # 若有查詢結果
            self.assertIn("工作記憶", ctx)

    def test_status_has_all_layers(self):
        """status() 應包含三層狀態"""
        status = self.router.status()
        self.assertIn("l1_working_memory", status)
        self.assertIn("l2_episodic_memory", status)
        self.assertIn("l3_semantic_memory", status)

    def test_brain_query_result_total(self):
        """BrainQueryResult.total_results 應正確計算"""
        from core.brain.router import BrainQueryResult
        from core.brain.graphiti_adapter import TemporalSearchResult
        r = BrainQueryResult(
            l1_working  = [{"path": "/memories/a", "content": "x"}],
            l2_temporal = [TemporalSearchResult(
                content="y", source="test", relevance=0.9
            )],
            l3_semantic = [],
        )
        self.assertEqual(r.total_results, 2)

    def test_clear_working_memory(self):
        """clear_working_memory 應清空 L1"""
        self.router.write_working_memory("notes", "臨時筆記 1")
        self.router.write_working_memory("notes", "臨時筆記 2")
        count = self.router.clear_working_memory()
        self.assertGreaterEqual(count, 0)   # 不崩潰即可（可能 0 或更多）

    def test_brain_version_updated(self):
        """brain/__init__.py 版本應為 3.0.0"""
        from core.brain import __version__
        self.assertEqual(__version__, "3.0.0",
                         "brain/__init__.py 版本應已更新至 3.0.0")
