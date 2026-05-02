"""
tests/unit/test_write_queue.py — E-02 Write Queue 序列化測試

覆蓋：
  - serialized_writes=False 不改變行為
  - serialized_writes=True 基本寫入
  - 100 threads × 10 writes = 1000 rows, 0 丟失（核心驗收）
  - 寫入錯誤傳播回 caller
  - close() 正確停止 worker
  - 讀取不被寫入阻塞
"""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from project_brain.core.brain_db import BrainDB


class TestSerializedWritesFalse(unittest.TestCase):
    """serialized_writes=False 走原路徑，行為不變。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = BrainDB(Path(self._tmp.name), serialized_writes=False)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_default_mode_has_no_queue(self):
        self.assertIsNone(self.db._write_queue)
        self.assertIsNone(self.db._write_worker_thread)

    def test_default_add_node_works(self):
        nid = self.db.add_node("n1", "Rule", "Test rule", content="details")
        self.assertEqual(nid, "n1")
        node = self.db.get_node("n1")
        self.assertIsNotNone(node)
        self.assertEqual(node["title"], "Test rule")


class TestSerializedWritesBasic(unittest.TestCase):
    """serialized_writes=True 基本寫入。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = BrainDB(Path(self._tmp.name), serialized_writes=True)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_queue_and_worker_created(self):
        self.assertIsNotNone(self.db._write_queue)
        self.assertIsNotNone(self.db._write_worker_thread)
        self.assertTrue(self.db._write_worker_thread.is_alive())

    def test_single_write_commits(self):
        nid = self.db.add_node("n1", "Rule", "Test rule")
        self.assertEqual(nid, "n1")
        node = self.db.get_node("n1")
        self.assertIsNotNone(node)

    def test_execute_write_via_queue(self):
        """_execute_write routes through queue in serialized mode."""
        self.db._execute_write(
            "INSERT INTO brain_meta(key,value) VALUES(?,?)",
            ("test_key", "test_val"),
        )
        row = self.db.conn.execute(
            "SELECT value FROM brain_meta WHERE key='test_key'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "test_val")

    def test_update_node_via_queue(self):
        self.db.add_node("n1", "Rule", "Original")
        result = self.db.update_node("n1", title="Updated")
        self.assertTrue(result)
        node = self.db.get_node("n1")
        self.assertEqual(node["title"], "Updated")

    def test_delete_node_via_queue(self):
        self.db.add_node("n1", "Rule", "To delete")
        result = self.db.delete_node("n1")
        self.assertTrue(result)
        self.assertIsNone(self.db.get_node("n1"))


class TestConcurrentWritesZeroLoss(unittest.TestCase):
    """核心驗收：100 threads × 10 writes = 1000 rows, 0 丟失。"""

    def test_100_threads_10_writes_each(self):
        with tempfile.TemporaryDirectory() as td:
            db = BrainDB(Path(td), serialized_writes=True)
            errors = []
            barrier = threading.Barrier(100)

            def writer(thread_id):
                try:
                    barrier.wait(timeout=10)
                    for i in range(10):
                        nid = f"t{thread_id}_n{i}"
                        db.add_node(nid, "Rule", f"Node {nid}")
                except Exception as e:
                    errors.append((thread_id, e))

            threads = [threading.Thread(target=writer, args=(t,)) for t in range(100)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            # Verify zero loss
            count = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            db.close()

            self.assertEqual(len(errors), 0,
                             f"Errors occurred: {errors[:5]}")
            self.assertEqual(count, 1000,
                             f"Expected 1000 rows, got {count}")

    def test_50_threads_20_writes_each(self):
        """Additional stress test: 50 × 20 = 1000."""
        with tempfile.TemporaryDirectory() as td:
            db = BrainDB(Path(td), serialized_writes=True)
            errors = []

            def writer(thread_id):
                try:
                    for i in range(20):
                        nid = f"t{thread_id}_n{i}"
                        db.add_node(nid, "Pitfall", f"Pitfall {nid}",
                                    content=f"Content for {nid}")
                except Exception as e:
                    errors.append((thread_id, e))

            threads = [threading.Thread(target=writer, args=(t,)) for t in range(50)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            count = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            db.close()
            self.assertEqual(len(errors), 0)
            self.assertEqual(count, 1000)


class TestWriteQueueErrorPropagation(unittest.TestCase):
    """寫入錯誤傳播回 caller。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = BrainDB(Path(self._tmp.name), serialized_writes=True)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_bad_sql_raises_on_caller_thread(self):
        with self.assertRaises(Exception):
            self.db._execute_write("INSERT INTO nonexistent_table VALUES(?)", ("x",))

    def test_worker_continues_after_error(self):
        """Error in one write doesn't kill the worker."""
        try:
            self.db._execute_write("INVALID SQL", ())
        except Exception:
            pass
        # Worker should still be alive and functional
        self.db.add_node("n1", "Rule", "After error")
        self.assertIsNotNone(self.db.get_node("n1"))


class TestWriteQueueShutdown(unittest.TestCase):
    """close() 正確停止 worker。"""

    def test_close_stops_worker(self):
        with tempfile.TemporaryDirectory() as td:
            db = BrainDB(Path(td), serialized_writes=True)
            thread = db._write_worker_thread
            self.assertTrue(thread.is_alive())
            db.close()
            self.assertFalse(thread.is_alive())

    def test_double_close_safe(self):
        with tempfile.TemporaryDirectory() as td:
            db = BrainDB(Path(td), serialized_writes=True)
            db.close()
            db.close()  # should not raise


class TestReadsNotBlocked(unittest.TestCase):
    """讀取不被寫入阻塞（WAL concurrent readers）。"""

    def test_read_during_writes(self):
        with tempfile.TemporaryDirectory() as td:
            db = BrainDB(Path(td), serialized_writes=True)
            # Pre-populate
            db.add_node("existing", "Rule", "Existing node")

            read_results = []
            write_done = threading.Event()

            def heavy_writer():
                for i in range(50):
                    db.add_node(f"hw_{i}", "Note", f"Heavy write {i}")
                write_done.set()

            def reader():
                for _ in range(10):
                    node = db.get_node("existing")
                    read_results.append(node is not None)
                    time.sleep(0.01)

            wt = threading.Thread(target=heavy_writer)
            rt = threading.Thread(target=reader)
            wt.start()
            rt.start()
            rt.join(timeout=10)
            wt.join(timeout=10)
            db.close()

            self.assertTrue(all(read_results),
                            "All reads should succeed during writes")


if __name__ == "__main__":
    unittest.main()
