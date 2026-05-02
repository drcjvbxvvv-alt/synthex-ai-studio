"""
tests/unit/test_push_central.py — E-05 Push to Central 測試

覆蓋：
  - select_nodes 篩選邏輯
  - PII 清理
  - push dry-run
  - push 成功/失敗計數
  - CentralBrainClient.add_knowledge（mock）
  - RBAC push_to_central permission
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project_brain.integrations.push_central import PushTransport, PushResult


def _make_brain(tmp_path):
    from project_brain.engine import ProjectBrain
    brain = ProjectBrain(str(tmp_path))
    # Add some test nodes
    brain.add_knowledge(title="JWT 必須驗證過期", content="exp claim 必須檢查", kind="Rule", confidence=0.9)
    brain.add_knowledge(title="資料庫連線池耗盡", content="連線未正確釋放導致 timeout", kind="Pitfall", confidence=0.85)
    brain.add_knowledge(title="選用 PostgreSQL", content="ACID 保證優於 MongoDB", kind="Decision", confidence=0.75)
    brain.add_knowledge(title="低信心筆記", content="待確認的觀察", kind="Note", confidence=0.4)
    return brain


class TestSelectNodes(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = _make_brain(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_select_all_above_threshold(self):
        transport = PushTransport()
        nodes = transport.select_nodes(self.brain.db, min_confidence=0.7)
        self.assertEqual(len(nodes), 3)  # 0.9 + 0.85 + 0.75, not 0.4

    def test_select_by_kind(self):
        transport = PushTransport()
        nodes = transport.select_nodes(self.brain.db, kind="Pitfall", min_confidence=0.5)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["type"], "Pitfall")

    def test_select_high_threshold_filters(self):
        transport = PushTransport()
        nodes = transport.select_nodes(self.brain.db, min_confidence=0.9)
        self.assertEqual(len(nodes), 1)

    def test_select_max_nodes_limit(self):
        transport = PushTransport()
        nodes = transport.select_nodes(self.brain.db, min_confidence=0.5, max_nodes=2)
        self.assertEqual(len(nodes), 2)

    def test_select_empty_when_no_match(self):
        transport = PushTransport()
        nodes = transport.select_nodes(self.brain.db, kind="ADR", min_confidence=0.99)
        self.assertEqual(len(nodes), 0)

    def test_select_ordered_by_confidence_desc(self):
        transport = PushTransport()
        nodes = transport.select_nodes(self.brain.db, min_confidence=0.5)
        confs = [n["confidence"] for n in nodes]
        self.assertEqual(confs, sorted(confs, reverse=True))


class TestSanitizeNodes(unittest.TestCase):

    def test_pii_stripped(self):
        transport = PushTransport()
        nodes = [{
            "id": "n1", "type": "Rule",
            "title": "Contact alice@corp.com for details",
            "content": "Use 10.0.1.5 for internal",
            "confidence": 0.9, "tags": "[]",
        }]
        sanitized = transport.sanitize_nodes(nodes)
        self.assertEqual(len(sanitized), 1)
        self.assertNotIn("alice@corp.com", sanitized[0]["title"])
        self.assertNotIn("10.0.1.5", sanitized[0]["content"])

    def test_empty_title_skipped(self):
        transport = PushTransport()
        nodes = [{"id": "n1", "type": "Note", "title": "", "content": "x", "confidence": 0.5, "tags": "[]"}]
        sanitized = transport.sanitize_nodes(nodes)
        self.assertEqual(len(sanitized), 0)

    def test_kind_field_mapping(self):
        transport = PushTransport()
        nodes = [{"id": "n1", "type": "Pitfall", "title": "Bug", "content": "x", "confidence": 0.5, "tags": "[]"}]
        sanitized = transport.sanitize_nodes(nodes)
        self.assertEqual(sanitized[0]["kind"], "Pitfall")


class TestPreview(unittest.TestCase):

    def test_preview_truncates(self):
        transport = PushTransport()
        nodes = [{"id": "abcdef123456789", "kind": "Rule", "title": "A" * 200, "confidence": 0.9}]
        preview = transport.preview(nodes)
        self.assertEqual(len(preview), 1)
        self.assertLessEqual(len(preview[0]["title"]), 80)
        self.assertLessEqual(len(preview[0]["id"]), 12)


class TestPush(unittest.TestCase):

    def test_push_success(self):
        transport = PushTransport()
        mock_client = mock.MagicMock()
        mock_client.add_knowledge.return_value = {"success": True, "node_id": "central-1"}

        nodes = [
            {"title": "Rule A", "content": "Content A", "kind": "Rule", "confidence": 0.9, "tags": "[]", "source": "test"},
            {"title": "Rule B", "content": "Content B", "kind": "Rule", "confidence": 0.8, "tags": "[]", "source": "test"},
        ]
        result = transport.push(mock_client, nodes)
        self.assertEqual(result.pushed_ok, 2)
        self.assertEqual(result.pushed_fail, 0)
        self.assertEqual(mock_client.add_knowledge.call_count, 2)

    def test_push_partial_failure(self):
        transport = PushTransport()
        mock_client = mock.MagicMock()
        mock_client.add_knowledge.side_effect = [
            {"success": True},
            Exception("Network error"),
        ]
        nodes = [
            {"title": "A", "content": "A", "kind": "Rule", "confidence": 0.9, "tags": "[]", "source": ""},
            {"title": "B", "content": "B", "kind": "Rule", "confidence": 0.8, "tags": "[]", "source": ""},
        ]
        result = transport.push(mock_client, nodes)
        self.assertEqual(result.pushed_ok, 1)
        self.assertEqual(result.pushed_fail, 1)
        self.assertEqual(len(result.errors), 1)

    def test_push_error_response(self):
        transport = PushTransport()
        mock_client = mock.MagicMock()
        mock_client.add_knowledge.return_value = {"error": "permission_denied"}

        nodes = [{"title": "X", "content": "Y", "kind": "Note", "confidence": 0.5, "tags": "[]", "source": ""}]
        result = transport.push(mock_client, nodes)
        self.assertEqual(result.pushed_fail, 1)


class TestParseTags(unittest.TestCase):

    def test_json_list(self):
        self.assertEqual(PushTransport._parse_tags('["a","b"]'), ["a", "b"])

    def test_plain_list(self):
        self.assertEqual(PushTransport._parse_tags(["x", "y"]), ["x", "y"])

    def test_comma_separated(self):
        self.assertEqual(PushTransport._parse_tags("a, b, c"), ["a", "b", "c"])

    def test_empty(self):
        self.assertEqual(PushTransport._parse_tags(""), [])
        self.assertEqual(PushTransport._parse_tags("[]"), [])


class TestRBACPermission(unittest.TestCase):

    def test_push_to_central_requires_contributor(self):
        from project_brain.rbac import has_permission, TOOL_PERMISSIONS
        self.assertEqual(TOOL_PERMISSIONS["push_to_central"], "contributor")
        self.assertTrue(has_permission("contributor", "contributor"))
        self.assertFalse(has_permission("reader", "contributor"))


if __name__ == "__main__":
    unittest.main()
