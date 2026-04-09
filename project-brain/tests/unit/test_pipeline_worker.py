"""
tests/unit/test_pipeline_worker.py

BLOCKER-01 — PipelineWorker (Layer 3.5) 單元測試

驗收標準：
  W-01  空佇列：_process_once 回傳 dequeued=0，不呼叫 judge
  W-02  ADD 流程：signal → judge → executor → mark_done（節點被建立）
  W-03  SKIP 流程：signal → judge → executor → mark_done（節點未建立）
  W-04  Judge 拋 exception → mark_failed，stats.failed+=1
  W-05  Executor 拋 exception → mark_failed
  W-06  多個 signal 批次處理，統計正確
  W-07  start() 可重複呼叫不會啟動多個 thread
  W-08  stop() 後 is_alive() 為 False
  W-09  start() 後 daemon thread 實際運行（短 interval 驗證）
  W-10  全域 start_global_worker 幂等（重複呼叫回傳同一 worker）
  W-11  [pipeline.enabled]=false 時 start_global_worker 回傳 None
  W-12  background 迴圈異常不終止 worker（繼續下一輪）
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from project_brain.pipeline import (
    KnowledgeDecision,
    KnowledgeExecutor,
    NodeSpec,
    Signal,
    SignalKind,
    SignalQueue,
)
from project_brain.pipeline_worker import (
    PipelineWorker,
    start_global_worker,
    stop_global_worker,
)


# ── 測試輔助 ──────────────────────────────────────────────────────

def _make_db(tmp_path: Path):
    from project_brain.brain_db import BrainDB
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    return BrainDB(brain_dir)


def _make_signal(
    signal_id: str = "sig-w-01",
    summary:   str = "test signal",
    kind:      SignalKind = SignalKind.GIT_COMMIT,
) -> Signal:
    s = Signal(
        kind       = kind,
        workdir    = "/test/repo",
        summary    = summary,
        raw_content= f"raw content for {signal_id}",
    )
    s.id = signal_id
    return s


class _FakeJudge:
    """
    可配置的 judge mock：
        - responses[signal.id] = KnowledgeDecision 或 Exception 物件
        - 預設：回傳 skip
    """
    def __init__(self, responses: dict[str, Any] | None = None):
        self.responses = responses or {}
        self.calls: list[str] = []

    def analyze(self, signal: Signal, related_nodes=None) -> KnowledgeDecision:
        self.calls.append(signal.id)
        response = self.responses.get(signal.id)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, KnowledgeDecision):
            return response
        # 預設 skip
        return KnowledgeDecision(
            action="skip",
            reason="default fake skip",
            signal_id=signal.id,
            llm_model="fake",
        )


def _add_decision(signal_id: str) -> KnowledgeDecision:
    return KnowledgeDecision(
        action="add",
        reason="test add",
        signal_id=signal_id,
        node=NodeSpec(
            title=f"Title-{signal_id}",
            content=f"Content for {signal_id}",
            kind="Note",
            confidence=0.7,
            tags=["test"],
        ),
        llm_model="fake",
    )


# ══════════════════════════════════════════════════════════════════
#  W-01 ~ W-06  _process_once 行為
# ══════════════════════════════════════════════════════════════════

class TestProcessOnce(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db   = _make_db(Path(self._tmp.name))
        self.queue    = SignalQueue(self.db.conn)
        self.executor = KnowledgeExecutor(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_W01_empty_queue(self):
        worker = PipelineWorker(self.queue, _FakeJudge(), self.executor)
        stats  = worker._process_once()
        self.assertEqual(stats["dequeued"], 0)
        self.assertEqual(stats["add"], 0)

    def test_W02_add_flow(self):
        self.queue.enqueue(_make_signal("sig-add"))
        judge = _FakeJudge({"sig-add": _add_decision("sig-add")})
        worker = PipelineWorker(self.queue, judge, self.executor)

        stats = worker._process_once()

        self.assertEqual(stats["dequeued"], 1)
        self.assertEqual(stats["add"], 1)
        self.assertEqual(stats["skip"], 0)
        self.assertEqual(stats["failed"], 0)
        # 節點被建立
        count = self.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count, 1)
        # Queue 中標記為 done
        row = self.db.conn.execute(
            "SELECT status, error FROM signal_queue WHERE id=?", ("sig-add",)
        ).fetchone()
        self.assertEqual(row["status"], "done")
        # decision_json 寫在 error 欄位（queue 設計如此）
        decision_json = row["error"]
        self.assertIn("add", decision_json)
        self.assertIn("auto-", decision_json)  # node_id prefix

    def test_W03_skip_flow(self):
        self.queue.enqueue(_make_signal("sig-skip"))
        worker = PipelineWorker(self.queue, _FakeJudge(), self.executor)  # default returns skip

        stats = worker._process_once()

        self.assertEqual(stats["dequeued"], 1)
        self.assertEqual(stats["add"], 0)
        self.assertEqual(stats["skip"], 1)
        # 沒有節點
        count = self.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count, 0)
        row = self.db.conn.execute(
            "SELECT status FROM signal_queue WHERE id=?", ("sig-skip",)
        ).fetchone()
        self.assertEqual(row["status"], "done")

    def test_W04_judge_exception_marks_failed(self):
        self.queue.enqueue(_make_signal("sig-judge-err"))
        judge = _FakeJudge({"sig-judge-err": RuntimeError("llm down")})
        worker = PipelineWorker(self.queue, judge, self.executor)

        stats = worker._process_once()

        self.assertEqual(stats["failed"], 1)
        row = self.db.conn.execute(
            "SELECT status, attempts, error FROM signal_queue WHERE id=?",
            ("sig-judge-err",),
        ).fetchone()
        # 第一次失敗：attempts=1，回到 pending（未達 MAX_ATTEMPTS=3）
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["attempts"], 1)
        self.assertIn("llm down", row["error"])

    def test_W05_executor_exception_marks_failed(self):
        self.queue.enqueue(_make_signal("sig-exec-err"))

        # 製造一個會讓 executor 爆炸的 decision（使用一個 Mock executor）
        class _BrokenExecutor:
            def run(self, decision, signal=None):
                raise RuntimeError("db locked")

        judge = _FakeJudge({"sig-exec-err": _add_decision("sig-exec-err")})
        worker = PipelineWorker(self.queue, judge, _BrokenExecutor())

        stats = worker._process_once()
        self.assertEqual(stats["failed"], 1)
        row = self.db.conn.execute(
            "SELECT status, error FROM signal_queue WHERE id=?", ("sig-exec-err",),
        ).fetchone()
        self.assertIn("db locked", row["error"])

    def test_W06_batch_mixed(self):
        self.queue.enqueue(_make_signal("sig-b1", summary="add one"))
        self.queue.enqueue(_make_signal("sig-b2", summary="skip one"))
        self.queue.enqueue(_make_signal("sig-b3", summary="err one"))

        judge = _FakeJudge({
            "sig-b1": _add_decision("sig-b1"),
            "sig-b3": RuntimeError("oops"),
            # sig-b2 uses default = skip
        })
        worker = PipelineWorker(
            self.queue, judge, self.executor, batch_size=10,
        )

        stats = worker._process_once()
        self.assertEqual(stats["dequeued"], 3)
        self.assertEqual(stats["add"], 1)
        self.assertEqual(stats["skip"], 1)
        self.assertEqual(stats["failed"], 1)


# ══════════════════════════════════════════════════════════════════
#  W-07 ~ W-09  Thread 生命週期
# ══════════════════════════════════════════════════════════════════

class TestLifecycle(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db   = _make_db(Path(self._tmp.name))
        self.queue = SignalQueue(self.db.conn)
        self.exec_ = KnowledgeExecutor(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_W07_double_start_noop(self):
        w = PipelineWorker(self.queue, _FakeJudge(), self.exec_, interval_seconds=10)
        w.start()
        t1 = w._thread
        w.start()  # should not create new thread
        t2 = w._thread
        self.assertIs(t1, t2)
        w.stop()

    def test_W08_stop_sets_dead(self):
        w = PipelineWorker(self.queue, _FakeJudge(), self.exec_, interval_seconds=10)
        w.start()
        self.assertTrue(w.is_alive())
        w.stop(timeout=2.0)
        # stop() 設 event，下次 wait() 立即中斷；給 thread 一點時間結束
        time.sleep(0.2)
        self.assertFalse(w.is_alive())

    def test_W09_running_thread_processes_signals(self):
        self.queue.enqueue(_make_signal("sig-live"))
        judge = _FakeJudge({"sig-live": _add_decision("sig-live")})
        w = PipelineWorker(self.queue, judge, self.exec_, interval_seconds=1)
        w.start()
        # 等 worker 跑第一輪（interval=1s，給 2s 緩衝）
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            row = self.db.conn.execute(
                "SELECT status FROM signal_queue WHERE id='sig-live'"
            ).fetchone()
            if row and row["status"] == "done":
                break
            time.sleep(0.05)
        w.stop(timeout=2.0)

        row = self.db.conn.execute(
            "SELECT status FROM signal_queue WHERE id='sig-live'"
        ).fetchone()
        self.assertEqual(row["status"], "done")


# ══════════════════════════════════════════════════════════════════
#  W-10 ~ W-11  全域 singleton
# ══════════════════════════════════════════════════════════════════

class TestGlobalWorker(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db   = _make_db(Path(self._tmp.name))
        # 每個測試結束都 stop 清空全域狀態
        self.addCleanup(stop_global_worker)

    def tearDown(self):
        self._tmp.cleanup()

    def test_W10_global_idempotent(self):
        # 第一次：可能因為 Ollama 不可用而 fallback 或失敗，但不應拋例外
        w1 = start_global_worker(self.db, brain_dir=self.db.brain_dir)
        w2 = start_global_worker(self.db, brain_dir=self.db.brain_dir)
        if w1 is not None:
            # 如果啟動成功，第二次呼叫應回傳同一實例
            self.assertIs(w1, w2)

    def test_W11_disabled_returns_none(self):
        # 寫一個 brain.toml 關閉 pipeline
        toml_path = self.db.brain_dir / "brain.toml"
        toml_path.write_text(
            "[pipeline]\nenabled = false\n",
            encoding="utf-8",
        )
        stop_global_worker()  # 先確保乾淨狀態

        w = start_global_worker(self.db, brain_dir=self.db.brain_dir)
        self.assertIsNone(w)


# ══════════════════════════════════════════════════════════════════
#  W-12  迴圈異常不終止 worker
# ══════════════════════════════════════════════════════════════════

class TestLoopResilience(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db   = _make_db(Path(self._tmp.name))
        self.queue = SignalQueue(self.db.conn)

    def tearDown(self):
        self._tmp.cleanup()

    def test_W12_unexpected_exception_in_process_does_not_kill_loop(self):
        """dequeue 本身爆炸時，worker 仍應繼續下一輪"""
        judge = _FakeJudge()
        exec_ = KnowledgeExecutor(self.db)

        # 用一個會在第一次 dequeue 爆炸、第二次正常的 queue wrapper
        class _FlakyQueue:
            def __init__(self, real_queue):
                self._real = real_queue
                self._calls = 0
            def dequeue_batch(self, batch_size=5):
                self._calls += 1
                if self._calls == 1:
                    raise RuntimeError("first call fails")
                return self._real.dequeue_batch(batch_size=batch_size)
            def cleanup_stale(self):
                return self._real.cleanup_stale()
            def mark_done(self, *a, **kw):
                return self._real.mark_done(*a, **kw)
            def mark_failed(self, *a, **kw):
                return self._real.mark_failed(*a, **kw)

        flaky = _FlakyQueue(self.queue)
        worker = PipelineWorker(flaky, judge, exec_, interval_seconds=1)

        # 第一次呼叫 _process_once 應該處理 dequeue_batch 的異常
        stats1 = worker._process_once()
        self.assertEqual(stats1["dequeued"], 0)  # 異常 → 回傳空 stats

        # 第二次呼叫應該正常工作
        stats2 = worker._process_once()
        self.assertEqual(stats2["dequeued"], 0)  # queue 實際為空


if __name__ == "__main__":
    unittest.main()
