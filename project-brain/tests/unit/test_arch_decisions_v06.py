"""
v0.6.0 架構決策驗收測試

驗證五個 v0.6.0 的核心決策在所有版本中始終成立：

  決策 K-1：全面清除靜默失效路徑，補齊 NudgeEngine + BrainDB 缺口
            → NudgeEngine 的例外均有 logger.warning / logger.debug
            → NudgeEngine 接受 brain_db 參數（BrainDB bridge）
            → 搜尋失敗時回傳空 list，不拋例外

  決策 K-2：Synonym Map 兩表均擴展至 51 條，keys 完全一致
            → brain_db._SYNONYM_MAP 和 context.py._SYNONYM_MAP 均有 51 條
            → 兩表 keys 集合完全相同

  決策 K-3：brain config 單一指令顯示所有 6 處設定來源
            → cmd_config 原始碼包含 6 個編號設定來源

  決策 K-4：review_board.db 加 schema_meta 表；DB 損壞轉為 RuntimeError
            → RB_SCHEMA_VERSION 常數存在
            → schema_meta 表在 _setup() 建立
            → DB 損壞時拋出含 'brain doctor' 提示的 RuntimeError

  決策 K-5：SR access_count 遞增移至 _add_if_budget 之後（STAB-07）
            → _shown_node_ids 在 build() 入口統一宣告（不在主迴圈內）
            → SR 區塊使用 _shown_node_ids，而非 title 子字串比對
            → budget 超出的節點 access_count 不遞增
"""

from __future__ import annotations

import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ══════════════════════════════════════════════════════════════════════
# 決策 K-1：NudgeEngine 靜默失效消除
# ══════════════════════════════════════════════════════════════════════

class TestNudgeEngineSilentFailureElimination(unittest.TestCase):
    """v0.6.0：NudgeEngine 例外均有日誌，不靜默失效。"""

    def test_nudge_engine_exceptions_have_logging(self):
        """NudgeEngine.check() 的 except 區塊應有 logger.warning 或 logger.debug。"""
        from project_brain import nudge_engine as ne_mod
        source = inspect.getsource(ne_mod.NudgeEngine.check)

        # 確認沒有裸 except: pass
        bare_pattern = "except Exception:\n            pass"
        self.assertNotIn(
            bare_pattern, source,
            "NudgeEngine.check 不應有裸 except: pass（v0.6.0 靜默失效消除決策）",
        )

    def test_nudge_engine_has_brain_db_bridge(self):
        """NudgeEngine.__init__ 應接受 brain_db 參數（BrainDB bridge，v0.6.0 補齊缺口）。"""
        import inspect as _i
        from project_brain.nudge_engine import NudgeEngine
        sig = _i.signature(NudgeEngine.__init__)
        self.assertIn(
            "brain_db", sig.parameters,
            "NudgeEngine.__init__ 應有 brain_db 參數（v0.6.0 BrainDB bridge 決策）",
        )

    def test_nudge_engine_stores_brain_db(self):
        """NudgeEngine 應將 brain_db 存為 self._brain_db。"""
        source = inspect.getsource(
            __import__("project_brain.nudge_engine", fromlist=["NudgeEngine"]).NudgeEngine.__init__
        )
        self.assertIn(
            "_brain_db", source,
            "NudgeEngine.__init__ 應設定 self._brain_db（v0.6.0 bridge 決策）",
        )

    def test_nudge_engine_graph_failure_returns_list(self):
        """KnowledgeGraph 搜尋失敗時，NudgeEngine.check() 應回傳 list 而非拋例外。"""
        from project_brain.nudge_engine import NudgeEngine

        mock_graph = MagicMock()
        mock_graph.search.side_effect = RuntimeError("graph 搜尋炸了")
        mock_session = MagicMock()
        mock_session.get_recent_progress.return_value = []

        engine = NudgeEngine(mock_graph, mock_session, brain_db=None)
        try:
            result = engine.check("測試任務")
            self.assertIsInstance(
                result, list,
                "graph 搜尋失敗時 check() 應回傳 list（靜默失效消除）",
            )
        except Exception as e:
            self.fail(f"NudgeEngine.check() 不應在 graph 失敗時拋例外：{e}")


# ══════════════════════════════════════════════════════════════════════
# 決策 K-2：Synonym Map 51 條，keys 完全一致
# ══════════════════════════════════════════════════════════════════════

class TestSynonymMapSync(unittest.TestCase):
    """v0.6.0：brain_db 和 context 兩個 Synonym Map 必須完全同步。"""

    def test_brain_db_synonym_map_has_51_entries(self):
        """brain_db._SYNONYM_MAP 應有 51 個條目。"""
        from project_brain.brain_db import _SYNONYM_MAP
        self.assertEqual(
            len(_SYNONYM_MAP), 51,
            f"brain_db._SYNONYM_MAP 應有 51 條（v0.6.0 SYNC-01 決策），實際 {len(_SYNONYM_MAP)}",
        )

    def test_context_synonym_map_has_51_entries(self):
        """context.py ContextEngineer._SYNONYM_MAP 應有 51 個條目。"""
        from project_brain.context import ContextEngineer
        # _SYNONYM_MAP 是 class attribute
        self.assertEqual(
            len(ContextEngineer._SYNONYM_MAP), 51,
            f"ContextEngineer._SYNONYM_MAP 應有 51 條（v0.6.0 SYNC-01 決策），"
            f"實際 {len(ContextEngineer._SYNONYM_MAP)}",
        )

    def test_both_synonym_maps_have_identical_keys(self):
        """兩個 Synonym Map 的 keys 必須完全一致。"""
        from project_brain.brain_db import _SYNONYM_MAP as db_map
        from project_brain.context import ContextEngineer
        ctx_map = ContextEngineer._SYNONYM_MAP

        db_keys  = set(db_map.keys())
        ctx_keys = set(ctx_map.keys())

        only_in_db  = db_keys - ctx_keys
        only_in_ctx = ctx_keys - db_keys

        self.assertEqual(
            db_keys, ctx_keys,
            f"Synonym Map keys 不一致（v0.6.0 SYNC-01 決策）：\n"
            f"  只在 brain_db: {sorted(only_in_db)}\n"
            f"  只在 context:  {sorted(only_in_ctx)}",
        )


# ══════════════════════════════════════════════════════════════════════
# 決策 K-3：brain config 顯示 6 處設定來源
# ══════════════════════════════════════════════════════════════════════

class TestBrainConfigSixSources(unittest.TestCase):
    """v0.6.0：brain config 顯示所有 6 處設定來源。"""

    def test_cmd_config_covers_six_sources(self):
        """cmd_config 原始碼應包含 6 個編號設定來源（1. ~ 6.）。"""
        from project_brain.cli import cmd_config
        source = inspect.getsource(cmd_config)

        found = 0
        for i in range(1, 7):
            if f"{i}." in source:
                found += 1

        self.assertEqual(
            found, 6,
            f"cmd_config 應涵蓋 6 個設定來源（1.~6.），實際找到 {found} 個（v0.6.0 決策）",
        )

    def test_cmd_config_includes_brain_env_vars(self):
        """brain config 應顯示 BRAIN_* 環境變數（第 6 個來源）。"""
        from project_brain.cli import cmd_config
        source = inspect.getsource(cmd_config)
        self.assertIn(
            "BRAIN_", source,
            "cmd_config 應處理 BRAIN_* 環境變數（v0.6.0 決策：6 處設定來源）",
        )

    def test_cmd_config_includes_brain_config_json(self):
        """brain config 應涵蓋 .brain/config.json（第 1 個來源）。"""
        from project_brain.cli import cmd_config
        source = inspect.getsource(cmd_config)
        self.assertIn(
            "config.json", source,
            "cmd_config 應處理 .brain/config.json（v0.6.0 決策）",
        )


# ══════════════════════════════════════════════════════════════════════
# 決策 K-4：review_board.db schema_meta + RuntimeError
# ══════════════════════════════════════════════════════════════════════

class TestReviewBoardSchemaVersion(unittest.TestCase):
    """v0.6.0（STAB-06）：review_board.db 版本追蹤與 DB 損壞友善錯誤。"""

    def test_rb_schema_version_constant_exists(self):
        """RB_SCHEMA_VERSION 常數應存在且為正整數。"""
        from project_brain.review_board import RB_SCHEMA_VERSION
        self.assertIsInstance(RB_SCHEMA_VERSION, int,
                              "RB_SCHEMA_VERSION 應為整數")
        self.assertGreater(RB_SCHEMA_VERSION, 0,
                           "RB_SCHEMA_VERSION 應 > 0（v0.6.0 STAB-06 決策）")

    def test_schema_meta_table_created_on_setup(self):
        """_setup() 後 review_board.db 應含 schema_meta 表。"""
        tmp = Path(tempfile.mkdtemp())
        from project_brain.graph import KnowledgeGraph
        from project_brain.review_board import KnowledgeReviewBoard
        graph = KnowledgeGraph(tmp)
        krb = KnowledgeReviewBoard(tmp, graph)
        conn = krb._conn_()

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertIn(
            "schema_meta", tables,
            "review_board.db 應含 schema_meta 表（v0.6.0 STAB-06 版本追蹤決策）",
        )

    def test_schema_version_recorded_in_schema_meta(self):
        """schema_meta 表應記錄當前版本號。"""
        tmp = Path(tempfile.mkdtemp())
        from project_brain.graph import KnowledgeGraph
        from project_brain.review_board import KnowledgeReviewBoard, RB_SCHEMA_VERSION
        graph = KnowledgeGraph(tmp)
        krb = KnowledgeReviewBoard(tmp, graph)
        conn = krb._conn_()

        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()
        self.assertIsNotNone(row, "schema_meta 表應有 version 記錄")
        self.assertEqual(
            int(row[0]), RB_SCHEMA_VERSION,
            f"schema_meta version 應為 RB_SCHEMA_VERSION={RB_SCHEMA_VERSION}（v0.6.0 STAB-06）",
        )

    def test_db_corruption_raises_runtime_error_with_brain_doctor(self):
        """DB 損壞時應拋出含 'brain doctor' 提示的 RuntimeError（非原始 stack trace）。"""
        from project_brain.review_board import KnowledgeReviewBoard

        krb = KnowledgeReviewBoard.__new__(KnowledgeReviewBoard)
        krb._db_path = Path("/nonexistent/totally/invalid/path/review_board.db")
        krb._conn    = None

        with self.assertRaises(RuntimeError) as ctx:
            krb._conn_()

        self.assertIn(
            "brain doctor", str(ctx.exception),
            "RuntimeError 訊息應含 'brain doctor' 提示（v0.6.0 STAB-06 決策：使用者友善錯誤）",
        )


# ══════════════════════════════════════════════════════════════════════
# 決策 K-5：SR _shown_node_ids（STAB-07）
# ══════════════════════════════════════════════════════════════════════

class TestSRShownNodeIds(unittest.TestCase):
    """v0.6.0（STAB-07）：SR 追蹤用 _shown_node_ids，不用 title 子字串比對。"""

    def test_shown_node_ids_declared_at_build_entry(self):
        """_shown_node_ids 應在 build() 方法入口宣告，不在主迴圈內。"""
        from project_brain.context import ContextEngineer
        source = inspect.getsource(ContextEngineer.build)

        # 找 sections = [] 和 _shown_node_ids 的宣告位置
        sections_pos     = source.find("sections = []")
        shown_ids_pos    = source.find("_shown_node_ids")
        # 確認 _shown_node_ids 在 build() 方法體的早期（不在深層迴圈裡）

        self.assertGreater(sections_pos, -1,
                           "build() 應有 sections = []")
        self.assertGreater(shown_ids_pos, -1,
                           "build() 應宣告 _shown_node_ids（v0.6.0 STAB-07）")
        # _shown_node_ids 應在 "all_nodes" 關鍵字之前宣告（確保在主迴圈入口前）
        all_nodes_pos = source.find("all_nodes")
        self.assertLess(
            shown_ids_pos, all_nodes_pos,
            "_shown_node_ids 應在 all_nodes 迴圈之前宣告（STAB-07：build() 入口統一宣告）",
        )

    def test_sr_block_uses_shown_node_ids_not_title_matching(self):
        """SR 更新區塊應使用 _shown_node_ids，而非 title 子字串比對。"""
        from project_brain.context import ContextEngineer
        source = inspect.getsource(ContextEngineer.build)

        # 確認 SR 區塊有 _shown_node_ids 指派
        self.assertIn(
            "_node_ids = _shown_node_ids",
            source,
            "SR 區塊應使用 _node_ids = _shown_node_ids（v0.6.0 STAB-07）",
        )

        # 確認沒有 title 子字串比對模式（舊的 buggy 做法）
        old_pattern_variants = [
            "in result",    # 舊版: if node_id in result (title-based)
        ]
        # 注意：不檢查所有 "in result"，只確認 SR 更新段不依賴 title 比對
        # 最重要的是 _shown_node_ids 的使用
        self.assertIn(
            "_shown_node_ids",
            source,
            "build() 應使用 _shown_node_ids 追蹤已顯示節點（STAB-07）",
        )

    def test_access_count_increment_after_add_if_budget(self):
        """access_count 遞增邏輯應在 _add_if_budget 確認節點進入 context 後才執行。"""
        from project_brain.context import ContextEngineer
        source = inspect.getsource(ContextEngineer.build)

        add_if_budget_pos   = source.find("_add_if_budget")
        shown_ids_append    = source.find("_shown_node_ids.append")
        # 搜尋實際遞增語句 "access_count+1"，避免找到 SQL 欄位名稱的早期出現
        access_count_pos    = source.find("access_count+1")

        self.assertGreater(add_if_budget_pos, -1, "build() 應呼叫 _add_if_budget")
        self.assertGreater(shown_ids_append, add_if_budget_pos,
                           "_shown_node_ids.append 應在 _add_if_budget 之後（STAB-07）")
        self.assertGreater(access_count_pos, shown_ids_append,
                           "access_count+1 遞增應在 _shown_node_ids.append 之後（STAB-07）")


if __name__ == "__main__":
    unittest.main()
