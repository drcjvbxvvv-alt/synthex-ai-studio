"""
v0.1.0 架構決策驗收測試

驗證兩個 v0.1.0 的核心決策在所有版本中始終成立：

  決策 A：使用 SQLite WAL 而非 PostgreSQL
          → 所有主要 DB 連線都必須啟用 WAL 模式

  決策 B：知識衰減不刪除節點，只降低可見度
          → _apply_decay 只 UPDATE confidence / meta，從不 DELETE
          → 衰減後節點數量不變
          → confidence 不低於 DECAY_FLOOR
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════
# 決策 A：SQLite WAL 模式
# ══════════════════════════════════════════════════════════════════════

class TestWALDecision(unittest.TestCase):
    """v0.1.0：所有主要 DB 類別必須啟用 WAL 模式。"""

    def _wal_mode(self, conn: sqlite3.Connection) -> str:
        return conn.execute("PRAGMA journal_mode").fetchone()[0]

    def test_brain_db_uses_wal(self, tmp_path=None):
        """BrainDB 連線應為 WAL 模式。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp()) if tmp_path is None else tmp_path
        from project_brain.brain_db import BrainDB
        db = BrainDB(tmp)
        self.assertEqual(self._wal_mode(db.conn), "wal",
                         "BrainDB 應啟用 WAL 模式（multi-process read-write 安全）")

    def test_knowledge_graph_uses_wal(self, tmp_path=None):
        """KnowledgeGraph 連線應為 WAL 模式。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp()) if tmp_path is None else tmp_path
        from project_brain.graph import KnowledgeGraph
        graph = KnowledgeGraph(tmp)
        self.assertEqual(self._wal_mode(graph._conn), "wal",
                         "KnowledgeGraph 應啟用 WAL 模式")

    def test_review_board_uses_wal(self, tmp_path=None):
        """KnowledgeReviewBoard 連線應為 WAL 模式。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp()) if tmp_path is None else tmp_path
        from project_brain.graph import KnowledgeGraph
        from project_brain.review_board import KnowledgeReviewBoard
        graph = KnowledgeGraph(tmp)
        krb = KnowledgeReviewBoard(tmp, graph)
        conn = krb._conn_()
        self.assertEqual(self._wal_mode(conn), "wal",
                         "KnowledgeReviewBoard 應啟用 WAL 模式（STAB-06 後）")


# ══════════════════════════════════════════════════════════════════════
# 決策 B：衰減不刪除節點
# ══════════════════════════════════════════════════════════════════════

class TestDecayNoDeleteDecision(unittest.TestCase):
    """v0.1.0：知識衰減只降低信心，不刪除節點。"""

    def _setup(self):
        """建立測試用 KnowledgeGraph + DecayEngine，返回 (tmp_path, graph, engine)。"""
        import tempfile
        from project_brain.graph import KnowledgeGraph
        from project_brain.decay_engine import DecayEngine
        tmp = Path(tempfile.mkdtemp())
        graph = KnowledgeGraph(tmp)
        engine = DecayEngine(graph, workdir=str(tmp))
        return tmp, graph, engine

    def test_apply_decay_does_not_delete_node(self):
        """_apply_decay 後節點仍存在（不可刪除）。"""
        _, graph, engine = self._setup()
        graph.add_node("n1", "Rule", "永恆規則",
                       content="不應被衰減刪除",
                       meta={"confidence": 0.9})

        before = graph._conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE id='n1'"
        ).fetchone()[0]
        self.assertEqual(before, 1)

        # 執行衰減（信心降到 0.2，標記 deprecated）
        engine._apply_decay("n1", old_conf=0.9, new_conf=0.2, deprecated=True)

        after = graph._conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE id='n1'"
        ).fetchone()[0]
        self.assertEqual(after, 1,
                         "衰減後節點必須仍存在，不可被刪除（v0.1.0 決策）")

    def test_apply_decay_reduces_confidence(self):
        """_apply_decay 應更新 confidence 欄位。"""
        _, graph, engine = self._setup()
        graph.add_node("n2", "Pitfall", "老舊陷阱",
                       meta={"confidence": 0.8})

        engine._apply_decay("n2", old_conf=0.8, new_conf=0.3, deprecated=False)

        row = graph._conn.execute(
            "SELECT confidence FROM nodes WHERE id='n2'"
        ).fetchone()
        self.assertAlmostEqual(row["confidence"], 0.3, places=3,
                               msg="confidence 欄位應被更新為衰減後的值")

    def test_apply_decay_deprecated_flag_in_meta(self):
        """信心極低時 meta.deprecated 應設為 True，節點仍存在。"""
        _, graph, engine = self._setup()
        graph.add_node("n3", "Decision", "過時決策",
                       meta={"confidence": 0.9})

        engine._apply_decay("n3", old_conf=0.9, new_conf=0.06, deprecated=True)

        row = graph._conn.execute(
            "SELECT meta FROM nodes WHERE id='n3'"
        ).fetchone()
        self.assertIsNotNone(row, "節點必須仍存在")
        meta = json.loads(row["meta"] or "{}")
        self.assertTrue(meta.get("deprecated"),
                        "deprecated 旗標應設為 True（只降低可見度，不刪除）")

    def test_decay_floor_respected(self):
        """衰減引擎的 DECAY_FLOOR 防止信心降至 0。"""
        from project_brain.decay_engine import DECAY_FLOOR
        self.assertGreater(DECAY_FLOOR, 0,
                           "DECAY_FLOOR 必須 > 0，防止節點完全消失")
        self.assertLessEqual(DECAY_FLOOR, 0.1,
                             "DECAY_FLOOR 不應過高（應允許足夠衰減）")

    def test_total_node_count_unchanged_after_bulk_decay(self):
        """批次衰減後知識庫節點總數不變。"""
        _, graph, engine = self._setup()
        for i in range(5):
            graph.add_node(f"node{i}", "Rule", f"規則 {i}",
                           meta={"confidence": 0.9})
        graph._conn.commit()

        before = graph._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]

        # 對所有節點執行衰減
        for i in range(5):
            engine._apply_decay(f"node{i}", old_conf=0.9, new_conf=0.1,
                                deprecated=True)

        after = graph._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(before, after,
                         "批次衰減後節點總數必須不變（歷史記錄有考古價值，刪除不可逆）")


if __name__ == "__main__":
    unittest.main()
