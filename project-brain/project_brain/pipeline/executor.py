"""
project_brain/pipeline/executor.py — Auto Knowledge Pipeline Layer 4

Layer 4 — 確定性執行器（Phase 1）。

接收 Layer 3 產出的 KnowledgeDecision，執行對應的 DB 操作：
  add  → BrainDB.add_node() + pipeline_metrics 記錄
  skip → pipeline_metrics 記錄（不寫節點）

設計原則（docs/AUTO_KNOWLEDGE_PIPELINE.md）：
- 不含任何業務判斷邏輯
- 冪等：同一 signal_id 不重複執行
- LLM 只輸出 KnowledgeDecision；Executor 確定性執行
- 所有 add_node 操作由 BrainDB 的 _write_guard() 保護
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from project_brain.pipeline.signal import Signal

if TYPE_CHECKING:
    from project_brain.brain_db import BrainDB

logger = logging.getLogger(__name__)


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

    def __init__(self, brain_db: "BrainDB") -> None:
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
