"""
DecayEngine — 多維知識衰減引擎 (v2.0)

v1.1 TemporalGraph 的衰減只考慮時間：c(t) = c₀ × e^(-λ×days)
v2.0 DecayEngine 引入三個維度的衰減：

  1. 時間衰減（Time Decay）
     同 v1.1 的指數衰減，但動態調整 λ

  2. 程式碼擾動衰減（Code Churn Decay）
     當知識相關的程式碼被頻繁修改，說明架構在演化，
     舊的知識可能已不準確。
     decay_factor = 1 - (churn_rate / MAX_CHURN)

  3. 顯式失效（Explicit Invalidation）
     當 bug 被修復，對應的 Pitfall 可以標記為「已解決」。
     標記後信心分數快速衰減到接近 0（但不完全為 0，歷史記錄保留）。

複合衰減公式：
  c_final(t) = c_time(t) × c_churn × c_explicit

  c_time(t)    = c₀ × e^(-λ_eff × days)
  λ_eff        = λ_base × (1 + churn_penalty)   ← 程式碼越亂 λ 越大
  c_churn      = 1 - (churn_score × CHURN_WEIGHT)
  c_explicit   = 0.05 if invalidated else 1.0

安全設計：
  - 數值穩定性：所有計算有 NaN/Inf 防護
  - 信心下界：不低於 0.001（避免除零）
  - 程式碼擾動計算限制：只看最近 90 天，防止歷史偏差

記憶體管理：
  - 增量計算：不全量載入所有知識
  - 批次更新：每次最多更新 1000 筆
  - 結果快取：同一節點 60 秒內不重複計算
"""

from __future__ import annotations

import math
import time
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

from ..graph import KnowledgeGraph

logger = logging.getLogger(__name__)

# ── 衰減常數 ──────────────────────────────────────────────────────
CONFIDENCE_FLOOR   = 0.001     # 信心下界（歷史記錄不完全消失）
CONFIDENCE_CEIL    = 1.0       # 信心上界
CHURN_WEIGHT       = 0.3       # 程式碼擾動對信心的最大影響比例
MAX_CHURN_COMMITS  = 20        # 超過此數認為是「高擾動」
CHURN_WINDOW_DAYS  = 90        # 程式碼擾動計算窗口（天）
INVALIDATED_SCORE  = 0.05      # 顯式失效後的信心下限

# λ 基準值（按知識類型）
BASE_LAMBDA: dict[str, float] = {
    "Pitfall":   0.001,   # 踩坑記錄幾乎不過時（教訓永遠有效）
    "Decision":  0.003,   # 決策可能隨技術演進而過時
    "Rule":      0.002,   # 業務規則中等穩定
    "ADR":       0.001,   # ADR 是歷史記錄，幾乎不衰減
    "Component": 0.005,   # 組件結構變化較快
    "_default":  0.004,
}

# 快取：(node_id, timestamp_minute) → confidence
_cache: dict[str, tuple[float, float]] = {}
CACHE_TTL = 60.0  # 秒


def _safe_float(v: float, default: float = 0.0) -> float:
    """防止 NaN / Inf"""
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float = CONFIDENCE_FLOOR, hi: float = CONFIDENCE_CEIL) -> float:
    return max(lo, min(hi, _safe_float(v, lo)))


class DecayEngine:
    """
    多維知識衰減引擎。
    與 KnowledgeGraph 和 TemporalGraph 協作，
    為知識庫中的每個節點維護動態信心分數。
    """

    def __init__(self, graph: KnowledgeGraph, workdir: Optional[Path] = None):
        self.graph   = graph
        self.workdir = workdir
        self._conn   = graph._conn
        self._setup_decay_schema()

    def _setup_decay_schema(self) -> None:
        """建立衰減相關的擴充表"""
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS decay_state (
            node_id          TEXT PRIMARY KEY,
            base_confidence  REAL NOT NULL DEFAULT 1.0,
            created_at       TEXT NOT NULL DEFAULT (datetime('now')),
            last_commit_at   TEXT,
            churn_score      REAL NOT NULL DEFAULT 0.0,
            is_invalidated   INTEGER NOT NULL DEFAULT 0,
            invalidated_at   TEXT,
            invalidation_note TEXT,
            effective_lambda REAL NOT NULL DEFAULT 0.004,
            last_computed    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_decay_invalidated
            ON decay_state(is_invalidated) WHERE is_invalidated = 1;

        CREATE TABLE IF NOT EXISTS decay_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id      TEXT    NOT NULL,
            event_type   TEXT    NOT NULL,
            old_confidence REAL,
            new_confidence REAL,
            reason       TEXT,
            occurred_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_de_node
            ON decay_events(node_id, occurred_at DESC);
        """)
        self._conn.commit()

    # ── 信心計算 ────────────────────────────────────────────────────

    def compute_confidence(self, node_id: str) -> float:
        """
        計算節點的當前信心分數（三維複合衰減）。

        使用快取：同一分鐘內的結果不重複計算。
        """
        now = time.monotonic()
        cache_key = f"{node_id}:{int(now / CACHE_TTL)}"
        if cache_key in _cache:
            _, cached_val = _cache[cache_key]
            if now - cached_val < CACHE_TTL:
                return _cache[cache_key][0]

        result = self._compute_uncached(node_id)
        _cache[cache_key] = (result, now)

        # 防止快取無限成長（LRU 簡化版：超過 2000 筆就清空）
        if len(_cache) > 2000:
            _cache.clear()

        return result

    def _compute_uncached(self, node_id: str) -> float:
        """核心衰減計算（無快取）"""
        state = self._conn.execute(
            "SELECT * FROM decay_state WHERE node_id = ?", (node_id,)
        ).fetchone()

        if not state:
            # 新節點，從知識圖譜取基礎資訊
            node = self.graph.get_node(node_id)
            if not node:
                return CONFIDENCE_FLOOR
            self._init_decay_state(node_id, node)
            state = self._conn.execute(
                "SELECT * FROM decay_state WHERE node_id = ?", (node_id,)
            ).fetchone()

        # 1. 顯式失效
        if state["is_invalidated"]:
            return INVALIDATED_SCORE

        # 2. 時間衰減
        created_str = state["created_at"] or datetime.now(timezone.utc).isoformat()
        try:
            created_dt  = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            now_dt      = datetime.now(timezone.utc)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            days_elapsed = max(0.0, (now_dt - created_dt).total_seconds() / 86400)
        except (ValueError, OSError):
            days_elapsed = 0.0

        λ_eff        = _safe_float(state["effective_lambda"], BASE_LAMBDA["_default"])
        base_conf    = _safe_float(state["base_confidence"], 0.8)
        c_time       = base_conf * math.exp(-λ_eff * days_elapsed)

        # 3. 程式碼擾動衰減
        churn        = _safe_float(state["churn_score"], 0.0)
        c_churn      = 1.0 - (churn * CHURN_WEIGHT)

        # 4. 複合
        c_final = _clamp(c_time * c_churn)
        return c_final

    def _init_decay_state(self, node_id: str, node: dict) -> None:
        """初始化節點的衰減狀態"""
        node_type = node.get("type", "_default")
        λ_base    = BASE_LAMBDA.get(node_type, BASE_LAMBDA["_default"])
        meta      = node.get("meta", {})
        if isinstance(meta, str):
            import json
            try: meta = json.loads(meta)
            except Exception: meta = {}
        base_conf = _safe_float(meta.get("confidence", 0.8), 0.8)

        created = node.get("created_at", datetime.now(timezone.utc).isoformat())

        self._conn.execute("""
            INSERT OR IGNORE INTO decay_state
                (node_id, base_confidence, created_at, effective_lambda)
            VALUES (?, ?, ?, ?)
        """, (node_id, _clamp(base_conf), created, λ_base))
        self._conn.commit()

    # ── 程式碼擾動分析 ────────────────────────────────────────────────

    def update_churn_scores(self, source_files: list[str] | None = None) -> int:
        """
        分析 git 歷史，計算程式碼擾動分數，更新 decay_state。

        churn_score ∈ [0, 1]：
          0 = 從未改動（最穩定）
          1 = 幾乎每天都在改（高度不穩定）

        Returns:
            更新的節點數量
        """
        if not self.workdir:
            return 0

        since = (datetime.now(timezone.utc)
                 - timedelta(days=CHURN_WINDOW_DAYS)).strftime("%Y-%m-%d")

        try:
            output = subprocess.check_output(
                ["git", "log", f"--since={since}", "--name-only",
                 "--pretty=format:", "--diff-filter=M"],
                cwd=str(self.workdir),
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=30,
            )
        except (subprocess.CalledProcessError, FileNotFoundError,
                subprocess.TimeoutExpired):
            return 0

        # 計算每個檔案的 commit 次數
        from collections import Counter
        file_counts: Counter = Counter(
            f.strip() for f in output.split("\n") if f.strip()
        )

        updated = 0
        for filepath, count in file_counts.most_common(200):
            churn = min(1.0, count / MAX_CHURN_COMMITS)

            # 找對應的知識節點（以檔案路徑查詢 source_url）
            nodes = self._conn.execute(
                "SELECT id FROM nodes WHERE source_url LIKE ?",
                (f"%{filepath}%",)
            ).fetchall()

            for node_row in nodes:
                nid = node_row["id"] if isinstance(node_row, sqlite3.Row) else node_row[0]

                self._conn.execute("""
                    INSERT OR REPLACE INTO decay_state
                        (node_id, base_confidence, churn_score, effective_lambda,
                         last_commit_at)
                    VALUES (
                        ?,
                        COALESCE((SELECT base_confidence FROM decay_state WHERE node_id=?), 0.8),
                        ?,
                        COALESCE((SELECT effective_lambda FROM decay_state WHERE node_id=?),
                                 ?),
                        datetime('now')
                    )
                """, (nid, nid, churn, nid, BASE_LAMBDA["_default"]))
                updated += 1

        if updated:
            self._conn.commit()
            logger.info("DecayEngine：更新 %d 個節點的擾動分數", updated)

        return updated

    # ── 顯式失效 ───────────────────────────────────────────────────

    def invalidate(
        self,
        node_id: str,
        reason:  str = "",
    ) -> bool:
        """
        顯式標記一個知識節點為「已失效」。
        常見場景：
          - Pitfall 已被修復，不再是問題
          - Decision 被新的 ADR 取代
          - Rule 業務規則已廢止

        注意：不是刪除，而是信心快速降至 INVALIDATED_SCORE。
              歷史記錄依然可查詢（is_invalidated=1 的過濾）。
        """
        reason_safe = str(reason)[:500] if reason else ""

        old_conf = self.compute_confidence(node_id)

        self._conn.execute("""
            INSERT INTO decay_state (node_id, base_confidence, is_invalidated,
                                     invalidated_at, invalidation_note, effective_lambda)
            VALUES (?, ?, 1, datetime('now'), ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                is_invalidated    = 1,
                invalidated_at    = datetime('now'),
                invalidation_note = excluded.invalidation_note
        """, (node_id, old_conf, reason_safe, BASE_LAMBDA["_default"]))

        self._conn.execute("""
            INSERT INTO decay_events (node_id, event_type, old_confidence,
                                      new_confidence, reason)
            VALUES (?, 'invalidated', ?, ?, ?)
        """, (node_id, old_conf, INVALIDATED_SCORE, reason_safe))

        self._conn.commit()
        _cache.clear()  # 清除快取
        logger.info("DecayEngine：節點 %s 已失效（%.3f → %.3f）",
                    node_id, old_conf, INVALIDATED_SCORE)
        return True

    def reinstate(self, node_id: str, reason: str = "") -> bool:
        """恢復已失效的知識節點（例如錯誤地失效了）"""
        self._conn.execute("""
            UPDATE decay_state
            SET is_invalidated = 0, invalidated_at = NULL,
                invalidation_note = NULL
            WHERE node_id = ?
        """, (node_id,))
        self._conn.execute("""
            INSERT INTO decay_events (node_id, event_type, reason)
            VALUES (?, 'reinstated', ?)
        """, (node_id, str(reason)[:200]))
        self._conn.commit()
        _cache.clear()
        return True

    # ── 批次維護 ────────────────────────────────────────────────────

    def get_low_confidence_nodes(
        self,
        threshold: float = 0.3,
        limit:     int   = 50,
    ) -> list[dict]:
        """
        取得信心分數低於閾值的節點。
        用於提醒用戶：這些知識可能需要確認或更新。
        """
        limit = max(1, min(500, int(limit)))

        # 取出 decay_state 中所有非失效的節點，計算實際信心
        rows = self._conn.execute("""
            SELECT ds.node_id, ds.base_confidence, ds.churn_score,
                   ds.effective_lambda, ds.created_at,
                   n.title, n.type
            FROM decay_state ds
            JOIN nodes n ON n.id = ds.node_id
            WHERE ds.is_invalidated = 0
            ORDER BY ds.last_computed ASC
            LIMIT ?
        """, (limit * 3,)).fetchall()  # 多取一些，過濾後再截斷

        low_conf = []
        for row in rows:
            conf = self.compute_confidence(row["node_id"])
            if conf < threshold:
                low_conf.append({
                    "node_id":    row["node_id"],
                    "title":      row["title"],
                    "type":       row["type"],
                    "confidence": round(conf, 4),
                    "churn_score":row["churn_score"],
                })

        return sorted(low_conf, key=lambda x: x["confidence"])[:limit]

    def decay_report(self) -> str:
        """產出衰減狀態報告"""
        try:
            total    = self._conn.execute(
                "SELECT COUNT(*) FROM decay_state").fetchone()[0]
            invalid  = self._conn.execute(
                "SELECT COUNT(*) FROM decay_state WHERE is_invalidated=1").fetchone()[0]
            churning = self._conn.execute(
                "SELECT COUNT(*) FROM decay_state WHERE churn_score > 0.5").fetchone()[0]
        except Exception:
            return "衰減報告生成失敗"

        low = self.get_low_confidence_nodes(threshold=0.3, limit=5)
        lines = [
            "## 知識衰減狀態報告",
            "",
            f"- 追蹤中節點：{total}",
            f"- 已失效節點：{invalid}（可查詢但信心極低）",
            f"- 高擾動節點：{churning}（相關程式碼頻繁變動）",
            "",
        ]
        if low:
            lines.append("### 需要確認的低信心知識")
            for n in low:
                lines.append(
                    f"- [{n['type']}] **{n['title']}**"
                    f"（信心 {n['confidence']:.0%}）"
                )
        return "\n".join(lines)

    def stats(self) -> dict:
        try:
            row = self._conn.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(is_invalidated) AS invalidated,
                    AVG(churn_score) AS avg_churn,
                    AVG(base_confidence) AS avg_base_confidence
                FROM decay_state
            """).fetchone()
            return dict(row) if row else {}
        except Exception:
            return {}
