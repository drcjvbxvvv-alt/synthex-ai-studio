"""
tests/unit/test_webui_fts_ngram.py

P1-3 修復驗收 — WebUI _sync_fts 使用 BrainDB._ngram() 保持 CJK 搜尋一致性

背景：WebUI PATCH 後 _sync_fts 直接寫 raw title/content 到 FTS5，
但 BrainDB.add_node() 使用 CJK n-gram tokenization。修復後 WebUI
也使用 _ngram()，確保中文編輯後仍可搜尋。
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from project_brain.core.brain_db import BrainDB


def _sync_fts_import():
    """Import the WebUI _sync_fts function."""
    from project_brain.interfaces.web_ui.server import _sync_fts
    return _sync_fts


class TestWebUIFTSNgram(unittest.TestCase):
    """驗證 _sync_fts 使用 n-gram tokenization。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = BrainDB(Path(self._tmp.name))

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass
        self._tmp.cleanup()

    def test_cjk_searchable_after_sync_fts(self):
        """中文節點經 _sync_fts 後仍可透過子詞搜尋找到。"""
        _sync_fts = _sync_fts_import()

        # Add node via BrainDB (correct n-gram)
        self.db.add_node(
            node_id="n1", node_type="Rule",
            title="部署到 Kubernetes 必須使用 Helm",
            content="所有生產環境部署必須使用 Helm Chart",
            tags=[], confidence=0.9,
        )

        # Simulate WebUI PATCH: update title directly in nodes table
        self.db.conn.execute(
            "UPDATE nodes SET title=? WHERE id='n1'",
            ("部署到 Kubernetes 改用 Kustomize",)
        )
        self.db.conn.commit()

        # Run WebUI _sync_fts (should use _ngram)
        _sync_fts(self.db.conn, "n1")
        self.db.conn.commit()

        # Search for sub-word should still work
        results = self.db.search_nodes("Kubernetes")
        found_ids = [r["id"] for r in results]
        self.assertIn("n1", found_ids, "Node should be findable after _sync_fts")

    def test_cjk_subword_searchable_after_sync_fts(self):
        """中文子詞搜尋在 _sync_fts 後仍可用。"""
        _sync_fts = _sync_fts_import()

        self.db.add_node(
            node_id="n2", node_type="Pitfall",
            title="資料庫連線逾時設定",
            content="PostgreSQL 連線池必須設定 timeout",
            tags=[], confidence=0.8,
        )

        # Simulate WebUI edit
        self.db.conn.execute(
            "UPDATE nodes SET title=? WHERE id='n2'",
            ("資料庫連線逾時最佳實踐",)
        )
        self.db.conn.commit()
        _sync_fts(self.db.conn, "n2")
        self.db.conn.commit()

        # Search with partial CJK term
        results = self.db.search_nodes("連線逾時")
        found_ids = [r["id"] for r in results]
        self.assertIn("n2", found_ids, "CJK sub-word search should work after _sync_fts")

    def test_fts_content_uses_ngram_not_raw(self):
        """_sync_fts 寫入 FTS5 的內容應包含 n-gram tokens，非 raw text。"""
        _sync_fts = _sync_fts_import()

        self.db.add_node(
            node_id="n3", node_type="Rule",
            title="認證機制規則",
            content="JWT 必須驗證 exp",
            tags=[], confidence=0.9,
        )

        # Simulate WebUI edit
        self.db.conn.execute(
            "UPDATE nodes SET title=? WHERE id='n3'",
            ("認證機制最佳實踐",)
        )
        self.db.conn.commit()
        _sync_fts(self.db.conn, "n3")
        self.db.conn.commit()

        # Read FTS5 content directly
        row = self.db.conn.execute(
            "SELECT title FROM nodes_fts WHERE id='n3'"
        ).fetchone()
        self.assertIsNotNone(row, "FTS5 entry should exist")
        fts_title = row[0]
        # N-gram of "認證機制最佳實踐" should produce bigrams
        # Raw text would just be "認證機制最佳實踐" without spaces
        ngram_output = BrainDB._ngram("認證機制最佳實踐")
        self.assertEqual(fts_title, ngram_output,
                         f"FTS5 title should be n-gram tokenized: got {fts_title!r}, "
                         f"expected {ngram_output!r}")

    def test_sync_fts_nonexistent_node(self):
        """_sync_fts on non-existent node should not crash."""
        _sync_fts = _sync_fts_import()
        # Should not raise
        _sync_fts(self.db.conn, "nonexistent-id")

    def test_english_text_unaffected(self):
        """English text should still work correctly after _sync_fts."""
        _sync_fts = _sync_fts_import()

        self.db.add_node(
            node_id="n4", node_type="Decision",
            title="Use PostgreSQL over MySQL",
            content="ACID guarantees required",
            tags=[], confidence=0.85,
        )

        self.db.conn.execute(
            "UPDATE nodes SET title=? WHERE id='n4'",
            ("Use PostgreSQL for all services",)
        )
        self.db.conn.commit()
        _sync_fts(self.db.conn, "n4")
        self.db.conn.commit()

        results = self.db.search_nodes("PostgreSQL")
        found_ids = [r["id"] for r in results]
        self.assertIn("n4", found_ids)


if __name__ == "__main__":
    unittest.main()
