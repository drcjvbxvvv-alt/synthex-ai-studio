"""
tests/unit/test_kg_braindb_sync.py

B-02 — KnowledgeGraph → BrainDB 事件驅動同步驗收測試
(docs/ROADMAP.md §4 B-02, docs/ARCHITECTURE_REVIEW.md §3 MEDIUM-02)

背景：
  KnowledgeGraph (knowledge_graph.db) 和 BrainDB (brain.db) 是兩個獨立 SQLite
  檔案，過去只有 review_board.approve() 手動雙寫保持同步。本模組實作 Observer
  pattern：graph.add_node() / update_node() 在 commit 後呼叫 _emit()，
  ProjectBrain 透過 _on_graph_node_upserted() 回呼 brain_db.sync_from_graph_node()。

測試群組：
  TestObserverAPI          — add/remove listener, _emit 基本行為
  TestAddNodeSync          — add_node 觸發 BrainDB 同步
  TestUpdateNodeSync       — update_node 觸發 BrainDB 同步
  TestListenerResilience   — listener 失敗不影響 graph 寫入
  TestEngineIntegration    — ProjectBrain._on_graph_node_upserted 接線
  TestIdempotency          — 重複觸發不重複資料
  TestConcurrency          — 50 threads 並發 add_node，BrainDB 最終一致
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from project_brain.graph import KnowledgeGraph
from project_brain.core.brain_db import BrainDB


# ══════════════════════════════════════════════════════════════════
#  測試輔助 Fixtures
# ══════════════════════════════════════════════════════════════════

class _KGFixture(unittest.TestCase):
    """每個測試獨立 tmp 目錄 + KnowledgeGraph（無 BrainDB）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.graph = KnowledgeGraph(self.tmp_path)

    def tearDown(self):
        try:
            self.graph.close()
        except Exception:
            pass
        self._tmp.cleanup()


class _PairFixture(unittest.TestCase):
    """每個測試獨立 tmp 目錄 + BrainDB + KnowledgeGraph（shared conn）.

    C-01: unified brain.db — KnowledgeGraph shares BrainDB connection.
    No Observer sync needed; writes go directly to the single DB.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.bdb = BrainDB(self.tmp_path)
        # C-01: KG shares BrainDB connection — single unified brain.db
        self.graph = KnowledgeGraph(self.tmp_path, conn=self.bdb.conn)

    def tearDown(self):
        try:
            self.graph.close()
        except Exception:
            pass
        try:
            self.bdb.close()
        except Exception:
            pass
        self._tmp.cleanup()

    def _bdb_node(self, node_id: str):
        return self.bdb.get_node(node_id)

    def _bdb_search(self, query: str, limit: int = 10):
        return self.bdb.search_nodes(query, limit=limit)


# ══════════════════════════════════════════════════════════════════
#  TestObserverAPI — add/remove listener + _emit 基本行為
# ══════════════════════════════════════════════════════════════════

class TestObserverAPI(_KGFixture):

    def test_OBS01_add_listener_registers_callable(self):
        """add_listener 後 listener 在 _listeners list 中。"""
        fn = MagicMock()
        self.graph.add_listener(fn)
        self.assertIn(fn, self.graph._listeners)

    def test_OBS02_add_listener_idempotent(self):
        """同一 callable 加兩次，list 中只有一份。"""
        fn = MagicMock()
        self.graph.add_listener(fn)
        self.graph.add_listener(fn)
        self.assertEqual(self.graph._listeners.count(fn), 1)

    def test_OBS03_remove_listener_unregisters(self):
        """remove_listener 後 callable 不再在 list 中。"""
        fn = MagicMock()
        self.graph.add_listener(fn)
        self.graph.remove_listener(fn)
        self.assertNotIn(fn, self.graph._listeners)

    def test_OBS04_remove_listener_noop_if_not_registered(self):
        """remove_listener 對未登記的 callable 不拋出例外。"""
        fn = MagicMock()
        try:
            self.graph.remove_listener(fn)  # should not raise
        except Exception as e:
            self.fail(f"remove_listener raised unexpectedly: {e}")

    def test_OBS05_emit_calls_all_listeners(self):
        """_emit 呼叫所有已登記的 listener。"""
        fn1, fn2 = MagicMock(), MagicMock()
        self.graph.add_listener(fn1)
        self.graph.add_listener(fn2)
        self.graph._emit("node_upserted", {"node_id": "x"})
        fn1.assert_called_once_with("node_upserted", {"node_id": "x"})
        fn2.assert_called_once_with("node_upserted", {"node_id": "x"})

    def test_OBS06_emit_continues_after_listener_failure(self):
        """一個 listener 拋出例外，第二個 listener 仍被呼叫。"""
        failing = MagicMock(side_effect=RuntimeError("boom"))
        ok_fn   = MagicMock()
        self.graph.add_listener(failing)
        self.graph.add_listener(ok_fn)
        self.graph._emit("node_upserted", {"node_id": "x"})
        ok_fn.assert_called_once()


# ══════════════════════════════════════════════════════════════════
#  TestAddNodeSync — add_node 觸發 BrainDB 同步
# ══════════════════════════════════════════════════════════════════

class TestAddNodeSync(_PairFixture):

    def test_ADD01_new_node_searchable_in_braindb(self):
        """C-01: graph.add_node() writes to unified brain.db, visible via BrainDB."""
        self.graph.add_node("n1", "Rule", "Avoid circular imports")
        # C-01: shared connection — node is directly visible via BrainDB
        node = self._bdb_node("n1")
        self.assertIsNotNone(node, "node should be directly visible in BrainDB via shared conn")
        self.assertEqual(node["title"], "Avoid circular imports")

    def test_ADD02_synced_node_has_correct_type(self):
        """同步後 BrainDB 節點的 type 與 graph 一致。"""
        self.graph.add_node("n2", "Pitfall", "Watch for race conditions", content="detail")
        node = self._bdb_node("n2")
        self.assertIsNotNone(node)
        self.assertEqual(node["type"], "Pitfall")

    def test_ADD03_synced_node_has_correct_content(self):
        """同步後 BrainDB 節點的 content 與 graph 一致。"""
        self.graph.add_node("n3", "Decision", "Use SQLite", content="lightweight and embedded")
        node = self._bdb_node("n3")
        self.assertIsNotNone(node)
        self.assertIn("lightweight", node.get("content", ""))

    def test_ADD04_synced_node_has_correct_confidence(self):
        """同步後 BrainDB 節點的 confidence 與 graph 傳入值一致。"""
        self.graph.add_node("n4", "Rule", "Always test", meta={"confidence": 0.92})
        node = self._bdb_node("n4")
        self.assertIsNotNone(node)
        self.assertAlmostEqual(float(node["confidence"]), 0.92, places=2)

    def test_ADD05_upsert_node_updates_braindb(self):
        """graph.add_node() 同 id 覆寫（upsert）時，BrainDB 內容也更新。"""
        self.graph.add_node("n5", "Note", "Old title", content="old")
        self.graph.add_node("n5", "Note", "New title", content="new")
        node = self._bdb_node("n5")
        self.assertIsNotNone(node)
        self.assertEqual(node["title"], "New title")

    def test_ADD06_listener_not_called_before_commit(self):
        """listener 只在 commit 之後被呼叫（emit 在 with lock 外）。"""
        call_count = {"n": 0}

        def counting_listener(event, data):
            # 在 listener 被呼叫時，node 應已存在於 graph DB
            node = self.graph.get_node(data["node_id"])
            if node is not None:
                call_count["n"] += 1

        self.graph.add_listener(counting_listener)
        self.graph.add_node("n6", "Rule", "Title after commit")
        self.assertEqual(call_count["n"], 1,
                         "listener should see committed node in graph DB")


# ══════════════════════════════════════════════════════════════════
#  TestUpdateNodeSync — update_node 觸發 BrainDB 同步
# ══════════════════════════════════════════════════════════════════

class TestUpdateNodeSync(_PairFixture):

    def setUp(self):
        super().setUp()
        # 建立一個初始節點（同步到兩個 DB）
        self.graph.add_node("u1", "Rule", "Original title", content="original content",
                            meta={"confidence": 0.7})

    def test_UPD01_title_update_synced_to_braindb(self):
        """graph.update_node(title=...) 後，BrainDB 節點 title 更新。"""
        self.graph.update_node("u1", title="Updated title")
        node = self._bdb_node("u1")
        self.assertIsNotNone(node)
        self.assertEqual(node["title"], "Updated title")

    def test_UPD02_content_update_synced_to_braindb(self):
        """graph.update_node(content=...) 後，BrainDB 節點 content 更新。"""
        self.graph.update_node("u1", content="new content body")
        node = self._bdb_node("u1")
        self.assertIsNotNone(node)
        self.assertIn("new content body", node.get("content", ""))

    def test_UPD03_confidence_update_synced_to_braindb(self):
        """graph.update_node(confidence=...) 後，BrainDB 節點 confidence 更新。"""
        self.graph.update_node("u1", confidence=0.95)
        node = self._bdb_node("u1")
        self.assertIsNotNone(node)
        self.assertAlmostEqual(float(node["confidence"]), 0.95, places=2)

    def test_UPD04_update_nonexistent_node_does_not_emit(self):
        """update_node 對不存在的 node_id 回傳 False，不觸發 listener。"""
        called = []
        self.graph.add_listener(lambda e, d: called.append(d))
        result = self.graph.update_node("nonexistent_xyz", title="X")
        self.assertFalse(result)
        self.assertEqual(len(called), 0)

    def test_UPD05_no_change_update_does_not_emit(self):
        """update_node 傳入全 None（無更新）不觸發 listener。"""
        called = []
        self.graph.add_listener(lambda e, d: called.append(d))
        result = self.graph.update_node("u1")  # no kwargs
        self.assertTrue(result)
        self.assertEqual(len(called), 0)


# ══════════════════════════════════════════════════════════════════
#  TestListenerResilience — listener 失敗不影響 graph 寫入
# ══════════════════════════════════════════════════════════════════

class TestListenerResilience(_KGFixture):

    def test_RES01_failing_listener_does_not_rollback_graph(self):
        """listener 拋出例外時，KG 節點已 commit，不被回滾。"""
        self.graph.add_listener(lambda e, d: 1 / 0)  # ZeroDivisionError
        # Should not raise
        self.graph.add_node("r1", "Rule", "Resilience test")
        node = self.graph.get_node("r1")
        self.assertIsNotNone(node, "graph node must be committed despite listener failure")

    def test_RES02_failing_listener_logs_warning(self):
        """listener 失敗時記錄 WARNING log（不 raise）。"""
        import logging
        self.graph.add_listener(lambda e, d: (_ for _ in ()).throw(ValueError("test error")))
        with self.assertLogs("project_brain.graph", level=logging.WARNING):
            self.graph.add_node("r2", "Note", "Log test")

    def test_RES03_second_listener_called_after_first_fails(self):
        """第一個 listener 失敗，第二個 listener 仍被呼叫。"""
        second_called = []
        self.graph.add_listener(lambda e, d: 1 / 0)
        self.graph.add_listener(lambda e, d: second_called.append(d["node_id"]))
        self.graph.add_node("r3", "Rule", "Chain test")
        self.assertIn("r3", second_called)


# ══════════════════════════════════════════════════════════════════
#  TestEngineIntegration — ProjectBrain 接線驗收
# ══════════════════════════════════════════════════════════════════

class TestEngineIntegration(unittest.TestCase):
    """透過 ProjectBrain 驗證 graph → db 的完整接線。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_engine(self):
        from project_brain.engine import ProjectBrain
        return ProjectBrain(str(self.tmp_path))

    def test_ENG01_engine_graph_shares_db_connection(self):
        """C-01: engine.graph shares BrainDB connection (no Observer needed)."""
        engine = self._make_engine()
        _ = engine.graph  # trigger lazy init
        # C-01: graph and db share the same SQLite connection
        self.assertIs(engine.graph._conn, engine.db.conn,
                      "graph and db should share the same connection in C-01")

    def test_ENG02_add_node_via_engine_syncs_to_db(self):
        """engine.graph.add_node() 後，engine.db.search_nodes() 能找到節點。"""
        engine = self._make_engine()
        engine.graph.add_node("e1", "Rule", "Engine sync test", content="auto sync")
        results = engine.db.search_nodes("Engine sync test", limit=5)
        ids = [r["id"] for r in results]
        self.assertIn("e1", ids)

    def test_ENG03_update_node_via_engine_syncs_to_db(self):
        """engine.graph.update_node() 後，engine.db 中的內容更新。"""
        engine = self._make_engine()
        engine.graph.add_node("e2", "Rule", "Before update")
        engine.graph.update_node("e2", title="After update")
        node = engine.db.get_node("e2")
        self.assertIsNotNone(node)
        self.assertEqual(node["title"], "After update")

    def test_ENG04_sync_failure_does_not_raise(self):
        """engine.db 寫入失敗時，_on_graph_node_upserted 不向上拋出例外。"""
        engine = self._make_engine()
        # 確保 db 先初始化
        _ = engine.db
        # 用 mock 讓 sync_from_graph_node 拋出例外
        with patch.object(engine.db, "sync_from_graph_node", side_effect=OSError("disk full")):
            # 不應拋出
            try:
                engine.graph.add_node("e3", "Note", "Sync failure test")
            except Exception as exc:
                self.fail(f"graph.add_node raised unexpectedly: {exc}")
        # graph 節點應已儲存
        self.assertIsNotNone(engine.graph.get_node("e3"))

    def test_ENG05_two_engines_have_independent_listeners(self):
        """兩個 ProjectBrain 實例的 graph._listeners 互不干擾。"""
        import tempfile
        tmp2 = tempfile.TemporaryDirectory()
        try:
            engine1 = self._make_engine()
            from project_brain.engine import ProjectBrain
            engine2 = ProjectBrain(tmp2.name)
            _ = engine1.graph
            _ = engine2.graph
            # 兩個 graph 實例各自有獨立的 listener list
            self.assertIsNot(engine1.graph._listeners, engine2.graph._listeners)
        finally:
            tmp2.cleanup()


# ══════════════════════════════════════════════════════════════════
#  TestIdempotency — 重複觸發不重複資料
# ══════════════════════════════════════════════════════════════════

class TestIdempotency(_PairFixture):

    def test_IDM01_double_add_same_node_only_one_row_in_braindb(self):
        """同一 node_id add_node 兩次，BrainDB 只有一筆（upsert 冪等）。"""
        self.graph.add_node("d1", "Rule", "First")
        self.graph.add_node("d1", "Rule", "Second")  # upsert
        rows = self.bdb.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE id=?", ("d1",)
        ).fetchone()[0]
        self.assertEqual(rows, 1)

    def test_IDM02_graph_add_twice_no_duplicate(self):
        """C-01: graph.add_node() called twice with same id → only one row in DB."""
        self.graph.add_node("d2", "Note", "Idem", content="")
        self.graph.add_node("d2", "Note", "Idem", content="")
        rows = self.bdb.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE id=?", ("d2",)
        ).fetchone()[0]
        self.assertEqual(rows, 1)

    def test_IDM03_unknown_event_type_is_ignored(self):
        """sync_from_graph_node 對未知 event 靜默忽略，不寫入 BrainDB。"""
        self.bdb.sync_from_graph_node("node_deleted", {"node_id": "d3"})
        node = self._bdb_node("d3")
        self.assertIsNone(node, "unknown event should not create a node")


# ══════════════════════════════════════════════════════════════════
#  TestConcurrency — 50 threads 並發 add_node，BrainDB 最終一致
# ══════════════════════════════════════════════════════════════════

class TestConcurrency(_PairFixture):

    def test_CON01_50_concurrent_adds_all_synced_to_braindb(self):
        """50 threads 同時 add_node，BrainDB 最終節點數與 graph 一致。"""
        n_threads = 50
        errors = []

        def _worker(i):
            try:
                self.graph.add_node(
                    f"con_{i:03d}", "Note", f"Concurrent note {i}",
                    content=f"content {i}",
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"threads raised errors: {errors}")

        # 驗證 BrainDB 節點數與 graph 一致
        graph_count = self.graph._conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE id LIKE 'con_%'"
        ).fetchone()[0]
        bdb_count = self.bdb.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE id LIKE 'con_%'"
        ).fetchone()[0]
        self.assertEqual(bdb_count, graph_count,
                         f"BrainDB has {bdb_count} nodes, graph has {graph_count}")
        self.assertEqual(graph_count, n_threads)


if __name__ == "__main__":
    unittest.main()
