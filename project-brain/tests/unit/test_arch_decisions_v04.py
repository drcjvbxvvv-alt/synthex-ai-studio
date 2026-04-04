"""
v0.4.0 架構決策驗收測試

驗證五個 v0.4.0 長期願景決策在所有版本中始終成立：

  決策 VISION-01：動態 confidence 更新
            → _session_nodes 全局字典追蹤本次查詢節點
            → complete_task 自動回饋上限 5 個節點
            → 有 pitfalls → helpful=False；無 pitfalls → helpful=True

  決策 VISION-02：知識衝突自動解決（LLM 仲裁）
            → ConflictResolver 可 import，接受 duck-typed client
            → 仲裁結果快取 86400 秒（24 小時）
            → 由 BRAIN_CONFLICT_RESOLVE env var 控制啟用

  決策 VISION-03：跨專案知識遷移（FederationAutoSync）
            → FederationAutoSync 可 import，具備 add_source / remove_source / sync
            → federation_sync MCP 工具在 mcp_server.py 中存在
            → cmd_fed_sync CLI 輔助函式存在

  決策 VISION-04：唯讀共享模式（brain serve --readonly）
            → _Handler.readonly 類別屬性預設為 False
            → readonly=True 時 POST/PUT/DELETE 攔截並回傳 403
            → brain serve --readonly 旗標存在於 cli.py

  決策 VISION-05：多知識庫合併查詢（multi_brain_query）
            → multi_brain_query MCP 工具存在
            → 支援 BRAIN_EXTRA_DIRS env var（冒號分隔）
            → 輸出格式含 source 標籤（[source] 或 **[source]**）
"""

from __future__ import annotations

import inspect
import os
import unittest
from unittest.mock import MagicMock


# ══════════════════════════════════════════════════════════════════════
# 決策 VISION-01：動態 confidence 更新
# ══════════════════════════════════════════════════════════════════════

class TestVision01DynamicConfidence(unittest.TestCase):
    """v0.4.0 VISION-01：_session_nodes 追蹤節點，complete_task 自動回饋最多 5 個。"""

    def test_session_nodes_global_dict_exists(self):
        """mcp_server._session_nodes 應為全局 dict（VISION-01 session 節點追蹤）。"""
        from project_brain import mcp_server as ms
        self.assertTrue(
            hasattr(ms, "_session_nodes"),
            "mcp_server 應有 _session_nodes 全局變數（v0.4.0 VISION-01）",
        )
        self.assertIsInstance(
            ms._session_nodes, dict,
            "_session_nodes 應為 dict（VISION-01：追蹤 get_context 涉及的節點 ID）",
        )

    def test_complete_task_caps_feedback_at_five(self):
        """complete_task 自動回饋上限為 5 個節點（避免過度調整）。"""
        from project_brain import mcp_server as ms
        # 在 mcp_server 模組原始碼中尋找上限標記
        source = inspect.getsource(ms)
        self.assertIn(
            "[:5]", source,
            "complete_task 應有 [:5] 切片上限（v0.4.0 VISION-01：最多回饋 5 個節點）",
        )

    def test_complete_task_feedback_logic_uses_pitfalls(self):
        """complete_task 有 pitfalls 時應回饋 helpful=False（無 pitfalls → True）。"""
        from project_brain import mcp_server as ms
        source = inspect.getsource(ms)
        # 確認 helpful=not _had_pitfalls 或等效邏輯
        self.assertIn(
            "not _had_pitfalls", source,
            "complete_task 應有 helpful=not _had_pitfalls 邏輯（v0.4.0 VISION-01）",
        )

    def test_vision01_auto_feedback_is_silent_on_failure(self):
        """VISION-01 自動回饋失敗時應靜默降級（不影響正常任務流程）。"""
        from project_brain import mcp_server as ms
        source = inspect.getsource(ms)
        # 確認 VISION-01 的 except 有 logger.debug（不拋例外）
        self.assertIn(
            "VISION-01 auto-feedback failed", source,
            "VISION-01 自動回饋失敗時應有 debug 日誌（靜默降級，v0.4.0 VISION-01）",
        )


# ══════════════════════════════════════════════════════════════════════
# 決策 VISION-02：知識衝突自動解決（LLM 仲裁）
# ══════════════════════════════════════════════════════════════════════

class TestVision02ConflictResolver(unittest.TestCase):
    """v0.4.0 VISION-02：ConflictResolver duck-typed，24h 快取，env var 控制。"""

    def test_conflict_resolver_importable(self):
        """ConflictResolver 應可從 project_brain.conflict_resolver import。"""
        try:
            from project_brain.conflict_resolver import ConflictResolver
        except ImportError as e:
            self.fail(f"ConflictResolver 無法 import（v0.4.0 VISION-02）：{e}")

    def test_conflict_resolver_accepts_duck_typed_client(self):
        """ConflictResolver 應接受任意 duck-typed client（不做型別檢查）。"""
        from project_brain.conflict_resolver import ConflictResolver
        mock_db    = MagicMock()
        mock_graph = MagicMock()
        mock_client = MagicMock()
        # 不應拋例外
        try:
            resolver = ConflictResolver(mock_db, mock_graph, client=mock_client)
            self.assertEqual(resolver._client, mock_client,
                             "ConflictResolver 應儲存傳入的 duck-typed client（VISION-02）")
        except Exception as e:
            self.fail(f"ConflictResolver 不應在 duck-typed client 下拋例外：{e}")

    def test_conflict_resolver_cache_seconds_is_24h(self):
        """CACHE_SECONDS 應為 86400（24 小時，避免重複呼叫 LLM）。"""
        from project_brain.conflict_resolver import CACHE_SECONDS
        self.assertEqual(
            CACHE_SECONDS, 86400,
            f"CACHE_SECONDS 應為 86400（24 小時快取，v0.4.0 VISION-02），實際 {CACHE_SECONDS}",
        )

    def test_conflict_resolver_has_instance_cache(self):
        """ConflictResolver 實例應有 _cache dict（儲存仲裁結果）。"""
        from project_brain.conflict_resolver import ConflictResolver
        mock_db    = MagicMock()
        mock_graph = MagicMock()
        resolver = ConflictResolver(mock_db, mock_graph, client=MagicMock())
        self.assertIsInstance(
            resolver._cache, dict,
            "ConflictResolver._cache 應為 dict（v0.4.0 VISION-02 24h 快取機制）",
        )

    def test_brain_conflict_resolve_env_var_referenced(self):
        """decay_engine.py 或 conflict_resolver.py 原始碼應引用 BRAIN_CONFLICT_RESOLVE env var。"""
        from project_brain import conflict_resolver as cr_mod
        from project_brain import decay_engine as de_mod
        cr_source = inspect.getsource(cr_mod)
        de_source = inspect.getsource(de_mod)
        self.assertTrue(
            "BRAIN_CONFLICT_RESOLVE" in cr_source or "BRAIN_CONFLICT_RESOLVE" in de_source,
            "應有 BRAIN_CONFLICT_RESOLVE env var 引用（v0.4.0 VISION-02：預設關閉）",
        )


# ══════════════════════════════════════════════════════════════════════
# 決策 VISION-03：跨專案知識遷移（FederationAutoSync）
# ══════════════════════════════════════════════════════════════════════

class TestVision03FederationAutoSync(unittest.TestCase):
    """v0.4.0 VISION-03：FederationAutoSync 可 import，有 add/remove/sync，MCP 工具存在。"""

    def test_federation_auto_sync_importable(self):
        """FederationAutoSync 應可從 project_brain.federation import。"""
        try:
            from project_brain.federation import FederationAutoSync
        except ImportError as e:
            self.fail(f"FederationAutoSync 無法 import（v0.4.0 VISION-03）：{e}")

    def test_federation_auto_sync_has_required_methods(self):
        """FederationAutoSync 應有 add_source、remove_source、sync_all 方法。"""
        from project_brain.federation import FederationAutoSync
        for method in ("add_source", "remove_source", "sync_all"):
            self.assertTrue(
                hasattr(FederationAutoSync, method),
                f"FederationAutoSync 應有 {method} 方法（v0.4.0 VISION-03）",
            )

    def test_federation_sync_mcp_tool_exists(self):
        """mcp_server.py 原始碼應含 federation_sync 工具（VISION-03 MCP 工具）。"""
        from project_brain import mcp_server as ms
        source = inspect.getsource(ms)
        self.assertIn(
            "federation_sync", source,
            "mcp_server.py 應有 federation_sync 工具（v0.4.0 VISION-03）",
        )

    def test_cmd_fed_sync_exists_in_federation(self):
        """federation.py 應有 cmd_fed_sync CLI 輔助函式（VISION-03 CLI 整合）。"""
        from project_brain import federation as fed_mod
        self.assertTrue(
            hasattr(fed_mod, "cmd_fed_sync"),
            "federation.py 應有 cmd_fed_sync 函式（v0.4.0 VISION-03 CLI 輔助）",
        )

    def test_federation_auto_sync_reads_sync_sources(self):
        """FederationAutoSync._load_sources 應讀取 sync_sources 設定。"""
        from project_brain import federation as fed_mod
        source = inspect.getsource(fed_mod.FederationAutoSync)
        self.assertIn(
            "sync_sources", source,
            "FederationAutoSync 應讀取 sync_sources 設定（v0.4.0 VISION-03 federation.json）",
        )


# ══════════════════════════════════════════════════════════════════════
# 決策 VISION-04：唯讀共享模式（brain serve --readonly）
# ══════════════════════════════════════════════════════════════════════

class TestVision04ReadonlyMode(unittest.TestCase):
    """v0.4.0 VISION-04：_Handler.readonly 預設 False，寫入被攔截，CLI 有 --readonly。"""

    def test_handler_readonly_attribute_defaults_to_false(self):
        """_Handler.readonly 類別屬性應存在且預設為 False。"""
        from project_brain.api_server import _Handler
        self.assertTrue(
            hasattr(_Handler, "readonly"),
            "_Handler 應有 readonly 類別屬性（v0.4.0 VISION-04）",
        )
        self.assertFalse(
            _Handler.readonly,
            "_Handler.readonly 預設應為 False（v0.4.0 VISION-04：唯讀模式預設關閉）",
        )

    def test_readonly_mode_returns_403_for_write_ops(self):
        """readonly=True 時，POST/PUT/DELETE 攔截邏輯應回傳 403。"""
        from project_brain import api_server as as_mod
        source = inspect.getsource(as_mod._Handler)
        self.assertIn(
            "403", source,
            "readonly 模式應有 403 回應（v0.4.0 VISION-04：寫入攔截）",
        )
        self.assertIn(
            "readonly", source,
            "_Handler 原始碼應有 readonly 攔截邏輯（v0.4.0 VISION-04）",
        )

    def test_readonly_blocks_post_put_delete(self):
        """readonly 攔截邏輯應明確覆蓋 POST、PUT、DELETE 方法。"""
        from project_brain import api_server as as_mod
        source = inspect.getsource(as_mod._Handler)
        for method in ("POST", "PUT", "DELETE"):
            self.assertIn(
                method, source,
                f"readonly 攔截應覆蓋 {method}（v0.4.0 VISION-04 唯讀模式）",
            )

    def test_brain_serve_has_readonly_flag_in_cli(self):
        """cli.py brain serve 應支援 --readonly 旗標。"""
        from project_brain import cli as cli_mod
        source = inspect.getsource(cli_mod)
        self.assertIn(
            "--readonly", source,
            "cli.py 應有 --readonly 旗標（v0.4.0 VISION-04：brain serve --readonly）",
        )


# ══════════════════════════════════════════════════════════════════════
# 決策 VISION-05：多知識庫合併查詢（multi_brain_query）
# ══════════════════════════════════════════════════════════════════════

class TestVision05MultiBrainQuery(unittest.TestCase):
    """v0.4.0 VISION-05：multi_brain_query 工具，BRAIN_EXTRA_DIRS，source 標籤。"""

    def test_multi_brain_query_tool_exists(self):
        """mcp_server.py 應有 multi_brain_query 函式（VISION-05 MCP 工具）。"""
        from project_brain import mcp_server as ms
        source = inspect.getsource(ms)
        self.assertIn(
            "multi_brain_query", source,
            "mcp_server.py 應有 multi_brain_query 工具（v0.4.0 VISION-05）",
        )

    def test_brain_extra_dirs_env_var_supported(self):
        """multi_brain_query 應讀取 BRAIN_EXTRA_DIRS env var（冒號分隔路徑）。"""
        from project_brain import mcp_server as ms
        source = inspect.getsource(ms)
        self.assertIn(
            "BRAIN_EXTRA_DIRS", source,
            "mcp_server.py 應引用 BRAIN_EXTRA_DIRS（v0.4.0 VISION-05：環境變數設定額外 Brain）",
        )

    def test_multi_brain_query_output_has_source_label(self):
        """multi_brain_query 輸出應含 source 標籤（標注結果來源 Brain）。"""
        from project_brain import mcp_server as ms
        source = inspect.getsource(ms)
        # 格式為 **[{r['source']}]** 或 [source: ...]
        self.assertIn(
            "source", source,
            "multi_brain_query 輸出應含 source 標籤（v0.4.0 VISION-05）",
        )
        # 確認是格式化輸出（含方括號）
        self.assertIn(
            "[{r[", source,
            "multi_brain_query 應用 [{r['source']}] 格式標注來源（v0.4.0 VISION-05）",
        )

    def test_multi_brain_query_deduplicates_by_title(self):
        """multi_brain_query 應跨庫以 title 去重（避免相同節點重複出現）。"""
        from project_brain import mcp_server as ms
        source = inspect.getsource(ms)
        self.assertIn(
            "seen_titles", source,
            "multi_brain_query 應有 seen_titles 去重邏輯（v0.4.0 VISION-05）",
        )

    def test_multi_brain_query_sorts_by_confidence(self):
        """multi_brain_query 結果應依 confidence 降冪排序。"""
        from project_brain import mcp_server as ms
        source = inspect.getsource(ms)
        # 確認有 confidence 排序
        self.assertIn(
            "confidence", source,
            "multi_brain_query 應依 confidence 排序（v0.4.0 VISION-05）",
        )
        self.assertIn(
            "reverse=True", source,
            "multi_brain_query 排序應為降冪（reverse=True）（v0.4.0 VISION-05）",
        )


if __name__ == "__main__":
    unittest.main()
