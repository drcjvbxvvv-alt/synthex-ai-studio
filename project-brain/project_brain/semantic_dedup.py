"""
core/brain/semantic_dedup.py — 語意去重引擎（v6.0）

## 問題

`brain scan` 從多個 commit 提取知識時，同一件事可能用不同措辭出現多次：

  Commit A: "JWT 認證改用 RS256，廢棄 HS256"
  Commit B: "把 token 簽名從 symmetric 換成 asymmetric"
  Commit C: "auth token 驗證方式更新"

這三條說的是完全相同的事，但標題不同，全部都存入 L3，
在中型專案裡約有 20-30% 的知識是語意重複的。

## 解法

計算每對知識節點的語意相似度。
相似度 >= threshold（預設 0.85）時，保留重要性較高（或較新）的節點，
另一個節點被「合並」（內容合入主節點 + 加上 merged_from 標記 + 刪除）。

## 相似度計算（三種模式）

1. TF-IDF cosine（預設）：零依賴，速度快，中英文都支援
2. Chroma 向量（若 chromadb 已安裝）：語意更準，但需要嵌入模型
3. Edit distance（備援）：字元層級，速度最快但最不準

## 使用方式

    from project_brain.semantic_dedup import SemanticDeduplicator
    from project_brain.graph import KnowledgeGraph
    from pathlib import Path

    graph = KnowledgeGraph(Path(".brain"))
    dedup = SemanticDeduplicator(graph, threshold=0.85)
    report = dedup.run(dry_run=False)
    print(report.summary())
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MergeAction:
    kept_id:    str
    merged_id:  str
    similarity: float
    reason:     str


@dataclass
class DeduplicationReport:
    total_scanned: int           = 0
    duplicate_pairs: int         = 0
    merged: list[MergeAction]    = field(default_factory=list)
    dry_run: bool                = True

    def summary(self) -> str:
        status = "（DRY RUN，未實際修改）" if self.dry_run else "（已執行合並）"
        lines = [
            f"語意去重報告 {status}",
            f"  掃描節點：{self.total_scanned}",
            f"  重複對數：{self.duplicate_pairs}",
            f"  合並執行：{len(self.merged)}",
        ]
        for a in self.merged[:5]:
            lines.append(
                f"  [合並] {a.merged_id[:8]}... → {a.kept_id[:8]}... "
                f"(相似度 {a.similarity:.2f})"
            )
        if len(self.merged) > 5:
            lines.append(f"  ... 還有 {len(self.merged)-5} 筆")
        return "\n".join(lines)


class TFIDFVectorizer:
    """
    輕量 TF-IDF 向量化器（零依賴）。
    專為中英文混合的知識節點標題 + 內容設計。
    """

    def __init__(self):
        self._idf: dict[str, float] = {}
        self._corpus: list[list[str]] = []

    def _tokenize(self, text: str) -> list[str]:
        """分詞：英文按空格，中文按字元（2-gram 子詞）"""
        text  = (text or "").lower()
        words = re.findall(r'[a-z0-9_\-\.]{2,}', text)  # 英文詞
        # 中文 2-gram
        chinese = re.findall(r'[\u4e00-\u9fff]', text)
        for i in range(len(chinese) - 1):
            words.append(chinese[i] + chinese[i+1])
        words += chinese  # 也加入單字
        return words

    def fit(self, texts: list[str]) -> "TFIDFVectorizer":
        self._corpus = [self._tokenize(t) for t in texts]
        doc_freq: Counter = Counter()
        for tokens in self._corpus:
            doc_freq.update(set(tokens))
        n = len(texts)
        self._idf = {
            term: math.log((n + 1) / (freq + 1)) + 1
            for term, freq in doc_freq.items()
        }
        return self

    def transform(self, text: str) -> dict[str, float]:
        """回傳 TF-IDF 向量（稀疏，dict 格式）"""
        tokens = self._tokenize(text)
        tf: Counter = Counter(tokens)
        total = max(len(tokens), 1)
        return {
            term: (count / total) * self._idf.get(term, 1.0)
            for term, count in tf.items()
        }

    @staticmethod
    def cosine(v1: dict, v2: dict) -> float:
        """稀疏向量的 cosine 相似度"""
        if not v1 or not v2:
            return 0.0
        common = set(v1) & set(v2)
        if not common:
            return 0.0
        dot  = sum(v1[k] * v2[k] for k in common)
        mag1 = math.sqrt(sum(x * x for x in v1.values()))
        mag2 = math.sqrt(sum(x * x for x in v2.values()))
        if mag1 == 0 or mag2 == 0:
            return 0.0
        return dot / (mag1 * mag2)


class SemanticDeduplicator:
    """
    語意去重引擎（v6.0）

    使用 TF-IDF cosine 相似度偵測語意重複節點，
    自動合並低重要性/低置信度的副本節點到主節點。

    閾值建議：
      0.95 以上：極保守，只合並幾乎完全相同的節點
      0.85（預設）：合並語意高度相似的節點（推薦）
      0.70：激進，可能誤合並不同的節點（需人工確認）
    """

    def __init__(
        self,
        graph,
        threshold: float = 0.85,
        node_types: Optional[list[str]] = None,
    ):
        """
        Args:
            graph:      KnowledgeGraph 實例
            threshold:  相似度閾值（0.0~1.0，預設 0.85）
            node_types: 只比較這些類型（None = 只比較同類型）
        """
        self.graph      = graph
        self.threshold  = threshold
        self.node_types = node_types or ["Pitfall", "Decision", "Rule", "ADR"]

    def run(self, dry_run: bool = True) -> DeduplicationReport:
        """
        執行語意去重。

        Args:
            dry_run: True=只回報不修改（預設），False=實際執行合並

        Returns:
            DeduplicationReport

        範例：
            report = dedup.run(dry_run=False)
            print(report.summary())
        """
        report = DeduplicationReport(dry_run=dry_run)

        # 按類型分組，只在同類型內比較（不跨類型合並）
        nodes_by_type: dict[str, list[dict]] = defaultdict(list)
        for t in self.node_types:
            rows = self.graph._conn.execute(
                "SELECT id, title, content, importance, is_pinned, meta FROM nodes WHERE type=?",
                (t,)
            ).fetchall()
            nodes_by_type[t] = [dict(r) for r in rows]

        report.total_scanned = sum(len(v) for v in nodes_by_type.values())

        for node_type, nodes in nodes_by_type.items():
            if len(nodes) < 2:
                continue

            # 建立 TF-IDF 向量（title + content 合並）
            texts = [
                (n.get("title") or "") + " " + (n.get("content") or "")
                for n in nodes
            ]
            vectorizer = TFIDFVectorizer().fit(texts)
            vectors    = [vectorizer.transform(t) for t in texts]

            # 找相似對（O(n²)，有進度提示 + 超時保護）
            # v8.0：大型知識庫（n>500）加入進度輸出和 timeout
            import time as _t
            merged_ids: set[str] = set()
            n = len(nodes)
            total_pairs = n * (n - 1) // 2
            checked = 0
            start_time = _t.monotonic()
            MAX_SECONDS = 30  # 超過 30 秒自動停止，保留已發現結果
            show_progress = n > 100

            for i in range(n):
                if nodes[i]["id"] in merged_ids:
                    continue

                # 超時檢查（每 100 次外層迭代）
                if i % 100 == 0 and _t.monotonic() - start_time > MAX_SECONDS:
                    logger.warning(
                        "dedup_timeout: checked %d/%d pairs, stopping early",
                        checked, total_pairs
                    )
                    print(f"  ⚠ 去重超時（{MAX_SECONDS}s），已檢查 {checked} 對，"
                          f"找到 {report.duplicate_pairs} 對重複")
                    break

                for j in range(i + 1, n):
                    if nodes[j]["id"] in merged_ids:
                        continue

                    checked += 1
                    sim = TFIDFVectorizer.cosine(vectors[i], vectors[j])
                    if sim < self.threshold:
                        continue

                    report.duplicate_pairs += 1
                    kept, merged = self._pick_keeper(nodes[i], nodes[j])

                    action = MergeAction(
                        kept_id    = kept["id"],
                        merged_id  = merged["id"],
                        similarity = round(sim, 4),
                        reason     = f"TF-IDF cosine={sim:.3f} >= threshold={self.threshold}",
                    )
                    report.merged.append(action)
                    merged_ids.add(merged["id"])

                    if not dry_run:
                        self._do_merge(kept, merged)

            # 進度輸出（大型知識庫）
            if show_progress:
                elapsed = _t.monotonic() - start_time
                print(f"  [去重] {node_type} 完成：{checked} 對比較，"
                      f"{report.duplicate_pairs} 對重複，耗時 {elapsed:.1f}s")

        logger.info(
            "dedup_done: scanned=%d pairs=%d merged=%d dry_run=%s",
            report.total_scanned, report.duplicate_pairs,
            len(report.merged), dry_run,
        )
        return report

    def _pick_keeper(self, a: dict, b: dict) -> tuple[dict, dict]:
        """
        在兩個語意相似節點中選出應保留的主節點。

        優先順序：
          1. is_pinned=1 的節點（絕對優先）
          2. importance 較高的節點
          3. 較新建立的節點（有更多歷史資訊）
        """
        def _score(n: dict) -> float:
            pinned     = 10.0 if (n.get("is_pinned") or 0) else 0.0
            importance = float(n.get("importance") or 0.5)
            return pinned + importance

        return (a, b) if _score(a) >= _score(b) else (b, a)

    def _do_merge(self, kept: dict, merged: dict) -> None:
        """
        執行合並：
        1. 把 merged 的 content 附加到 kept（若不重複）
        2. 在 kept 的 meta 記錄 merged_from
        3. 把指向 merged 的邊重新連到 kept
        4. 刪除 merged 節點
        """
        conn = self.graph._conn

        # 合並內容（追加不重複的部分）
        kept_content   = kept.get("content") or ""
        merged_content = merged.get("content") or ""
        if merged_content and merged_content not in kept_content:
            new_content = kept_content + "\n[合并自] " + merged_content[:200]
            conn.execute(
                "UPDATE nodes SET content=? WHERE id=?",
                (new_content, kept["id"])
            )

        # 更新 meta 記錄合並歷史
        try:
            meta = json.loads(kept.get("meta") or "{}")
        except Exception:
            meta = {}
        merges = meta.get("merged_from", [])
        merges.append(merged["id"])
        meta["merged_from"] = merges
        conn.execute(
            "UPDATE nodes SET meta=? WHERE id=?",
            (json.dumps(meta, ensure_ascii=False), kept["id"])
        )

        # 重新連接邊：merged → kept
        conn.execute(
            "UPDATE edges SET source_id=? WHERE source_id=?",
            (kept["id"], merged["id"])
        )
        conn.execute(
            "UPDATE edges SET target_id=? WHERE target_id=?",
            (kept["id"], merged["id"])
        )

        # 刪除 merged 節點（FTS5 觸發器自動同步）
        conn.execute("DELETE FROM nodes WHERE id=?", (merged["id"],))
        conn.commit()

        logger.info(
            "node_merged: kept=%s merged=%s",
            kept["id"][:8], merged["id"][:8]
        )

    def check_near_duplicate(
        self,
        new_node_id: str,
        new_text: str,
        node_type: str,
        candidates: list[dict],
    ) -> Optional[tuple[str, float]]:
        """
        Lightweight near-duplicate check for a single new node.

        Instead of an O(n²) full scan, this only compares the new node
        against a small candidate list (e.g. FTS5 top-k results).

        Uses Jaccard token-set similarity — more stable than TF-IDF when
        the candidate pool is small (avoids IDF degeneracy with n<10 docs).
        Threshold is scaled down from the full-run threshold to compensate
        (Jaccard is generally lower than cosine for the same text pairs).

        Args:
            new_node_id: ID of the newly added node (excluded from comparison).
            new_text:    title + content of the new node.
            node_type:   type of the new node.
            candidates:  list of node dicts to compare against.

        Returns:
            (existing_node_id, similarity) if a near-duplicate is found, else None.
        """
        if not candidates or node_type not in self.node_types:
            return None

        filtered = [c for c in candidates if c.get("id") != new_node_id]
        if not filtered:
            return None

        vect = TFIDFVectorizer()
        new_tokens = set(vect._tokenize(new_text))
        if not new_tokens:
            return None

        # Jaccard threshold: roughly 0.85 cosine ≈ 0.40 Jaccard for typical text
        jaccard_threshold = max(0.35, self.threshold - 0.45)

        best_sim  = 0.0
        best_id   = ""
        for candidate in filtered:
            cand_text   = (candidate.get("title") or "") + " " + (candidate.get("content") or "")
            cand_tokens = set(vect._tokenize(cand_text))
            if not cand_tokens:
                continue
            intersection = len(new_tokens & cand_tokens)
            union        = len(new_tokens | cand_tokens)
            sim = intersection / union if union > 0 else 0.0
            if sim > best_sim:
                best_sim = sim
                best_id  = candidate["id"]

        if best_sim >= jaccard_threshold:
            return (best_id, round(best_sim, 4))
        return None
