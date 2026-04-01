"""
core/brain/spaced_repetition.py — 間隔重複衰減引擎（v8.1）

## 研究背景

傳統 DecayEngine 的衰減是單向線性的：
  confidence(t) = confidence(0) × e^(-λt)

問題：使用次數完全不影響衰減速度。
一條被查詢 100 次的關鍵規則，和從未被查詢的噪聲節點，以同樣速度衰減。

## Anki 啟發的解法

Anki 的 SM-2 算法：
  interval_next = interval × ease_factor
  ease_factor   = max(1.3, ease + 0.1 - (5 - quality) × (0.08 + (5 - quality) × 0.02))

Project Brain 的變體：
  confidence_next = confidence × (1 + recall_bonus - decay_penalty)
  recall_bonus    = min(0.05, 0.01 × access_count)   # 每次訪問 +1%，上限 +5%
  decay_penalty   = base_decay × (1 - recall_bonus)  # 常被訪問的節點衰減更慢

效果：
  - 常被查詢的節點：衰減速度最多降低 50%
  - 從未查詢的節點：正常速度衰減
  - 被釘選的節點：完全免疫衰減（繼承自 DecayEngine）

## 使用方式

    from project_brain.spaced_repetition import SpacedRepetitionEngine
    engine = SpacedRepetitionEngine(graph)

    # 記錄一次訪問（brain context 查詢時呼叫）
    engine.record_access("node_id_123")

    # 執行 SR 感知的衰減（取代 DecayEngine）
    engine.decay_cycle()
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AccessRecord:
    """節點訪問記錄"""
    node_id:      str
    access_count: int
    last_access:  str   # ISO 8601
    ease_factor:  float = 2.5  # SM-2 初始值


class SpacedRepetitionEngine:
    """
    間隔重複衰減引擎（v8.1）。

    增強 DecayEngine：使用次數影響衰減速度。
    常被訪問的節點自動強化，長期不用的節點加速消退。

    SQLite schema：
      sr_access（node_id, access_count, last_access_ts, ease_factor）
    """

    BASE_DECAY     = 0.03   # 每個衰減週期的基礎衰減率（3%）
    RECALL_BONUS   = 0.01   # 每次訪問提升的衰減抵消（1%）
    MAX_BONUS      = 0.05   # 最大抵消（5%，相當於 100+ 次訪問後衰減減半）
    MIN_CONFIDENCE = 0.05   # 最低信心（防止永遠為 0）

    def __init__(self, graph):
        """
        Args:
            graph: KnowledgeGraph 實例
        """
        self.graph  = graph
        self._db    = graph.db_path.parent / "sr_access.db"
        self._setup_db()

    # ── 公開 API ──────────────────────────────────────────────────────────

    def record_access(self, node_id: str) -> None:
        """
        記錄節點被訪問一次（v9.0：同時更新主表 access_count）。

        雙寫策略（向後相容）：
        - 主表 nodes.access_count++（新方式，合入主表）
        - sr_access 表（舊方式，保留以免破壞現有查詢）
        """
        # 更新主表
        self.graph.record_access(node_id)
        # 同時更新 sr_access（向後相容）
        conn = self._conn()
        conn.execute("""
            INSERT INTO sr_access(node_id, access_count, last_access_ts, ease_factor)
            VALUES(?, 1, datetime('now'), 2.5)
            ON CONFLICT(node_id) DO UPDATE SET
                access_count   = access_count + 1,
                last_access_ts = datetime('now')
        """, (node_id,))
        conn.commit()

    def get_access_record(self, node_id: str) -> Optional[AccessRecord]:
        """取得節點的訪問記錄"""
        row = self._conn().execute(
            "SELECT * FROM sr_access WHERE node_id=?", (node_id,)
        ).fetchone()
        if not row:
            return None
        return AccessRecord(
            node_id      = row["node_id"],
            access_count = row["access_count"],
            last_access  = row["last_access_ts"],
            ease_factor  = row["ease_factor"],
        )

    def decay_cycle(self, dry_run: bool = False) -> dict:
        """
        執行一次 SR 感知的衰減週期。

        對比傳統 DecayEngine：
        - is_pinned=True 的節點跳過（繼承）
        - 訪問次數高的節點衰減更慢
        - 記錄每次衰減到日誌

        Args:
            dry_run: True=只計算，不寫入

        Returns:
            dict: {decayed: int, boosted: int, skipped_pinned: int, avg_bonus: float}
        """
        nodes = self.graph._conn.execute("""
            SELECT id, confidence, is_pinned, emotional_weight
            FROM nodes
            WHERE type NOT IN ('Component', 'Directory')
        """).fetchall()

        stats = {"decayed": 0, "boosted": 0, "skipped_pinned": 0, "avg_bonus": 0.0}
        bonuses = []

        for _row in nodes:
            node       = dict(_row)  # sqlite3.Row → dict（支援 .get()）
            nid        = node["id"]
            confidence = float(node.get("confidence") or 0.8)
            is_pinned  = bool(node.get("is_pinned") or 0)

            if is_pinned:
                stats["skipped_pinned"] += 1
                continue

            # 計算 recall bonus
            rec = self.get_access_record(nid)
            access_count = rec.access_count if rec else 0
            recall_bonus = min(self.MAX_BONUS, self.RECALL_BONUS * access_count)
            bonuses.append(recall_bonus)

            # SR 衰減公式（B-1 優化：emotional_weight 接入）
            # emotional_weight=1.0（極痛苦）→ decay_rate 降低 30%，記憶更持久
            ew         = float((dict(node) if hasattr(node, "keys") else node).get("emotional_weight") or 0.5)
            ew_factor  = 1.0 - (ew - 0.5) * 0.3  # ew=0.5→1.0, ew=1.0→0.85, ew=0.0→1.15
            ew_factor  = max(0.5, min(1.2, ew_factor))  # 限制在合理範圍
            decay_rate = self.BASE_DECAY * (1.0 - recall_bonus / self.MAX_BONUS * 0.5) * ew_factor
            new_conf   = max(self.MIN_CONFIDENCE, confidence * (1.0 - decay_rate))

            if recall_bonus > 0:
                stats["boosted"] += 1
            else:
                stats["decayed"] += 1

            if not dry_run:
                self.graph._conn.execute(
                    "UPDATE nodes SET confidence=? WHERE id=?",
                    (round(new_conf, 4), nid)
                )

        if not dry_run:
            self.graph._conn.commit()

        stats["avg_bonus"] = round(sum(bonuses) / len(bonuses), 4) if bonuses else 0.0
        logger.info(
            "SR decay: decayed=%d boosted=%d pinned=%d avg_bonus=%.3f",
            stats["decayed"], stats["boosted"], stats["skipped_pinned"], stats["avg_bonus"]
        )
        return stats

    def top_accessed(self, limit: int = 10) -> list[dict]:
        """回傳訪問次數最多的節點（診斷用）"""
        rows = self._conn().execute("""
            SELECT s.node_id, s.access_count, s.last_access_ts, s.ease_factor,
                   n.title, n.confidence
            FROM sr_access s
            LEFT JOIN nodes n ON s.node_id = n.id
            ORDER BY s.access_count DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        """回傳整體 SR 統計"""
        row = self._conn().execute("""
            SELECT COUNT(*) as tracked,
                   SUM(access_count) as total_accesses,
                   MAX(access_count) as max_accesses,
                   AVG(access_count) as avg_accesses
            FROM sr_access
        """).fetchone()
        return dict(row) if row else {}

    # ── 內部 ──────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self._db), check_same_thread=False, timeout=5)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        return c

    def _setup_db(self) -> None:
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sr_access (
                node_id        TEXT PRIMARY KEY,
                access_count   INTEGER NOT NULL DEFAULT 0,
                last_access_ts TEXT NOT NULL DEFAULT (datetime('now')),
                ease_factor    REAL NOT NULL DEFAULT 2.5
            );
            CREATE INDEX IF NOT EXISTS idx_sr_access ON sr_access(access_count DESC);
        """)
        conn.commit()
