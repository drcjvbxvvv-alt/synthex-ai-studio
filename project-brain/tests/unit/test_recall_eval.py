"""
tests/unit/test_recall_eval.py

RecallEvaluator 驗收測試 — 量化檢索品質評估框架

覆蓋：
  - Metric 計算邏輯（recall@K, MRR, nDCG, noise rate, context tokens）
  - Dataset I/O（JSONL load/save）
  - Dataset 自動生成
  - RecallEvaluator 端到端
  - Edge cases（空結果、空 dataset、完美結果）
"""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from project_brain.core.brain_db import BrainDB
from project_brain.eval import (
    EvalQuery,
    EvalResult,
    RecallEvaluator,
    avg_context_tokens,
    generate_eval_dataset,
    load_eval_dataset,
    mean_reciprocal_rank,
    ndcg_at_k,
    noise_rate,
    recall_at_k,
    save_eval_dataset,
)


# ═══════════════════════════════════════════════════════════════════
#  Metric calculation tests (pure logic, no I/O)
# ═══════════════════════════════════════════════════════════════════

class TestRecallAtK(unittest.TestCase):

    def test_perfect_recall(self):
        """All queries hit → recall = 1.0."""
        results = [
            EvalResult("q1", ["a"], ["a", "b", "c"], hit_at={3: True}),
            EvalResult("q2", ["x"], ["x", "y", "z"], hit_at={3: True}),
        ]
        self.assertEqual(recall_at_k(results, 3), 1.0)

    def test_zero_recall(self):
        """No queries hit → recall = 0.0."""
        results = [
            EvalResult("q1", ["a"], ["b", "c", "d"], hit_at={3: False}),
            EvalResult("q2", ["x"], ["y", "z", "w"], hit_at={3: False}),
        ]
        self.assertEqual(recall_at_k(results, 3), 0.0)

    def test_partial_recall(self):
        """1 of 2 queries hit → recall = 0.5."""
        results = [
            EvalResult("q1", ["a"], ["a", "b", "c"], hit_at={3: True}),
            EvalResult("q2", ["x"], ["y", "z", "w"], hit_at={3: False}),
        ]
        self.assertEqual(recall_at_k(results, 3), 0.5)

    def test_empty_results(self):
        self.assertEqual(recall_at_k([], 3), 0.0)


class TestMRR(unittest.TestCase):

    def test_first_position(self):
        """Relevant at position 1 → RR = 1.0."""
        results = [EvalResult("q", ["a"], ["a"], reciprocal_rank=1.0)]
        self.assertEqual(mean_reciprocal_rank(results), 1.0)

    def test_second_position(self):
        """Relevant at position 2 → RR = 0.5."""
        results = [EvalResult("q", ["a"], ["b", "a"], reciprocal_rank=0.5)]
        self.assertEqual(mean_reciprocal_rank(results), 0.5)

    def test_not_found(self):
        """No relevant result → RR = 0.0."""
        results = [EvalResult("q", ["a"], ["b", "c"], reciprocal_rank=0.0)]
        self.assertEqual(mean_reciprocal_rank(results), 0.0)

    def test_average_of_multiple(self):
        """MRR is average of per-query RR."""
        results = [
            EvalResult("q1", ["a"], ["a"], reciprocal_rank=1.0),
            EvalResult("q2", ["a"], ["b", "a"], reciprocal_rank=0.5),
        ]
        self.assertAlmostEqual(mean_reciprocal_rank(results), 0.75)

    def test_empty(self):
        self.assertEqual(mean_reciprocal_rank([]), 0.0)


class TestNDCG(unittest.TestCase):

    def test_perfect_ndcg(self):
        """Relevant at position 1 → nDCG = 1.0."""
        results = [EvalResult("q", ["a"], ["a", "b", "c"])]
        self.assertAlmostEqual(ndcg_at_k(results, 3), 1.0)

    def test_relevant_at_position_2(self):
        """Relevant at position 2 → DCG = 1/log2(3), IDCG = 1/log2(2)."""
        results = [EvalResult("q", ["a"], ["b", "a", "c"])]
        expected = (1.0 / math.log2(3)) / (1.0 / math.log2(2))
        self.assertAlmostEqual(ndcg_at_k(results, 3), expected, places=3)

    def test_no_relevant(self):
        results = [EvalResult("q", ["a"], ["b", "c", "d"])]
        self.assertAlmostEqual(ndcg_at_k(results, 3), 0.0)

    def test_empty(self):
        self.assertEqual(ndcg_at_k([], 3), 0.0)


class TestNoiseRate(unittest.TestCase):

    def test_all_noise(self):
        """No relevant results → noise = 1.0."""
        results = [EvalResult("q", ["a"], ["b", "c", "d"])]
        self.assertAlmostEqual(noise_rate(results, 3), 1.0)

    def test_no_noise(self):
        """All relevant → noise = 0.0."""
        results = [EvalResult("q", ["a", "b", "c"], ["a", "b", "c"])]
        self.assertAlmostEqual(noise_rate(results, 3), 0.0)

    def test_partial_noise(self):
        """1 relevant, 2 noise → noise = 2/3."""
        results = [EvalResult("q", ["a"], ["a", "b", "c"])]
        self.assertAlmostEqual(noise_rate(results, 3), 2.0 / 3.0, places=3)

    def test_empty(self):
        self.assertEqual(noise_rate([], 3), 0.0)


class TestAvgContextTokens(unittest.TestCase):

    def test_average(self):
        results = [
            EvalResult("q1", [], [], context_tokens=100),
            EvalResult("q2", [], [], context_tokens=200),
        ]
        self.assertEqual(avg_context_tokens(results), 150.0)

    def test_empty(self):
        self.assertEqual(avg_context_tokens([]), 0.0)


# ═══════════════════════════════════════════════════════════════════
#  Dataset I/O tests
# ═══════════════════════════════════════════════════════════════════

class TestDatasetIO(unittest.TestCase):

    def test_round_trip(self):
        """save → load preserves data."""
        queries = [
            EvalQuery("JWT auth", ["rule-123"], ["auth", "security"]),
            EvalQuery("database timeout", ["pitfall-456"], ["db"]),
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = Path(f.name)
        save_eval_dataset(queries, path)
        loaded = load_eval_dataset(path)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].query, "JWT auth")
        self.assertEqual(loaded[0].expected, ["rule-123"])
        self.assertEqual(loaded[0].tags, ["auth", "security"])
        self.assertEqual(loaded[1].query, "database timeout")
        path.unlink()

    def test_load_skips_bad_lines(self):
        """Malformed lines are skipped, not crash."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w",
                                         delete=False, encoding="utf-8") as f:
            f.write('{"query": "good", "expected": ["a"]}\n')
            f.write('bad json line\n')
            f.write('{"missing_query": true}\n')
            f.write('{"query": "also good", "expected": ["b"]}\n')
            path = Path(f.name)
        loaded = load_eval_dataset(path)
        self.assertEqual(len(loaded), 2)
        path.unlink()

    def test_load_skips_comments_and_blanks(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w",
                                         delete=False, encoding="utf-8") as f:
            f.write("# comment line\n")
            f.write("\n")
            f.write('{"query": "q1", "expected": ["a"]}\n')
            path = Path(f.name)
        loaded = load_eval_dataset(path)
        self.assertEqual(len(loaded), 1)
        path.unlink()


# ═══════════════════════════════════════════════════════════════════
#  Dataset generation tests
# ═══════════════════════════════════════════════════════════════════

class TestGenerateDataset(unittest.TestCase):

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

    def _add(self, nid, title, confidence=0.9, kind="Rule"):
        self.db.add_node(
            node_id=nid, node_type=kind,
            title=title, content=f"Content for {title}",
            tags=[], confidence=confidence,
        )

    def test_generates_from_high_confidence_nodes(self):
        self._add("r1", "Use RS256 for JWT signing", 0.9)
        self._add("r2", "Database timeout must be set", 0.8)
        self._add("r3", "Low confidence rule", 0.3)  # below threshold
        self.db.conn.close()

        queries = generate_eval_dataset(self.brain_dir, min_confidence=0.7)
        self.assertEqual(len(queries), 2)
        ids = {q.expected[0] for q in queries}
        self.assertIn("r1", ids)
        self.assertIn("r2", ids)
        self.assertNotIn("r3", ids)

    def test_respects_max_queries(self):
        for i in range(20):
            self._add(f"n{i}", f"Rule number {i}", 0.9)
        self.db.conn.close()

        queries = generate_eval_dataset(self.brain_dir, max_queries=5)
        self.assertEqual(len(queries), 5)

    def test_skips_deprecated_nodes(self):
        self._add("r1", "Active rule", 0.9)
        self.db.conn.execute(
            "UPDATE nodes SET is_deprecated=1 WHERE id='r1'"
        )
        self.db.conn.commit()
        self.db.conn.close()

        queries = generate_eval_dataset(self.brain_dir)
        self.assertEqual(len(queries), 0)

    def test_deduplicates_similar_titles(self):
        self._add("r1", "Use RS256 for JWT", 0.9)
        self._add("r2", "Use RS256 for JWT", 0.85)  # same title
        self.db.conn.close()

        queries = generate_eval_dataset(self.brain_dir)
        self.assertEqual(len(queries), 1)

    def test_empty_db(self):
        self.db.conn.close()
        queries = generate_eval_dataset(self.brain_dir)
        self.assertEqual(len(queries), 0)


# ═══════════════════════════════════════════════════════════════════
#  RecallEvaluator end-to-end tests
# ═══════════════════════════════════════════════════════════════════

class TestRecallEvaluator(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self._tmp.name)
        self.db = BrainDB(self.brain_dir)
        # Populate with test data
        for i in range(10):
            self.db.add_node(
                node_id=f"rule-{i:04d}",
                node_type="Rule",
                title=f"Important rule about topic {i}",
                content=f"Detailed content about topic {i} with specifics",
                tags=json.dumps(["test"]),
                confidence=0.9,
            )

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass
        self._tmp.cleanup()

    def test_run_with_generated_dataset(self):
        """Generate + run should produce valid report."""
        self.db.conn.close()
        ev = RecallEvaluator(self.brain_dir)
        count = ev.generate_dataset(min_confidence=0.8)
        self.assertGreater(count, 0)
        report = ev.run(k=3)

        # Check report structure
        self.assertIn("metrics", report)
        self.assertIn("summary", report)
        self.assertIn("per_query", report)

        m = report["metrics"]
        self.assertIn("recall_at_3", m)
        self.assertIn("mrr", m)
        self.assertIn("ndcg_at_3", m)
        self.assertIn("noise_rate_at_3", m)
        self.assertIn("avg_context_tokens", m)
        self.assertIn("avg_latency_ms", m)

        # Value ranges
        self.assertGreaterEqual(m["recall_at_3"], 0.0)
        self.assertLessEqual(m["recall_at_3"], 1.0)
        self.assertGreaterEqual(m["mrr"], 0.0)
        self.assertLessEqual(m["mrr"], 1.0)
        self.assertGreaterEqual(m["avg_latency_ms"], 0.0)

    def test_run_with_manual_dataset(self):
        """Run with manually specified queries."""
        self.db.conn.close()
        ev = RecallEvaluator(self.brain_dir)
        ev.queries = [
            EvalQuery("topic 0", ["rule-0000"]),
            EvalQuery("topic 1", ["rule-0001"]),
            EvalQuery("nonexistent topic xyz", ["rule-9999"]),
        ]
        report = ev.run(k=3)
        self.assertEqual(report["summary"]["total_queries"], 3)

    def test_run_empty_dataset(self):
        """Empty dataset → empty report."""
        self.db.conn.close()
        ev = RecallEvaluator(self.brain_dir)
        report = ev.run(k=3)
        self.assertEqual(report["summary"]["total_queries"], 0)
        self.assertEqual(report["metrics"]["recall_at_3"], 0.0)

    def test_load_and_run(self):
        """Load from JSONL file → run."""
        # Save dataset
        dataset_path = Path(self._tmp.name) / "eval" / "queries.jsonl"
        save_eval_dataset([
            EvalQuery("topic 0", ["rule-0000"]),
            EvalQuery("topic 5", ["rule-0005"]),
        ], dataset_path)

        self.db.conn.close()
        ev = RecallEvaluator(self.brain_dir)
        loaded = ev.load_dataset(dataset_path)
        self.assertEqual(loaded, 2)
        report = ev.run(k=3)
        self.assertEqual(report["summary"]["total_queries"], 2)

    def test_report_per_query_details(self):
        """per_query section should have details for each query."""
        self.db.conn.close()
        ev = RecallEvaluator(self.brain_dir)
        ev.queries = [EvalQuery("topic 0", ["rule-0000"])]
        report = ev.run(k=3)
        self.assertEqual(len(report["per_query"]), 1)
        pq = report["per_query"][0]
        self.assertIn("query", pq)
        self.assertIn("expected", pq)
        self.assertIn("retrieved_top3", pq)
        self.assertIn("hit_at_3", pq)
        self.assertIn("reciprocal_rank", pq)
        self.assertIn("elapsed_ms", pq)

    def test_report_by_tag_breakdown(self):
        """Tags with ≥2 queries should get breakdown."""
        self.db.conn.close()
        ev = RecallEvaluator(self.brain_dir)
        ev.queries = [
            EvalQuery("topic 0", ["rule-0000"], tags=["auth"]),
            EvalQuery("topic 1", ["rule-0001"], tags=["auth"]),
            EvalQuery("topic 2", ["rule-0002"], tags=["db"]),
        ]
        report = ev.run(k=3)
        if "by_tag" in report:
            self.assertIn("auth", report["by_tag"])
            self.assertEqual(report["by_tag"]["auth"]["count"], 2)


if __name__ == "__main__":
    unittest.main()
