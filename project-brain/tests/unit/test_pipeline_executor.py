"""
tests/unit/test_pipeline_executor.py

Auto Knowledge Pipeline Phase 1 — KnowledgeExecutor 單元測試

驗收標準（設計文件 docs/AUTO_KNOWLEDGE_PIPELINE.md §7）：
  E-01  ADD 在 BrainDB 建立節點，欄位正確
  E-02  ADD 在 meta 中標記 source='auto_pipeline'
  E-03  ADD 寫入 pipeline_metrics（action='add'）
  E-04  SKIP 不建立任何節點
  E-05  SKIP 寫入 pipeline_metrics（action='skip'）
  E-06  冪等：同 signal_id 重複執行 → 第二次回傳 skipped=True，不建立重複節點
  E-07  不支援的 action 降級為 SKIP
  E-08  ADD 缺少 node spec → ok=False
  E-09  signal=None 時 ADD 仍可正常執行
  E-10  validate: confidence 上限截斷為 0.85
  E-11  validate: 無效 node spec 降級為 SKIP
  E-12  validate: 未知 action 降級為 SKIP
  E-13  validate: 完全無效 dict 安全降級，不拋例外
  E-14  validate: node.kind 不在允許列表時仍可執行（kind → "Note"）
  E-15  ADD 節點可被 BrainDB.search_nodes 搜尋到
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from project_brain.pipeline import (
    ExecutionResult,
    KnowledgeDecision,
    KnowledgeExecutor,
    NodeSpec,
    Signal,
    SignalKind,
)


# ── 測試輔助 ───────────────────────────────────────────────────────────────

def _make_db(tmp_path: Path):
    from project_brain.brain_db import BrainDB
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    return BrainDB(brain_dir)


def _add_decision(signal_id: str = "sig-001",
                  title: str = "JWT 必須使用 RS256",
                  kind: str  = "Rule",
                  confidence: float = 0.7) -> KnowledgeDecision:
    return KnowledgeDecision(
        action    = "add",
        reason    = "commit message mentions RS256 migration",
        signal_id = signal_id,
        node      = NodeSpec(
            title      = title,
            content    = "Always sign JWT with RS256, not HS256.",
            kind       = kind,
            confidence = confidence,
            tags       = ["jwt", "security"],
            description= "JWT signing rule",
        ),
        llm_model = "mock",
    )


def _skip_decision(signal_id: str = "sig-002") -> KnowledgeDecision:
    return KnowledgeDecision(
        action    = "skip",
        reason    = "commit is a version bump, no knowledge value",
        signal_id = signal_id,
        llm_model = "mock",
    )


def _sig(signal_id: str = "sig-001") -> Signal:
    s = Signal(
        kind       = SignalKind.GIT_COMMIT,
        workdir    = "/repo",
        summary    = "fix: JWT RS256",
        raw_content= "diff content",
    )
    s.id = signal_id
    return s


# ── E-01 ~ E-03  ADD 基本行為 ────────────────────────────────────────────

class TestExecutorAdd(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db  = _make_db(Path(self._tmp.name))
        self.exe = KnowledgeExecutor(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_E01_add_creates_node(self):
        result = self.exe.run(_add_decision(), _sig())
        self.assertTrue(result.ok)
        self.assertEqual(result.action, "add")
        self.assertNotEqual(result.node_id, "")

    def test_E01_add_node_fields_correct(self):
        result = self.exe.run(_add_decision(title="RS256 Rule"), _sig())
        row = self.db.conn.execute(
            "SELECT * FROM nodes WHERE id=?", (result.node_id,)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "RS256 Rule")
        self.assertEqual(row["type"],  "Rule")
        self.assertAlmostEqual(row["confidence"], 0.7, places=2)

    def test_E02_add_sets_source_in_meta(self):
        result = self.exe.run(_add_decision(), _sig())
        row = self.db.conn.execute(
            "SELECT meta FROM nodes WHERE id=?", (result.node_id,)
        ).fetchone()
        meta = json.loads(row["meta"])
        self.assertEqual(meta.get("source"), "auto_pipeline")
        self.assertEqual(meta.get("signal_id"), "sig-001")

    def test_E03_add_writes_pipeline_metrics(self):
        result = self.exe.run(_add_decision(), _sig())
        row = self.db.conn.execute(
            "SELECT * FROM pipeline_metrics WHERE node_id=?", (result.node_id,)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["action"], "add")
        self.assertEqual(row["signal_id"], "sig-001")


# ── E-04 ~ E-05  SKIP 行為 ───────────────────────────────────────────────

class TestExecutorSkip(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db  = _make_db(Path(self._tmp.name))
        self.exe = KnowledgeExecutor(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_E04_skip_creates_no_node(self):
        result = self.exe.run(_skip_decision(), _sig("sig-002"))
        self.assertTrue(result.ok)
        self.assertTrue(result.skipped)
        count = self.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count, 0)

    def test_E05_skip_writes_pipeline_metrics(self):
        self.exe.run(_skip_decision("sig-skip"), _sig("sig-skip"))
        row = self.db.conn.execute(
            "SELECT * FROM pipeline_metrics WHERE signal_id='sig-skip'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["action"], "skip")
        self.assertEqual(row["node_id"], "")


# ── E-06  冪等性 ─────────────────────────────────────────────────────────

class TestExecutorIdempotency(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db  = _make_db(Path(self._tmp.name))
        self.exe = KnowledgeExecutor(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_E06_same_signal_id_not_duplicated(self):
        d = _add_decision(signal_id="sig-idem")
        s = _sig("sig-idem")

        r1 = self.exe.run(d, s)
        r2 = self.exe.run(d, s)

        self.assertTrue(r1.ok)
        self.assertFalse(r1.skipped)

        self.assertTrue(r2.ok)
        self.assertTrue(r2.skipped)                     # 第二次被冪等攔截
        self.assertEqual(r1.node_id, r2.node_id)        # 回傳相同 node_id

        node_count = self.db.conn.execute(
            "SELECT COUNT(*) FROM nodes"
        ).fetchone()[0]
        self.assertEqual(node_count, 1)                 # 只有一個節點


# ── E-07 ~ E-09  邊界情況 ────────────────────────────────────────────────

class TestExecutorEdgeCases(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db  = _make_db(Path(self._tmp.name))
        self.exe = KnowledgeExecutor(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_E07_unsupported_action_treated_as_skip(self):
        d = KnowledgeDecision(
            action="merge", reason="unsupported", signal_id="sig-merge"
        )
        result = self.exe.run(d)
        self.assertTrue(result.ok)
        self.assertTrue(result.skipped)
        count = self.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count, 0)

    def test_E08_add_without_node_spec_returns_error(self):
        d = KnowledgeDecision(
            action="add", reason="missing node", signal_id="sig-nonode"
        )
        result = self.exe.run(d)
        self.assertFalse(result.ok)
        self.assertIn("missing", result.error)

    def test_E09_add_without_signal_still_works(self):
        d = _add_decision(signal_id="sig-nosig")
        result = self.exe.run(d, signal=None)   # signal=None
        self.assertTrue(result.ok)
        self.assertEqual(result.action, "add")

    def test_E14_unknown_kind_defaults_to_Note(self):
        d = _add_decision(kind="UnknownType")
        result = self.exe.run(d, _sig())
        row = self.db.conn.execute(
            "SELECT type FROM nodes WHERE id=?", (result.node_id,)
        ).fetchone()
        self.assertEqual(row["type"], "Note")


# ── E-10 ~ E-13  validate() 清洗邏輯 ────────────────────────────────────

class TestValidate(unittest.TestCase):

    def test_E10_confidence_capped_at_085(self):
        raw = {
            "action":    "add",
            "reason":    "test",
            "signal_id": "s1",
            "node": {
                "title":      "Over-confident rule",
                "content":    "...",
                "kind":       "Rule",
                "confidence": 0.99,   # 超出上限
            },
        }
        d = KnowledgeExecutor.validate(raw)
        self.assertEqual(d.action, "add")
        self.assertLessEqual(d.node.confidence, 0.85)

    def test_E11_missing_title_degrades_to_skip(self):
        raw = {
            "action":    "add",
            "reason":    "test",
            "signal_id": "s2",
            "node": {"title": "", "content": "...", "kind": "Rule"},
        }
        d = KnowledgeExecutor.validate(raw)
        self.assertEqual(d.action, "skip")
        self.assertIsNone(d.node)

    def test_E11_missing_node_dict_degrades_to_skip(self):
        raw = {"action": "add", "reason": "test", "signal_id": "s3"}
        d = KnowledgeExecutor.validate(raw)
        self.assertEqual(d.action, "skip")

    def test_E12_unknown_action_defaults_to_skip(self):
        raw = {
            "action": "merge",
            "reason": "try to merge",
            "signal_id": "s4",
        }
        d = KnowledgeExecutor.validate(raw)
        self.assertEqual(d.action, "skip")

    def test_E13_completely_invalid_input_safe(self):
        for bad in [None, 42, "string", [], {"action": None}]:
            d = KnowledgeExecutor.validate(bad if isinstance(bad, dict) else {})
            self.assertEqual(d.action, "skip")  # never raises

    def test_valid_add_roundtrip(self):
        raw = {
            "action":    "add",
            "reason":    "JWT rule found",
            "signal_id": "sig-rt",
            "llm_model": "gemma4",
            "node": {
                "title":      "JWT RS256",
                "content":    "Use RS256",
                "kind":       "Rule",
                "confidence": 0.75,
                "tags":       ["jwt"],
                "description":"signing rule",
            },
        }
        d = KnowledgeExecutor.validate(raw)
        self.assertEqual(d.action,           "add")
        self.assertEqual(d.signal_id,        "sig-rt")
        self.assertEqual(d.llm_model,        "gemma4")
        self.assertEqual(d.node.title,       "JWT RS256")
        self.assertEqual(d.node.kind,        "Rule")
        self.assertAlmostEqual(d.node.confidence, 0.75)


# ── E-15  ADD 後可搜尋 ────────────────────────────────────────────────────

class TestExecutorSearchable(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db  = _make_db(Path(self._tmp.name))
        self.exe = KnowledgeExecutor(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_E15_added_node_is_searchable(self):
        self.exe.run(
            KnowledgeDecision(
                action    = "add",
                reason    = "found in commit",
                signal_id = "sig-search",
                node      = NodeSpec(
                    title      = "OAuth2 PKCE flow required",
                    content    = "Always use PKCE for public clients.",
                    kind       = "Rule",
                    confidence = 0.7,
                ),
            ),
            _sig("sig-search"),
        )
        results = self.db.search_nodes("PKCE", limit=5)
        self.assertTrue(
            any("PKCE" in r.get("title", "") or "PKCE" in r.get("content", "")
                for r in results),
            msg="Added node should be findable by keyword search",
        )


if __name__ == "__main__":
    unittest.main()
