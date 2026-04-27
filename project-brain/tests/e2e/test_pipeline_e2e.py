"""
tests/e2e/test_pipeline_e2e.py — D-04 E2E Pipeline 整合測試

驗證 signal emit → pipeline worker → knowledge executor → L3 write
的完整資料流，不依賴真實 LLM（使用 StubJudge）。

Ollama 依賴的測試用 BRAIN_TEST_OLLAMA=1 環境變數控制，
未設定時自動 skip — CI 安全。

執行：
  # 無 Ollama（stub 流程）
  pytest tests/e2e/test_pipeline_e2e.py -v

  # 含 Ollama 整合（需本地 ollama 服務）
  BRAIN_TEST_OLLAMA=1 pytest tests/e2e/test_pipeline_e2e.py -v -m e2e_ollama
"""
from __future__ import annotations

import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import pytest

from project_brain.core.brain_db import BrainDB
from project_brain.pipeline.executor import KnowledgeDecision, KnowledgeExecutor, NodeSpec
from project_brain.pipeline.signal import Signal, SignalKind, SignalQueue
from project_brain.pipeline.worker import PipelineWorker

# ── Ollama skip helper ────────────────────────────────────────────────────────

_OLLAMA_ENABLED = os.environ.get("BRAIN_TEST_OLLAMA", "").strip() == "1"
requires_ollama = pytest.mark.skipif(
    not _OLLAMA_ENABLED,
    reason="Ollama not available — set BRAIN_TEST_OLLAMA=1 to run these tests",
)

# ── Fixtures & helpers ────────────────────────────────────────────────────────

class StubJudge:
    """
    Deterministic judge stub — no LLM required.

    Always decides ``action="add"`` with a predictable node title so tests
    can assert the node was written to L3.
    """

    def __init__(self, action: str = "add", fail: bool = False) -> None:
        self.action = action
        self.fail = fail
        self.calls: list[Signal] = []

    def analyze(self, signal: Signal) -> KnowledgeDecision:
        self.calls.append(signal)
        if self.fail:
            raise RuntimeError("stub judge forced failure")
        node = None
        if self.action == "add":
            node = NodeSpec(
                title=f"e2e-{signal.id[:8]}",
                content=f"Auto-extracted from signal: {signal.summary[:100]}",
                kind="Note",
                confidence=0.7,
                tags=["e2e", "auto"],
            )
        return KnowledgeDecision(
            action=self.action,
            reason="stub decision",
            signal_id=signal.id,
            confidence=0.8,
            node=node,
            llm_model="stub",
        )


def _make_signal(workdir: str, summary: str = "test signal", kind: SignalKind = SignalKind.MANUAL) -> Signal:
    return Signal(
        kind=kind,
        workdir=workdir,
        summary=summary,
        raw_content=f"raw content for: {summary}",
        metadata={"source": "e2e_test"},
    )


@pytest.fixture
def brain_setup():
    """Temp brain dir with BrainDB, SignalQueue, KnowledgeExecutor."""
    with tempfile.TemporaryDirectory() as tmp:
        brain_dir = Path(tmp) / ".brain"
        brain_dir.mkdir()
        db = BrainDB(brain_dir)
        queue = SignalQueue(db.conn)
        executor = KnowledgeExecutor(db)
        yield {
            "brain_dir": brain_dir,
            "workdir": str(tmp),
            "db": db,
            "queue": queue,
            "executor": executor,
        }
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# TestSignalToL3Flow — core pipeline mechanics with stub judge
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalToL3Flow:
    """
    Signal → judge → executor → L3 write.

    Uses StubJudge so no Ollama is required.
    """

    def test_enqueue_single_signal(self, brain_setup):
        """Signal can be enqueued and appears in pending count."""
        q = brain_setup["queue"]
        sig = _make_signal(brain_setup["workdir"])
        inserted = q.enqueue(sig)
        assert inserted is True
        assert q.pending_count() == 1

    def test_process_once_add_writes_l3_node(self, brain_setup):
        """_process_once with add-stub creates a node in BrainDB."""
        q = brain_setup["queue"]
        db = brain_setup["db"]
        sig = _make_signal(brain_setup["workdir"], summary="commit: fix auth bug")
        q.enqueue(sig)

        judge = StubJudge(action="add")
        worker = PipelineWorker(queue=q, judge=judge, executor=brain_setup["executor"])
        stats = worker._process_once()

        assert stats["dequeued"] == 1
        assert stats["add"] == 1
        assert stats["failed"] == 0

        # Node should be in BrainDB
        expected_title = f"e2e-{sig.id[:8]}"
        rows = db.conn.execute(
            "SELECT id, title FROM nodes WHERE title=?", (expected_title,)
        ).fetchall()
        assert len(rows) == 1, f"Expected 1 node, found {len(rows)}"

    def test_process_once_skip_does_not_write_node(self, brain_setup):
        """_process_once with skip-stub writes no node to BrainDB."""
        q = brain_setup["queue"]
        db = brain_setup["db"]
        sig = _make_signal(brain_setup["workdir"], summary="minor comment edit")
        q.enqueue(sig)

        judge = StubJudge(action="skip")
        worker = PipelineWorker(queue=q, judge=judge, executor=brain_setup["executor"])
        stats = worker._process_once()

        assert stats["skip"] == 1
        # No new nodes
        count = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        assert count == 0

    def test_process_once_judge_failure_retries_signal(self, brain_setup):
        """
        When judge.analyze raises, signal attempts++ and returns to pending
        (retry semantics — MAX_ATTEMPTS=3, so 2 more retries remain).
        After MAX_ATTEMPTS failures the signal moves to 'failed'.
        """
        q = brain_setup["queue"]
        sig = _make_signal(brain_setup["workdir"], summary="trigger judge failure")
        q.enqueue(sig)

        judge = StubJudge(fail=True)
        worker = PipelineWorker(queue=q, judge=judge, executor=brain_setup["executor"])

        # First failure: signal back in pending (1 attempt used, 2 remain)
        stats = worker._process_once()
        assert stats["failed"] == 1
        assert q.pending_count() == 1   # re-queued for retry

        # Second failure: still pending
        stats = worker._process_once()
        assert stats["failed"] == 1
        assert q.pending_count() == 1

        # Third failure: MAX_ATTEMPTS reached → status='failed', no longer pending
        stats = worker._process_once()
        assert stats["failed"] == 1
        assert q.pending_count() == 0   # exhausted — moved to 'failed'

    def test_process_batch_of_three(self, brain_setup):
        """Three signals all get processed in one batch."""
        q = brain_setup["queue"]
        for i in range(3):
            q.enqueue(_make_signal(brain_setup["workdir"], summary=f"signal-{i}"))

        judge = StubJudge(action="add")
        worker = PipelineWorker(queue=q, judge=judge, executor=brain_setup["executor"],
                                batch_size=10)
        stats = worker._process_once()

        assert stats["dequeued"] == 3
        assert stats["add"] == 3

    def test_idempotent_signal_dedup(self, brain_setup):
        """Identical (kind, workdir, summary) enqueue is idempotent."""
        q = brain_setup["queue"]
        sig1 = _make_signal(brain_setup["workdir"], summary="identical summary")
        sig2 = _make_signal(brain_setup["workdir"], summary="identical summary")
        q.enqueue(sig1)
        inserted = q.enqueue(sig2)  # duplicate — should be rejected
        assert inserted is False
        assert q.pending_count() == 1

    def test_signal_queue_survives_empty_process(self, brain_setup):
        """_process_once with empty queue returns zeros, no crash."""
        q = brain_setup["queue"]
        judge = StubJudge()
        worker = PipelineWorker(queue=q, judge=judge, executor=brain_setup["executor"])
        stats = worker._process_once()
        assert stats == {"dequeued": 0, "add": 0, "skip": 0, "failed": 0}

    def test_different_signal_kinds_all_processed(self, brain_setup):
        """Multiple SignalKind values all flow through correctly."""
        q = brain_setup["queue"]
        kinds = [SignalKind.GIT_COMMIT, SignalKind.TASK_COMPLETE, SignalKind.MANUAL]
        for kind in kinds:
            q.enqueue(_make_signal(brain_setup["workdir"],
                                   summary=f"{kind.value} event", kind=kind))

        judge = StubJudge(action="add")
        worker = PipelineWorker(queue=q, judge=judge, executor=brain_setup["executor"],
                                batch_size=10)
        stats = worker._process_once()
        assert stats["add"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# TestPipelineLatency — end-to-end timing
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineLatency:
    """
    Signal-to-L3 latency budget.

    Target: < 5000ms per signal (ROADMAP D-04).
    On a dev machine without embedder the stub path is typically < 50ms.
    """

    def test_single_signal_latency_under_5s(self, brain_setup):
        """enqueue → _process_once → L3 write must complete within 5 seconds."""
        q = brain_setup["queue"]
        sig = _make_signal(brain_setup["workdir"], summary="latency test signal")
        q.enqueue(sig)

        judge = StubJudge(action="add")
        worker = PipelineWorker(queue=q, judge=judge, executor=brain_setup["executor"])

        t0 = time.monotonic()
        worker._process_once()
        elapsed_ms = (time.monotonic() - t0) * 1000

        assert elapsed_ms < 5000, (
            f"Pipeline latency {elapsed_ms:.0f}ms exceeds 5000ms budget"
        )

    def test_batch_10_signals_latency_under_30s(self, brain_setup):
        """10 signals processed together must finish within 30 seconds total."""
        q = brain_setup["queue"]
        for i in range(10):
            q.enqueue(_make_signal(brain_setup["workdir"], summary=f"batch signal {i}"))

        judge = StubJudge(action="add")
        worker = PipelineWorker(queue=q, judge=judge, executor=brain_setup["executor"],
                                batch_size=10)

        t0 = time.monotonic()
        worker._process_once()
        elapsed_ms = (time.monotonic() - t0) * 1000

        assert elapsed_ms < 30_000, (
            f"Batch latency {elapsed_ms:.0f}ms exceeds 30s budget"
        )


# ─────────────────────────────────────────────────────────────────────────────
# TestPipelineWorkerLifecycle — thread start/stop
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineWorkerLifecycle:
    """Worker daemon thread starts and stops cleanly."""

    def test_worker_starts_and_stops(self, brain_setup):
        q = brain_setup["queue"]
        judge = StubJudge(action="skip")
        worker = PipelineWorker(queue=q, judge=judge, executor=brain_setup["executor"],
                                interval_seconds=60)  # long interval so no auto-fire
        worker.start()
        assert worker.is_alive()
        worker.stop(timeout=2.0)
        assert not worker.is_alive()

    def test_worker_double_start_is_noop(self, brain_setup):
        """Calling start() twice is idempotent."""
        q = brain_setup["queue"]
        judge = StubJudge(action="skip")
        worker = PipelineWorker(queue=q, judge=judge, executor=brain_setup["executor"],
                                interval_seconds=60)
        worker.start()
        thread_id = worker._thread.ident
        worker.start()  # second call — should not spawn new thread
        assert worker._thread.ident == thread_id
        worker.stop(timeout=2.0)

    def test_worker_processes_signal_when_started(self, brain_setup):
        """Worker thread picks up an enqueued signal within 3 seconds."""
        q = brain_setup["queue"]
        db = brain_setup["db"]
        sig = _make_signal(brain_setup["workdir"], summary="thread processed")
        q.enqueue(sig)

        judge = StubJudge(action="add")
        worker = PipelineWorker(queue=q, judge=judge, executor=brain_setup["executor"],
                                interval_seconds=1, batch_size=5)
        worker.start()
        # Give worker up to 3 seconds to process
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and q.pending_count() > 0:
            time.sleep(0.05)
        worker.stop(timeout=2.0)

        assert q.pending_count() == 0, "Signal still pending after 3 seconds"
        count = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        assert count == 1


# ─────────────────────────────────────────────────────────────────────────────
# TestPipelineOllama — real LLM tests (skipped unless BRAIN_TEST_OLLAMA=1)
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineOllama:
    """
    Tests requiring a real Ollama instance.

    Run with: BRAIN_TEST_OLLAMA=1 pytest tests/e2e/ -m e2e_ollama
    """

    @requires_ollama
    @pytest.mark.e2e_ollama
    def test_real_judge_git_commit_signal(self, brain_setup):
        """Real LLMJudgmentEngine can analyze a git commit signal."""
        from project_brain.pipeline.llm_judgment import LLMJudgmentEngine
        db = brain_setup["db"]
        q = brain_setup["queue"]

        sig = Signal(
            kind=SignalKind.GIT_COMMIT,
            workdir=brain_setup["workdir"],
            summary="feat: add JWT RS256 token validation with expiry check",
            raw_content=(
                "+def verify_jwt(token: str, public_key: str) -> dict:\n"
                "+    payload = jwt.decode(token, public_key, algorithms=['RS256'])\n"
                "+    if payload.get('exp', 0) < time.time():\n"
                "+        raise ValueError('Token expired')\n"
                "+    return payload\n"
            ),
        )
        q.enqueue(sig)

        try:
            judge = LLMJudgmentEngine(model="llama3.2:3b")
        except Exception as e:
            pytest.skip(f"Cannot init LLMJudgmentEngine: {e}")

        executor = KnowledgeExecutor(db)
        worker = PipelineWorker(queue=q, judge=judge, executor=executor,
                                interval_seconds=60)

        t0 = time.monotonic()
        stats = worker._process_once()
        elapsed_ms = (time.monotonic() - t0) * 1000

        assert stats["dequeued"] == 1
        assert stats["failed"] == 0
        assert elapsed_ms < 15_000, f"Real LLM took {elapsed_ms:.0f}ms > 15s"
        # add OR skip are both valid decisions
        assert stats["add"] + stats["skip"] == 1
