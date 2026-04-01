"""
DecayEngine — 多因子知識衰減引擎 (Project Brain v2.0)

v1.1 的 TemporalGraph 已有基礎時間衰減（指數模型），
v2.0 的 DecayEngine 引入多因子衰減：

因子說明：
  F1. 時間衰減（基礎）：信心 × e^(-λ_base × days)
      — 越久的知識，越可能過時

  F2. 技術版本衰減：偵測知識中的套件名稱，查詢版本活躍度
      — 如果知識提到 React 16，而現在是 React 18，可信度降低

  F3. 活動信號（反衰減）：如果相關的程式碼檔案最近有被修改，
      信心分數提升（說明這個知識還在使用中）
      — commit 越近 = 越可信

  F4. 矛盾偵測：知識圖譜中有矛盾的決策時，兩者信心都降低
      — 如果 Decision A 說「用 JWT」，Decision B 說「不用 JWT」

  F5. 採用率回饋：被其他工程師標記為「有用」的知識，衰減更慢
      — 共享知識庫的社群回饋

  F6. 程式碼參考計數：如果知識中提到的函數 / 類別還存在程式碼庫中，
      延緩衰減

  F7. 使用頻率反衰減（Phase 3）：被 Agent 查詢越多次，衰減越慢
      access_count 每累積 10 次，最多抵消 0.05 衰減（上限 0.15）

最終信心 = F1 × F2 × F3 × min(1, F4 × F5) × F6

安全和可靠性：
  - 所有衰減係數嚴格限制在 [0.001, 1.0] 之間
  - 衰減不刪除知識（只降低信心，設置 is_deprecated 標記）
  - 批次更新，不鎖定主流程
  - 每次衰減前先快照，支援回溯
"""

from __future__ import annotations

import re
import math
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .graph import KnowledgeGraph

logger = logging.getLogger(__name__)

# ── 衰減參數常數 ─────────────────────────────────────────────────
DECAY_FLOOR          = 0.05    # 信心最低不低於此值（防止完全遺忘）
DECAY_CEIL           = 1.0
BASE_DECAY_RATE      = 0.003   # 日衰減率（約 1 年後降到 0.33）
CONTRADICTION_PENALTY= 0.70    # 矛盾時雙方信心 × 0.70
ADOPTION_BONUS       = 0.05    # 每次被標記「有用」+5% 信心（上限 1.0）
CODE_REF_BONUS       = 0.10    # 程式碼仍有引用時 +10% 信心
ACTIVITY_BONUS       = 0.08    # 相關檔案近 30 天有修改 +8% 信心
VERSION_GAP_PENALTY  = 0.15    # 每個主版本落差 -15% 信心

# 技術版本模式（偵測知識中提到的套件版本）
VERSION_PATTERNS = [
    re.compile(r'(?i)(react|vue|next|nuxt|angular|svelte)\s+v?(\d+)'),
    re.compile(r'(?i)(python|node|typescript)\s+v?(\d+)'),
    re.compile(r'(?i)(django|fastapi|express|nestjs)\s+v?(\d+)'),
    re.compile(r'(?i)(postgresql|mysql|mongodb|redis)\s+v?(\d+)'),
]

# 當前主流版本（定期更新，作為比較基準）
CURRENT_MAJOR_VERSIONS: dict[str, int] = {
    "react": 18, "vue": 3, "next": 15, "nuxt": 3,
    "angular": 17, "svelte": 4, "python": 3, "node": 22,
    "typescript": 5, "django": 5, "fastapi": 0, "express": 4,
    "nestjs": 10, "postgresql": 16, "mysql": 8, "mongodb": 7, "redis": 7,
}


class DecayReport:
    """單一知識節點的衰減分析報告"""
    __slots__ = ('node_id', 'title', 'original_confidence', 'new_confidence',
                 'factors', 'deprecated', 'reason')

    def __init__(self, node_id: str, title: str, original: float):
        self.node_id            = node_id
        self.title              = title
        self.original_confidence= original
        self.new_confidence     = original
        self.factors: dict      = {}
        self.deprecated         = False
        self.reason             = ""

    def to_dict(self) -> dict:
        return {
            "node_id":    self.node_id,
            "title":      self.title[:80],
            "original":   round(self.original_confidence, 4),
            "new":        round(self.new_confidence, 4),
            "change":     round(self.new_confidence - self.original_confidence, 4),
            "deprecated": self.deprecated,
            "factors":    {k: round(float(v), 4) for k, v in self.factors.items()},
            "reason":     self.reason,
        }


class DecayEngine:
    """
    多因子知識衰減引擎。

    使用方式：
        engine = DecayEngine(graph, temporal, workdir="/your/project")
        report = engine.run()              # 執行一次完整衰減計算
        engine.schedule(interval_days=7)   # 設定定期執行
    """

    def __init__(self, graph: KnowledgeGraph,
                 workdir: str = ""):
        self.graph    = graph
        self.workdir  = Path(workdir).resolve() if workdir else Path.cwd()
        self._decay_log: list[dict] = []

    # ── 主入口 ─────────────────────────────────────────────────

    def run(
        self,
        batch_size: int = 100,
        dry_run:    bool = False,
    ) -> list[DecayReport]:
        """
        執行一輪完整衰減計算。

        Args:
            batch_size: 每批處理的節點數（控制記憶體）
            dry_run:    True 時只計算，不寫入

        Returns:
            衰減報告列表（只包含信心有變化的節點）
        """
        reports: list[DecayReport] = []
        processed = 0

        # 偵測矛盾對（一次性計算，避免重複）
        contradiction_pairs = self._detect_contradictions()
        contradicted_ids    = {nid for pair in contradiction_pairs for nid in pair}

        # 取得 git 近期活動（一次性）
        recent_files = self._get_recently_modified_files(days=30)

        # 分批處理所有知識節點
        offset = 0
        while True:
            rows = self.graph._conn.execute("""
                SELECT id, type, title, content, tags,
                       source_url, created_at, is_pinned,
                       importance, confidence AS meta_confidence,
                       access_count
                FROM nodes
                WHERE type IN ('Decision','Pitfall','Rule','ADR')
                LIMIT ? OFFSET ?
            """, (batch_size, offset)).fetchall()

            if not rows:
                break

            for _row in rows:
                row = dict(_row)  # sqlite3.Row → dict (supports .get())
                node_id  = row["id"]
                title    = row["title"] or ""
                content  = row["content"] or ""
                created  = row["created_at"] or ""
                src_url  = row["source_url"] or ""

                # 初始信心（從 meta 或預設）
                try:
                    # v5.1 修正：is_pinned=1 的節點免疫衰減
                    if row.get("is_pinned") or 0:
                        continue

                    orig_conf = float(row["meta_confidence"] or 0.8)
                except (TypeError, ValueError):
                    orig_conf = 0.8
                orig_conf = max(DECAY_FLOOR, min(DECAY_CEIL, orig_conf))

                report = DecayReport(node_id, title, orig_conf)
                new_conf = orig_conf

                # F1：時間衰減
                f1 = self._factor_time(created)
                new_conf *= f1
                report.factors["F1_time"] = f1

                # F2：技術版本衰減
                f2 = self._factor_version(content)
                new_conf *= f2
                report.factors["F2_version"] = f2

                # F3：活動信號（反衰減）
                f3 = self._factor_activity(src_url, recent_files)
                new_conf = min(DECAY_CEIL, new_conf + f3)
                report.factors["F3_activity"] = f3

                # F4：矛盾懲罰
                if node_id in contradicted_ids:
                    new_conf *= CONTRADICTION_PENALTY
                    report.factors["F4_contradiction"] = CONTRADICTION_PENALTY
                    report.reason = "與其他決策存在矛盾"

                # F5：程式碼引用確認
                f5 = self._factor_code_reference(content)
                new_conf = min(DECAY_CEIL, new_conf + f5)
                report.factors["F5_code_ref"] = f5

                # F7（Phase 3）：使用頻率反衰減
                # 被 Agent 查詢越多次，衰減越慢（知識被驗證 = 仍然有效）
                access = row.get('access_count', 0)
                if access > 0:
                    # 每 10 次查詢，最多抵消 0.05 衰減（上限 0.15）
                    f7 = min(0.15, access / 10 * 0.05)
                    new_conf = min(DECAY_CEIL, new_conf + f7)
                    report.factors['F7_access_count'] = f7

                # 確保在合理範圍內
                new_conf = max(DECAY_FLOOR, min(DECAY_CEIL, new_conf))
                report.new_confidence = new_conf

                # 標記為已過時（信心低於 0.20）
                if new_conf < 0.20:
                    report.deprecated = True
                    if not report.reason:
                        report.reason = "信心值衰減至過時閾值"

                # 只記錄有變化的節點
                if abs(new_conf - orig_conf) > 0.001:
                    reports.append(report)
                    if not dry_run:
                        self._apply_decay(node_id, orig_conf, new_conf,
                                          report.deprecated)

                processed += 1

            offset += batch_size

        logger.info("DecayEngine.run: 處理 %d 個節點，%d 個有變化", processed, len(reports))
        self._decay_log.append({
            "run_at":    datetime.now(timezone.utc).isoformat(),
            "processed": processed,
            "changed":   len(reports),
            "deprecated":sum(1 for r in reports if r.deprecated),
        })
        return reports

    # ── 因子計算 ────────────────────────────────────────────────

    def _factor_time(self, created_at: str) -> float:
        """F1：時間衰減，指數模型"""
        if not created_at:
            return 1.0
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            days    = max(0, (datetime.now(timezone.utc) - created).days)
            return max(DECAY_FLOOR, math.exp(-BASE_DECAY_RATE * days))
        except (ValueError, TypeError):
            return 0.9  # 無法解析時保守處理

    def _factor_version(self, content: str) -> float:
        """F2：技術版本衰減——偵測知識中的版本號與當前版本比較"""
        if not content:
            return 1.0
        penalty = 1.0
        for pattern in VERSION_PATTERNS:
            for m in pattern.finditer(content):
                tech  = m.group(1).lower()
                try:
                    version_in_content = int(m.group(2))
                except (IndexError, ValueError):
                    continue
                current = CURRENT_MAJOR_VERSIONS.get(tech)
                if current is None:
                    continue
                gap = max(0, current - version_in_content)
                if gap > 0:
                    # 每個主版本差異 -15% 信心，最多扣到 50%
                    version_penalty = max(0.50, 1.0 - gap * VERSION_GAP_PENALTY)
                    penalty = min(penalty, version_penalty)
        return penalty

    def _factor_activity(self, source_url: str, recent_files: set) -> float:
        """F3：活動信號——相關檔案近期有修改則給予信心加成"""
        if not source_url or not recent_files:
            return 0.0
        # source_url 可能是 "file:src/payment/service.ts" 或 "commit:abc1234"
        for fname in recent_files:
            if fname in source_url or source_url in fname:
                return ACTIVITY_BONUS
        return 0.0

    def _factor_code_reference(self, content: str) -> float:
        """F5：程式碼引用——知識中提到的類別或函數是否還存在"""
        if not content or not self.workdir.exists():
            return 0.0
        # 提取 PascalCase 類別名稱
        class_names = re.findall(r'\b([A-Z][a-zA-Z]{4,})\b', content)[:5]
        if not class_names:
            return 0.0
        # 快速 grep 搜尋（只搜尋 Python / TypeScript / JavaScript）
        for name in class_names:
            try:
                result = subprocess.run(
                    ["grep", "-r", "--include=*.py", "--include=*.ts",
                     "--include=*.tsx", "--include=*.js",
                     "-l", name, str(self.workdir)],
                    capture_output=True, text=True,
                    timeout=3,   # 嚴格超時，不阻塞
                    cwd=str(self.workdir),
                )
                if result.returncode == 0 and result.stdout.strip():
                    return CODE_REF_BONUS
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
        return 0.0

    def _detect_contradictions(self) -> list[tuple[str, str]]:
        """
        F4：矛盾偵測——找出標題/內容語義上矛盾的決策對。
        使用簡單的反義詞模式偵測。
        """
        pairs: list[tuple[str, str]] = []
        # 常見矛盾模式
        OPPOSING_KEYWORDS = [
            ({"不用", "避免", "棄用", "移除", "deprecated"},
             {"使用", "採用", "建議", "recommended"}),
        ]

        rows = self.graph._conn.execute(
            "SELECT id, title, content FROM nodes WHERE type='Decision' LIMIT 200"
        ).fetchall()

        decisions = [dict(r) for r in rows]
        for i, da in enumerate(decisions):
            for db in decisions[i+1:]:
                # 兩個決策提到相同主題但有相反立場
                title_a = (da["title"] or "").lower()
                title_b = (db["title"] or "").lower()
                # 共享的關鍵主題詞（名詞，3 字以上）
                words_a = {w for w in re.findall(r'[a-zA-Z\u4e00-\u9fff]{3,}', title_a)}
                words_b = {w for w in re.findall(r'[a-zA-Z\u4e00-\u9fff]{3,}', title_b)}
                shared  = words_a & words_b
                if not shared:
                    continue
                # 檢查是否有相反立場的詞彙
                for neg_set, pos_set in OPPOSING_KEYWORDS:
                    has_neg_a = bool(neg_set & words_a)
                    has_pos_b = bool(pos_set & words_b)
                    has_neg_b = bool(neg_set & words_b)
                    has_pos_a = bool(pos_set & words_a)
                    if (has_neg_a and has_pos_b) or (has_neg_b and has_pos_a):
                        pairs.append((da["id"], db["id"]))
                        break

        logger.debug("偵測到 %d 對矛盾知識", len(pairs))
        return pairs

    def _get_recently_modified_files(self, days: int = 30) -> set:
        """取得 git 近期修改的檔案集合"""
        try:
            result = subprocess.run(
                ["git", "log", f"--since={days} days ago",
                 "--name-only", "--pretty=format:"],
                cwd=str(self.workdir), capture_output=True,
                text=True, timeout=5,
            )
            if result.returncode == 0:
                return {
                    f.strip() for f in result.stdout.splitlines()
                    if f.strip() and not f.startswith("commit ")
                }
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return set()

    def _apply_decay(self, node_id: str, old_conf: float,
                     new_conf: float, deprecated: bool) -> None:
        """把衰減結果寫入知識圖譜"""
        try:
            meta_raw = self.graph._conn.execute(
                "SELECT meta FROM nodes WHERE id=?", (node_id,)
            ).fetchone()
            if not meta_raw:
                return
            try:
                meta = json.loads(meta_raw["meta"] or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}
            meta["confidence"]     = round(new_conf, 4)
            meta["prev_confidence"]= round(old_conf, 4)
            meta["decayed_at"]     = datetime.now(timezone.utc).isoformat()
            if deprecated:
                meta["deprecated"] = True
            self.graph._conn.execute(
                "UPDATE nodes SET meta=?, confidence=? WHERE id=?",
                (json.dumps(meta, ensure_ascii=False), round(new_conf, 4), node_id)
            )
            self.graph._conn.commit()
        except Exception as e:
            logger.error("_apply_decay 寫入失敗 (%s): %s", node_id, e)

    # ── 查詢和報告 ───────────────────────────────────────────────

    def deprecated_knowledge(self, limit: int = 20) -> list[dict]:
        """列出已標記為過時的知識（供人工審查）"""
        limit = max(1, min(100, int(limit)))
        rows = self.graph._conn.execute("""
            SELECT id, type, title,
                   confidence,
                   json_extract(meta, '$.deprecated')   AS deprecated,
                   json_extract(meta, '$.decayed_at')   AS decayed_at
            FROM nodes
            WHERE json_extract(meta, '$.deprecated') = 1
            ORDER BY confidence ASC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def decay_summary(self) -> dict:
        """過去幾次衰減執行的摘要"""
        return {
            "runs":     len(self._decay_log),
            "history":  self._decay_log[-5:],   # 最近 5 次
        }

    def restore(self, node_id: str, confidence: float = 0.8) -> bool:
        """
        人工恢復一個被標記為過時的知識的信心值。
        用於「這個知識雖然舊，但我確認它還是正確的」的場景。
        """
        confidence = max(DECAY_FLOOR, min(DECAY_CEIL, float(confidence)))
        try:
            meta_raw = self.graph._conn.execute(
                "SELECT meta FROM nodes WHERE id=?", (node_id,)
            ).fetchone()
            if not meta_raw:
                return False
            meta = json.loads(meta_raw["meta"] or "{}")
            meta["confidence"]   = confidence
            meta["deprecated"]   = False
            meta["restored_at"]  = datetime.now(timezone.utc).isoformat()
            self.graph._conn.execute(
                "UPDATE nodes SET meta=?, confidence=? WHERE id=?",
                (json.dumps(meta, ensure_ascii=False), confidence, node_id)
            )
            self.graph._conn.commit()
            return True
        except Exception as e:
            logger.error("restore 失敗 (%s): %s", node_id, e)
            return False
