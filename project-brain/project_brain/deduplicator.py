"""
core/brain/deduplicator.py — 語意去重引擎（v6.0）

## 問題背景（來自 ARCHITECTURAL_REFLECTION.md 缺陷 4）

`brain scan` 從 500 個 commit 中提取知識時，
同一件事可能以不同措辭出現在多個 commit：

    Commit A: "JWT 認證改用 RS256，廢棄 HS256"
    Commit B: "把 token 簽名從 symmetric 換成 asymmetric"
    Commit C: "auth token 驗證方式更新"

三條說的是相同的事，但標題不同，全部存入 L3，
導致：① 重複佔用 Context Budget  ② 相同建議反覆出現干擾 Agent

## 解法

掃描後對同類型節點計算 TF-IDF 向量的 cosine similarity，
similarity ≥ threshold 時自動合並（保留最長內容，合並 tags，刪除重複節點）。

完全不依賴 LLM，零 API 費用。

## 使用方式

    from project_brain.deduplicator import SemanticDeduplicator

    dedup = SemanticDeduplicator(graph)
    report = dedup.run(threshold=0.88)
    print(f"合並了 {report.merged_count} 對重複知識")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DeduplicationReport:
    """去重執行報告"""
    total_checked:  int = 0
    duplicate_pairs: list[tuple[str, str, float]] = field(default_factory=list)
    merged_count:   int = 0
    skipped_pinned: int = 0
    threshold:      float = 0.88

    def summary(self) -> str:
        lines = [
            f"=== 語意去重報告（threshold={self.threshold:.2f}）===",
            f"  檢查節點：{self.total_checked}",
            f"  發現重複對：{len(self.duplicate_pairs)}",
            f"  合並成功：{self.merged_count}",
            f"  跳過（釘選）：{self.skipped_pinned}",
        ]
        if self.duplicate_pairs:
            lines.append("\n  已合並的重複對：")
            for a, b, sim in self.duplicate_pairs[:10]:
                lines.append(f"    [{sim:.2f}] {a[:30]}… ← {b[:30]}…")
            if len(self.duplicate_pairs) > 10:
                lines.append(f"    ... 共 {len(self.duplicate_pairs)} 對")
        return "\n".join(lines)


class SemanticDeduplicator:
    """
    語意去重引擎（v6.0）

    算法：TF-IDF 向量化 → cosine similarity → 高相似度節點合並

    為什麼用 TF-IDF 而不是 Embedding：
    - 零 API 費用
    - 本地計算，<1 秒完成 100 個節點
    - 對工程術語（JWT / RS256 / idempotency_key）精準度足夠
    - Embedding 對同義詞更好，但工程知識通常用相同術語

    合並策略：
    - 保留 importance 較高的節點（或 is_pinned=1 的節點）作為主節點
    - 主節點的 content 取兩節點中較長的那份（資訊量更多）
    - Tags 取聯集
    - 刪除從節點
    """

    def __init__(self, graph, min_content_len: int = 10):
        """
        Args:
            graph:           KnowledgeGraph 實例
            min_content_len: content 最少字元數，低於此值不參與去重
        """
        self.graph           = graph
        self.min_content_len = min_content_len

    def run(
        self,
        threshold:  float = 0.88,
        node_types: Optional[list[str]] = None,
        dry_run:    bool = False,
    ) -> DeduplicationReport:
        """
        執行語意去重。

        Args:
            threshold:  cosine similarity 閾值（0.88 = 高度相似）
            node_types: 只對這些類型去重（None = Pitfall + Decision + Rule + ADR）
            dry_run:    True = 只報告，不實際合並

        Returns:
            DeduplicationReport

        範例：
            dedup = SemanticDeduplicator(brain.graph)
            report = dedup.run(threshold=0.88)
            print(report.summary())
        """
        import json
        target_types = node_types or ["Pitfall", "Decision", "Rule", "ADR"]
        report = DeduplicationReport(threshold=threshold)

        for node_type in target_types:
            rows = self.graph._conn.execute(
                "SELECT id, title, content, tags, importance, is_pinned "
                "FROM nodes WHERE type=? ORDER BY importance DESC, is_pinned DESC",
                (node_type,)
            ).fetchall()

            nodes = [dict(r) for r in rows]
            if len(nodes) < 2:
                continue

            report.total_checked += len(nodes)
            self._dedup_group(nodes, report, dry_run)

        return report

    def _dedup_group(
        self, nodes: list[dict], report: DeduplicationReport, dry_run: bool
    ) -> None:
        """對同一類型的節點群組執行去重"""
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            import numpy as np
        except ImportError:
            logger.warning("sklearn 未安裝，語意去重跳過。pip install scikit-learn")
            return

        # 過濾 content 太短的節點
        eligible = [
            n for n in nodes
            if len((n.get("content") or "").strip()) >= self.min_content_len
        ]
        if len(eligible) < 2:
            return

        # TF-IDF 向量化（title + content 合並）
        texts = [
            f"{n['title']} {n.get('content','')}"
            for n in eligible
        ]
        try:
            vec   = TfidfVectorizer(
                analyzer="char_wb", ngram_range=(2, 4),
                max_features=5000, sublinear_tf=True,
            )
            matrix = vec.fit_transform(texts)
        except Exception as e:
            logger.warning("TF-IDF 向量化失敗：%s", e)
            return

        sim_matrix = cosine_similarity(matrix)
        merged_ids: set[str] = set()

        for i in range(len(eligible)):
            if eligible[i]["id"] in merged_ids:
                continue
            for j in range(i + 1, len(eligible)):
                if eligible[j]["id"] in merged_ids:
                    continue
                sim = float(sim_matrix[i, j])
                if sim < report.threshold:
                    continue

                # 發現重複對
                main, dup = self._pick_main(eligible[i], eligible[j])
                report.duplicate_pairs.append((main["title"], dup["title"], sim))

                if main.get("is_pinned") and not dup.get("is_pinned"):
                    pass  # main 是釘選節點，保留
                elif dup.get("is_pinned"):
                    # dup 是釘選節點，不能刪除
                    report.skipped_pinned += 1
                    continue

                if not dry_run:
                    self._merge_nodes(main, dup)
                    merged_ids.add(dup["id"])
                    report.merged_count += 1

    def _pick_main(
        self, a: dict, b: dict
    ) -> tuple[dict, dict]:
        """選擇主節點：釘選 > importance 高 > content 較長"""
        if a.get("is_pinned") and not b.get("is_pinned"):
            return a, b
        if b.get("is_pinned") and not a.get("is_pinned"):
            return b, a
        if (a.get("importance") or 0.5) >= (b.get("importance") or 0.5):
            return a, b
        return b, a

    def _merge_nodes(self, main: dict, dup: dict) -> None:
        """合並 dup 到 main，然後刪除 dup"""
        import json

        # content 取較長的
        main_content = (main.get("content") or "").strip()
        dup_content  = (dup.get("content")  or "").strip()
        merged_content = main_content if len(main_content) >= len(dup_content) else dup_content

        # tags 取聯集
        try:
            main_tags = set(json.loads(main.get("tags") or "[]"))
            dup_tags  = set(json.loads(dup.get("tags")  or "[]"))
            merged_tags = json.dumps(sorted(main_tags | dup_tags), ensure_ascii=False)
        except Exception:
            merged_tags = main.get("tags") or "[]"

        conn = self.graph._conn
        conn.execute(
            "UPDATE nodes SET content=?, tags=? WHERE id=?",
            (merged_content, merged_tags, main["id"])
        )
        # 刪除重複節點（edges 會因 ON DELETE CASCADE 自動清理）
        conn.execute("DELETE FROM nodes WHERE id=?", (dup["id"],))
        conn.commit()
        logger.info(
            "dedup_merged: main=%s dup=%s",
            main["id"][:8], dup["id"][:8]
        )
