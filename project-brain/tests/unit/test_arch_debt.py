"""
tests/unit/test_arch_debt.py

架構債修復驗收 — traces 採樣、backup 保留設定、search 契約不變

覆蓋：
  - traces 採樣：search_nodes 不再每次寫 trace
  - backup 保留天數：env / config.json / default
  - search_nodes 功能不受 refactor 影響
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project_brain.core.brain_db import BrainDB


class _DBFixture(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self._tmp.name)
        self.db = BrainDB(self.brain_dir)

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass
        self._tmp.cleanup()

    def _add(self, nid, title, kind="Rule", confidence=0.8):
        self.db.add_node(
            node_id=nid, node_type=kind,
            title=title, content=f"Content for {title}",
            tags=[], confidence=confidence,
        )


# ═══════════════════════════════════════════════════════════════════
#  Trace sampling
# ═══════════════════════════════════════════════════════════════════

class TestTraceSampling(_DBFixture):

    def test_trace_not_written_every_search(self):
        """With sample_rate=5, only 1 in 5 searches writes a trace."""
        self.db._ctx._trace_sample_rate = 5
        self.db._ctx._trace_counter = 0
        self._add("n1", "Test rule for searching")

        # Run 4 searches — should not write any trace (counter 1,2,3,4)
        for _ in range(4):
            self.db.search_nodes("Test")

        trace_count = self.db.conn.execute(
            "SELECT COUNT(*) FROM traces"
        ).fetchone()[0]
        self.assertEqual(trace_count, 0, "No trace should be written for first 4 searches")

    def test_trace_written_on_nth_search(self):
        """The Nth search (matching sample_rate) writes a trace."""
        self.db._ctx._trace_sample_rate = 3
        self.db._ctx._trace_counter = 0
        self._add("n1", "Test rule for tracing")

        # 3 searches — trace on 3rd
        for _ in range(3):
            self.db.search_nodes("Test")

        trace_count = self.db.conn.execute(
            "SELECT COUNT(*) FROM traces"
        ).fetchone()[0]
        self.assertEqual(trace_count, 1, "One trace should be written after 3 searches")

    def test_trace_sample_rate_1_writes_every_time(self):
        """sample_rate=1 preserves original behavior (write every search)."""
        self.db._ctx._trace_sample_rate = 1
        self.db._ctx._trace_counter = 0
        self._add("n1", "Test rule")

        for _ in range(5):
            self.db.search_nodes("Test")

        trace_count = self.db.conn.execute(
            "SELECT COUNT(*) FROM traces"
        ).fetchone()[0]
        self.assertEqual(trace_count, 5)

    def test_trace_sample_rate_from_env(self):
        """BRAIN_TRACE_SAMPLE_RATE env var controls sampling."""
        with mock.patch.dict(os.environ, {"BRAIN_TRACE_SAMPLE_RATE": "10"}):
            db2 = BrainDB(self.brain_dir)
            self.assertEqual(db2._trace_sample_rate, 10)
            db2.conn.close()

    def test_default_trace_sample_rate(self):
        """Default sample rate is 5."""
        self.assertEqual(self.db._ctx._trace_sample_rate, 5)

    def test_search_still_returns_results_with_sampling(self):
        """Sampling doesn't affect search results."""
        self.db._ctx._trace_sample_rate = 100
        self._add("n1", "JWT signing rule")
        results = self.db.search_nodes("JWT")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["id"], "n1")


# ═══════════════════════════════════════════════════════════════════
#  Backup retention
# ═══════════════════════════════════════════════════════════════════

class TestBackupRetention(_DBFixture):

    def test_default_keep_count(self):
        """Default backup retention is 7."""
        self.assertEqual(self.db._backup_keep_count(), 7)

    def test_env_override(self):
        """BRAIN_BACKUP_KEEP env var overrides default."""
        with mock.patch.dict(os.environ, {"BRAIN_BACKUP_KEEP": "3"}):
            self.assertEqual(self.db._backup_keep_count(), 3)

    def test_env_minimum_1(self):
        """Retention cannot go below 1."""
        with mock.patch.dict(os.environ, {"BRAIN_BACKUP_KEEP": "0"}):
            self.assertEqual(self.db._backup_keep_count(), 1)

    def test_config_json_override(self):
        """config.json backup_keep overrides default."""
        cfg_path = self.brain_dir / "config.json"
        cfg_path.write_text(json.dumps({"backup_keep": 14}))
        # Clear env to test config.json fallback
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.db._backup_keep_count(), 14)

    def test_env_beats_config(self):
        """Env var takes priority over config.json."""
        cfg_path = self.brain_dir / "config.json"
        cfg_path.write_text(json.dumps({"backup_keep": 14}))
        with mock.patch.dict(os.environ, {"BRAIN_BACKUP_KEEP": "3"}):
            self.assertEqual(self.db._backup_keep_count(), 3)

    def test_invalid_env_falls_through(self):
        """Invalid env value falls through to config/default."""
        with mock.patch.dict(os.environ, {"BRAIN_BACKUP_KEEP": "abc"}):
            self.assertEqual(self.db._backup_keep_count(), 7)


# ═══════════════════════════════════════════════════════════════════
#  Search contract preservation
# ═══════════════════════════════════════════════════════════════════

class TestSearchContract(_DBFixture):
    """Verify search_nodes behavior unchanged after refactor."""

    def test_basic_search(self):
        self._add("n1", "JWT signing algorithm")
        results = self.db.search_nodes("JWT")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["id"], "n1")

    def test_node_type_filter(self):
        self._add("r1", "Rule about auth", kind="Rule")
        self._add("p1", "Pitfall about auth", kind="Pitfall")
        results = self.db.search_nodes("auth", node_type="Pitfall")
        types = {r["type"] for r in results}
        self.assertFalse(types - {"Pitfall"})

    def test_has_search_score(self):
        self._add("n1", "Test rule")
        results = self.db.search_nodes("Test")
        if results:
            self.assertIn("_search_score", results[0])

    def test_has_effective_confidence(self):
        self._add("n1", "Test rule")
        results = self.db.search_nodes("Test")
        if results:
            self.assertIn("effective_confidence", results[0])

    def test_empty_query_returns_empty(self):
        self.assertEqual(self.db.search_nodes(""), [])


if __name__ == "__main__":
    unittest.main()
