"""
v0.2.0 架構決策驗收測試

驗證兩個 v0.2.0 的核心決策在所有版本中始終成立：

  決策 C：BRAIN_WORKDIR 改為非必要（自動偵測為主）
          → _find_brain_root() 從任意子目錄往上找 .brain/
          → 找不到時回傳 None（不拋錯）
          → BRAIN_WORKDIR env var 為選填，提供時優先使用

  決策 D：查詢展開限每詞 3 個同義詞，總上限 15
          → _expand_query() 每個 token 最多貢獻 3 個同義詞
          → 總回傳詞數不超過 EXPAND_LIMIT（預設 15）
          → EXPAND_LIMIT 可透過 BRAIN_EXPAND_LIMIT 環境變數覆蓋
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════
# 決策 C：BRAIN_WORKDIR 自動偵測
# ══════════════════════════════════════════════════════════════════════

class TestBrainWorkdirDecision(unittest.TestCase):
    """v0.2.0：BRAIN_WORKDIR 改為非必要，_find_brain_root 自動往上偵測。"""

    def _find_brain_root(self, start: str):
        """直接引用 mcp_server 的 _find_brain_root"""
        from project_brain.mcp_server import _find_brain_root
        return _find_brain_root(start)

    def test_find_brain_root_finds_brain_dir(self):
        """從含有 .brain/ 的目錄出發，應直接找到自身。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        brain_dir = tmp / ".brain"
        brain_dir.mkdir()

        result = self._find_brain_root(str(tmp))
        self.assertEqual(result, tmp.resolve(),
                         "_find_brain_root 應在含 .brain/ 的目錄回傳該目錄")

    def test_find_brain_root_walks_up(self):
        """從子目錄出發，應往上走找到 .brain/。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".brain").mkdir()
        subdir = tmp / "src" / "deep" / "nested"
        subdir.mkdir(parents=True)

        result = self._find_brain_root(str(subdir))
        self.assertEqual(result, tmp.resolve(),
                         "_find_brain_root 應往上走找到 .brain/（v0.2.0 決策：auto-detect）")

    def test_find_brain_root_returns_none_when_not_found(self):
        """找不到 .brain/ 時應回傳 None，不拋出例外。"""
        import tempfile
        # 使用沒有 .brain/ 的臨時目錄
        tmp = Path(tempfile.mkdtemp())
        # 確保此路徑確實不含 .brain/
        for parent in [tmp, *tmp.parents]:
            if (parent / ".brain").is_dir():
                self.skipTest(f"意外在 {parent} 找到 .brain/，跳過測試")

        result = self._find_brain_root(str(tmp))
        self.assertIsNone(result,
                          "_find_brain_root 找不到 .brain/ 時應回傳 None（不拋錯）")

    def test_find_brain_root_handles_file_path(self):
        """傳入檔案路徑時，應以其父目錄為起點向上搜尋。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".brain").mkdir()
        filepath = tmp / "some_file.py"
        filepath.touch()

        result = self._find_brain_root(str(filepath))
        self.assertEqual(result, tmp.resolve(),
                         "傳入檔案路徑時應以父目錄為起點（v0.2.0 決策）")

    def test_brain_workdir_env_is_optional(self):
        """BRAIN_WORKDIR env var 不存在時系統不應啟動失敗（選填）。"""
        # 僅驗證 _find_brain_root 函式可被呼叫，不需要 BRAIN_WORKDIR
        original = os.environ.pop("BRAIN_WORKDIR", None)
        try:
            from project_brain.mcp_server import _find_brain_root
            # 可以正常呼叫，回傳 None 或有效路徑都可接受
            result = _find_brain_root("/tmp")
            # 沒有拋出例外即通過
            self.assertIn(type(result), [type(None), Path],
                          "BRAIN_WORKDIR 未設定時 _find_brain_root 不應拋錯（v0.2.0 決策）")
        finally:
            if original is not None:
                os.environ["BRAIN_WORKDIR"] = original

    def test_find_brain_root_not_sensitive_to_trailing_slash(self):
        """帶尾斜線的路徑也能正確找到 .brain/。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".brain").mkdir()

        with_slash = str(tmp) + "/"
        result = self._find_brain_root(with_slash)
        self.assertIsNotNone(result,
                             "帶尾斜線的路徑也應能找到 .brain/")


# ══════════════════════════════════════════════════════════════════════
# 決策 D：查詢展開上限
# ══════════════════════════════════════════════════════════════════════

class TestQueryExpansionDecision(unittest.TestCase):
    """v0.2.0：查詢展開限每詞 3 個同義詞，總上限 15。"""

    def _make_engine(self, tmp_path):
        from project_brain.graph import KnowledgeGraph
        from project_brain.context import ContextEngineer
        graph = KnowledgeGraph(tmp_path)
        brain_dir = tmp_path / ".brain"
        brain_dir.mkdir(exist_ok=True)
        return ContextEngineer(graph, brain_dir=brain_dir)

    def test_expand_limit_default_is_15(self):
        """EXPAND_LIMIT 預設值應為 15。"""
        # 暫時移除環境變數確保讀到預設值
        original = os.environ.pop("BRAIN_EXPAND_LIMIT", None)
        try:
            import importlib
            import project_brain.context as ctx_mod
            importlib.reload(ctx_mod)
            self.assertEqual(ctx_mod.EXPAND_LIMIT, 15,
                             "EXPAND_LIMIT 預設值應為 15（v0.2.0 決策：cap 15 total terms）")
        finally:
            if original is not None:
                os.environ["BRAIN_EXPAND_LIMIT"] = original
            import importlib, project_brain.context as ctx_mod
            importlib.reload(ctx_mod)

    def test_expand_query_total_not_exceed_limit(self):
        """_expand_query 回傳總詞數不超過 EXPAND_LIMIT。"""
        import tempfile
        from project_brain.context import EXPAND_LIMIT
        tmp = Path(tempfile.mkdtemp())
        engine = self._make_engine(tmp)

        # 使用一個會觸發大量同義詞擴展的查詢
        long_query = "資料庫 測試 錯誤 遷移 容器 日誌 配置 重試 部署 async"
        result = engine._expand_query(long_query)

        self.assertLessEqual(len(result), EXPAND_LIMIT,
                             f"_expand_query 回傳 {len(result)} 個詞，超過 EXPAND_LIMIT={EXPAND_LIMIT}（v0.2.0 決策）")

    def test_each_term_contributes_at_most_3_synonyms(self):
        """單一 token 最多貢獻 3 個同義詞（[:3] cap）。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        engine = self._make_engine(tmp)

        # 直接用 _SYNONYM_MAP 找一個有超過 3 個同義詞的詞
        synonym_map = engine._SYNONYM_MAP
        test_word = None
        for word, syns in synonym_map.items():
            if len(syns) > 3:
                test_word = word
                break

        if test_word is None:
            self.skipTest("找不到有超過 3 個同義詞的詞，跳過測試")

        result = engine._expand_query(test_word)
        # 結果包含原始詞 + 最多 3 個同義詞 = 最多 4 個
        self.assertLessEqual(len(result), 4,
                             f"單詞 '{test_word}' 展開後應最多 4 項（原詞+3同義詞），實際 {len(result)} 個")

    def test_expand_limit_env_configurable(self):
        """EXPAND_LIMIT 可透過 BRAIN_EXPAND_LIMIT 環境變數調整。"""
        import importlib
        import project_brain.context as ctx_mod

        original = os.environ.get("BRAIN_EXPAND_LIMIT")
        try:
            os.environ["BRAIN_EXPAND_LIMIT"] = "5"
            importlib.reload(ctx_mod)
            self.assertEqual(ctx_mod.EXPAND_LIMIT, 5,
                             "設定 BRAIN_EXPAND_LIMIT=5 後 EXPAND_LIMIT 應為 5（v0.2.0 決策：env-configurable）")
        finally:
            if original is not None:
                os.environ["BRAIN_EXPAND_LIMIT"] = original
            else:
                os.environ.pop("BRAIN_EXPAND_LIMIT", None)
            importlib.reload(ctx_mod)

    def test_expand_query_returns_list(self):
        """_expand_query 必須回傳 list（不回傳 None 或其他型別）。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        engine = self._make_engine(tmp)

        result = engine._expand_query("測試查詢")
        self.assertIsInstance(result, list,
                              "_expand_query 應回傳 list")

    def test_expand_query_includes_original_terms(self):
        """_expand_query 結果應包含原始輸入詞（不只是同義詞）。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        engine = self._make_engine(tmp)

        result = engine._expand_query("資料庫")
        # 原始詞應在結果中
        found = any("資料庫" in r or "database" in r.lower() or "db" in r.lower()
                    for r in result)
        self.assertTrue(found,
                        "_expand_query 結果應包含原始詞或其直接變體")

    def test_expand_query_empty_input(self):
        """空查詢應回傳空 list 或不拋出例外。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        engine = self._make_engine(tmp)

        try:
            result = engine._expand_query("")
            self.assertIsInstance(result, list,
                                  "空查詢應回傳 list（可為空）")
        except Exception as e:
            self.fail(f"_expand_query('') 不應拋出例外：{e}")


if __name__ == "__main__":
    unittest.main()
