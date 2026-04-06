"""
project_brain/pipeline.py — Auto Knowledge Pipeline: Layer 1, 2 & 4

Phase 1 實作：
  Layer 1/2 — Signal / SignalKind / SignalQueue（SQLite 持久化）
  Layer 4   — NodeSpec / KnowledgeDecision / ExecutionResult / KnowledgeExecutor

架構原則（設計文件 docs/AUTO_KNOWLEDGE_PIPELINE.md）：
- 信號收集與 LLM 分析嚴格非同步，不阻塞主流程
- SQLite 持久化，進程重啟不遺失信號
- CAS（Compare-And-Swap）確保多實例競爭安全
- 去重索引防止同一事件重複分析
- LLM 只輸出 KnowledgeDecision；Executor 確定性執行，不含業務判斷
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
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from project_brain.brain_db import BrainDB

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

    # ── Phase 3+（待數據驗證後決定）───────────────────────���──────────────
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


# ── SignalQueue ───────────────────────────────────────────────────────��─────

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

    # ── 寫入操作 ─────────────────────────────────────────────────────��─

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

    # ── 讀取操作（不需加鎖）─────────────────────────────────���──────────

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


# ── Layer 4 資料結構 ────────────────────────────────────────────────────────

_VALID_KINDS = frozenset({"Note", "Decision", "Pitfall", "Rule", "ADR", "Component"})


@dataclass
class NodeSpec:
    """LLM 指定要新增的知識節點規格。"""
    title:       str
    content:     str
    kind:        str   = "Note"   # Note | Decision | Pitfall | Rule | ADR | Component
    confidence:  float = 0.6      # auto pipeline 上限 0.85
    tags:        list  = field(default_factory=list)
    description: str   = ""


@dataclass
class KnowledgeDecision:
    """
    Phase 1 精簡版：只有 add / skip 兩種 action。
    由 LLMJudgmentEngine 產生，KnowledgeExecutor 消費。
    """
    action:     str            # "add" | "skip"
    reason:     str            # LLM 的決策理由（可審計）
    signal_id:  str            # 來源信號 ID
    confidence: float = 0.8   # LLM 對自身判斷的信心
    node:       Optional[NodeSpec] = None   # action=="add" 時必填
    llm_model:  str   = ""


@dataclass
class ExecutionResult:
    ok:      bool
    action:  str  = ""
    node_id: str  = ""
    skipped: bool = False
    error:   str  = ""


# ── KnowledgeExecutor ─────────────────────────────────────────────────────

class KnowledgeExecutor:
    """
    Layer 4 — 確定性執行器（Phase 1）。

    接收 KnowledgeDecision，執行對應的 DB 操作：
      add  → BrainDB.add_node() + pipeline_metrics 記錄
      skip → pipeline_metrics 記錄（不寫節點）

    設計原則：
    - 不含任何業務判斷邏輯
    - 冪等：同一 signal_id 不重複執行
    - 所有 add_node 操作由 BrainDB 的 _write_guard() 保護
    """

    MAX_AUTO_CONFIDENCE = 0.85  # 自動提取知識的信心上限

    def __init__(self, brain_db: BrainDB) -> None:
        self._db = brain_db

    # ── 主入口 ────────────────────────────────────────────────────────────

    def run(self, decision: KnowledgeDecision,
            signal: Optional[Signal] = None) -> ExecutionResult:
        """執行一個 KnowledgeDecision。"""
        # 冪等檢查：同 signal_id + action='add' 已處理過 → 直接回傳
        if decision.signal_id and decision.action == "add":
            existing = self._db.conn.execute(
                "SELECT node_id FROM pipeline_metrics"
                " WHERE signal_id=? AND action='add'",
                (decision.signal_id,),
            ).fetchone()
            if existing:
                logger.debug(
                    "executor: idempotent skip  signal_id=%s node_id=%s",
                    decision.signal_id, existing[0]
                )
                return ExecutionResult(
                    ok=True, action="add", node_id=existing[0], skipped=True
                )

        dispatch = {
            "add":  self._do_add,
            "skip": self._do_skip,
        }
        handler = dispatch.get(decision.action)
        if handler is None:
            logger.warning(
                "executor: unsupported action '%s', treating as skip", decision.action
            )
            return self._do_skip(
                KnowledgeDecision(
                    action="skip",
                    reason=f"unsupported action: {decision.action}",
                    signal_id=decision.signal_id,
                ),
                signal,
            )
        return handler(decision, signal)

    # ── 操作實作 ─────────────────────────────────────────────────────────

    def _do_add(self, d: KnowledgeDecision,
                signal: Optional[Signal]) -> ExecutionResult:
        if not d.node:
            logger.warning("executor: ADD action missing node spec  signal_id=%s", d.signal_id)
            return ExecutionResult(ok=False, action="add", error="node spec missing")

        node_id   = f"auto-{uuid.uuid4().hex[:12]}"
        node_type = d.node.kind if d.node.kind in _VALID_KINDS else "Note"

        try:
            self._db.add_node(
                node_id     = node_id,
                node_type   = node_type,
                title       = d.node.title,
                content     = d.node.content,
                tags        = d.node.tags,
                confidence  = d.node.confidence,
                description = d.node.description,
                meta        = {
                    "source":    "auto_pipeline",
                    "signal_id": signal.id if signal else d.signal_id,
                    "llm_model": d.llm_model,
                    "reason":    d.reason[:200],
                },
            )
        except Exception as e:
            logger.error("executor: add_node failed: %s", e)
            return ExecutionResult(ok=False, action="add", error=str(e))

        self._record_metric(node_id, d, signal, "add")
        logger.info(
            "executor: ADD  node_id=%s kind=%s title=%.60s",
            node_id, node_type, d.node.title
        )
        return ExecutionResult(ok=True, action="add", node_id=node_id)

    def _do_skip(self, d: KnowledgeDecision,
                 signal: Optional[Signal]) -> ExecutionResult:
        self._record_metric("", d, signal, "skip")
        logger.debug("executor: SKIP  reason=%.80s", d.reason)
        return ExecutionResult(ok=True, action="skip", skipped=True)

    # ── 輔助 ─────────────────────────────────────────────────────────────

    def _record_metric(self, node_id: str, d: KnowledgeDecision,
                       signal: Optional[Signal], action: str) -> None:
        """寫入 pipeline_metrics，失敗只 log 不拋例外。"""
        try:
            sid = d.signal_id or (signal.id if signal else "")
            self._db.conn.execute(
                """INSERT OR IGNORE INTO pipeline_metrics
                   (node_id, signal_id, action, llm_model)
                   VALUES (?, ?, ?, ?)""",
                (node_id, sid, action, d.llm_model or ""),
            )
            self._db.conn.commit()
        except Exception as e:
            logger.debug("executor: pipeline_metrics write failed: %s", e)

    # ── 驗證（LLM 輸出清洗）─────────────────────────────────────────────

    @classmethod
    def validate(cls, raw: dict) -> KnowledgeDecision:
        """
        從 LLM 原始輸出 dict 建立合法的 KnowledgeDecision。

        保證：
        - action 一定是 "add" 或 "skip"
        - confidence 不超過 MAX_AUTO_CONFIDENCE（0.85）
        - node spec 不合法時降級為 SKIP
        - 任何 exception 都安全降級為 SKIP
        """
        try:
            action = str(raw.get("action", "skip")).lower().strip()
            if action not in ("add", "skip"):
                logger.debug("executor: unknown action '%s' → skip", action)
                action = "skip"

            node = None
            if action == "add":
                node_data = raw.get("node") or {}
                if not isinstance(node_data, dict) or not node_data.get("title", "").strip():
                    return KnowledgeDecision(
                        action="skip",
                        reason=f"invalid or missing node spec (raw action=add)",
                        signal_id=str(raw.get("signal_id", "")),
                        llm_model=str(raw.get("llm_model", "")),
                    )
                raw_conf = float(node_data.get("confidence", 0.6))
                node = NodeSpec(
                    title       = str(node_data.get("title", ""))[:200].strip(),
                    content     = str(node_data.get("content", ""))[:2000],
                    kind        = str(node_data.get("kind", "Note")),
                    confidence  = min(raw_conf, cls.MAX_AUTO_CONFIDENCE),
                    tags        = list(node_data.get("tags", [])),
                    description = str(node_data.get("description", ""))[:300],
                )

            return KnowledgeDecision(
                action     = action,
                reason     = str(raw.get("reason", ""))[:500],
                signal_id  = str(raw.get("signal_id", "")),
                confidence = float(raw.get("confidence", 0.8)),
                node       = node,
                llm_model  = str(raw.get("llm_model", "")),
            )

        except Exception as e:
            logger.warning("executor: validate() exception: %s", e)
            return KnowledgeDecision(
                action    = "skip",
                reason    = f"validation error: {e}",
                signal_id = raw.get("signal_id", "") if isinstance(raw, dict) else "",
                llm_model = "",
            )
