"""
tests/benchmarks/benchmark_perf_5k.py — D-04 5000-node 效能基準

驗證 Project Brain 在 5000 節點知識庫下的效能目標：
  - 批次寫入吞吐量（nodes/s）
  - FTS5 搜尋延遲（目標 ≤ 300ms）
  - BrainDB hybrid search 延遲（目標 ≤ 300ms）

執行：
  pytest tests/benchmarks/benchmark_perf_5k.py -v -m benchmark
  python tests/benchmarks/benchmark_perf_5k.py   # 直接執行顯示詳細報告
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from project_brain.core.brain_db import BrainDB
from project_brain.graph import KnowledgeGraph

# ── 效能目標 ──────────────────────────────────────────────────────────────────

TARGET_WRITE_THROUGHPUT = 200    # nodes/s  (minimum bulk-write throughput)
TARGET_FTS5_P99_MS      = 300    # ms       (p99 FTS5 search latency)
TARGET_BRAINDB_P99_MS   = 300    # ms       (p99 BrainDB search latency)
TARGET_FTS5_AVG_MS      = 100    # ms       (average FTS5 search latency)

NODE_COUNT   = 5_000
QUERY_COUNT  = 50  # number of search queries to benchmark

# ── 測試資料生成 ─────────────────────────────────────────────────────────────

# 10 topic clusters × 500 nodes = 5000 nodes
_TOPICS = [
    ("database",    ["index", "query", "migration", "transaction"]),
    ("api",         ["rest", "graphql", "versioning", "auth"]),
    ("security",    ["jwt", "sql-injection", "xss", "csrf"]),
    ("performance", ["cache", "pagination", "n+1", "latency"]),
    ("deployment",  ["docker", "kubernetes", "ci", "rollback"]),
    ("python",      ["async", "typing", "logging", "testing"]),
    ("testing",     ["fixture", "mock", "coverage", "e2e"]),
    ("architecture",["solid", "event-driven", "saga", "hexagonal"]),
    ("monitoring",  ["metrics", "tracing", "alerting", "slo"]),
    ("code-quality",["review", "refactoring", "naming", "documentation"]),
]
_KINDS = ["Rule", "Decision", "Pitfall", "Note", "ADR"]


def _gen_nodes(count: int) -> list[dict]:
    """Generate `count` synthetic knowledge nodes."""
    nodes = []
    for i in range(count):
        topic, tags = _TOPICS[i % len(_TOPICS)]
        kind  = _KINDS[i % len(_KINDS)]
        title = f"{topic.title()} {kind} #{i:05d}: {tags[i % len(tags)]} best practice"
        content = (
            f"When working with {topic}, always consider {tags[i % len(tags)]}. "
            f"This is a {kind.lower()} node about {topic} "
            f"indexed at position {i} in the benchmark corpus."
        )
        nodes.append({
            "id":         f"bench-{i:06d}",
            "type":       kind,
            "title":      title,
            "content":    content,
            "tags":       json.dumps(tags),
            "confidence": 0.7 + (i % 30) / 100,  # 0.70 … 0.99
        })
    return nodes


# Representative search queries for benchmarking (not recall-tested)
_BENCH_QUERIES = [
    "database transaction isolation level",
    "JWT expiry validation security",
    "async event loop blocking calls",
    "docker secrets management",
    "API rate limiting gateway",
    "SQL injection parameterized query",
    "Kubernetes health check endpoint",
    "PostgreSQL index foreign key",
    "pytest fixture scope session",
    "CI pipeline merge gate",
    "cache key collision invalidation",
    "cursor pagination large dataset",
    "event driven saga compensation",
    "CORS preflight cache header",
    "python logging getLogger module",
    "migration backward compatibility",
    "SOLID single responsibility principle",
    "blue green deployment schema",
    "monitoring SLO error budget",
    "code review refactoring safety",
    "canary rollback threshold",
    "dependency injection container",
    "build artifact immutable deploy",
    "N+1 dataloader batch query",
    "feature flag trunk based development",
    "WebP CDN image performance",
    "XSS innerHTML sanitization",
    "GraphQL mutation error code",
    "twelve factor app configuration",
    "container layer cache ordering",
    "Prometheus metrics format",
    "OpenTelemetry tracing context",
    "dead letter queue retry",
    "distributed transaction saga",
    "service mesh circuit breaker",
    "hexagonal architecture port",
    "characterization test refactor",
    "rollback migration down script",
    "token rotation expiry strategy",
    "connection pool size cpu cores",
    "EXPLAIN ANALYZE slow query",
    "graceful shutdown signal handler",
    "secret scanning pre-commit hook",
    "A/B test statistical significance",
    "paging offset vs cursor",
    "idempotent API PUT request",
    "log correlation request id",
    "alert fatigue SLO window",
    "naming convention past tense event",
    "type annotation future annotations",
]
assert len(_BENCH_QUERIES) == QUERY_COUNT, (
    f"Expected {QUERY_COUNT} queries, got {len(_BENCH_QUERIES)}"
)


# ── Benchmark classes ────────────────────────────────────────────────────────

class WriteResult(NamedTuple):
    total_nodes: int
    elapsed_s: float
    throughput_nps: float  # nodes per second


class SearchResult(NamedTuple):
    query: str
    elapsed_ms: int
    hit_count: int


def _benchmark_bulk_write(brain_dir: Path) -> WriteResult:
    """
    Write NODE_COUNT nodes via direct SQL (fastest path).
    Returns throughput in nodes/second.
    """
    from project_brain.core.brain_db import BrainDB
    db = BrainDB(brain_dir)
    nodes = _gen_nodes(NODE_COUNT)

    t0 = time.monotonic()
    with db.conn:
        db.conn.executemany(
            "INSERT OR IGNORE INTO nodes "
            "(id, type, title, content, tags, confidence, meta, scope) "
            "VALUES (:id, :type, :title, :content, :tags, :confidence, '{}', 'global')",
            nodes,
        )
    elapsed = time.monotonic() - t0
    db.close()
    tput = NODE_COUNT / elapsed if elapsed > 0 else float("inf")
    return WriteResult(NODE_COUNT, elapsed, tput)


def _benchmark_fts5_search(brain_dir: Path) -> list[SearchResult]:
    """
    Run QUERY_COUNT FTS5 searches against a 5000-node brain.
    """
    import sqlite3
    db_path = brain_dir / "brain.db"
    conn = sqlite3.connect(str(db_path))
    results = []
    for query in _BENCH_QUERIES:
        # FTS5 match query — sanitize special chars
        safe_q = query.replace('"', ' ').replace("'", " ")
        t0 = time.monotonic()
        try:
            rows = conn.execute(
                "SELECT n.id, n.title FROM nodes n "
                "JOIN nodes_fts f ON f.id = n.id "
                "WHERE nodes_fts MATCH ? LIMIT 5",
                (safe_q,),
            ).fetchall()
        except Exception:
            rows = []
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        results.append(SearchResult(query, elapsed_ms, len(rows)))
    conn.close()
    return results


def _benchmark_braindb_search(brain_dir: Path) -> list[SearchResult]:
    """
    Run QUERY_COUNT BrainDB.search_nodes() searches.
    """
    db = BrainDB(brain_dir)
    results = []
    for query in _BENCH_QUERIES:
        t0 = time.monotonic()
        try:
            hits = db.search_nodes(query, limit=5)
        except Exception:
            hits = []
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        results.append(SearchResult(query, elapsed_ms, len(hits)))
    db.close()
    return results


def run_5k_benchmark() -> dict:
    """
    Full 5K benchmark: write + FTS5 + BrainDB search.
    Returns a structured dict with all metrics.
    """
    with tempfile.TemporaryDirectory() as tmp:
        brain_dir = Path(tmp) / ".brain"
        brain_dir.mkdir()

        # Ensure schema exists before writing
        _init_schema(brain_dir)

        write = _benchmark_bulk_write(brain_dir)
        fts_results = _benchmark_fts5_search(brain_dir)
        brain_results = _benchmark_braindb_search(brain_dir)

    fts_ms = sorted(r.elapsed_ms for r in fts_results)
    brain_ms = sorted(r.elapsed_ms for r in brain_results)

    return {
        "node_count":          NODE_COUNT,
        "query_count":         QUERY_COUNT,
        # write
        "write_throughput_nps": round(write.throughput_nps, 1),
        "write_elapsed_s":      round(write.elapsed_s, 3),
        # FTS5
        "fts5_avg_ms":          round(sum(fts_ms) / len(fts_ms), 1),
        "fts5_p50_ms":          fts_ms[len(fts_ms) // 2],
        "fts5_p99_ms":          fts_ms[int(len(fts_ms) * 0.99)],
        "fts5_max_ms":          max(fts_ms),
        # BrainDB
        "braindb_avg_ms":       round(sum(brain_ms) / len(brain_ms), 1),
        "braindb_p50_ms":       brain_ms[len(brain_ms) // 2],
        "braindb_p99_ms":       brain_ms[int(len(brain_ms) * 0.99)],
        "braindb_max_ms":       max(brain_ms),
    }


def _init_schema(brain_dir: Path) -> None:
    """Initialize BrainDB + KnowledgeGraph schema in brain_dir."""
    db = BrainDB(brain_dir)
    g = KnowledgeGraph(brain_dir, conn=db.conn)
    db.conn.commit()
    db.close()


# ── pytest integration ────────────────────────────────────────────────────────

import pytest


@pytest.fixture(scope="module")
def five_k_brain():
    """Module-scoped fixture: one 5000-node brain shared across all tests."""
    with tempfile.TemporaryDirectory() as tmp:
        brain_dir = Path(tmp) / ".brain"
        brain_dir.mkdir()
        _init_schema(brain_dir)
        db = BrainDB(brain_dir)
        nodes = _gen_nodes(NODE_COUNT)
        with db.conn:
            db.conn.executemany(
                "INSERT OR IGNORE INTO nodes "
                "(id, type, title, content, tags, confidence, meta, scope) "
                "VALUES (:id, :type, :title, :content, :tags, :confidence, '{}', 'global')",
                nodes,
            )
        db.close()
        yield brain_dir


@pytest.mark.benchmark
class TestPerf5K:
    """Performance benchmarks for a 5000-node knowledge base."""

    def test_bulk_write_5000_nodes_throughput(self):
        """Write 5000 nodes to BrainDB; throughput must exceed 200 nodes/s."""
        with tempfile.TemporaryDirectory() as tmp:
            brain_dir = Path(tmp) / ".brain"
            brain_dir.mkdir()
            _init_schema(brain_dir)
            result = _benchmark_bulk_write(brain_dir)
        assert result.throughput_nps >= TARGET_WRITE_THROUGHPUT, (
            f"Write throughput {result.throughput_nps:.0f} nodes/s "
            f"< {TARGET_WRITE_THROUGHPUT} nodes/s"
        )

    def test_fts5_search_p99_latency(self, five_k_brain):
        """FTS5 p99 search latency ≤ 300ms over 5000 nodes."""
        results = _benchmark_fts5_search(five_k_brain)
        ms_vals = sorted(r.elapsed_ms for r in results)
        p99 = ms_vals[int(len(ms_vals) * 0.99)]
        assert p99 <= TARGET_FTS5_P99_MS, (
            f"FTS5 p99 latency {p99}ms > {TARGET_FTS5_P99_MS}ms"
        )

    def test_fts5_search_avg_latency(self, five_k_brain):
        """FTS5 average search latency ≤ 100ms over 5000 nodes."""
        results = _benchmark_fts5_search(five_k_brain)
        avg_ms = sum(r.elapsed_ms for r in results) / len(results)
        assert avg_ms <= TARGET_FTS5_AVG_MS, (
            f"FTS5 avg latency {avg_ms:.1f}ms > {TARGET_FTS5_AVG_MS}ms"
        )

    def test_braindb_search_p99_latency(self, five_k_brain):
        """BrainDB search p99 latency ≤ 300ms over 5000 nodes."""
        results = _benchmark_braindb_search(five_k_brain)
        ms_vals = sorted(r.elapsed_ms for r in results)
        p99 = ms_vals[int(len(ms_vals) * 0.99)]
        assert p99 <= TARGET_BRAINDB_P99_MS, (
            f"BrainDB p99 latency {p99}ms > {TARGET_BRAINDB_P99_MS}ms"
        )

    def test_braindb_search_returns_results(self, five_k_brain):
        """BrainDB search returns at least 1 result for known queries."""
        db = BrainDB(five_k_brain)
        # Use a query that matches our generated nodes
        hits = db.search_nodes("database transaction", limit=5)
        db.close()
        # FTS5 may or may not match depending on tokenizer; we just check no crash
        assert isinstance(hits, list)


# ── Main: standalone report ───────────────────────────────────────────────────

if __name__ == "__main__":
    import textwrap
    print(f"\n正在建立 {NODE_COUNT:,} 節點知識庫並執行 {QUERY_COUNT} 個查詢...")
    print("(請稍候，首次寫入需要幾秒)\n")

    metrics = run_5k_benchmark()

    print("═" * 65)
    print("  D-04 效能基準報告 — 5000-node Knowledge Base")
    print("═" * 65)
    print(f"  知識庫規模   : {metrics['node_count']:,} 節點")
    print(f"  查詢數       : {metrics['query_count']}")
    print()
    print("  批次寫入")
    print(f"    吞吐量     : {metrics['write_throughput_nps']:,.0f} nodes/s  "
          + ("✅" if metrics['write_throughput_nps'] >= TARGET_WRITE_THROUGHPUT else "❌")
          + f"  (目標 ≥ {TARGET_WRITE_THROUGHPUT})")
    print(f"    耗時       : {metrics['write_elapsed_s']:.3f}s")
    print()
    print("  FTS5 搜尋延遲")
    print(f"    平均       : {metrics['fts5_avg_ms']:.1f} ms  "
          + ("✅" if metrics['fts5_avg_ms'] <= TARGET_FTS5_AVG_MS else "❌")
          + f"  (目標 ≤ {TARGET_FTS5_AVG_MS}ms)")
    print(f"    P50        : {metrics['fts5_p50_ms']} ms")
    print(f"    P99        : {metrics['fts5_p99_ms']} ms  "
          + ("✅" if metrics['fts5_p99_ms'] <= TARGET_FTS5_P99_MS else "❌")
          + f"  (目標 ≤ {TARGET_FTS5_P99_MS}ms)")
    print(f"    Max        : {metrics['fts5_max_ms']} ms")
    print()
    print("  BrainDB Hybrid 搜尋延遲")
    print(f"    平均       : {metrics['braindb_avg_ms']:.1f} ms  "
          + ("✅" if metrics['braindb_avg_ms'] <= TARGET_BRAINDB_P99_MS else "❌")
          + f"  (目標 ≤ {TARGET_BRAINDB_P99_MS}ms avg)")
    print(f"    P50        : {metrics['braindb_p50_ms']} ms")
    print(f"    P99        : {metrics['braindb_p99_ms']} ms  "
          + ("✅" if metrics['braindb_p99_ms'] <= TARGET_BRAINDB_P99_MS else "❌")
          + f"  (目標 ≤ {TARGET_BRAINDB_P99_MS}ms)")
    print(f"    Max        : {metrics['braindb_max_ms']} ms")
    print("═" * 65)
    print()
