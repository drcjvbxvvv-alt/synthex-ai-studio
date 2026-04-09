"""
project_brain/pipeline/signal.py — Auto Knowledge Pipeline Layer 1 & 2

Phase 1 實作：
  Layer 1/2 — Signal / SignalKind / SignalQueue（SQLite 持久化）

架構原則（設計文件 docs/AUTO_KNOWLEDGE_PIPELINE.md）：
- 信號收集與 LLM 分析嚴格非同步，不阻塞主流程
- SQLite 持久化，進程重啟不遺失信號
- CAS（Compare-And-Swap）確保多實例競爭安全
- 去重索引防止同一事件重複分析
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ── Signal 種類定義 ────────────────────────────────────────────────────────

class SignalKind(str, Enum):
    # ── Phase 1（基礎設施）──────────────────────────────────────────────
    GIT_COMMIT    = "git_commit"    # git commit 事件
    TASK_COMPLETE = "task_complete" # complete_task MCP 工具呼叫

    # ── Phase 2（信號擴展）──────────────────────────────────────────────
    MCP_TOOL_CALL = "mcp_tool_call" # MCP 工具呼叫記錄
    TEST_FAILURE  = "test_failure"  # 測試失敗（累積 >= 3 次才觸發）
    TEST_PASS     = "test_pass"     # 測試通過（追蹤解決）
    MANUAL        = "manual"        # 人工觸發分析

    # ── Phase 3+（待數據驗證後決定）─────────────────────────────────────
    KNOWLEDGE_GAP = "knowledge_gap" # get_context 返回空（見設計文件 4.1 節）
    CI_EVENT      = "ci_event"      # CI/CD pipeline 事件（未來）
    PR_COMMENT    = "pr_comment"    # PR review 留言（未來）


# ── Signal 資料結構 ────────────────────────────────────────────────────────

@dataclass
class Signal:
    """
    標準化事件單元。

    kind / workdir / summary / raw_content 為必填，其餘有預設值。
    summary 用於去重索引（同 kind + workdir + summary 的 pending 信號只保留一個）。
    """
    kind:        SignalKind
    workdir:     str
    summary:     str        # 一行摘要，< 500 chars，用於去重
    raw_content: str        # 原始內容（diff / traceback / log），截斷至 10000 chars
    metadata:    dict = field(default_factory=dict)
    priority:    int  = 5   # 1=最高, 10=最低
    id:          str  = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp:   str  = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_row(self) -> tuple:
        """轉為 INSERT 用的 tuple（對應 signal_queue 欄位順序）。"""
        return (
            self.id,
            self.kind.value if isinstance(self.kind, SignalKind) else str(self.kind),
            self.workdir,
            self.timestamp,
            self.summary[:500],
            self.raw_content[:10_000],
            json.dumps(self.metadata, ensure_ascii=False),
            self.priority,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Signal":
        return cls(
            id          = row["id"],
            kind        = SignalKind(row["kind"]),
            workdir     = row["workdir"],
            timestamp   = row["timestamp"],
            summary     = row["summary"],
            raw_content = row["raw_content"],
            metadata    = json.loads(row["metadata"] or "{}"),
            priority    = row["priority"],
        )


# ── SignalQueue ─────────────────────────────────────────────────────────────

class SignalQueue:
    """
    SQLite 持久化信號佇列。

    - 寫入操作使用 threading.Lock 保護（WAL 模式下多進程安全）
    - dequeue_batch 使用 CAS（pending → processing）確保每個信號只被一個 worker 取走
    - 去重依賴 signal_queue 表的 UNIQUE INDEX idx_signal_dedup
    """

    MAX_QUEUE_SIZE       = 500  # 佇列上限；超過時丟棄 priority >= 8 的低優先信號
    MAX_PENDING_AGE_DAYS = 30   # 超過此天數的 pending 自動標記 skipped（設計決策 #2）
    MAX_ATTEMPTS         = 3    # 最多重試次數

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()

    # ── 寫入操作 ─────────────────────────────────────────────────────────

    def enqueue(self, signal: Signal) -> bool:
        """
        寫入信號。

        回傳 True  → 已接受
        回傳 False → 已丟棄（重複 or 背壓）
        """
        with self._lock:
            # 背壓檢查：佇列接近上限時丟棄低優先信號
            count = self._conn.execute(
                "SELECT COUNT(*) FROM signal_queue WHERE status='pending'"
            ).fetchone()[0]
            if count >= self.MAX_QUEUE_SIZE and signal.priority >= 8:
                logger.debug(
                    "signal_queue: backpressure drop  kind=%s id=%s",
                    signal.kind, signal.id
                )
                return False

            try:
                self._conn.execute(
                    """INSERT INTO signal_queue
                       (id, kind, workdir, timestamp, summary, raw_content, metadata, priority)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    signal.to_row(),
                )
                self._conn.commit()
                logger.debug("signal_queue: enqueued  kind=%s id=%s", signal.kind, signal.id)
                return True
            except sqlite3.IntegrityError:
                # idx_signal_dedup 觸發 → 相同 (kind, workdir, summary) 已在 pending
                logger.debug(
                    "signal_queue: dedup drop  kind=%s summary=%.60s",
                    signal.kind, signal.summary
                )
                return False

    def dequeue_batch(self, batch_size: int = 5) -> list[Signal]:
        """
        原子性取出一批待處理信號（pending → processing）。

        使用 CAS 確保多實例安全：
          UPDATE ... WHERE status='pending' AND id IN (...)
        """
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM signal_queue
                   WHERE status = 'pending'
                   ORDER BY priority ASC, created_at ASC
                   LIMIT ?""",
                (batch_size,),
            ).fetchall()
            if not rows:
                return []

            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" * len(ids))
            self._conn.execute(
                f"UPDATE signal_queue SET status='processing'"
                f" WHERE id IN ({placeholders}) AND status='pending'",
                ids,
            )
            self._conn.commit()
            return [Signal.from_row(r) for r in rows]

    def mark_done(self, signal_id: str, decision_json: Optional[str] = None) -> None:
        """標記信號已完成處理。decision_json 為可選的 KnowledgeDecision 序列化結果。"""
        with self._lock:
            self._conn.execute(
                """UPDATE signal_queue
                   SET status='done', processed_at=datetime('now'), error=?
                   WHERE id=?""",
                (decision_json, signal_id),
            )
            self._conn.commit()

    def mark_failed(self, signal_id: str, error: str) -> None:
        """
        標記失敗。attempts += 1，達到 MAX_ATTEMPTS 後 status → 'failed'（不再重試）。
        未達上限時 status 回到 'pending' 等待下次 worker 輪詢。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT attempts FROM signal_queue WHERE id=?", (signal_id,)
            ).fetchone()
            if not row:
                return
            new_attempts = (row["attempts"] or 0) + 1
            new_status = "failed" if new_attempts >= self.MAX_ATTEMPTS else "pending"
            self._conn.execute(
                """UPDATE signal_queue
                   SET status=?, attempts=?, error=?
                   WHERE id=?""",
                (new_status, new_attempts, str(error)[:500], signal_id),
            )
            self._conn.commit()

    def mark_skipped(self, signal_id: str, reason: str = "") -> None:
        """標記信號已略過（gate 條件不符）。"""
        with self._lock:
            self._conn.execute(
                "UPDATE signal_queue SET status='skipped', error=? WHERE id=?",
                (reason[:200], signal_id),
            )
            self._conn.commit()

    def cleanup_stale(self) -> int:
        """
        將超過 MAX_PENDING_AGE_DAYS 天的 pending 信號標記為 skipped。
        回傳清理筆數。
        """
        with self._lock:
            cur = self._conn.execute(
                f"""UPDATE signal_queue
                    SET status='skipped',
                        error='stale: exceeded {self.MAX_PENDING_AGE_DAYS} days'
                    WHERE status = 'pending'
                      AND created_at < datetime('now', '-{self.MAX_PENDING_AGE_DAYS} days')"""
            )
            self._conn.commit()
            cleaned = cur.rowcount
            if cleaned:
                logger.info("signal_queue: cleaned %d stale signals", cleaned)
            return cleaned

    # ── 讀取操作（不需加鎖）──────────────────────────────────────────────

    def stats(self) -> dict:
        """回傳各狀態的信號筆數。"""
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM signal_queue GROUP BY status"
        ).fetchall()
        result = {r["status"]: r["n"] for r in rows}
        result["total"] = sum(result.values())
        return result

    def pending_count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM signal_queue WHERE status='pending'"
        ).fetchone()[0]
