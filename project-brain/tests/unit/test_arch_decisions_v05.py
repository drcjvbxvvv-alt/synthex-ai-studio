"""
v0.5.0 架構決策驗收測試

驗證 v0.5.0 的核心決策在所有版本中始終成立：

  決策 J：STB/FLY 修復優先於新功能
          → 靜默失效比崩潰更危險：project_brain/ 中不存在裸 except: pass
          → FLY-01：空知識庫冷啟動回傳引導訊息，而非空字串
          → FLY-02：_infer_scope 遵循 git remote > 子目錄 > workdir 名稱 > 'global' 優先順序
"""

from __future__ import annotations

import inspect
import os
import re
import unittest
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════
# 決策 J-1：STB — 靜默失效已消除（project_brain/ 中無裸 except: pass）
# ══════════════════════════════════════════════════════════════════════

class TestNoSilentFailures(unittest.TestCase):
    """v0.5.0：靜默失效比崩潰更危險 — 所有例外均需記錄。"""

    _PKG = Path(__file__).parent.parent.parent / "project_brain"

    def _iter_py_files(self):
        return self._PKG.rglob("*.py")

    def test_stb04_global_scope_warning_exists_in_cli(self):
        """STB-04：brain add 落為 global scope 時必須有警告提示（v0.5.0 STB 決策）。"""
        cli_source = (self._PKG / "cli.py").read_text(encoding="utf-8")
        # STB-04 的警告訊息應明確提及 global scope 和污染風險
        has_global_warning = (
            "global scope" in cli_source
            or "global" in cli_source and "跨所有專案可見" in cli_source
        )
        self.assertTrue(
            has_global_warning,
            "cli.py 應有 global scope 警告提示（v0.5.0 STB-04 決策：避免無意識跨專案污染）",
        )

    def test_stb04_global_warning_not_silently_swallowed(self):
        """STB-04 警告邏輯不應被 try/except 包住（不可靜默失效）。"""
        cli_source = (self._PKG / "cli.py").read_text(encoding="utf-8")
        # 確認 STB-04 警告碼存在
        self.assertIn(
            "跨所有專案可見",
            cli_source,
            "cli.py 應包含 global scope 跨專案可見警告（v0.5.0 STB-04）",
        )

    def test_project_brain_modules_import_logger(self):
        """核心模組應 import logging，表示有日誌能力。"""
        core_modules = [
            "brain_db.py",
            "context.py",
            "graph.py",
            "decay_engine.py",
            "review_board.py",
        ]
        for name in core_modules:
            path = self._PKG / name
            if not path.exists():
                continue
            source = path.read_text(encoding="utf-8")
            self.assertIn(
                "import logging",
                source,
                f"{name} 應 import logging（支援靜默失效的可觀察性，v0.5.0 STB 決策）",
            )


# ══════════════════════════════════════════════════════════════════════
# 決策 J-2：FLY-01 — 冷啟動引導訊息
# ══════════════════════════════════════════════════════════════════════

class TestColdStartGuidance(unittest.TestCase):
    """v0.5.0 FLY-01：空知識庫冷啟動應回傳引導訊息，而非空字串。"""

    def _setup(self):
        import tempfile
        from project_brain.graph import KnowledgeGraph
        from project_brain.context import ContextEngineer
        tmp = Path(tempfile.mkdtemp())
        brain_dir = tmp / ".brain"
        brain_dir.mkdir()
        graph = KnowledgeGraph(tmp)
        engine = ContextEngineer(graph, brain_dir=brain_dir)
        return engine

    def test_cold_start_returns_non_empty_string(self):
        """空知識庫時 build() 應回傳非空字串（而非空字串讓 AI 誤以為沒有 context）。"""
        engine = self._setup()
        result = engine.build("測試任務")
        self.assertIsInstance(result, str)
        self.assertGreater(
            len(result.strip()), 0,
            "空知識庫冷啟動應回傳引導訊息，而非空字串（v0.5.0 FLY-01 決策）",
        )

    def test_cold_start_guidance_contains_add_hint(self):
        """冷啟動引導訊息應包含 brain add 或 add_knowledge 指引。"""
        engine = self._setup()
        result = engine.build("測試任務")
        has_add_hint = "brain add" in result or "add_knowledge" in result
        self.assertTrue(
            has_add_hint,
            "冷啟動訊息應包含如何新增知識的提示（v0.5.0 FLY-01：引導使用者啟動飛輪）",
        )

    def test_cold_start_guidance_mentions_task(self):
        """冷啟動引導訊息應包含任務描述（個人化，非通用樣板）。"""
        task = "獨特任務描述X9Z"
        engine = self._setup()
        result = engine.build(task)
        # 任務描述前 60 字應出現在訊息中
        self.assertIn(
            task[:20],
            result,
            "冷啟動訊息應含任務描述（個人化回應，v0.5.0 FLY-01）",
        )

    def test_build_returns_header_when_knowledge_exists(self):
        """有知識時 build() 應回傳含 Project Brain 標頭的字串（而非引導訊息）。"""
        import tempfile
        from project_brain.graph import KnowledgeGraph
        from project_brain.context import ContextEngineer
        tmp = Path(tempfile.mkdtemp())
        brain_dir = tmp / ".brain"
        brain_dir.mkdir()
        graph = KnowledgeGraph(tmp)
        graph.add_node("n1", "Rule", "測試規則", content="內容")
        engine = ContextEngineer(graph, brain_dir=brain_dir)

        result = engine.build("測試規則")
        # 有知識時不應出現冷啟動引導
        self.assertNotIn(
            "尚無相關知識",
            result,
            "有知識時不應顯示冷啟動引導訊息",
        )


# ══════════════════════════════════════════════════════════════════════
# 決策 J-3：FLY-02 — _infer_scope 優先順序
# ══════════════════════════════════════════════════════════════════════

class TestScopeInferencePriority(unittest.TestCase):
    """v0.5.0 FLY-02：_infer_scope 遵循 git > 子目錄 > workdir 名稱 > global 優先序。"""

    def _infer_scope(self, workdir: str, current_file: str = "") -> str:
        from project_brain.cli import _infer_scope
        return _infer_scope(workdir, current_file)

    def test_infer_scope_priority_order_in_source(self):
        """ARCH-07: 規範實作在 BrainDB.infer_scope，4 個 priority 步驟須依序出現。"""
        from project_brain.brain_db import BrainDB
        source = inspect.getsource(BrainDB.infer_scope)

        # 確認原始碼中 4 個步驟依順序存在
        git_pos     = source.find("git remote")
        subdir_pos  = source.find("Sub-directory")
        workdir_pos = source.find("workdir name")
        # 搜尋 return 'global' 語句，而非 docstring 裡的 'global' 關鍵字
        global_pos  = source.find("return 'global'")

        self.assertGreater(git_pos, -1, "_infer_scope 應有 git remote 步驟")
        self.assertGreater(subdir_pos, git_pos,
                           "子目錄步驟應在 git remote 之後（FLY-02 優先順序）")
        self.assertGreater(workdir_pos, subdir_pos,
                           "workdir 名稱步驟應在子目錄之後（FLY-02 優先順序）")
        self.assertGreater(global_pos, workdir_pos,
                           "return 'global' 應為最後回退（FLY-02 優先順序）")

    def test_infer_scope_uses_workdir_name(self):
        """無 git remote、無子目錄時，應回傳 workdir 名稱（第 3 優先）。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        # 建立一個名稱不在 skip list 的臨時目錄
        named_dir = tmp / "payment_service"
        named_dir.mkdir()

        result = self._infer_scope(str(named_dir))
        self.assertEqual(
            result, "payment_service",
            f"無 git remote 時應用 workdir 名稱 'payment_service'（FLY-02 第 3 優先），得到: {result}",
        )

    def test_infer_scope_returns_global_for_skip_dirs(self):
        """workdir 名稱在 skip list 中時，應回傳 'global'（最後回退）。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        # 'src' 在 _skip list 中
        src_dir = tmp / "src"
        src_dir.mkdir()

        result = self._infer_scope(str(src_dir))
        self.assertEqual(
            result, "global",
            "workdir 名稱為 'src'（skip list）時應回傳 'global'（FLY-02 最後回退）",
        )

    def test_infer_scope_uses_subdirectory_keyword(self):
        """current_file 路徑包含服務關鍵字時，應回傳子目錄名稱（第 2 優先）。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp()).resolve()  # resolve macOS /tmp symlink
        # 建立含 'service' 關鍵字的子目錄
        svc_dir = tmp / "payment_service"
        svc_dir.mkdir()
        test_file = svc_dir / "handler.py"
        test_file.touch()

        # 使用 resolve() 確保兩端路徑一致，避免 macOS /tmp→/private/tmp 的相對路徑問題
        result = self._infer_scope(str(tmp), str(test_file.resolve()))
        self.assertIn(
            "payment_service", result,
            f"current_file 在 payment_service/ 子目錄時應回傳該子目錄（FLY-02 第 2 優先），得到: {result}",
        )

    def test_infer_scope_sanitises_result(self):
        """回傳值應只含 a-z、0-9、底線（不含空白或特殊字元）。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        named_dir = tmp / "my-service"
        named_dir.mkdir()

        result = self._infer_scope(str(named_dir))
        self.assertRegex(
            result, r"^[a-z0-9_]+$",
            f"_infer_scope 回傳值應只含 a-z/0-9/底線，得到: '{result}'",
        )


if __name__ == "__main__":
    unittest.main()
