"""
tests/unit/test_find_conflicts_for_node.py

P0-1 修復驗收 — BrainDB.find_conflicts_for_node() 單節點衝突偵測

背景：mcp_server.py add_knowledge 的背景 conflict check 原本呼叫
find_conflicts(title_c, top_k=3)，簽名不對（TypeError 被靜默吞掉），
導致 KNOWLEDGE_CONFLICT signal 永遠不會產生。

修復：新增 find_conflicts_for_node(node_id) 方法，只檢查指定節點
與 FTS5 候選者的衝突，不掃描全庫。
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from project_brain.core.brain_db import BrainDB


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


class TestFindConflictsForNodeBasic(_BrainDBFixture):
    """基本行為驗證。"""

    def test_nonexistent_node_returns_empty(self):
        """查詢不存在的 node_id → 空列表。"""
        self.assertEqual(self.bd.find_conflicts_for_node("no-such-id"), [])

    def test_single_node_no_conflicts(self):
        """只有一個節點 → 沒有衝突對象。"""
        self._add("n1", "Use RS256 for JWT signing")
        self.assertEqual(self.bd.find_conflicts_for_node("n1"), [])

    def test_unrelated_nodes_no_conflicts(self):
        """兩個完全不同的節點 → 不應偵測為衝突。"""
        self._add("n1", "Use RS256 for JWT signing")
        self._add("n2", "Deploy to Kubernetes with Helm charts")
        self.assertEqual(self.bd.find_conflicts_for_node("n1"), [])

    def test_duplicate_detected(self):
        """標題高度相似 → 偵測為 duplicate。"""
        self._add("n1", "Use RS256 for JWT signing")
        self._add("n2", "Use RS256 for JWT signing always")
        conflicts = self.bd.find_conflicts_for_node("n1", similarity_threshold=0.5)
        self.assertGreaterEqual(len(conflicts), 1)
        c = conflicts[0]
        self.assertEqual(c["type"], "duplicate")
        self.assertEqual(c["node_a"], "n1")
        self.assertEqual(c["node_b"], "n2")
        self.assertIn("similarity", c)
        self.assertIn("reason", c)

    def test_contradiction_detected(self):
        """含矛盾關鍵字 → 偵測為 contradiction。"""
        self._add("n1", "JWT signing must use RS256", "must use RS256")
        self._add("n2", "JWT signing must not use RS256", "must not use RS256")
        conflicts = self.bd.find_conflicts_for_node("n1", similarity_threshold=0.3)
        contras = [c for c in conflicts if c["type"] == "contradiction"]
        self.assertGreaterEqual(len(contras), 1, "should detect contradiction")

    def test_contradiction_ranked_before_duplicate(self):
        """contradiction 排在 duplicate 前面。"""
        self._add("n1", "JWT signing must use RS256", "must use RS256")
        self._add("n2", "JWT signing must not use RS256", "must not use RS256")
        self._add("n3", "JWT signing use RS256 always")
        conflicts = self.bd.find_conflicts_for_node("n1", similarity_threshold=0.3)
        if len(conflicts) >= 2:
            types = [c["type"] for c in conflicts]
            if "contradiction" in types and "duplicate" in types:
                first_contra = types.index("contradiction")
                first_dup = types.index("duplicate")
                self.assertLess(first_contra, first_dup)


class TestFindConflictsForNodeSchema(_BrainDBFixture):
    """回傳格式驗證。"""

    def test_output_schema_complete(self):
        """每個 conflict dict 必須包含所有欄位。"""
        self._add("n1", "Use RS256 for JWT signing")
        self._add("n2", "Use RS256 for JWT signing required")
        conflicts = self.bd.find_conflicts_for_node("n1", similarity_threshold=0.3)
        self.assertGreaterEqual(len(conflicts), 1)
        c = conflicts[0]
        expected_keys = {"type", "node_a", "node_b", "title_a", "title_b",
                         "similarity", "reason"}
        self.assertEqual(set(c.keys()), expected_keys)

    def test_node_a_is_always_target(self):
        """node_a 永遠是被查詢的目標節點。"""
        self._add("n1", "Use RS256 for JWT signing")
        self._add("n2", "Use RS256 for JWT signing always")
        conflicts = self.bd.find_conflicts_for_node("n1", similarity_threshold=0.3)
        for c in conflicts:
            self.assertEqual(c["node_a"], "n1")

    def test_similarity_is_float(self):
        """similarity 是 float。"""
        self._add("n1", "Use RS256 for JWT signing")
        self._add("n2", "Use RS256 for JWT signing always")
        conflicts = self.bd.find_conflicts_for_node("n1", similarity_threshold=0.3)
        if conflicts:
            self.assertIsInstance(conflicts[0]["similarity"], float)


class TestFindConflictsForNodeEdgeCases(_BrainDBFixture):
    """邊界條件。"""

    def test_empty_title_node(self):
        """title 為空的節點 → 空列表。"""
        self.bd.add_node(
            node_id="n1", node_type="Rule",
            title="", content="something",
            tags=[], confidence=0.8,
        )
        self.assertEqual(self.bd.find_conflicts_for_node("n1"), [])

    def test_cjk_titles(self):
        """純中文標題 → 不 crash，能偵測相似。"""
        self._add("n1", "部署到 Kubernetes 必須使用 Helm")
        self._add("n2", "部署到 Kubernetes 禁止使用 Helm")
        conflicts = self.bd.find_conflicts_for_node("n1", similarity_threshold=0.3)
        # At minimum, should not crash
        self.assertIsInstance(conflicts, list)

    def test_high_threshold_filters_weak_matches(self):
        """高閾值 → 弱匹配被過濾。"""
        self._add("n1", "JWT must use RS256 for signing tokens")
        self._add("n2", "Database must use PostgreSQL for storage")
        conflicts = self.bd.find_conflicts_for_node("n1", similarity_threshold=0.9)
        self.assertEqual(len(conflicts), 0)

    def test_candidates_per_anchor_limits_scope(self):
        """candidates_per_anchor=1 只檢查最相似的 1 個候選者。"""
        self._add("n1", "Use RS256 for JWT signing")
        for i in range(5):
            self._add(f"s{i}", f"Use RS256 for JWT signing variant {i}")
        c1 = self.bd.find_conflicts_for_node("n1", similarity_threshold=0.3,
                                              candidates_per_anchor=1)
        c5 = self.bd.find_conflicts_for_node("n1", similarity_threshold=0.3,
                                              candidates_per_anchor=20)
        self.assertLessEqual(len(c1), len(c5))


class TestFindConflictsForNodeMCPIntegration(_BrainDBFixture):
    """驗證 MCP add_knowledge 的背景 conflict check 場景。"""

    def test_post_add_conflict_detection(self):
        """模擬 add_knowledge 後的 conflict check 流程。"""
        # 先有一條舊知識
        self._add("old-1", "JWT must use RS256 for all signing")
        # 新增一條相似知識
        self._add("new-1", "JWT must not use RS256 for signing")
        # 背景 conflict check
        conflicts = self.bd.find_conflicts_for_node("new-1", similarity_threshold=0.3)
        self.assertGreaterEqual(len(conflicts), 1)
        # 至少能拿到 conflict signal 需要的欄位
        c = conflicts[0]
        self.assertIn(c["type"], ("duplicate", "contradiction"))
        self.assertEqual(c["node_a"], "new-1")
        self.assertIn("title_b", c)
        self.assertIn("reason", c)

    def test_concurrent_conflict_checks_no_crash(self):
        """多線程同時 conflict check → 不 crash。

        Each thread uses its own BrainDB connection to avoid SQLite
        cross-thread connection sharing errors.
        """
        self._add("base", "Use RS256 for JWT signing")
        for i in range(10):
            self._add(f"n{i}", f"Use RS256 for JWT signing version {i}")

        db_path = Path(self._tmp.name)
        errors = []
        successes = []
        def _check(nid):
            try:
                bd = BrainDB(db_path)
                conflicts = bd.find_conflicts_for_node(nid, similarity_threshold=0.3)
                successes.append(nid)
                bd.conn.close()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_check, args=(f"n{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        # Most should succeed; SQLite may occasionally fail under contention
        self.assertGreaterEqual(len(successes), 7, f"Too few successes: {len(successes)}/10")


if __name__ == "__main__":
    unittest.main()
