"""
tests/unit/test_find_conflicts.py

HIGH-03 — BrainDB.find_conflicts() O(n²) → FTS5 候選者過濾優化 驗收測試
(ARCHITECTURE_REVIEW.md §3 HIGH-03, §5.2 Phase 2)

背景：原本 find_conflicts() 使用硬編碼 LIMIT 500 + 巢狀 for 迴圈做 pairwise
Jaccard，在 5000 節點知識庫中會 skip 掉 90%+ 的可能衝突（只看前 500 筆）。
HIGH-03 修法使用 FTS5 n-gram match 做前置候選者過濾，把複雜度從 O(n²) 降到
O(n · K · log n)，K 預設 10。

本檔案驗收：
  1. 既有行為（基本重複/矛盾偵測）
  2. HIGH-03 的修法效果（> 500 節點時仍能偵測衝突）
  3. 輸出格式 / 排序 / top-50 cap
  4. Edge cases（空 DB、純 CJK、無 title 等）
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from project_brain.core.brain_db import BrainDB


# ══════════════════════════════════════════════════════════════════
#  測試輔助
# ══════════════════════════════════════════════════════════════════

class _BrainDBFixture(unittest.TestCase):
    """每個測試獨立 tmp BrainDB。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.bd = BrainDB(Path(self._tmp.name))

    def tearDown(self):
        try:
            self.bd.conn.close()
        except Exception:
            pass
        self._tmp.cleanup()

    def _add(self, node_id: str, title: str, content: str = "",
             kind: str = "Rule") -> None:
        self.bd.add_node(
            node_id=node_id, node_type=kind,
            title=title, content=content,
            tags=[], confidence=0.8,
        )


# ══════════════════════════════════════════════════════════════════
#  F-01 ~ F-04  基本行為
# ══════════════════════════════════════════════════════════════════

class TestFindConflictsBasic(_BrainDBFixture):

    def test_F01_empty_db_returns_empty_list(self):
        self.assertEqual(self.bd.find_conflicts(), [])

    def test_F02_single_node_no_conflicts(self):
        self._add("n1", "Lone rule")
        self.assertEqual(self.bd.find_conflicts(), [])

    def test_F03_unrelated_nodes_no_conflicts(self):
        self._add("n1", "Use RS256 for JWT signing")
        self._add("n2", "Pin Docker image versions explicitly")
        self._add("n3", "Use PostgreSQL instead of MySQL")
        # 三個節點 title 完全不同 → 無衝突
        self.assertEqual(self.bd.find_conflicts(), [])

    def test_F04_duplicate_detected(self):
        self._add("n1", "Use RS256 for JWT signing always always",
                  "must use asymmetric RS256")
        self._add("n2", "Use RS256 for JWT signing always often",
                  "always use RS256 instead of HS256")
        # title 重疊 5/6 ≈ 0.83 > 0.7
        conflicts = self.bd.find_conflicts(similarity_threshold=0.7)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["type"], "duplicate")
        ids = {conflicts[0]["node_a"], conflicts[0]["node_b"]}
        self.assertEqual(ids, {"n1", "n2"})


# ══════════════════════════════════════════════════════════════════
#  F-05 ~ F-08  矛盾偵測
# ══════════════════════════════════════════════════════════════════

class TestContradictionDetection(_BrainDBFixture):

    def test_F05_must_vs_must_not(self):
        self._add("n1", "JWT tokens must rotate every quarter",
                  "tokens must expire after 90 days")
        self._add("n2", "JWT tokens must not rotate every quarter",
                  "tokens must not be rotated more than yearly")
        conflicts = self.bd.find_conflicts(similarity_threshold=0.6)
        contradictions = [c for c in conflicts if c["type"] == "contradiction"]
        self.assertGreaterEqual(len(contradictions), 1)
        ids = {contradictions[0]["node_a"], contradictions[0]["node_b"]}
        self.assertEqual(ids, {"n1", "n2"})

    def test_F06_enable_vs_disable(self):
        self._add("n1", "Always enable CORS strict mode in production",
                  "must enable strict mode")
        self._add("n2", "Always disable CORS strict mode in production",
                  "do not enable strict; disable CORS")
        conflicts = self.bd.find_conflicts(similarity_threshold=0.6)
        contradictions = [c for c in conflicts if c["type"] == "contradiction"]
        self.assertGreaterEqual(len(contradictions), 1)

    def test_F07_cjk_contradiction_必須_vs_禁止(self):
        self._add("n1", "production database access 必須 approved",
                  "必須 by security team first")
        self._add("n2", "production database access 禁止 approved",
                  "禁止 direct shell access to prod DB")
        conflicts = self.bd.find_conflicts(similarity_threshold=0.6)
        contradictions = [c for c in conflicts if c["type"] == "contradiction"]
        self.assertGreaterEqual(len(contradictions), 1)

    def test_F08_contradictions_ranked_before_duplicates(self):
        # 先建立 duplicate (高相似度)
        self._add("d1", "Avoid using global singletons in tests",
                  "global state breaks test isolation")
        self._add("d2", "Avoid using global singletons in tests",
                  "global state makes tests flaky")
        # 再建立 contradiction (較低相似度但 contradiction 關鍵字)
        self._add("c1", "JWT keys must rotate monthly",
                  "keys must be rotated every month")
        self._add("c2", "JWT keys must not rotate monthly",
                  "do not rotate keys more than yearly")

        conflicts = self.bd.find_conflicts(similarity_threshold=0.6)
        # contradiction 應該排在 duplicate 之前（即使相似度較低）
        self.assertGreater(len(conflicts), 0)
        types = [c["type"] for c in conflicts]
        # 找到第一個 contradiction 和第一個 duplicate 的 index
        first_contra = next((i for i, t in enumerate(types) if t == "contradiction"), None)
        first_dup    = next((i for i, t in enumerate(types) if t == "duplicate"),     None)
        if first_contra is not None and first_dup is not None:
            self.assertLess(first_contra, first_dup,
                            "contradiction 應排在 duplicate 之前")


# ══════════════════════════════════════════════════════════════════
#  F-09 ~ F-11  輸出格式 / 排序 / 上限
# ══════════════════════════════════════════════════════════════════

class TestOutputFormat(_BrainDBFixture):

    def test_F09_conflict_dict_has_required_fields(self):
        self._add("n1", "Services should use OAuth2 flow correctly",
                  "OAuth2 authorization code flow")
        self._add("n2", "Services should use OAuth2 flow properly",
                  "OAuth2 authorization code flow always")
        conflicts = self.bd.find_conflicts(similarity_threshold=0.6)
        self.assertGreaterEqual(len(conflicts), 1)
        c = conflicts[0]
        for key in ("type", "node_a", "node_b", "title_a", "title_b",
                    "similarity", "reason"):
            self.assertIn(key, c, f"conflict dict 缺 {key}")
        self.assertIn(c["type"], ("duplicate", "contradiction"))
        self.assertIsInstance(c["similarity"], float)
        self.assertGreaterEqual(c["similarity"], 0.6)
        self.assertLessEqual(c["similarity"],    1.0)

    def test_F10_results_sorted_by_similarity_desc(self):
        # 建立多組 duplicate 對，相似度不同
        self._add("a1", "use async await pattern for IO in javascript",
                  "async io pattern")
        self._add("a2", "use async await pattern for IO in javascript",
                  "async io everywhere")  # 100% 相似 title
        self._add("b1", "use callback pattern for legacy code",
                  "legacy callback handler")
        self._add("b2", "use callback pattern for legacy code projects",
                  "callback for older code")  # 部分相似

        conflicts = self.bd.find_conflicts(similarity_threshold=0.5)
        # 同類型（都是 duplicate）下，similarity 應降序
        dupes = [c for c in conflicts if c["type"] == "duplicate"]
        sims  = [c["similarity"] for c in dupes]
        self.assertEqual(sims, sorted(sims, reverse=True))

    def test_F11_results_capped_at_50(self):
        # 建立 60 組 near-duplicate (共 120 個節點)
        for i in range(60):
            self._add(f"a{i}", f"Pattern group {i} should be used correctly always",
                      "use this pattern")
            self._add(f"b{i}", f"Pattern group {i} should be used correctly often",
                      "apply this pattern")
        conflicts = self.bd.find_conflicts(similarity_threshold=0.7)
        self.assertLessEqual(len(conflicts), 50,
                             f"find_conflicts 應限制輸出 ≤ 50，實際 {len(conflicts)}")


# ══════════════════════════════════════════════════════════════════
#  F-12 ~ F-14  去重與一致性
# ══════════════════════════════════════════════════════════════════

class TestDeduplication(_BrainDBFixture):

    def test_F12_symmetric_pair_counted_once(self):
        """(a,b) 和 (b,a) 是同一對，不該出現兩次"""
        self._add("n1", "Redis cluster mode should use consistent hashing",
                  "consistent hashing avoids hotspots")
        self._add("n2", "Redis cluster mode should use consistent hashing",
                  "avoids hotspots in distributed cache")
        conflicts = self.bd.find_conflicts(similarity_threshold=0.6)
        # 同一 pair 最多出現一次
        pairs = [(c["node_a"], c["node_b"]) for c in conflicts]
        normalised = {tuple(sorted(p)) for p in pairs}
        self.assertEqual(len(pairs), len(normalised))

    def test_F13_node_not_compared_with_itself(self):
        self._add("self", "Self referential rule test case",
                  "this rule refers to itself")
        conflicts = self.bd.find_conflicts(similarity_threshold=0.5)
        for c in conflicts:
            self.assertNotEqual(c["node_a"], c["node_b"],
                                "節點不應與自己比對")

    def test_F14_similarity_threshold_respected(self):
        self._add("n1", "apple banana cherry date elderberry",
                  "content A")
        self._add("n2", "apple banana cherry date fig",  # 4/6 = 0.67 overlap
                  "content B")
        # threshold=0.8 → 不應回傳
        self.assertEqual(len(self.bd.find_conflicts(similarity_threshold=0.8)), 0)
        # threshold=0.5 → 應該回傳
        self.assertGreaterEqual(
            len(self.bd.find_conflicts(similarity_threshold=0.5)), 1,
        )


# ══════════════════════════════════════════════════════════════════
#  F-15 ~ F-17  HIGH-03 核心效果：> 500 節點不再被截斷
# ══════════════════════════════════════════════════════════════════

class TestScaleBeyond500(_BrainDBFixture):

    def test_F15_conflict_detected_beyond_500_nodes(self):
        """
        關鍵驗收：建立 600 個無關節點 + 2 個衝突節點（最後加入），
        原本的 LIMIT 500 會 skip 掉後面加入的衝突對；HIGH-03 修法後能偵測到。
        """
        # 600 個無關節點
        for i in range(600):
            self._add(f"noise-{i}",
                      f"Noise topic {i} about unrelated subject matter {i}",
                      f"content noise {i}")
        # 2 個衝突節點（會排在最後）
        self._add("conflict-a", "Services must use mTLS between them",
                  "mutual TLS required for inter-service calls")
        self._add("conflict-b", "Services must use mTLS between them always",
                  "mTLS is mandatory between all services")

        conflicts = self.bd.find_conflicts(similarity_threshold=0.7)
        # 必須偵測到 conflict-a / conflict-b 的衝突
        pair_ids = [
            tuple(sorted((c["node_a"], c["node_b"])))
            for c in conflicts
        ]
        expected = tuple(sorted(("conflict-a", "conflict-b")))
        self.assertIn(expected, pair_ids,
                      "HIGH-03: > 500 節點時仍應偵測到最後加入的衝突對")

    def test_F16_runtime_reasonable_at_1000_nodes(self):
        """
        1000 節點的 find_conflicts 應在合理時間內完成（< 30 秒）。
        這是性能 smoke test，不是 benchmark — 目的是確保沒有退化到 O(n²)。
        """
        for i in range(1000):
            self._add(f"bulk-{i}", f"Topic {i} subject matter overview",
                      f"body {i}")
        t0 = time.monotonic()
        self.bd.find_conflicts(similarity_threshold=0.7)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 30.0,
                        f"find_conflicts(1000 nodes) 耗時 {elapsed:.2f}s — "
                        f"疑似退化到 O(n²)")

    def test_F17_no_trace_pollution(self):
        """
        HIGH-03: 內部 _find_conflict_candidates 不應寫 traces 表
        （與 search_nodes 不同，避免每次 find_conflicts 在 traces 留下
        數千筆無意義的記錄）。
        """
        for i in range(50):
            self._add(f"n{i}", f"Topic {i} subject content", f"body")
        # 先清空 traces
        try:
            self.bd.conn.execute("DELETE FROM traces")
            self.bd.conn.commit()
        except Exception:
            self.skipTest("traces table 不可用於此 DB version")

        self.bd.find_conflicts(similarity_threshold=0.7)
        count = self.bd.conn.execute(
            "SELECT COUNT(*) FROM traces"
        ).fetchone()[0]
        self.assertEqual(count, 0,
                         f"_find_conflict_candidates 不應寫 traces，"
                         f"但實際寫入 {count} 筆")


# ══════════════════════════════════════════════════════════════════
#  F-18 ~ F-20  Edge cases
# ══════════════════════════════════════════════════════════════════

class TestEdgeCases(_BrainDBFixture):

    def test_F18_empty_title_ignored(self):
        """
        空 title 的節點應該被安全略過（不拋錯、不當 anchor）。
        用直接 SQL 插入因為 add_node 會套用 n-gram 處理。
        """
        self._add("valid", "valid rule title", "content")
        # 直接塞一個空 title 的節點
        self.bd.conn.execute(
            "INSERT INTO nodes(id, type, title, content, confidence, created_at)"
            " VALUES(?, 'Rule', '', '', 0.8, datetime('now'))",
            ("empty-title",),
        )
        self.bd.conn.commit()
        # 不應拋例外
        conflicts = self.bd.find_conflicts(similarity_threshold=0.5)
        # 空 title 節點不會成為任何 pair
        for c in conflicts:
            self.assertNotEqual(c["node_a"], "empty-title")
            self.assertNotEqual(c["node_b"], "empty-title")

    def test_F19_candidates_per_anchor_limits_work(self):
        """candidates_per_anchor 參數應影響結果集（k 越大越多潛在 pair）"""
        # 建立 20 個近似 duplicate
        for i in range(20):
            self._add(f"dup-{i}",
                      f"Kubernetes pod security context mandatory field {i}",
                      "pod security")
        # k=3 只查 3 個候選者；k=15 查 15 個
        small_k = self.bd.find_conflicts(similarity_threshold=0.6,
                                         candidates_per_anchor=3)
        large_k = self.bd.find_conflicts(similarity_threshold=0.6,
                                         candidates_per_anchor=15)
        # large_k 應該發現 >= small_k 的衝突數量
        self.assertGreaterEqual(len(large_k), len(small_k))

    def test_F20_find_conflicts_is_idempotent(self):
        """重複呼叫 find_conflicts 應回傳相同結果（無副作用）"""
        self._add("n1", "Database transactions must use isolation level serializable",
                  "use SERIALIZABLE for financial transactions")
        self._add("n2", "Database transactions must use isolation level serializable always",
                  "SERIALIZABLE isolation for money transfers")
        r1 = self.bd.find_conflicts(similarity_threshold=0.6)
        r2 = self.bd.find_conflicts(similarity_threshold=0.6)
        self.assertEqual(len(r1), len(r2))
        # 同一組 pair
        pairs1 = {tuple(sorted((c["node_a"], c["node_b"]))) for c in r1}
        pairs2 = {tuple(sorted((c["node_a"], c["node_b"]))) for c in r2}
        self.assertEqual(pairs1, pairs2)


if __name__ == "__main__":
    unittest.main()
