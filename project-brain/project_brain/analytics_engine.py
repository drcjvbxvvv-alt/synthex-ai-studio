"""
project_brain/analytics_engine.py — ROI 指標計算引擎（PH1-05）

整合 brain_db.py 的分散分析功能，新增 ROI 可量化指標：
- query_hit_rate:        查詢命中率（有結果 vs 無結果）
- useful_knowledge_rate: 知識有效率（正向 feedback / 全部 feedback）
- pitfall_avoidance_score: Pitfall 節點查閱率（被查越多 = 越有保護作用）
- knowledge_roi_score:   綜合 ROI 分數 [0, 1]

設計原則：
- 不依賴 LLM
- 不直接import BrainDB（避免循環依賴），接受 conn 或 db 物件
- 所有計算靜默降級：任何欄位缺失都返回 None，不 crash
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class AnalyticsEngine:
    """Compute ROI and usage metrics from a brain.db connection."""

    def __init__(self, conn: sqlite3.Connection):
        """
        Args:
            conn: An open sqlite3.Connection to brain.db (or knowledge_graph.db).
                  The caller is responsible for connection lifecycle.
        """
        self._conn = conn

    # ── helpers ──────────────────────────────────────────────────────────────

    def _scalar(self, sql: str, params: tuple = ()) -> Optional[int | float]:
        """Execute a scalar query; return None on any error."""
        try:
            row = self._conn.execute(sql, params).fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        """Execute a query returning rows as dicts."""
        try:
            cur = self._conn.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            return []

    # ── ROI metrics ──────────────────────────────────────────────────────────

    def query_hit_rate(self) -> Optional[float]:
        """Ratio of trace queries that returned ≥1 result.

        Traces table records every search; result_count column counts hits.
        If the column doesn't exist (older schema), returns None.
        """
        total = self._scalar("SELECT COUNT(*) FROM traces")
        if not total:
            return None
        hits = self._scalar(
            "SELECT COUNT(*) FROM traces WHERE result_count > 0"
        )
        if hits is None:
            # Fallback: if result_count column missing, estimate from latency
            # (fast queries with latency_ms < 5 likely returned nothing)
            hits = self._scalar(
                "SELECT COUNT(*) FROM traces WHERE latency_ms >= 5"
            )
        if hits is None:
            return None
        return round(hits / total, 3)

    def useful_knowledge_rate(self) -> Optional[float]:
        """Fraction of feedback-bearing nodes rated as useful.

        Reads from events table: event_type='knowledge_outcome',
        payload JSON: {"node_id": ..., "was_useful": true/false}.
        """
        try:
            rows = self._rows(
                "SELECT payload FROM events WHERE event_type='knowledge_outcome'"
            )
        except Exception:
            return None

        if not rows:
            return None

        import json
        total = useful = 0
        for r in rows:
            try:
                p = json.loads(r.get("payload") or "{}")
                total += 1
                if p.get("was_useful"):
                    useful += 1
            except Exception as _e:
                logger.debug("feedback payload parse failed", exc_info=True)

        return round(useful / total, 3) if total else None

    def pitfall_avoidance_score(self) -> Optional[float]:
        """Fraction of Pitfall nodes that have been accessed at least once.

        A Pitfall that's never been read hasn't protected anyone. High access
        rate → the knowledge base is actively preventing recurrence.
        """
        total_pitfalls = self._scalar(
            "SELECT COUNT(*) FROM nodes WHERE type='Pitfall' OR kind='Pitfall'"
        )
        if not total_pitfalls:
            return None
        accessed = self._scalar(
            "SELECT COUNT(*) FROM nodes"
            " WHERE (type='Pitfall' OR kind='Pitfall') AND access_count > 0"
        )
        if accessed is None:
            return None
        return round(accessed / total_pitfalls, 3)

    def knowledge_roi_score(self) -> float:
        """Composite ROI score [0.0, 1.0].

        Weighted average of the three metrics above.
        Missing metrics are excluded from the average (no penalty for sparse data).
        """
        weights = {
            "hit_rate":         0.40,
            "useful_rate":      0.40,
            "pitfall_avoidance": 0.20,
        }
        values = {
            "hit_rate":         self.query_hit_rate(),
            "useful_rate":      self.useful_knowledge_rate(),
            "pitfall_avoidance": self.pitfall_avoidance_score(),
        }
        total_w = sum(w for k, w in weights.items() if values[k] is not None)
        if not total_w:
            return 0.0
        score = sum(
            values[k] * w
            for k, w in weights.items()
            if values[k] is not None
        )
        return round(score / total_w, 3)

    # ── full report ───────────────────────────────────────────────────────────

    def roi_metrics(self) -> dict:
        """Return all ROI metrics as a single dict."""
        return {
            "query_hit_rate":          self.query_hit_rate(),
            "useful_knowledge_rate":   self.useful_knowledge_rate(),
            "pitfall_avoidance_score": self.pitfall_avoidance_score(),
            "knowledge_roi_score":     self.knowledge_roi_score(),
        }

    def generate_report(self, period_days: int = 7) -> dict:
        """Full periodic report combining ROI + usage + growth metrics.

        Args:
            period_days: Look-back window for recent activity (default: 7 days).

        Returns:
            Dict with sections: roi, usage, growth, top_pitfalls, summary.
        """
        since = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()

        # ── ROI ──
        roi = self.roi_metrics()

        # ── usage ──
        total_nodes   = self._scalar("SELECT COUNT(*) FROM nodes") or 0
        total_queries = self._scalar("SELECT COUNT(*) FROM traces") or 0
        recent_adds   = self._scalar(
            "SELECT COUNT(*) FROM nodes WHERE created_at >= ?", (since,)
        ) or 0
        recent_queries = self._scalar(
            "SELECT COUNT(*) FROM traces WHERE created_at >= ?", (since,)
        ) or 0

        by_type = {
            r["t"]: r["c"]
            for r in self._rows(
                "SELECT COALESCE(type, kind, 'Note') t, COUNT(*) c"
                " FROM nodes GROUP BY t ORDER BY c DESC"
            )
        }

        # ── top Pitfall nodes accessed recently ──
        top_pitfalls = self._rows(
            "SELECT id, title, access_count, confidence FROM nodes"
            " WHERE (type='Pitfall' OR kind='Pitfall')"
            " AND access_count > 0"
            " ORDER BY access_count DESC LIMIT 5"
        )

        # ── summary text ──
        roi_score = roi["knowledge_roi_score"]
        if roi_score >= 0.70:
            summary = "Knowledge base is actively protecting your team. ROI is strong."
        elif roi_score >= 0.40:
            summary = "Knowledge base shows moderate ROI. Consider improving feedback loop."
        else:
            summary = (
                "Low ROI detected. Ensure agents call get_context() and "
                "report_knowledge_outcome() after each task."
            )

        return {
            "generated_at":   datetime.now(timezone.utc).isoformat() + "Z",
            "period_days":    period_days,
            "roi":            roi,
            "usage": {
                "total_nodes":    total_nodes,
                "total_queries":  total_queries,
                "recent_adds":    recent_adds,
                "recent_queries": recent_queries,
                "by_type":        by_type,
            },
            "top_pitfalls":   top_pitfalls,
            "summary":        summary,
        }
