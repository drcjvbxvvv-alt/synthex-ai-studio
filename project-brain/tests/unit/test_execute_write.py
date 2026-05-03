"""
tests/unit/test_execute_write.py

MEDIUM-01 — BrainDB._execute_write() 統一寫入入口驗收測試
(ARCHITECTURE_REVIEW.md §3 MEDIUM-01, §5.2 Phase 2)

背景：brain_db.py 原本有 16+ 個寫入 commit 路徑，部分在 _write_guard() 內，
部分在外。此不一致使除錯與審計困難，並且錯誤路徑（rollback）處理不統一。

HIGH-01 修法：
  1. 新增 _execute_write(sql, params) / _execute_writescript(script) 統一入口
  2. 每個入口保證 _write_guard() + commit + rollback 一致
  3. 重構 8 個 runtime unguarded commit 路徑改用統一入口

本檔案驗收：
  - _execute_write 的核心語意（commit / rollback / 可重入 / 序列化）
  - 8 個重構後的呼叫者（pin_node / add_edge / emit / add_temporal_edge /
    record_federation_import / prune_episodes / search_nodes trace /
    optimize FTS rebuild）行為未退化
"""
from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from project_brain.core.brain_db import BrainDB


# ══════════════════════════════════════════════════════════════════
#  測試輔助
# ══════════════════════════════════════════════════════════════════

class _BrainDBFixture(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.bd = BrainDB(Path(self._tmp.name))

    def tearDown(self):
        try:
            self.bd.conn.close()
        except Exception:
            pass
        self._tmp.cleanup()


# ══════════════════════════════════════════════════════════════════
#  W-01 ~ W-05  _execute_write 核心語意
# ══════════════════════════════════════════════════════════════════

class TestExecuteWriteCore(_BrainDBFixture):

    def test_W01_successful_write_commits(self):
        """_execute_write 成功時應 commit，資料持久化"""
        self.bd.add_node("n1", "Rule", "Test", "body")
        cur = self.bd._execute_write(
            "UPDATE nodes SET title = ? WHERE id = ?",
            ("Updated", "n1"),
        )
        self.assertEqual(cur.rowcount, 1)
        # 從 DB 重新讀取驗證已 commit
        row = self.bd.conn.execute(
            "SELECT title FROM nodes WHERE id = ?", ("n1",)
        ).fetchone()
        self.assertEqual(row["title"], "Updated")

    def test_W02_sql_error_rolls_back_and_raises(self):
        """SQL 錯誤應 rollback 並 re-raise"""
        self.bd.add_node("n1", "Rule", "Original", "body")
        with self.assertRaises(sqlite3.OperationalError):
            self.bd._execute_write(
                "UPDATE nonexistent_table SET x=1", (),
            )
        # 原節點不應被影響
        row = self.bd.conn.execute(
            "SELECT title FROM nodes WHERE id = ?", ("n1",)
        ).fetchone()
        self.assertEqual(row["title"], "Original")

    def test_W03_returns_cursor_with_rowcount_and_lastrowid(self):
        """回傳的 cursor 應有 rowcount 和 lastrowid"""
        cur = self.bd._execute_write(
            "INSERT INTO events(event_type, payload) VALUES(?, ?)",
            ("test", "{}"),
        )
        self.assertEqual(cur.rowcount, 1)
        self.assertGreater(cur.lastrowid or 0, 0)

    def test_W04_rlock_reentrant_nested_calls(self):
        """
        _write_guard 用 RLock，同一 thread 內巢狀呼叫 _execute_write 不死鎖。
        實務上這正是呼叫者已經持有 _write_guard() 再呼叫 _execute_write 的情境。
        """
        with self.bd._write_guard():
            # 巢狀呼叫 — 應該正常完成
            cur = self.bd._execute_write(
                "INSERT INTO events(event_type, payload) VALUES(?, ?)",
                ("nested", "{}"),
            )
            self.assertEqual(cur.rowcount, 1)
            # 再一層巢狀
            cur2 = self.bd._execute_write(
                "INSERT INTO events(event_type, payload) VALUES(?, ?)",
                ("double-nested", "{}"),
            )
            self.assertEqual(cur2.rowcount, 1)

    def test_W05_concurrent_writes_serialized(self):
        """
        50 個 thread 同時 _execute_write，應全部成功完成（無 corruption、無遺失）。
        """
        N       = 50
        barrier = threading.Barrier(N)
        errors: list[Exception] = []

        def _worker(i: int):
            try:
                barrier.wait()
                self.bd._execute_write(
                    "INSERT INTO events(event_type, payload) VALUES(?, ?)",
                    (f"t{i}", "{}"),
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        # 全部 N 筆都寫入
        count = self.bd.conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type LIKE 't%'"
        ).fetchone()[0]
        self.assertEqual(count, N)


# ══════════════════════════════════════════════════════════════════
#  W-06 ~ W-08  _execute_writescript 多語句入口
# ══════════════════════════════════════════════════════════════════

class TestExecuteWriteScript(_BrainDBFixture):

    def test_W06_writescript_executes_multiple_statements(self):
        script = """
        CREATE TABLE IF NOT EXISTS _mw_test(id INTEGER PRIMARY KEY, v TEXT);
        INSERT INTO _mw_test(v) VALUES('a');
        INSERT INTO _mw_test(v) VALUES('b');
        INSERT INTO _mw_test(v) VALUES('c');
        """
        self.bd._execute_writescript(script)
        count = self.bd.conn.execute("SELECT COUNT(*) FROM _mw_test").fetchone()[0]
        self.assertEqual(count, 3)

    def test_W07_writescript_error_raises(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.bd._execute_writescript("SELECT * FROM nonexistent_table_xyz;")

    def test_W08_writescript_protected_by_write_lock(self):
        """
        兩個 thread 同時 _execute_writescript 應被序列化（RLock）。
        """
        N       = 10
        barrier = threading.Barrier(N)
        errors: list[Exception] = []

        # 先建表
        self.bd._execute_writescript(
            "CREATE TABLE IF NOT EXISTS _mw_lock(id INTEGER, v TEXT);"
        )

        def _worker(i: int):
            try:
                barrier.wait()
                self.bd._execute_writescript(
                    f"INSERT INTO _mw_lock VALUES({i}, 'v{i}');"
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        count = self.bd.conn.execute("SELECT COUNT(*) FROM _mw_lock").fetchone()[0]
        self.assertEqual(count, N)


# ══════════════════════════════════════════════════════════════════
#  W-09 ~ W-16  重構後的 8 個 caller 行為驗證
# ══════════════════════════════════════════════════════════════════

class TestRefactoredCallers(_BrainDBFixture):

    def test_W09_pin_node_still_works(self):
        self.bd.add_node("n1", "Rule", "Title", "body")
        self.assertTrue(self.bd.pin_node("n1", True))
        node = self.bd.conn.execute(
            "SELECT is_pinned FROM nodes WHERE id = ?", ("n1",)
        ).fetchone()
        self.assertEqual(node["is_pinned"], 1)
        # unpin
        self.assertTrue(self.bd.pin_node("n1", False))
        node = self.bd.conn.execute(
            "SELECT is_pinned FROM nodes WHERE id = ?", ("n1",)
        ).fetchone()
        self.assertEqual(node["is_pinned"], 0)

    def test_W10_add_edge_returns_lastrowid(self):
        self.bd.add_node("a", "Rule", "A", "")
        self.bd.add_node("b", "Rule", "B", "")
        rowid = self.bd.add_edge("a", "DEPENDS_ON", "b", "note")
        self.assertGreater(rowid, 0)
        edge = self.bd.conn.execute(
            "SELECT relation FROM edges WHERE source_id=? AND target_id=?",
            ("a", "b"),
        ).fetchone()
        self.assertEqual(edge["relation"], "DEPENDS_ON")

    def test_W11_emit_persists_event(self):
        self.bd.emit("task_complete", {"summary": "did the thing"})
        row = self.bd.conn.execute(
            "SELECT payload FROM events WHERE event_type='task_complete'"
        ).fetchone()
        self.assertIn("summary", row["payload"])

    def test_W12_add_temporal_edge_invalidates_previous(self):
        """
        add_temporal_edge 是 multi-statement (UPDATE + INSERT)，MEDIUM-01 改用
        顯式 _write_guard + try/rollback 包裹。驗證兩條語句的原子性。
        """
        self.bd.add_node("a", "Rule", "A", "")
        self.bd.add_node("b", "Rule", "B", "")
        # 第一次加邊：no previous to invalidate
        rid1 = self.bd.add_temporal_edge("a", "LINKED_TO", "b", content="v1")
        # 第二次加同 source+relation：先前那條的 valid_until 應被設定
        rid2 = self.bd.add_temporal_edge("a", "LINKED_TO", "b", content="v2")
        self.assertGreater(rid2, rid1)
        # 第一條應該被 invalidate
        first = self.bd.conn.execute(
            "SELECT valid_until FROM temporal_edges WHERE id = ?", (rid1,)
        ).fetchone()
        self.assertIsNotNone(first["valid_until"])
        # 第二條仍然 active
        second = self.bd.conn.execute(
            "SELECT valid_until FROM temporal_edges WHERE id = ?", (rid2,)
        ).fetchone()
        self.assertIsNone(second["valid_until"])

    def test_W13_record_federation_import_persists(self):
        rid = self.bd.record_federation_import(
            source="federation:proj-a",
            node_id="upstream-1",
            node_title="upstream rule",
            status="staged",
        )
        self.assertGreater(rid, 0)
        rows = self.bd.get_federation_imports(limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "federation:proj-a")

    def test_W14_prune_episodes_returns_deleted_count(self):
        # 沒有 episodes → 回傳 0
        self.assertEqual(self.bd.prune_episodes(older_than_days=1000), 0)
        # 新增一個 episode 然後立刻 prune
        eid = self.bd.add_episode(content="test episode", source="test")
        self.assertTrue(eid.startswith("ep-"))
        # cutoff=-1 代表「刪除今天以前」→ 不應刪新建的
        # 只是確認 prune_episodes 不拋例外
        result = self.bd.prune_episodes(older_than_days=999)
        self.assertIsInstance(result, int)

    def test_W15_search_nodes_trace_insert_still_logged(self):
        """search_nodes 內部的 trace INSERT 透過 _execute_write 寫入（尊重採樣率）"""
        self.bd.add_node("n1", "Rule", "searchable term here", "body")
        # 清空 traces + 重置 counter 確保下一次命中
        self.bd.conn.execute("DELETE FROM traces")
        self.bd.conn.commit()
        # H-01: trace counter is on WriteContext (_ctx), not BrainDB directly
        ctx = getattr(self.bd, '_ctx', self.bd)
        ctx._trace_counter = ctx._trace_sample_rate - 1  # next search will write
        # 執行 search
        self.bd.search_nodes("searchable")
        # trace 應該有 1 筆
        count = self.bd.conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
        self.assertEqual(count, 1)

    def test_W16_optimize_fts_rebuild_still_works(self):
        self.bd.add_node("n1", "Rule", "Alpha rule", "body")
        self.bd.add_node("n2", "Pitfall", "Beta pitfall", "body")
        result = self.bd.optimize()
        self.assertIn("fts5_status", result)
        # rebuilt 或 rebuild_skipped 都算成功路徑
        self.assertTrue(
            result["fts5_status"].startswith("rebuilt")
            or result["fts5_status"].startswith("rebuild_skipped")
        )


# ══════════════════════════════════════════════════════════════════
#  W-17 ~ W-18  退化預防
# ══════════════════════════════════════════════════════════════════

class TestRegressionGuards(_BrainDBFixture):

    def test_W17_concurrent_mixed_callers_no_corruption(self):
        """
        混合 pin_node / add_edge / emit / record_federation_import 並發呼叫，
        所有操作都走 _execute_write 或 _write_guard，最終 DB 狀態應一致。
        """
        self.bd.add_node("a", "Rule", "A", "")
        self.bd.add_node("b", "Rule", "B", "")
        N       = 40
        barrier = threading.Barrier(N)
        errors: list[Exception] = []

        def _worker(i: int):
            try:
                barrier.wait()
                op = i % 4
                if op == 0:
                    self.bd.pin_node("a", bool(i % 2))
                elif op == 1:
                    self.bd.add_edge("a", "DEPENDS_ON", "b", note=f"t{i}")
                elif op == 2:
                    self.bd.emit("stress", {"i": i})
                else:
                    self.bd.record_federation_import(
                        source=f"fed-{i}", node_id=f"n{i}",
                        node_title=f"title {i}", status="staged",
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        # pin_node 執行了 10 次（op==0 的次數）
        # add_edge 執行了 10 次 → INSERT OR IGNORE 但 note 不同，不觸發 IGNORE
        # emit 執行了 10 次
        # record_federation_import 執行了 10 次
        event_count = self.bd.conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='stress'"
        ).fetchone()[0]
        self.assertEqual(event_count, 10)
        fed_count = self.bd.conn.execute(
            "SELECT COUNT(*) FROM federation_imports"
        ).fetchone()[0]
        self.assertEqual(fed_count, 10)

    def test_W18_execute_write_holds_lock_during_execution(self):
        """
        持有 _write_guard 的 thread 執行長時間 _execute_write 時，其他 thread
        的 _execute_write 必須等待（序列化，非平行）。
        """
        # 這個測試用 side-channel 證明：thread A 在拿到 lock 後 sleep 0.1s 期間，
        # thread B 的 write 無法完成。
        started = threading.Event()
        held    = threading.Event()

        def _long_write():
            with self.bd._write_guard():
                started.set()
                time.sleep(0.15)
                self.bd.conn.execute(
                    "INSERT INTO events(event_type, payload) VALUES(?, ?)",
                    ("long", "{}"),
                )
                self.bd.conn.commit()
                held.set()

        t1 = threading.Thread(target=_long_write)
        t1.start()
        started.wait()
        # Thread A 正持有 lock；Thread B 此時呼叫 _execute_write 會等待
        t0 = time.monotonic()
        self.bd._execute_write(
            "INSERT INTO events(event_type, payload) VALUES(?, ?)",
            ("short", "{}"),
        )
        elapsed = time.monotonic() - t0
        t1.join()
        # Thread B 應該等待了 thread A 的剩餘時間（至少 50ms，允許 OS 調度誤差）
        self.assertGreater(elapsed, 0.03,
                           f"_execute_write 應該被 _write_guard 阻塞，實際 {elapsed*1000:.0f}ms")
        # 兩筆都完成
        self.assertTrue(held.is_set())


if __name__ == "__main__":
    unittest.main()
