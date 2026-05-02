"""
tests/unit/test_ingest_pipeline.py — E-04 IngestPipeline 測試

覆蓋：
  - heuristic extraction（無 LLM）
  - LLM extraction（mock LLM）
  - dedup 跳過重複
  - confidence routing（≥ 0.7 → L3, < 0.7 → staging）
  - dry-run mode
  - error handling
  - IngestResult counters
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project_brain.integrations.ingest.base import (
    IngestResult, KnowledgeCandidate, RawDocument,
)
from project_brain.integrations.ingest.pipeline import IngestPipeline


def _make_doc(title="Test Doc", content="Test content.", source="test",
              metadata=None) -> RawDocument:
    return RawDocument(
        source=source, title=title, content=content,
        url="test://test", metadata=metadata or {},
    )


def _make_brain(tmp_path):
    """Create a minimal ProjectBrain for testing."""
    from project_brain.engine import ProjectBrain
    return ProjectBrain(str(tmp_path))


class TestHeuristicExtraction(unittest.TestCase):
    """Heuristic extraction without LLM."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = _make_brain(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_basic_extraction(self):
        pipeline = IngestPipeline(self.brain, llm_client=None)
        doc = _make_doc("Auth Bug", "The login crashes when session expires.")
        result = pipeline.run([doc], dry_run=True)
        self.assertEqual(result.documents_scanned, 1)
        self.assertEqual(result.candidates_extracted, 1)

    def test_pitfall_detected_from_keywords(self):
        pipeline = IngestPipeline(self.brain, llm_client=None)
        doc = _make_doc("Connection Error", "The database connection fails under load.")
        candidates = pipeline._extract(doc)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].kind, "Pitfall")

    def test_decision_detected_from_keywords(self):
        pipeline = IngestPipeline(self.brain, llm_client=None)
        doc = _make_doc("Architecture Decision", "We choose PostgreSQL for ACID guarantees.")
        candidates = pipeline._extract(doc)
        self.assertEqual(candidates[0].kind, "Decision")

    def test_rule_detected_from_keywords(self):
        pipeline = IngestPipeline(self.brain, llm_client=None)
        doc = _make_doc("API Convention", "All endpoints must use versioned paths.")
        candidates = pipeline._extract(doc)
        self.assertEqual(candidates[0].kind, "Rule")

    def test_kind_hint_from_metadata(self):
        pipeline = IngestPipeline(self.brain, llm_client=None)
        doc = _make_doc("Some Issue", "Description", metadata={"kind_hint": "Pitfall"})
        candidates = pipeline._extract(doc)
        self.assertEqual(candidates[0].kind, "Pitfall")

    def test_empty_content_skipped(self):
        pipeline = IngestPipeline(self.brain, llm_client=None)
        doc = _make_doc("", "", source="empty")
        candidates = pipeline._extract(doc)
        self.assertEqual(len(candidates), 0)

    def test_github_labels_as_tags(self):
        pipeline = IngestPipeline(self.brain, llm_client=None)
        doc = _make_doc("Issue", "Body", metadata={"labels": ["bug", "auth"]})
        candidates = pipeline._extract(doc)
        self.assertIn("bug", candidates[0].tags)
        self.assertIn("auth", candidates[0].tags)


class TestLLMExtraction(unittest.TestCase):
    """LLM extraction with mock client."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = _make_brain(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_llm_json_parsed(self):
        mock_llm = mock.MagicMock()
        mock_llm.complete.return_value = json.dumps([{
            "title": "LLM Extracted",
            "content": "LLM extracted content.",
            "kind": "Decision",
            "confidence": 0.8,
            "tags": ["arch"],
        }])

        pipeline = IngestPipeline(self.brain, llm_client=mock_llm, llm_rate_limit_rpm=600)
        doc = _make_doc("Source Doc", "Raw source content.")
        candidates = pipeline._extract(doc)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "LLM Extracted")
        self.assertEqual(candidates[0].kind, "Decision")
        self.assertAlmostEqual(candidates[0].confidence, 0.8)

    def test_llm_returns_code_fenced_json(self):
        mock_llm = mock.MagicMock()
        mock_llm.complete.return_value = '```json\n[{"title":"Fenced","content":"Body","kind":"Rule","confidence":0.7,"tags":[]}]\n```'

        pipeline = IngestPipeline(self.brain, llm_client=mock_llm, llm_rate_limit_rpm=600)
        candidates = pipeline._extract(_make_doc("X", "Y"))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "Fenced")

    def test_llm_failure_falls_back_to_heuristic(self):
        mock_llm = mock.MagicMock()
        mock_llm.complete.side_effect = RuntimeError("LLM down")

        pipeline = IngestPipeline(self.brain, llm_client=mock_llm, llm_rate_limit_rpm=600)
        candidates = pipeline._extract(_make_doc("Bug Report", "Something crashed."))
        self.assertEqual(len(candidates), 1)
        # Should fall back to heuristic
        self.assertIn(candidates[0].kind, ("Pitfall", "Note"))

    def test_llm_returns_garbage_falls_back(self):
        mock_llm = mock.MagicMock()
        mock_llm.complete.return_value = "Sorry, I can't help with that."

        pipeline = IngestPipeline(self.brain, llm_client=mock_llm, llm_rate_limit_rpm=600)
        candidates = pipeline._extract(_make_doc("Doc", "Content"))
        self.assertEqual(len(candidates), 1)  # heuristic fallback


class TestDedup(unittest.TestCase):
    """Dedup skips existing nodes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = _make_brain(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_exact_title_deduped(self):
        # Add existing node
        self.brain.add_knowledge(title="Existing Rule", content="Already there.", kind="Rule")

        pipeline = IngestPipeline(self.brain, llm_client=None)
        doc = _make_doc("Existing Rule", "Duplicate content.")
        result = pipeline.run([doc])
        self.assertEqual(result.duplicates_skipped, 1)
        self.assertEqual(result.total_written, 0)

    def test_novel_node_not_deduped(self):
        pipeline = IngestPipeline(self.brain, llm_client=None)
        doc = _make_doc("Completely New Topic", "Fresh content about something new.")
        result = pipeline.run([doc])
        self.assertEqual(result.duplicates_skipped, 0)
        self.assertGreater(result.total_written, 0)


class TestConfidenceRouting(unittest.TestCase):
    """Confidence ≥ 0.7 → L3, < 0.7 → staging."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = _make_brain(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_high_confidence_goes_to_l3(self):
        pipeline = IngestPipeline(self.brain, llm_client=None)
        # Heuristic with closed issue + comments → 0.65, but we override threshold
        doc = _make_doc("High Conf Rule", "Must use HTTPS everywhere.", metadata={"kind_hint": "Rule"})
        result = pipeline.run([doc], auto_approve_threshold=0.3)  # low threshold → L3
        self.assertGreater(result.written_to_l3, 0)

    def test_low_confidence_goes_to_staging_or_l3(self):
        pipeline = IngestPipeline(self.brain, llm_client=None)
        doc = _make_doc("Generic Note", "Some general info.")
        # Heuristic confidence is 0.5, threshold 0.7 → staging (or L3 if no KRB)
        result = pipeline.run([doc], auto_approve_threshold=0.7)
        self.assertGreater(result.total_written, 0)


class TestDryRun(unittest.TestCase):
    """Dry run extracts but doesn't write."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = _make_brain(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_dry_run_no_writes(self):
        pipeline = IngestPipeline(self.brain, llm_client=None)
        docs = [_make_doc(f"Doc {i}", f"Content {i}") for i in range(5)]
        result = pipeline.run(docs, dry_run=True)
        self.assertEqual(result.documents_scanned, 5)
        self.assertEqual(result.candidates_extracted, 5)
        self.assertEqual(result.total_written, 0)

        # Verify nothing was written to DB
        count = self.brain.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count, 0)


class TestIngestResult(unittest.TestCase):

    def test_total_written(self):
        r = IngestResult(written_to_l3=3, written_to_staging=2)
        self.assertEqual(r.total_written, 5)

    def test_empty_result(self):
        r = IngestResult()
        self.assertEqual(r.total_written, 0)
        self.assertEqual(r.errors, [])


if __name__ == "__main__":
    unittest.main()
