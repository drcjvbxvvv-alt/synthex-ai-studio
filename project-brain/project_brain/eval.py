"""project_brain/eval.py — Retrieval quality evaluation framework.

Provides a ``RecallEvaluator`` that measures how well the search pipeline
finds expected knowledge nodes for a set of queries.

Designed for the "real recall eval" item from SYSTEM_DEEP_REVIEW §11 D1:
  - Build eval sets from the live knowledge base (high-confidence nodes)
  - Measure recall@K, MRR, nDCG, noise rate, avg context tokens
  - Run regressions after synonym/embedding/ranking changes

Eval dataset format (JSONL, one object per line)::

    {"query": "JWT signing algorithm", "expected": ["rule-abc12345"], "tags": ["auth"]}

Usage::

    evaluator = RecallEvaluator(brain_dir)
    evaluator.load_dataset(path)          # or evaluator.generate_dataset()
    report = evaluator.run()
    print(report["recall_at_3"])
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Data structures ──────────────────────────────────────────────

@dataclass
class EvalQuery:
    """One evaluation query with expected node IDs."""
    query: str
    expected: list[str]       # node IDs that should appear in results
    tags: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """Result of running one eval query."""
    query: str
    expected: list[str]
    retrieved: list[str]      # node IDs actually returned (ranked)
    hit_at: dict[int, bool] = field(default_factory=dict)  # {k: bool}
    reciprocal_rank: float = 0.0
    elapsed_ms: int = 0
    context_tokens: int = 0


# ── Metric computation (pure functions, no I/O) ─────────────────

def recall_at_k(results: list[EvalResult], k: int = 3) -> float:
    """Fraction of queries where at least one expected node appears in top-K."""
    if not results:
        return 0.0
    hits = sum(1 for r in results if r.hit_at.get(k, False))
    return hits / len(results)


def mean_reciprocal_rank(results: list[EvalResult]) -> float:
    """MRR: average of 1/rank for the first relevant result per query."""
    if not results:
        return 0.0
    return sum(r.reciprocal_rank for r in results) / len(results)


def ndcg_at_k(results: list[EvalResult], k: int = 3) -> float:
    """Normalized Discounted Cumulative Gain at K.

    For our binary relevance (relevant=1, not=0):
      DCG  = sum(1/log2(rank+1)) for relevant items in top-K
      IDCG = sum(1/log2(i+1)) for i in 1..min(num_expected, K)
    """
    if not results:
        return 0.0
    total_ndcg = 0.0
    for r in results:
        expected_set = set(r.expected)
        dcg = 0.0
        for i, nid in enumerate(r.retrieved[:k]):
            if nid in expected_set:
                dcg += 1.0 / math.log2(i + 2)  # rank is 1-indexed
        ideal_count = min(len(r.expected), k)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
        total_ndcg += (dcg / idcg) if idcg > 0 else 0.0
    return total_ndcg / len(results)


def noise_rate(results: list[EvalResult], k: int = 3) -> float:
    """Fraction of top-K results that are not in the expected set."""
    total_slots = 0
    noise_slots = 0
    for r in results:
        expected_set = set(r.expected)
        top_k = r.retrieved[:k]
        total_slots += len(top_k)
        noise_slots += sum(1 for nid in top_k if nid not in expected_set)
    return noise_slots / total_slots if total_slots > 0 else 0.0


def avg_context_tokens(results: list[EvalResult]) -> float:
    """Average context token count across all queries."""
    if not results:
        return 0.0
    return sum(r.context_tokens for r in results) / len(results)


# ── Dataset I/O ──────────────────────────────────────────────────

def load_eval_dataset(path: Path) -> list[EvalQuery]:
    """Load eval queries from a JSONL file."""
    queries = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
                queries.append(EvalQuery(
                    query=obj["query"],
                    expected=obj["expected"],
                    tags=obj.get("tags", []),
                ))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("eval dataset line %d skipped: %s", line_no, e)
    return queries


def save_eval_dataset(queries: list[EvalQuery], path: Path) -> int:
    """Save eval queries to a JSONL file. Returns count written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for q in queries:
            f.write(json.dumps({
                "query": q.query,
                "expected": q.expected,
                "tags": q.tags,
            }, ensure_ascii=False) + "\n")
    return len(queries)


def generate_eval_dataset(brain_dir: Path,
                          min_confidence: float = 0.7,
                          max_queries: int = 100) -> list[EvalQuery]:
    """Auto-generate eval queries from high-confidence nodes.

    Strategy: for each qualifying node, generate a query from its title
    (stripped of common prefixes) and expect that node to appear in results.
    This gives a baseline "can Brain find its own knowledge?" eval.

    Args:
        brain_dir: path to .brain/ directory
        min_confidence: minimum node confidence to include
        max_queries: cap on generated queries
    """
    from project_brain.core.brain_db import BrainDB

    db = BrainDB(brain_dir)
    try:
        rows = db.conn.execute(
            "SELECT id, type, title, confidence, tags, scope "
            "FROM nodes "
            "WHERE confidence >= ? AND title != '' AND is_deprecated = 0 "
            "ORDER BY confidence DESC, access_count DESC "
            "LIMIT ?",
            (min_confidence, max_queries * 2),  # over-fetch for filtering
        ).fetchall()
    finally:
        db.conn.close()

    queries: list[EvalQuery] = []
    seen_titles: set[str] = set()

    for row in rows:
        title = row["title"] or ""
        if not title or len(title) < 5:
            continue

        # Deduplicate by normalized title
        norm = title.lower().strip()
        if norm in seen_titles:
            continue
        seen_titles.add(norm)

        # Generate query: use title directly (simplest baseline)
        # For more sophisticated generation, an LLM could rephrase
        query_text = title

        tags = []
        try:
            raw_tags = json.loads(row["tags"] or "[]")
            if isinstance(raw_tags, list):
                tags = [str(t) for t in raw_tags[:5]]
        except (json.JSONDecodeError, TypeError):
            pass
        if row["scope"] and row["scope"] != "global":
            tags.append(f"scope:{row['scope']}")
        if row["type"]:
            tags.append(f"type:{row['type']}")

        queries.append(EvalQuery(
            query=query_text,
            expected=[row["id"]],
            tags=tags,
        ))

        if len(queries) >= max_queries:
            break

    return queries


# ── Evaluator ────────────────────────────────────────────────────

class RecallEvaluator:
    """Run retrieval quality evaluation against a live Brain.

    Usage::

        ev = RecallEvaluator(brain_dir)
        ev.load_dataset(path)           # or ev.queries = generate_eval_dataset(...)
        report = ev.run(k=3)
        print(json.dumps(report, indent=2))
    """

    def __init__(self, brain_dir: Path) -> None:
        self.brain_dir = brain_dir
        self.queries: list[EvalQuery] = []

    def load_dataset(self, path: Path) -> int:
        """Load queries from JSONL. Returns count loaded."""
        self.queries = load_eval_dataset(path)
        return len(self.queries)

    def generate_dataset(self, min_confidence: float = 0.7,
                         max_queries: int = 100) -> int:
        """Auto-generate queries from the knowledge base. Returns count."""
        self.queries = generate_eval_dataset(
            self.brain_dir, min_confidence, max_queries,
        )
        return len(self.queries)

    def run(self, k: int = 3, search_limit: int = 10,
            use_hybrid: bool = False,
            min_score: float = None) -> dict[str, Any]:
        """Execute all queries and compute metrics.

        Args:
            k: top-K cutoff for recall/nDCG/noise metrics
            search_limit: how many results to request from search
            use_hybrid: if True, use hybrid_search (FTS5 + vector) instead of FTS5-only
            min_score: minimum relevance score threshold for hybrid search.
                       Results below this score are filtered out. None = no filtering.

        Returns:
            Structured report with metrics and per-query details.
        """
        from project_brain.core.brain_db import BrainDB

        if not self.queries:
            return self._empty_report(k)

        db = BrainDB(self.brain_dir)

        # Prepare embedder once if hybrid mode
        _embedder = None
        if use_hybrid:
            try:
                from project_brain.embedder import get_embedder
                _embedder = get_embedder()
            except Exception:
                logger.warning("hybrid mode requested but embedder unavailable, falling back to FTS5")

        results: list[EvalResult] = []

        try:
            for eq in self.queries:
                result = self._run_single(db, eq, k, search_limit, _embedder,
                                          min_score=min_score)
                results.append(result)
        finally:
            db.conn.close()

        report = self._compile_report(results, k)
        report["config"] = {
            "search_mode": "hybrid" if (use_hybrid and _embedder) else "fts5",
            "search_limit": search_limit,
            "k": k,
            "min_score": min_score,
        }
        return report

    def _run_single(self, db: "BrainDB", eq: EvalQuery,
                    k: int, search_limit: int,
                    embedder=None, min_score: float = None) -> EvalResult:
        """Run a single eval query."""
        expected_set = set(eq.expected)

        t0 = time.monotonic()
        if embedder:
            try:
                q_vec = embedder.embed(eq.query)
                search_results = db.hybrid_search(
                    eq.query, query_vector=q_vec, limit=search_limit,
                    min_score=min_score,
                )
            except Exception:
                search_results = db.search_nodes(eq.query, limit=search_limit)
        else:
            search_results = db.search_nodes(eq.query, limit=search_limit)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        retrieved_ids = [r["id"] for r in search_results if r.get("id")]

        # Compute hit@k for multiple k values
        hit_at: dict[int, bool] = {}
        for check_k in (1, 3, 5, 10):
            top = retrieved_ids[:check_k]
            hit_at[check_k] = bool(expected_set & set(top))

        # Reciprocal rank: 1/position of first relevant result
        rr = 0.0
        for i, nid in enumerate(retrieved_ids):
            if nid in expected_set:
                rr = 1.0 / (i + 1)
                break

        # Estimate context tokens (~4 chars per token)
        total_chars = sum(
            len(r.get("title", "")) + len(r.get("content", ""))
            for r in search_results
        )
        ctx_tokens = total_chars // 4

        return EvalResult(
            query=eq.query,
            expected=eq.expected,
            retrieved=retrieved_ids,
            hit_at=hit_at,
            reciprocal_rank=rr,
            elapsed_ms=elapsed_ms,
            context_tokens=ctx_tokens,
        )

    def _compile_report(self, results: list[EvalResult],
                        k: int) -> dict[str, Any]:
        """Aggregate per-query results into a metrics report."""
        report: dict[str, Any] = {
            "metrics": {
                "recall_at_1": round(recall_at_k(results, 1), 4),
                "recall_at_3": round(recall_at_k(results, 3), 4),
                "recall_at_5": round(recall_at_k(results, 5), 4),
                "recall_at_10": round(recall_at_k(results, 10), 4),
                "mrr": round(mean_reciprocal_rank(results), 4),
                "ndcg_at_3": round(ndcg_at_k(results, 3), 4),
                "noise_rate_at_3": round(noise_rate(results, 3), 4),
                "avg_context_tokens": round(avg_context_tokens(results), 1),
                "avg_latency_ms": round(
                    sum(r.elapsed_ms for r in results) / len(results), 1
                ),
                "max_latency_ms": max(r.elapsed_ms for r in results),
            },
            "summary": {
                "total_queries": len(results),
                "hits_at_3": sum(1 for r in results if r.hit_at.get(3, False)),
                "misses_at_3": sum(1 for r in results if not r.hit_at.get(3, False)),
            },
            "per_query": [
                {
                    "query": r.query[:80],
                    "expected": r.expected,
                    "retrieved_top3": r.retrieved[:3],
                    "hit_at_3": r.hit_at.get(3, False),
                    "reciprocal_rank": round(r.reciprocal_rank, 4),
                    "elapsed_ms": r.elapsed_ms,
                }
                for r in results
            ],
        }

        # Breakdown by tag (if tags available)
        tag_hits: dict[str, list[bool]] = {}
        for eq, er in zip(self.queries, results):
            for tag in eq.tags:
                tag_hits.setdefault(tag, []).append(er.hit_at.get(3, False))
        if tag_hits:
            report["by_tag"] = {
                tag: {
                    "count": len(hits),
                    "recall_at_3": round(sum(hits) / len(hits), 4),
                }
                for tag, hits in sorted(tag_hits.items())
                if len(hits) >= 2  # only report tags with ≥2 queries
            }

        return report

    def _empty_report(self, k: int) -> dict[str, Any]:
        return {
            "metrics": {
                "recall_at_1": 0.0, "recall_at_3": 0.0,
                "recall_at_5": 0.0, "recall_at_10": 0.0,
                "mrr": 0.0, "ndcg_at_3": 0.0,
                "noise_rate_at_3": 0.0, "avg_context_tokens": 0.0,
                "avg_latency_ms": 0.0, "max_latency_ms": 0,
            },
            "summary": {"total_queries": 0, "hits_at_3": 0, "misses_at_3": 0},
            "per_query": [],
        }
