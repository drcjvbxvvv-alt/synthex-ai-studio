"""
tests/unit/test_context_node_id.py

P2-1 修復驗收 — get_context full output 包含 node id

背景：full 模式的知識條目缺少 node id，導致 Agent 無法呼叫
report_knowledge_outcome(node_id=...)。修復後每條知識標題包含
[node_id[:8]]，且 footer 有結構化 Sources block。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from project_brain.core.brain_db import BrainDB
from project_brain.graph import KnowledgeGraph
from project_brain.engines.context import ContextEngineer


class _ContextFixture(unittest.TestCase):
    """Build a temporary BrainDB + KnowledgeGraph + ContextEngineer."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self._tmp.name)
        self.db = BrainDB(self.brain_dir)
        self.graph = KnowledgeGraph(self.brain_dir, conn=self.db.conn)
        self.ctx = ContextEngineer(self.graph, brain_dir=self.brain_dir)

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass
        self._tmp.cleanup()

    def _add(self, node_id: str, title: str, content: str = "",
             kind: str = "Rule") -> None:
        self.db.add_node(
            node_id=node_id, node_type=kind,
            title=title, content=content,
            tags=[], confidence=0.8,
        )
        # Also add to graph for search
        self.graph.add_node(node_id, kind, title, content=content)


class TestFullModeNodeId(_ContextFixture):
    """full 模式 output 包含 node id。"""

    def test_node_id_prefix_in_full_output(self):
        """full 模式每條知識標題應包含 [node_id[:8]]。"""
        self._add("pitfall-abc12345", "JWT must validate exp claim",
                   "Always check exp before trusting JWT", "Pitfall")
        result = self.ctx.build("JWT authentication", detail_level="full")
        # node_id[:8] = "pitfall-" should appear in output
        self.assertIn("[pitfall-", result)

    def test_node_id_in_summary_mode(self):
        """summary 模式也應包含 node id（已有功能）。"""
        self._add("rule-xyz98765", "Use RS256 for JWT signing",
                   "Required algorithm", "Rule")
        result = self.ctx.build("JWT", detail_level="summary")
        self.assertIn("[rule-xyz", result)

    def test_sources_block_in_full_output(self):
        """full 模式 footer 應有 Sources block。"""
        self._add("pitfall-aaa11111", "JWT exp validation required",
                   "Check exp claim", "Pitfall")
        result = self.ctx.build("JWT authentication", detail_level="full")
        self.assertIn("Sources", result)
        self.assertIn("report_knowledge_outcome", result)

    def test_sources_contains_full_node_ids(self):
        """Sources block 包含完整 node id（不截斷）。"""
        nid = "pitfall-bbb22222"
        self._add(nid, "Database timeout must be set",
                   "Always configure timeout", "Pitfall")
        result = self.ctx.build("database timeout", detail_level="full")
        # The full node id should be in the Sources block
        self.assertIn(nid, result)


class TestFmtNodeDirectly(_ContextFixture):
    """直接測試 _fmt_node 格式。"""

    def test_fmt_node_includes_node_id(self):
        """_fmt_node output 的第一行應包含 [node_id[:8]]。"""
        node = {
            "id": "rule-12345678abcdef",
            "type": "Rule",
            "title": "Use RS256 for JWT",
            "content": "Required",
            "confidence": 0.9,
        }
        result = self.ctx._fmt_node("📋 業務規則", node)
        first_line = result.split("\n")[0]
        self.assertIn("[rule-123", first_line)

    def test_fmt_node_no_id_graceful(self):
        """node 無 id 時不 crash，不顯示空 []。"""
        node = {
            "type": "Rule",
            "title": "Some rule",
            "content": "Details",
            "confidence": 0.8,
        }
        result = self.ctx._fmt_node("📋 業務規則", node)
        self.assertNotIn("[] ", result)

    def test_fmt_node_empty_id_graceful(self):
        """node id 為空字串時不顯示 []。"""
        node = {
            "id": "",
            "type": "Rule",
            "title": "Some rule",
            "content": "Details",
            "confidence": 0.8,
        }
        result = self.ctx._fmt_node("📋 業務規則", node)
        self.assertNotIn("[] ", result)


class TestEmptyKBNoSources(_ContextFixture):
    """空知識庫不應有 Sources block。"""

    def test_empty_kb_no_sources(self):
        """空知識庫的冷啟動提示不應包含 Sources。"""
        result = self.ctx.build("any task", detail_level="full")
        self.assertNotIn("Sources", result)


if __name__ == "__main__":
    unittest.main()
