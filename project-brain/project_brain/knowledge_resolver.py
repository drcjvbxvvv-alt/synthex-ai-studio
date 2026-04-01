"""
core/brain/knowledge_resolver.py — CRDT 知識衝突解決（v9.0）

## 問題背景

多個 AI Agent 對同一個問題可能有不同的「正確答案」：
- Engineering AI：「所有 API 必須驗證 JWT」
- Security AI：「JWT 必須在 Redis 黑名單中驗證」
- Legal AI：「用戶資料存取需要 Audit Log」

三個觀點都是「Rule」，但互相補充、有時衝突。
沒有衝突解決機制，知識庫會快速碎片化。

## CRDT 設計（Conflict-free Replicated Data Type 概念）

信心加權投票：
  confidence_score = confidence × (1 + 0.1 × is_pinned)
  winner = 最高信心的觀點（主版本）
  minority_views = 其餘觀點（不刪除，保留在 meta.minority_views）

合並策略：
  1. 標題保留 winner 的標題
  2. 內容合並：winner 內容 + 少數觀點摘要
  3. 信心取最高值
  4. 合並後標記 acked_by 欄位，說明哪些節點被合並

這讓系統保持 CRDT 的「最終一致性」：
  - 合並操作是交換律的（A 合 B = B 合 A）
  - 合並後不丟失任何觀點
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ResolvedKnowledge:
    """衝突解決後的知識節點"""
    winner_id:     str
    winner_title:  str
    merged_content: str
    final_confidence: float
    merged_ids:    list[str]      # 被合並的節點 ID（不包含 winner）
    minority_views: list[dict]    # 少數觀點摘要


class KnowledgeResolver:
    """
    CRDT 風格的知識衝突解決器。

    使用信心加權投票決定主版本，
    少數觀點以摘要形式保留在 meta.minority_views。

    使用範例：
        resolver = KnowledgeResolver(graph)

        # 找出相似節點的衝突
        conflicts = resolver.find_conflicts("JWT", threshold=0.7)

        # 解決特定節點的衝突
        result = resolver.resolve("node_jwt_rule_1")

        # 批次解決所有高信心衝突
        results = resolver.auto_resolve(min_confidence=0.8)
    """

    def __init__(self, graph):
        self.graph = graph

    MAX_NODES_FOR_CONFLICT = 200  # B-3: O(n²) 上限

    def find_conflicts(
        self,
        query: str = "",
        threshold: float = 0.7,
        node_type: str = "Rule",
        limit: int = 50,
    ) -> list[dict]:
        """
        找出語意相似但可能衝突的節點組。

        B-3 修補：加入節點數上限（MAX_NODES_FOR_CONFLICT=200）。
        TF-IDF cosine 是 O(n²)，300+ 節點時超過 3 秒。
        超過上限時取高信心的前 200 個，確保 <500ms。

        Args:
            query:       關鍵字過濾（空字串 = 全部）
            threshold:   cosine 相似度閾值
            node_type:   只看特定類型（Rule / Pitfall / Decision）
            limit:       最多回傳幾組衝突
        """
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            logger.warning("scikit-learn 未安裝，無法進行語意衝突偵測")
            return []

        nodes = self.graph._conn.execute("""
            SELECT id, type, title, content, confidence, is_pinned, perspective
            FROM nodes
            WHERE type = ?
            ORDER BY confidence DESC
        """, (node_type,)).fetchall()

        if len(nodes) < 2:
            return []

        # 過濾 query
        if query:
            nodes = [n for n in nodes
                     if query.lower() in (n["title"] or "").lower()
                     or query.lower() in (n["content"] or "").lower()]

        if len(nodes) < 2:
            return []

        # B-3: 節點上限，取高信心的前 N 個
        if len(nodes) > self.MAX_NODES_FOR_CONFLICT:
            logger.info(
                "find_conflicts: %d nodes > limit %d, using top-%d by confidence",
                len(nodes), self.MAX_NODES_FOR_CONFLICT, self.MAX_NODES_FOR_CONFLICT
            )
            nodes = nodes[:self.MAX_NODES_FOR_CONFLICT]

        texts  = [f"{n['title']} {n['content']}" for n in nodes]
        vec    = TfidfVectorizer(min_df=1).fit_transform(texts)
        sims   = cosine_similarity(vec)

        groups_found = []
        visited = set()

        for i in range(len(nodes)):
            if i in visited:
                continue
            similar = [j for j in range(len(nodes))
                       if j != i and sims[i][j] >= threshold]
            if similar:
                group = [dict(nodes[i])] + [dict(nodes[j]) for j in similar]
                max_sim = float(max(sims[i][j] for j in similar))
                groups_found.append({
                    "group":          group,
                    "max_similarity": round(max_sim, 3),
                })
                visited.add(i)
                visited.update(similar)

            if len(groups_found) >= limit:
                break

        return groups_found

    def resolve(
        self,
        node_id: str,
        strategy: str = "confidence_weighted",
        dry_run: bool = False,
    ) -> Optional[ResolvedKnowledge]:
        """
        解決單一節點與其相似節點之間的衝突。

        Args:
            node_id:  起始節點 ID
            strategy: 解決策略（目前只支援 confidence_weighted）
            dry_run:  True = 只計算，不寫入

        Returns:
            ResolvedKnowledge 或 None（找不到衝突）
        """
        node = self.graph.get_node(node_id)
        if not node:
            return None

        # 找相似節點
        conflicts = self.find_conflicts(
            query=node["title"][:20],
            threshold=0.65,
            node_type=node.get("type", "Rule"),
        )

        if not conflicts:
            return None

        # 找到包含此節點的衝突組
        target_group = None
        for c in conflicts:
            ids = [n["id"] for n in c["group"]]
            if node_id in ids:
                target_group = c["group"]
                break

        if not target_group or len(target_group) < 2:
            return None

        return self._resolve_group(target_group, dry_run=dry_run)

    def _resolve_group(
        self,
        group: list[dict],
        dry_run: bool = False,
    ) -> ResolvedKnowledge:
        """信心加權投票解決一組衝突節點"""
        # 計算每個節點的得分
        def score(n):
            conf    = float(n.get("confidence") or 0.8)
            pinned  = 1.1 if n.get("is_pinned") else 1.0
            return conf * pinned

        ranked  = sorted(group, key=score, reverse=True)
        winner  = ranked[0]
        losers  = ranked[1:]

        # 合並內容
        winner_content = winner.get("content") or ""
        minority_views = []
        for loser in losers:
            perspective = loser.get("perspective") or "未知觀點"
            summary = (loser.get("content") or "")[:150]
            minority_views.append({
                "id":          loser["id"],
                "perspective": perspective,
                "summary":     summary,
                "confidence":  loser.get("confidence"),
            })

        minority_block = ""
        if minority_views:
            parts = [f"  - [{v['perspective']}] {v['summary']}" for v in minority_views]
            minority_block = "\n\n**少數觀點**：\n" + "\n".join(parts)

        merged_content  = winner_content + minority_block
        final_conf      = float(winner.get("confidence") or 0.8)
        merged_ids      = [l["id"] for l in losers]

        result = ResolvedKnowledge(
            winner_id       = winner["id"],
            winner_title    = winner.get("title", ""),
            merged_content  = merged_content,
            final_confidence = final_conf,
            merged_ids      = merged_ids,
            minority_views  = minority_views,
        )

        if not dry_run:
            # 更新 winner 節點
            meta = json.loads(winner.get("meta") or "{}")
            meta["minority_views"] = minority_views
            meta["resolved_from"]  = merged_ids
            self.graph._conn.execute("""
                UPDATE nodes
                SET content = ?, confidence = ?, meta = ?
                WHERE id = ?
            """, (merged_content, final_conf, json.dumps(meta, ensure_ascii=False),
                  winner["id"]))
            # 標記 loser 節點為已合並（降低信心，不刪除）
            for lid in merged_ids:
                self.graph._conn.execute("""
                    UPDATE nodes SET confidence = confidence * 0.3,
                    meta = json_set(COALESCE(meta,'{}'), '$.merged_into', ?)
                    WHERE id = ?
                """, (winner["id"], lid))
            self.graph._conn.commit()
            logger.info("Resolved conflict: winner=%s merged=%s", winner["id"], merged_ids)

        return result

    def auto_resolve(
        self,
        threshold: float = 0.75,
        min_confidence: float = 0.7,
        dry_run: bool = False,
    ) -> list[ResolvedKnowledge]:
        """
        批次自動解決高信心衝突。

        只處理 confidence >= min_confidence 的節點，
        避免把不確定的知識強制合並。
        """
        results = []
        for node_type in ("Rule", "Pitfall", "Decision"):
            conflicts = self.find_conflicts(
                threshold=threshold, node_type=node_type
            )
            for c in conflicts:
                high_conf = [n for n in c["group"]
                             if float(n.get("confidence") or 0) >= min_confidence]
                if len(high_conf) >= 2:
                    r = self._resolve_group(high_conf, dry_run=dry_run)
                    results.append(r)
        return results
