"""
project_brain/pipeline_worker.py — Auto Knowledge Pipeline 背景 Worker

將 Signal → LLMJudgmentEngine → KnowledgeExecutor 串成持續運作的背景迴圈。

設計原則（docs/AUTO_KNOWLEDGE_PIPELINE.md §11）：
  - 非同步、不阻塞主流程（daemon thread）
  - 進程重啟安全（SignalQueue 已持久化到 SQLite）
  - CAS 保證多 worker 不會重複處理同一 signal
  - 單程序單 worker（guard 防重複啟動，仿 decay_daemon）
  - LLM 不可用時自動退到 pending，等 API 恢復再重試
  - 可觀測：每次迴圈記錄 processed / add / skip 計數

使用方式：
    from project_brain.pipeline_worker import PipelineWorker, start_global_worker

    # 方式 1: 手動建立（測試用）
    worker = PipelineWorker(queue, judge, executor, interval_seconds=60)
    worker.start()
    ...
    worker.stop()

    # 方式 2: 全域單例（mcp_server 使用）
    start_global_worker(brain_db, brain_dir)   # 自動讀 brain.toml
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

from project_brain.pipeline import (
    KnowledgeExecutor,
    Signal,
    SignalQueue,
)

logger = logging.getLogger(__name__)

# ── 常數 ──────────────────────────────────────────────────────────

DEFAULT_INTERVAL_SECONDS = 60     # 預設輪詢間隔（brain.toml 可覆寫）
DEFAULT_BATCH_SIZE       = 5      # 每次 dequeue 的信號數
STALE_CLEANUP_EVERY      = 100    # 每 N 次迴圈清一次 stale signal


# ── PipelineWorker ────────────────────────────────────────────────

class PipelineWorker:
    """
    Layer 3.5 — 將 Signal 送進 LLMJudgmentEngine 後交給 KnowledgeExecutor 的背景 worker。

    生命週期：
        start()  → daemon thread 啟動迴圈
        stop()   → 設 _stop Event，迴圈會在下次睡眠結束後退出
        is_alive → Thread.is_alive() 代理

    迴圈內每次執行 _process_once() 流程：
        1. dequeue_batch(batch_size) → list[Signal]
        2. 對每個 signal 呼叫 judge.analyze(signal) → KnowledgeDecision
        3. executor.run(decision, signal) → ExecutionResult
        4. queue.mark_done(signal.id, json_result) 或 mark_failed(signal.id, err)
        5. 每 STALE_CLEANUP_EVERY 次呼叫 queue.cleanup_stale()
    """

    def __init__(
        self,
        queue:             SignalQueue,
        judge:             Any,                      # LLMJudgmentEngine (duck-typed)
        executor:          KnowledgeExecutor,
        interval_seconds:  int = DEFAULT_INTERVAL_SECONDS,
        batch_size:        int = DEFAULT_BATCH_SIZE,
        name:              str = "brain-pipeline-worker",
    ) -> None:
        self._queue     = queue
        self._judge     = judge
        self._executor  = executor
        self._interval  = max(1, int(interval_seconds))
        self._batch     = max(1, int(batch_size))
        self._name      = name

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop_count = 0

    # ── 生命週期 ──────────────────────────────────────────────────

    def start(self) -> None:
        """啟動 daemon thread。重複呼叫為 no-op。"""
        if self._thread is not None and self._thread.is_alive():
            logger.debug("PipelineWorker.start: already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name=self._name,
        )
        self._thread.start()
        logger.info(
            "PipelineWorker started: interval=%ds batch=%d",
            self._interval, self._batch,
        )

    def stop(self, timeout: float = 5.0) -> None:
        """要求背景迴圈結束。timeout 後即使未結束也返回。"""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.debug("PipelineWorker stopped")

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── 主迴圈 ───────────────────────────────────────────────────

    def _loop(self) -> None:
        """背景迴圈。任何未捕獲異常都只記 log，不終止迴圈。"""
        while not self._stop_event.is_set():
            try:
                self._process_once()
            except Exception as e:
                logger.error("PipelineWorker: unhandled error in loop: %s", e, exc_info=True)

            # 定期清理 stale signals（超過 MAX_PENDING_AGE_DAYS 的 pending）
            self._loop_count += 1
            if self._loop_count % STALE_CLEANUP_EVERY == 0:
                try:
                    self._queue.cleanup_stale()
                except Exception as e:
                    logger.debug("PipelineWorker: cleanup_stale failed: %s", e)

            # wait() 會立即被 stop_event 中斷，不用等完整 interval
            self._stop_event.wait(timeout=self._interval)

    def _process_once(self) -> dict:
        """
        處理一個 batch。回傳統計字典（測試用）：
            {"dequeued": int, "add": int, "skip": int, "failed": int}
        """
        stats = {"dequeued": 0, "add": 0, "skip": 0, "failed": 0}
        try:
            batch = self._queue.dequeue_batch(batch_size=self._batch)
        except Exception as e:
            logger.error("PipelineWorker: dequeue_batch failed: %s", e)
            return stats

        stats["dequeued"] = len(batch)
        if not batch:
            return stats

        for signal in batch:
            self._process_signal(signal, stats)

        if stats["add"] or stats["skip"] or stats["failed"]:
            logger.info(
                "PipelineWorker.batch: dequeued=%d add=%d skip=%d failed=%d",
                stats["dequeued"], stats["add"], stats["skip"], stats["failed"],
            )
        return stats

    def _process_signal(self, signal: Signal, stats: dict) -> None:
        """處理單一 signal，更新 stats。所有錯誤都轉成 mark_failed。"""
        try:
            decision = self._judge.analyze(signal)
        except Exception as e:
            logger.warning(
                "PipelineWorker: judge.analyze raised for signal=%s: %s",
                signal.id[:8], e,
            )
            self._safe_mark_failed(signal.id, f"judge_error: {e}")
            stats["failed"] += 1
            return

        try:
            result = self._executor.run(decision, signal)
        except Exception as e:
            logger.warning(
                "PipelineWorker: executor.run raised for signal=%s: %s",
                signal.id[:8], e,
            )
            self._safe_mark_failed(signal.id, f"executor_error: {e}")
            stats["failed"] += 1
            return

        if result.ok:
            # 記錄到 signal_queue 的 error 欄位（當作 decision_json 備查）
            import json as _json
            decision_json = _json.dumps({
                "action":    result.action,
                "node_id":   result.node_id,
                "skipped":   result.skipped,
                "llm_model": decision.llm_model,
            }, ensure_ascii=False)
            self._safe_mark_done(signal.id, decision_json)

            if result.action == "add":
                stats["add"] += 1
            else:
                stats["skip"] += 1
        else:
            self._safe_mark_failed(signal.id, result.error or "unknown executor error")
            stats["failed"] += 1

    def _safe_mark_done(self, signal_id: str, decision_json: str) -> None:
        try:
            self._queue.mark_done(signal_id, decision_json=decision_json)
        except Exception as e:
            logger.error("PipelineWorker: mark_done failed for %s: %s", signal_id[:8], e)

    def _safe_mark_failed(self, signal_id: str, error: str) -> None:
        try:
            self._queue.mark_failed(signal_id, error=error)
        except Exception as e:
            logger.error("PipelineWorker: mark_failed failed for %s: %s", signal_id[:8], e)


# ── 全域單例（mcp_server 使用）──────────────────────────────────

_global_worker: Optional[PipelineWorker] = None
_global_worker_lock = threading.Lock()


def start_global_worker(
    brain_db:  Any,                     # BrainDB 實例
    brain_dir: Optional[Path] = None,
) -> Optional[PipelineWorker]:
    """
    啟動全域 PipelineWorker 單例（若尚未啟動）。

    讀取 brain.toml [pipeline] 決定：
      - enabled: false → 直接回傳 None（不啟動）
      - worker_interval_seconds: 輪詢間隔
      - pipeline.llm: LLMJudgmentEngine 後端

    已啟動時直接回傳既有 worker。設計為幂等，可重複呼叫。

    Args:
        brain_db:  BrainDB 實例，提供 signal_queue 用的 conn
        brain_dir: .brain/ 路徑；None 時從 brain_db.brain_dir 推導

    Returns:
        PipelineWorker 實例（若已啟動或啟動成功）
        None（若 [pipeline.enabled]=false 或啟動失敗）
    """
    global _global_worker

    with _global_worker_lock:
        if _global_worker is not None and _global_worker.is_alive():
            return _global_worker

        try:
            bd = Path(brain_dir) if brain_dir else Path(getattr(brain_db, "brain_dir", ""))

            from project_brain.brain_config import load_config
            cfg = load_config(bd)
            if not cfg.pipeline.enabled:
                logger.info("PipelineWorker: disabled by brain.toml [pipeline.enabled]=false")
                return None

            from project_brain.llm_judgment import LLMJudgmentEngine
            queue    = SignalQueue(brain_db.conn)
            judge    = LLMJudgmentEngine.from_brain_config(bd)
            executor = KnowledgeExecutor(brain_db)

            worker = PipelineWorker(
                queue            = queue,
                judge            = judge,
                executor         = executor,
                interval_seconds = cfg.pipeline.worker_interval_seconds,
            )
            worker.start()
            _global_worker = worker
            logger.info(
                "BLOCKER-01: PipelineWorker started (interval=%ds, model=%s)",
                cfg.pipeline.worker_interval_seconds, judge.model,
            )
            return worker

        except Exception as e:
            logger.warning("BLOCKER-01: PipelineWorker failed to start: %s", e, exc_info=True)
            return None


def stop_global_worker(timeout: float = 5.0) -> None:
    """停止全域 worker（主要用於測試或正常關機）。"""
    global _global_worker
    with _global_worker_lock:
        if _global_worker is not None:
            _global_worker.stop(timeout=timeout)
            _global_worker = None
