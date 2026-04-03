"""
core/brain/nudge_engine.py — 主動提醒引擎（v8.0）

## 問題

Project Brain 的第三個結構性邊界：被動記憶。
只有人問 `brain context`，系統才回應。
知識庫裡的踩坑，不會主動在「快要踩到」的時候提醒。

## 解法

NudgeEngine 分析當前任務（L1a progress 條目）、
比對 L3 的 Pitfall 節點，找出高度相關的潛在風險，
透過 `/v1/nudges` 端點讓 Agent 在任務開始前主動詢問。

## 使用方式

    engine = NudgeEngine(graph, session_store)
    nudges = engine.check("實作 Stripe 退款 API")

    # → [Nudge(title="Webhook 必須冪等", urgency="high", ...)]

    # 或透過 brain serve
    curl "http://localhost:7891/v1/nudges?task=實作+Stripe+退款"
    # → {"count": 2, "nudges": [...]}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class Nudge:
    """單一提醒項目"""
    node_id:      str
    title:        str
    content:      str
    urgency:      Literal["high", "medium", "low"]
    confidence:   float
    applies_when: str = ""
    is_pinned:    bool = False

    def to_dict(self) -> dict:
        return {
            "node_id":      self.node_id,
            "title":        self.title,
            "content":      self.content[:300],
            "urgency":      self.urgency,
            "confidence":   round(self.confidence, 3),
            "applies_when": self.applies_when,
            "is_pinned":    self.is_pinned,
        }


class NudgeEngine:
    """
    主動提醒引擎（v8.0）。

    檢索 L3 的 Pitfall 節點，按照優先度排序，
    過濾掉信心太低的條目，回傳潛在風險清單。

    優先度演算法：
    1. is_pinned=True → urgency="high"（最高優先）
    2. confidence > 0.7 → urgency="medium"
    3. confidence ≤ 0.7 → urgency="low"（仍然顯示，但排後）
    4. confidence < 0.4 → 排除（信心太低，不值得提醒）

    關鍵設計決策：
    - 不呼叫 LLM（即時性，0 費用）
    - 不依賴 L2（FalkorDB 可能不可用）
    - 只依賴 L3 SQLite（最穩定的層）
    """

    MIN_CONFIDENCE = 0.4  # 低於此值不提醒
    DEFAULT_TOP_K  = 5    # 預設最多回傳幾條

    def __init__(self, graph, session_store=None):
        """
        Args:
            graph:         KnowledgeGraph 實例
            session_store: SessionStore 實例（選填，用於讀取當前進度 context）
        """
        self.graph         = graph
        self.session_store = session_store

    def check(
        self,
        task:  str,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[Nudge]:
        """
        分析任務字串，回傳相關的潛在風險提醒。

        Args:
            task:  當前任務描述（關鍵字）
            top_k: 最多回傳幾條提醒

        Returns:
            list[Nudge]：按優先度排序（high > medium > low，同優先度按 confidence 排序）
        """
        nudges = self._from_l3_pitfalls(task, top_k * 2)   # 多搜一些再過濾

        # 補充 L1a 的 progress 上下文（如果有 session_store）
        if self.session_store:
            task_context = self._build_task_context()
            if task_context:
                extra = self._from_l3_pitfalls(task_context, top_k)
                seen  = {n.node_id for n in nudges}
                nudges.extend(n for n in extra if n.node_id not in seen)

        # 過濾低信心 + 排序 + 截取
        nudges = [n for n in nudges if n.confidence >= self.MIN_CONFIDENCE]
        nudges.sort(
            key=lambda n: (
                {"high": 0, "medium": 1, "low": 2}[n.urgency],
                -n.confidence,
                -int(n.is_pinned),
            )
        )
        return nudges[:top_k]

    def check_on_commit(self, commit_hash: str, files_changed: list[str]) -> list[Nudge]:
        """
        git commit 後的主動風險檢查。

        分析本次 commit 涉及的檔案，找出可能相關的踩坑。
        由 BrainEventBus 的 git.commit handler 呼叫。

        Args:
            commit_hash:   commit hash
            files_changed: 本次 commit 修改的檔案列表

        Returns:
            list[Nudge]：高優先度的潛在風險（urgency="high" 才回傳）
        """
        # 從檔名提取關鍵字
        keywords = set()
        for f in files_changed:
            parts = f.replace("/", " ").replace("_", " ").replace("-", " ").split()
            keywords.update(p for p in parts if len(p) > 3)

        if not keywords:
            return []

        query = " ".join(list(keywords)[:5])
        nudges = self.check(query, top_k=10)
        return [n for n in nudges if n.urgency == "high"]

    # ── 內部實作 ──────────────────────────────────────────────────────

    def _from_l3_pitfalls(self, query: str, top_k: int) -> list[Nudge]:
        """從 L3 搜尋相關 Pitfall 節點"""
        try:
            results = self.graph.search_nodes(
                query, node_type="Pitfall", limit=top_k
            )
        except Exception as e:
            logger.warning("NudgeEngine L3 search failed: %s", e)
            return []

        nudges = []
        now    = datetime.now(timezone.utc)
        for r in results:
            # BUG-02 fix ①: skip deprecated nodes
            if r.get("is_deprecated"):
                continue
            # BUG-02 fix ②: skip nodes whose valid_until has passed
            valid_until = r.get("valid_until")
            if valid_until:
                try:
                    vu = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
                    if vu.tzinfo is None:
                        vu = vu.replace(tzinfo=timezone.utc)
                    if vu < now:
                        continue
                except Exception:
                    pass  # malformed date — include the nudge to be safe
            # BUG-02 fix ③: use explicit None-check instead of `or` so that
            # confidence=0.0 is not silently promoted to 0.7.
            raw_conf  = r.get("confidence")
            conf      = float(raw_conf) if raw_conf is not None else 0.7
            is_pinned = bool(r.get("is_pinned") or 0)
            urgency   = (
                "high"   if is_pinned or conf > 0.85 else
                "medium" if conf > 0.65 else
                "low"
            )
            nudges.append(Nudge(
                node_id      = r["id"],
                title        = r.get("title", ""),
                content      = (r.get("content") or ""),
                urgency      = urgency,
                confidence   = conf,
                applies_when = r.get("applicability_condition", ""),
                is_pinned    = is_pinned,
            ))
        return nudges

    def _build_task_context(self) -> str:
        """從 L1a 工作記憶提取當前任務上下文"""
        if not self.session_store:
            return ""
        try:
            progress = self.session_store.list_all(category="progress")
            recent   = sorted(progress, key=lambda e: e.created_at, reverse=True)[:3]
            return " ".join(e.value[:100] for e in recent)
        except Exception:
            return ""
