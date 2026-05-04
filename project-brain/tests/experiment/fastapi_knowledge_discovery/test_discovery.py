"""
FastAPI Knowledge Discovery 實驗

用 FastAPI 的 20 個真實陷阱測試：
「開發者描述任務時，Brain 能否主動提醒相關的 Pitfall？」

對比 FTS5-only vs Hybrid (TF-IDF) 兩種搜尋模式。
零外部依賴（無 GPU/API key/網路）。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).parent
PITFALLS_PATH = DATA_DIR / "pitfalls.jsonl"
TASKS_PATH = DATA_DIR / "tasks.jsonl"
REPORT_PATH = DATA_DIR / "report.json"


@dataclass
class DiscoveryResult:
    task: str
    category: str
    expected_ids: list[str]
    mode: str  # "fts5" or "hybrid_tfidf"
    # Context search results
    context_hit: bool  # expected pitfall found in context
    context_found_ids: list[str]
    # Nudge results
    nudge_hit: bool  # expected pitfall found in nudges
    nudge_found_ids: list[str]
    elapsed_ms: int


def _load_jsonl(path: Path) -> list[dict]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                items.append(json.loads(line))
    return items


def _run_discovery(brain, pitfall_map, tasks, mode: str) -> list[DiscoveryResult]:
    """Run discovery experiment for one search mode."""
    from project_brain.engines.nudge_engine import NudgeEngine

    results = []
    ne = NudgeEngine(brain.graph, brain_db=brain.db)

    for task_entry in tasks:
        task_desc = task_entry["task"]
        expected_ids = set(task_entry["expected_pitfall_ids"])

        t0 = time.monotonic()

        # 1. Context search
        ctx = brain.get_context(task_desc) or ""
        context_found = set()
        for pid, pitfall in pitfall_map.items():
            # Check if pitfall title or key content appears in context
            if pitfall["title"][:40] in ctx or pitfall["id"] in ctx:
                context_found.add(pid)

        # 2. Nudge engine
        nudges = ne.check(task_desc, top_k=5)
        nudge_found = set()
        for nudge in nudges:
            for pid, pitfall in pitfall_map.items():
                if (pitfall["title"][:30] in nudge.title
                        or pitfall["title"][:30] in nudge.content):
                    nudge_found.add(pid)

        elapsed = int((time.monotonic() - t0) * 1000)

        # Hit = at least one expected pitfall found
        context_hit = bool(expected_ids & context_found)
        nudge_hit = bool(expected_ids & nudge_found)

        results.append(DiscoveryResult(
            task=task_desc,
            category=task_entry["category"],
            expected_ids=list(expected_ids),
            mode=mode,
            context_hit=context_hit,
            context_found_ids=list(context_found),
            nudge_hit=nudge_hit,
            nudge_found_ids=list(nudge_found),
            elapsed_ms=elapsed,
        ))

    return results


def _compute_metrics(results: list[DiscoveryResult]) -> dict:
    """Compute discovery metrics from results."""
    total = len(results)
    if not total:
        return {"discovery_rate": 0, "nudge_rate": 0, "combined_rate": 0}

    context_hits = sum(1 for r in results if r.context_hit)
    nudge_hits = sum(1 for r in results if r.nudge_hit)
    combined_hits = sum(1 for r in results if r.context_hit or r.nudge_hit)

    # By category
    by_category = {}
    categories = set(r.category for r in results)
    for cat in categories:
        cat_results = [r for r in results if r.category == cat]
        cat_hits = sum(1 for r in cat_results if r.context_hit or r.nudge_hit)
        by_category[cat] = {
            "total": len(cat_results),
            "hits": cat_hits,
            "rate": cat_hits / len(cat_results),
        }

    return {
        "total_tasks": total,
        "context_hits": context_hits,
        "context_discovery_rate": round(context_hits / total, 4),
        "nudge_hits": nudge_hits,
        "nudge_discovery_rate": round(nudge_hits / total, 4),
        "combined_hits": combined_hits,
        "combined_discovery_rate": round(combined_hits / total, 4),
        "avg_latency_ms": round(sum(r.elapsed_ms for r in results) / total, 1),
        "by_category": by_category,
    }


class TestFastAPIDiscovery:
    """FastAPI Knowledge Discovery experiment — FTS5 vs Hybrid."""

    def test_run_experiment(self, tmp_path, monkeypatch):
        # Shared setup
        monkeypatch.setenv("BRAIN_RELEVANCE_SELECTOR", "keyword")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "")
        monkeypatch.setenv("BRAIN_WORKDIR", str(tmp_path))
        monkeypatch.delenv("BRAIN_SYNTHESIZE", raising=False)

        pitfalls = _load_jsonl(PITFALLS_PATH)
        tasks = _load_jsonl(TASKS_PATH)

        # ═══ Round 1: FTS5 only ═══
        monkeypatch.setenv("BRAIN_EMBED_PROVIDER", "none")

        from project_brain.engine import ProjectBrain
        brain_fts5 = ProjectBrain(str(tmp_path / "fts5"))

        # Seed pitfalls
        pitfall_map = {}
        for p in pitfalls:
            nid = brain_fts5.add_knowledge(
                title=p["title"], content=p["content"],
                kind=p["kind"], confidence=0.9,
            )
            pitfall_map[p["id"]] = {**p, "node_id": nid}

        fts5_results = _run_discovery(brain_fts5, pitfall_map, tasks, "fts5")
        fts5_metrics = _compute_metrics(fts5_results)

        # ═══ Round 2: Hybrid (TF-IDF) ═══
        monkeypatch.setenv("BRAIN_EMBED_PROVIDER", "local")

        brain_hybrid = ProjectBrain(str(tmp_path / "hybrid"))

        # Re-seed (fresh brain for hybrid)
        pitfall_map_h = {}
        for p in pitfalls:
            nid = brain_hybrid.add_knowledge(
                title=p["title"], content=p["content"],
                kind=p["kind"], confidence=0.9,
            )
            pitfall_map_h[p["id"]] = {**p, "node_id": nid}

        hybrid_results = _run_discovery(brain_hybrid, pitfall_map_h, tasks, "hybrid_tfidf")
        hybrid_metrics = _compute_metrics(hybrid_results)

        # ═══ Comparison ═══
        fts5_rate = fts5_metrics["combined_discovery_rate"]
        hybrid_rate = hybrid_metrics["combined_discovery_rate"]
        improvement = hybrid_rate - fts5_rate

        # Build report
        report = {
            "experiment": "fastapi_knowledge_discovery",
            "version": "v0.60.0",
            "dataset": {
                "pitfalls": len(pitfalls),
                "tasks": len(tasks),
                "source": "FastAPI GitHub Issues (manually curated)",
            },
            "fts5": fts5_metrics,
            "hybrid_tfidf": hybrid_metrics,
            "comparison": {
                "fts5_combined_rate": fts5_rate,
                "hybrid_combined_rate": hybrid_rate,
                "absolute_improvement": round(improvement, 4),
                "relative_improvement": f"+{improvement*100:.1f}%" if improvement > 0 else f"{improvement*100:.1f}%",
            },
            "per_task_fts5": [
                {"task": r.task[:60], "category": r.category,
                 "context_hit": r.context_hit, "nudge_hit": r.nudge_hit}
                for r in fts5_results
            ],
            "per_task_hybrid": [
                {"task": r.task[:60], "category": r.category,
                 "context_hit": r.context_hit, "nudge_hit": r.nudge_hit}
                for r in hybrid_results
            ],
        }

        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        # Print summary
        print(f"\n{'='*65}")
        print(f"  FASTAPI KNOWLEDGE DISCOVERY EXPERIMENT")
        print(f"{'='*65}")
        print(f"  Source: 20 real pitfalls from FastAPI GitHub Issues")
        print(f"  Tasks:  20 natural-language task descriptions")
        print(f"")
        print(f"  ┌────────────────────┬──────────┬─────────────────┐")
        print(f"  │ Mode               │ FTS5     │ Hybrid (TF-IDF) │")
        print(f"  ├────────────────────┼──────────┼─────────────────┤")
        print(f"  │ Context Discovery  │ {fts5_metrics['context_discovery_rate']:>6.1%}  │ {hybrid_metrics['context_discovery_rate']:>6.1%}          │")
        print(f"  │ Nudge Discovery    │ {fts5_metrics['nudge_discovery_rate']:>6.1%}  │ {hybrid_metrics['nudge_discovery_rate']:>6.1%}          │")
        print(f"  │ Combined (either)  │ {fts5_rate:>6.1%}  │ {hybrid_rate:>6.1%}          │")
        print(f"  │ Avg Latency        │ {fts5_metrics['avg_latency_ms']:>5.1f}ms │ {hybrid_metrics['avg_latency_ms']:>5.1f}ms         │")
        print(f"  └────────────────────┴──────────┴─────────────────┘")
        print(f"")
        print(f"  Hybrid improvement: {report['comparison']['relative_improvement']}")
        print(f"")
        print(f"  By Category (Combined, FTS5 / Hybrid):")
        for cat in sorted(fts5_metrics["by_category"].keys()):
            f5 = fts5_metrics["by_category"].get(cat, {})
            hy = hybrid_metrics["by_category"].get(cat, {})
            print(f"    {cat:25s}: {f5.get('rate',0):>5.1%} / {hy.get('rate',0):>5.1%}")
        print(f"{'='*65}")
        print(f"  Report: {REPORT_PATH}")

        # Assertions (記錄用)
        assert len(fts5_results) == 20
        assert len(hybrid_results) == 20
        # At least some discoveries in both modes
        assert fts5_metrics["combined_hits"] > 0, "FTS5 found zero pitfalls"
        assert hybrid_metrics["combined_hits"] > 0, "Hybrid found zero pitfalls"
