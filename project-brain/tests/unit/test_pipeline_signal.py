"""
tests/unit/test_pipeline_signal.py

Auto Knowledge Pipeline Phase 1 — Signal + SignalQueue 單元測試

驗收標準（設計文件 docs/AUTO_KNOWLEDGE_PIPELINE.md §5）：
  T-01  基本入隊 / 出隊
  T-02  去重：同 (kind, workdir, summary) 的 pending 只保留一個
  T-03  背壓：佇列達上限時，低優先（priority >= 8）被丟棄；高優先仍可入隊
  T-04  mark_done  → status='done'
  T-05  mark_failed 重試：未達上限回到 pending；達 MAX_ATTEMPTS → 'failed'
  T-06  mark_skipped
  T-07  cleanup_stale — 超期 pending → skipped
  T-08  stats() 回傳正確計數
  T-09  dequeue_batch CAS — 同批次只取一次，不重複
  T-10  Signal.to_row / from_row 往返序列化
  T-11  brain_db migration v23~v26 — 表與索引均已建立
"""
from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from project_brain.pipeline import Signal, SignalKind, SignalQueue


# ── 測試輔助 ───────────────────────────────────────────────────────────────

def _make_conn() -> sqlite3.Connection:
    """建立含 signal_queue + pipeline_metrics 的 in-memory DB。"""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE signal_queue (
            id           TEXT PRIMARY KEY,
            kind         TEXT NOT NULL,
            workdir      TEXT NOT NULL,
            timestamp    TEXT NOT NULL,
            summary      TEXT NOT NULL,
            raw_content  TEXT NOT NULL,
            metadata     TEXT NOT NULL DEFAULT '{}',
            priority     INTEGER NOT NULL DEFAULT 5,
            status       TEXT NOT NULL DEFAULT 'pending',
            attempts     INTEGER NOT NULL DEFAULT 0,
            error        TEXT,
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            processed_at TEXT,
            CHECK (status IN ('pending','processing','done','failed','skipped'))
        );
        CREATE INDEX IF NOT EXISTS idx_signal_queue_status_priority
            ON signal_queue (status, priority, created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_dedup
            ON signal_queue (kind, workdir, summary)
            WHERE status = 'pending';
    """)
    return conn


def _sig(summary: str = "test summary", priority: int = 5,
         kind: SignalKind = SignalKind.GIT_COMMIT) -> Signal:
    return Signal(
        kind=kind,
        workdir="/tmp/test",
        summary=summary,
        raw_content="raw content",
        priority=priority,
    )


# ── T-01  基本入隊 / 出隊 ──────────────────────────────────────────────────

class TestEnqueueDequeue(unittest.TestCase):

    def setUp(self):
        self.q = SignalQueue(_make_conn())

    def test_enqueue_returns_true(self):
        self.assertTrue(self.q.enqueue(_sig()))

    def test_enqueued_signal_is_pending(self):
        s = _sig()
        self.q.enqueue(s)
        self.assertEqual(self.q.pending_count(), 1)

    def test_dequeue_batch_returns_signal(self):
        s = _sig()
        self.q.enqueue(s)
        batch = self.q.dequeue_batch(batch_size=5)
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0].id, s.id)

    def test_dequeue_changes_status_to_processing(self):
        self.q.enqueue(_sig())
        self.q.dequeue_batch()
        # pending should now be 0
        self.assertEqual(self.q.pending_count(), 0)

    def test_dequeue_empty_returns_empty_list(self):
        self.assertEqual(self.q.dequeue_batch(), [])


# ── T-02  去重 ─────────────────────────────────────────────────────────────

class TestDedup(unittest.TestCase):

    def setUp(self):
        self.q = SignalQueue(_make_conn())

    def test_duplicate_summary_dropped(self):
        s1 = _sig("same summary")
        s2 = _sig("same summary")
        self.assertTrue(self.q.enqueue(s1))
        self.assertFalse(self.q.enqueue(s2))
        self.assertEqual(self.q.pending_count(), 1)

    def test_different_summary_both_accepted(self):
        self.q.enqueue(_sig("summary A"))
        self.q.enqueue(_sig("summary B"))
        self.assertEqual(self.q.pending_count(), 2)

    def test_different_kind_same_summary_both_accepted(self):
        self.q.enqueue(_sig("same", kind=SignalKind.GIT_COMMIT))
        self.q.enqueue(_sig("same", kind=SignalKind.TASK_COMPLETE))
        self.assertEqual(self.q.pending_count(), 2)

    def test_done_signal_allows_reenqueue_same_summary(self):
        """完成後可再次入隊相同摘要（去重索引只對 pending 有效）。"""
        s = _sig("same summary")
        self.q.enqueue(s)
        batch = self.q.dequeue_batch()
        self.q.mark_done(batch[0].id)
        # now re-enqueue same summary → should succeed
        s2 = _sig("same summary")
        self.assertTrue(self.q.enqueue(s2))


# ── T-03  背壓 ─────────────────────────────────────────────────────────────

class TestBackpressure(unittest.TestCase):

    def test_low_priority_dropped_when_full(self):
        q = SignalQueue(_make_conn())
        q.MAX_QUEUE_SIZE = 3

        for i in range(3):
            q.enqueue(_sig(f"sig {i}", priority=5))

        # queue is now "full" (3 == MAX_QUEUE_SIZE)
        dropped = _sig("overflow low", priority=8)
        self.assertFalse(q.enqueue(dropped))

    def test_high_priority_accepted_when_full(self):
        q = SignalQueue(_make_conn())
        q.MAX_QUEUE_SIZE = 3

        for i in range(3):
            q.enqueue(_sig(f"sig {i}", priority=5))

        important = _sig("important high", priority=1)
        self.assertTrue(q.enqueue(important))


# ── T-04  mark_done ────────────────────────────────────────────────────────

class TestMarkDone(unittest.TestCase):

    def test_mark_done_sets_status(self):
        q = SignalQueue(_make_conn())
        q.enqueue(_sig())
        batch = q.dequeue_batch()
        q.mark_done(batch[0].id, '{"action":"skip"}')

        stats = q.stats()
        self.assertEqual(stats.get("done", 0), 1)
        self.assertEqual(stats.get("pending", 0), 0)


# ── T-05  mark_failed 重試邏輯 ────────────────────────────────────────────

class TestMarkFailed(unittest.TestCase):

    def setUp(self):
        self.q = SignalQueue(_make_conn())
        self.q.enqueue(_sig())
        self.sid = self.q.dequeue_batch()[0].id

    def test_first_failure_returns_to_pending(self):
        self.q.mark_failed(self.sid, "timeout")
        self.assertEqual(self.q.pending_count(), 1)

    def test_reaches_max_attempts_becomes_failed(self):
        for _ in range(SignalQueue.MAX_ATTEMPTS):
            self.q.dequeue_batch()  # re-claim if back to pending
            self.q.mark_failed(self.sid, "error")

        stats = self.q.stats()
        self.assertEqual(stats.get("failed", 0), 1)
        self.assertEqual(stats.get("pending", 0), 0)


# ── T-06  mark_skipped ────────────────────────────────────────────────────

class TestMarkSkipped(unittest.TestCase):

    def test_mark_skipped(self):
        q = SignalQueue(_make_conn())
        q.enqueue(_sig())
        batch = q.dequeue_batch()
        q.mark_skipped(batch[0].id, "gate not met")

        stats = q.stats()
        self.assertEqual(stats.get("skipped", 0), 1)


# ── T-07  cleanup_stale ───────────────────────────────────────────────────

class TestCleanupStale(unittest.TestCase):

    def test_cleanup_stale_marks_old_pending_as_skipped(self):
        q = SignalQueue(_make_conn())
        # Manually insert an old pending signal (31 days ago)
        conn = q._conn
        conn.execute(
            """INSERT INTO signal_queue
               (id, kind, workdir, timestamp, summary, raw_content, created_at)
               VALUES ('old-1', 'git_commit', '/tmp', '2000-01-01', 'old signal',
                       'raw', datetime('now', '-31 days'))"""
        )
        conn.commit()

        # Also insert a fresh signal
        q.enqueue(_sig("fresh signal"))

        cleaned = q.cleanup_stale()
        self.assertEqual(cleaned, 1)  # only the old one

        stats = q.stats()
        self.assertEqual(stats.get("skipped", 0), 1)
        self.assertEqual(stats.get("pending", 0), 1)  # fresh still pending


# ── T-08  stats ────────────────────────────────────────────────────────────

class TestStats(unittest.TestCase):

    def test_stats_counts_all_statuses(self):
        q = SignalQueue(_make_conn())
        q.enqueue(_sig("a"))
        q.enqueue(_sig("b"))
        batch = q.dequeue_batch(1)
        q.mark_done(batch[0].id)

        stats = q.stats()
        self.assertEqual(stats["done"],    1)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["total"],   2)


# ── T-09  dequeue_batch CAS ───────────────────────────────────────────────

class TestDequeueCAS(unittest.TestCase):

    def test_dequeue_twice_no_double_claim(self):
        q = SignalQueue(_make_conn())
        q.enqueue(_sig("only one"))

        batch1 = q.dequeue_batch()
        batch2 = q.dequeue_batch()

        self.assertEqual(len(batch1), 1)
        self.assertEqual(len(batch2), 0)  # already processing

    def test_priority_ordering(self):
        q = SignalQueue(_make_conn())
        q.enqueue(_sig("high prio", priority=1))
        q.enqueue(_sig("low prio",  priority=9))

        batch = q.dequeue_batch(batch_size=2)
        self.assertEqual(batch[0].priority, 1)
        self.assertEqual(batch[1].priority, 9)


# ── T-10  Signal 序列化往返 ────────────────────────────────────────────────

class TestSignalSerialization(unittest.TestCase):

    def test_to_row_from_row_roundtrip(self):
        q = SignalQueue(_make_conn())
        original = Signal(
            kind=SignalKind.GIT_COMMIT,
            workdir="/repo",
            summary="fix: token bug",
            raw_content="diff --git...",
            metadata={"commit_hash": "abc123", "files": ["auth.py"]},
            priority=3,
        )
        q.enqueue(original)
        recovered = q.dequeue_batch()[0]

        self.assertEqual(recovered.id,          original.id)
        self.assertEqual(recovered.kind,        original.kind)
        self.assertEqual(recovered.workdir,     original.workdir)
        self.assertEqual(recovered.summary,     original.summary)
        self.assertEqual(recovered.raw_content, original.raw_content)
        self.assertEqual(recovered.metadata,    original.metadata)
        self.assertEqual(recovered.priority,    original.priority)

    def test_long_content_truncated(self):
        s = Signal(
            kind=SignalKind.GIT_COMMIT,
            workdir="/repo",
            summary="x" * 600,       # > 500 chars
            raw_content="r" * 20_000, # > 10000 chars
        )
        row = s.to_row()
        self.assertLessEqual(len(row[4]), 500)     # summary
        self.assertLessEqual(len(row[5]), 10_000)  # raw_content


# ── T-11  BrainDB migration v23~v26 ───────────────────────────────────────

class TestBrainDBMigrations(unittest.TestCase):

    def test_signal_queue_table_created(self):
        from project_brain.brain_db import BrainDB
        with tempfile.TemporaryDirectory() as d:
            brain_dir = Path(d) / ".brain"
            brain_dir.mkdir()
            db = BrainDB(brain_dir)
            tables = {r[0] for r in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            self.assertIn("signal_queue",     tables)
            self.assertIn("pipeline_metrics", tables)

    def test_signal_queue_indexes_created(self):
        from project_brain.brain_db import BrainDB
        with tempfile.TemporaryDirectory() as d:
            brain_dir = Path(d) / ".brain"
            brain_dir.mkdir()
            db = BrainDB(brain_dir)
            indexes = {r[0] for r in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
            self.assertIn("idx_signal_queue_status_priority", indexes)
            self.assertIn("idx_signal_dedup",                 indexes)

    def test_signal_queue_works_with_brain_db_conn(self):
        """SignalQueue 可直接使用 BrainDB.conn 運作。"""
        from project_brain.brain_db import BrainDB
        with tempfile.TemporaryDirectory() as d:
            brain_dir = Path(d) / ".brain"
            brain_dir.mkdir()
            db = BrainDB(brain_dir)
            q  = SignalQueue(db.conn)

            sig = Signal(
                kind=SignalKind.GIT_COMMIT,
                workdir=str(d),
                summary="fix: integrate with BrainDB",
                raw_content="diff content",
            )
            self.assertTrue(q.enqueue(sig))
            self.assertEqual(q.pending_count(), 1)


if __name__ == "__main__":
    unittest.main()
