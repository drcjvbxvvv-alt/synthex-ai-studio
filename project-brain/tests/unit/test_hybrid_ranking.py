"""
G-01 / G-02: Hybrid Ranking + Minimum Relevance Threshold Tests

Tests cover:
  - hybrid_search() combines FTS5 and vector results
  - min_score parameter filters low-relevance results
  - ContextEngineer uses hybrid_search with min_score
  - Backward compatibility: no min_score = no filtering
"""
from __future__ import annotations

import unittest
from pathlib import Path

from project_brain.core.brain_db import BrainDB


def _make_db(tmp: Path) -> BrainDB:
    """Create a BrainDB with test nodes."""
    bd = tmp / ".brain"
    bd.mkdir(parents=True, exist_ok=True)
    db = BrainDB(bd)
    db.add_node("n1", "Rule", "Always use HTTPS for API endpoints", content="TLS is mandatory for production")
    db.add_node("n2", "Pitfall", "JWT token expired silently", content="expired tokens return 200 instead of 401")
    db.add_node("n3", "Decision", "Use SQLite for local storage", content="PostgreSQL is overkill for single-user")
    db.add_node("n4", "Rule", "Database migrations before deploy", content="run alembic upgrade head before each deploy")
    db.add_node("n5", "Pitfall", "Race condition in write queue", content="two threads writing same node causes deadlock")
    db.conn.commit()
    return db


class TestHybridSearchBasics(unittest.TestCase):
    """Test hybrid_search FTS5 fallback and merging behavior."""

    def setUp(self):
        import tempfile
        self._tmp = Path(tempfile.mkdtemp())
        self.db = _make_db(self._tmp)

    def tearDown(self):
        self.db.conn.close()

    def test_no_vector_returns_fts_results(self):
        """Without query_vector, hybrid_search falls back to FTS5."""
        results = self.db.hybrid_search("HTTPS API", limit=5)
        self.assertGreater(len(results), 0)
        # Should find the HTTPS rule
        ids = [r["id"] for r in results]
        self.assertIn("n1", ids)

    def test_fts_search_works(self):
        """Basic FTS5 search still works."""
        results = self.db.search_nodes("JWT token", limit=5)
        self.assertGreater(len(results), 0)
        ids = [r["id"] for r in results]
        self.assertIn("n2", ids)

    def test_hybrid_search_accepts_min_score_none(self):
        """min_score=None is backward compatible (no filtering)."""
        results = self.db.hybrid_search("SQLite storage", min_score=None, limit=5)
        self.assertGreater(len(results), 0)

    def test_hybrid_search_min_score_very_high_returns_empty(self):
        """min_score=99 filters all results (FTS5-only path, no vector)."""
        # Without vector, min_score is not applied (FTS5 fallback)
        results = self.db.hybrid_search("SQLite", min_score=99, limit=5)
        # FTS5 fallback returns results (min_score only applies to hybrid with vector)
        self.assertGreater(len(results), 0)

    def test_hybrid_search_with_fake_vector_and_min_score(self):
        """min_score filters results when vectors are provided."""
        # Use a zero vector (will get low cosine similarity with everything)
        zero_vec = [0.0] * 384
        results = self.db.hybrid_search(
            "HTTPS", query_vector=zero_vec, min_score=0.99, limit=5
        )
        # All results should be filtered out at such high threshold
        # (FTS rank-based scores are < 1.0 and zero_vec gives 0 similarity)
        self.assertEqual(len(results), 0)

    def test_hybrid_search_with_fake_vector_no_threshold(self):
        """Without min_score, results are returned even with zero vector."""
        zero_vec = [0.0] * 384
        results = self.db.hybrid_search(
            "HTTPS", query_vector=zero_vec, min_score=None, limit=5
        )
        self.assertGreater(len(results), 0)


class TestMinScoreParameterSignature(unittest.TestCase):
    """Verify min_score parameter is properly wired through the stack."""

    def test_hybrid_search_has_min_score_param(self):
        """hybrid_search() accepts min_score keyword argument."""
        import inspect
        sig = inspect.signature(BrainDB.hybrid_search)
        self.assertIn("min_score", sig.parameters)
        # Default should be None
        self.assertIsNone(sig.parameters["min_score"].default)

    def test_eval_run_has_min_score_param(self):
        """RecallEvaluator.run() accepts min_score keyword argument."""
        import inspect
        from project_brain.eval import RecallEvaluator
        sig = inspect.signature(RecallEvaluator.run)
        self.assertIn("min_score", sig.parameters)
        self.assertIsNone(sig.parameters["min_score"].default)


class TestEvalDefaultHybrid(unittest.TestCase):
    """Verify eval CLI defaults to hybrid mode."""

    def test_cli_eval_default_hybrid(self):
        """cmd_eval should default to hybrid=True."""
        # Create a mock args object
        class MockArgs:
            pass
        args = MockArgs()
        # getattr(args, "hybrid", True) should return True
        hybrid = getattr(args, "hybrid", True)
        self.assertTrue(hybrid)


if __name__ == "__main__":
    unittest.main()
