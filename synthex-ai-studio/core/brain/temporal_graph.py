"""
TemporalGraph — 時序知識圖譜 (v1.1，Graphiti 啟發設計)

核心概念：知識有時效性。三個月前的架構決策，和昨天的緊急修復，
對目前工作的參考價值是不同的。TemporalGraph 在現有 KnowledgeGraph
的基礎上加入時序推理能力。

設計原則（Graphiti 啟發）：
  1. 每個邊（關係）都有 valid_from / valid_until 時間戳
  2. 信心分數（confidence）隨時間衰減
  3. 可以問「當時的架構決策是什麼」，也可以問「現在的決策是什麼」
  4. 矛盾的知識不刪除，而是標記為「已被取代」並保留歷史

安全考量：
  - 時間戳只接受 ISO 8601 格式，防止注入
  - 衰減參數限制在合理範圍，防止數值溢出
  - 所有 SQL 使用參數化查詢

記憶體管理：
  - 歷史快照按需讀取，不全量載入
  - 定期清理 confidence < 0.01 的過期邊
"""

from __future__ import annotations

import re
import math
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .graph import KnowledgeGraph

logger = logging.getLogger(__name__)

# ── 安全常數 ────────────────────────────────────────────────────
ISO_PATTERN     = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}')
DECAY_MIN       = 0.001   # 衰減率下限
DECAY_MAX       = 0.999   # 衰減率上限
CONFIDENCE_FLOOR= 0.01    # 低於此值視為過期


def _validate_iso(ts: str) -> str:
    """驗證並正規化 ISO 8601 時間戳，防止注入"""
    if not ts:
        return datetime.now(timezone.utc).isoformat()
    ts = str(ts)[:30]   # 截斷超長字串
    if not ISO_PATTERN.match(ts):
        raise ValueError(f"無效的時間戳格式：{ts!r}，需要 ISO 8601")
    return ts


class TemporalGraph:
    """
    時序知識圖譜：在 KnowledgeGraph 基礎上加入時間維度。

    新增的 SQL Schema（擴充 .brain/knowledge_graph.db）：
      temporal_edges  — 帶時效的有向邊
      knowledge_snapshots — 特定時間點的知識快照索引
    """

    # 衰減模型：confidence(t) = confidence₀ × e^(-λ × days)
    # λ 依邊類型不同
    DECAY_RATES: dict[str, float] = {
        "DEPENDS_ON":   0.005,  # 依賴關係衰減慢（架構相對穩定）
        "CAUSED_BY":    0.001,  # 因果關係幾乎不衰減（歷史教訓）
        "SOLVED_BY":    0.001,  # 解法記錄不衰減
        "APPLIES_TO":   0.003,  # 規則適用性緩慢衰減
        "CONTRIBUTED_BY":0.002, # 貢獻者記錄穩定
        "SUPERSEDES":   0.000,  # 取代關係永遠有效
        "REFERENCES":   0.010,  # 引用關係衰減較快
        "_default":     0.005,
    }

    def __init__(self, graph: KnowledgeGraph):
        self.graph = graph
        self._conn = graph._conn   # 共用同一個 SQLite 連線
        self._setup_temporal_schema()

    def _setup_temporal_schema(self) -> None:
        """建立時序擴充表（冪等）"""
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS temporal_edges (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id    TEXT    NOT NULL,
            relation     TEXT    NOT NULL,
            target_id    TEXT    NOT NULL,
            confidence   REAL    NOT NULL DEFAULT 1.0,
            valid_from   TEXT    NOT NULL,
            valid_until  TEXT,
            decay_rate   REAL    NOT NULL DEFAULT 0.005,
            is_active    INTEGER NOT NULL DEFAULT 1,
            superseded_by INTEGER REFERENCES temporal_edges(id),
            note         TEXT,
            created_at   TEXT    DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_temporal_source
            ON temporal_edges(source_id, is_active);
        CREATE INDEX IF NOT EXISTS idx_temporal_target
            ON temporal_edges(target_id, is_active);
        CREATE INDEX IF NOT EXISTS idx_temporal_active
            ON temporal_edges(is_active, valid_from);

        CREATE TABLE IF NOT EXISTS knowledge_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_at  TEXT    NOT NULL,
            node_id      TEXT    NOT NULL,
            confidence   REAL    NOT NULL,
            context      TEXT,
            created_at   TEXT    DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_snapshot_time
            ON knowledge_snapshots(snapshot_at, node_id);
        """)
        self._conn.commit()

    # ── 邊操作 ──────────────────────────────────────────────────────

    def add_temporal_edge(
        self,
        source_id:  str,
        relation:   str,
        target_id:  str,
        confidence: float = 1.0,
        valid_from: str   = "",
        valid_until:str   = "",
        note:       str   = "",
    ) -> int:
        """
        加入一條帶時效的邊。
        若已存在相同的 source→relation→target 且 is_active=1，
        先將舊邊標記為 superseded，再插入新邊（保留歷史）。
        """
        # 輸入驗證
        confidence  = max(0.0, min(1.0, float(confidence)))
        valid_from  = _validate_iso(valid_from)
        valid_until = _validate_iso(valid_until) if valid_until else None
        decay_rate  = self.DECAY_RATES.get(relation, self.DECAY_RATES["_default"])
        decay_rate  = max(DECAY_MIN, min(DECAY_MAX, decay_rate))

        # 查詢是否有既存的活躍邊
        existing = self._conn.execute("""
            SELECT id FROM temporal_edges
            WHERE source_id=? AND relation=? AND target_id=? AND is_active=1
            LIMIT 1
        """, (source_id, relation, target_id)).fetchone()

        with self._conn:
            # 插入新邊
            cur = self._conn.execute("""
                INSERT INTO temporal_edges
                    (source_id, relation, target_id, confidence,
                     valid_from, valid_until, decay_rate, is_active, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """, (source_id, relation, target_id, confidence,
                  valid_from, valid_until, decay_rate, note[:500] if note else ""))
            new_id = cur.lastrowid

            # 標記舊邊為 superseded
            if existing:
                self._conn.execute("""
                    UPDATE temporal_edges
                    SET is_active=0, superseded_by=?
                    WHERE id=?
                """, (new_id, existing["id"]))

        return new_id

    def get_current_edges(
        self,
        source_id:  str,
        relation:   str | None = None,
        min_confidence: float  = 0.2,
    ) -> list[dict]:
        """
        取得目前（is_active=1 且 confidence 已衰減後 >= min_confidence）的邊。
        confidence 在查詢時即時計算，不需要預計算。
        """
        params: list = [source_id, min_confidence]
        rel_filter = ""
        if relation:
            rel_filter = " AND te.relation = ?"
            params.append(relation)

        rows = self._conn.execute(f"""
            SELECT
                te.id,
                te.source_id,
                te.relation,
                te.target_id,
                te.note,
                te.valid_from,
                te.valid_until,
                te.decay_rate,
                te.confidence AS initial_confidence,
                /* 時序衰減計算：conf₀ × e^(-λ × days_elapsed) */
                te.confidence * exp(
                    -te.decay_rate *
                    CAST(
                        (julianday('now') - julianday(te.valid_from))
                    AS REAL)
                ) AS current_confidence,
                n.title AS target_title,
                n.type  AS target_type
            FROM temporal_edges te
            LEFT JOIN nodes n ON n.id = te.target_id
            WHERE te.source_id = ?
              AND te.is_active  = 1
              {rel_filter}
            HAVING current_confidence >= ?
            ORDER BY current_confidence DESC
        """, params).fetchall()

        return [dict(r) for r in rows]

    def get_edge_history(self, source_id: str, target_id: str) -> list[dict]:
        """取得兩個節點間的完整歷史（包含已 superseded 的邊）"""
        rows = self._conn.execute("""
            SELECT te.*, n.title AS target_title
            FROM temporal_edges te
            LEFT JOIN nodes n ON n.id = te.target_id
            WHERE te.source_id = ? AND te.target_id = ?
            ORDER BY te.created_at DESC
        """, (source_id, target_id)).fetchall()
        return [dict(r) for r in rows]

    # ── 時序查詢 ────────────────────────────────────────────────────

    def at_time(self, node_id: str, timestamp: str) -> list[dict]:
        """
        查詢特定時間點，某個節點的知識狀態。
        回答：「三個月前，這個組件的依賴關係是什麼？」
        """
        ts = _validate_iso(timestamp)
        rows = self._conn.execute("""
            SELECT te.*, n.title AS target_title, n.type AS target_type
            FROM temporal_edges te
            LEFT JOIN nodes n ON n.id = te.target_id
            WHERE te.source_id = ?
              AND te.valid_from <= ?
              AND (te.valid_until IS NULL OR te.valid_until >= ?)
            ORDER BY te.confidence DESC
        """, (node_id, ts, ts)).fetchall()
        return [dict(r) for r in rows]

    def recent_changes(self, days: int = 30) -> list[dict]:
        """取得最近 N 天內發生變化的邊（新增或取代）"""
        days = max(1, min(365, int(days)))  # 安全範圍
        rows = self._conn.execute("""
            SELECT te.source_id, te.relation, te.target_id,
                   te.confidence, te.valid_from, te.is_active,
                   te.note,
                   ns.title AS source_title,
                   nt.title AS target_title
            FROM temporal_edges te
            LEFT JOIN nodes ns ON ns.id = te.source_id
            LEFT JOIN nodes nt ON nt.id = te.target_id
            WHERE te.created_at >= datetime('now', ? || ' days')
            ORDER BY te.created_at DESC
            LIMIT 50
        """, (f"-{days}",)).fetchall()
        return [dict(r) for r in rows]

    def confidence_timeline(self, source_id: str, target_id: str) -> list[dict]:
        """
        計算兩節點間信心值的時序變化曲線。
        用於視覺化知識的「老化」過程。
        """
        edges = self.get_edge_history(source_id, target_id)
        timeline = []
        for edge in edges:
            try:
                vf         = datetime.fromisoformat(edge["valid_from"])
                now        = datetime.now(timezone.utc)
                days       = max(0, (now.date() - vf.date()).days)
                initial    = float(edge["initial_confidence"])
                decay      = float(edge["decay_rate"])
                current    = initial * math.exp(-decay * days)
                timeline.append({
                    "edge_id":     edge["id"],
                    "relation":    edge["relation"],
                    "valid_from":  edge["valid_from"],
                    "days_elapsed":days,
                    "initial_confidence": round(initial, 4),
                    "current_confidence": round(max(0.0, current), 4),
                    "is_active":   bool(edge["is_active"]),
                })
            except (ValueError, KeyError):
                continue
        return sorted(timeline, key=lambda x: x["valid_from"])

    # ── 維護 ────────────────────────────────────────────────────────

    def prune_expired(self) -> int:
        """
        清理 confidence 已衰減至 CONFIDENCE_FLOOR 以下的邊。
        回傳清理筆數。在 prune 前先記錄 snapshot（保留可審計性）。
        """
        expired = self._conn.execute(f"""
            SELECT id, source_id, relation, target_id, confidence, valid_from, decay_rate
            FROM temporal_edges
            WHERE is_active = 1
              AND confidence * exp(
                  -decay_rate *
                  CAST((julianday('now') - julianday(valid_from)) AS REAL)
              ) < {CONFIDENCE_FLOOR}
        """).fetchall()

        if not expired:
            return 0

        with self._conn:
            # 記錄快照
            for edge in expired:
                self._conn.execute("""
                    INSERT INTO knowledge_snapshots
                        (snapshot_at, node_id, confidence, context)
                    VALUES (datetime('now'), ?, ?, ?)
                """, (edge["source_id"],
                      CONFIDENCE_FLOOR,
                      f"expired edge {edge['id']}: {edge['relation']}→{edge['target_id']}"))

            # 標記為非活躍（不刪除，保留歷史）
            ids = [e["id"] for e in expired]
            self._conn.execute(
                f"UPDATE temporal_edges SET is_active=0 WHERE id IN ({','.join('?'*len(ids))})",
                ids,
            )

        logger.info("TemporalGraph.prune_expired：清理 %d 條過期邊", len(expired))
        return len(expired)

    def stats(self) -> dict:
        rows = self._conn.execute("""
            SELECT
                COUNT(*)          AS total_edges,
                SUM(is_active)    AS active_edges,
                COUNT(DISTINCT source_id) AS unique_sources,
                MIN(valid_from)   AS oldest_edge,
                MAX(valid_from)   AS newest_edge
            FROM temporal_edges
        """).fetchone()
        return dict(rows) if rows else {}
