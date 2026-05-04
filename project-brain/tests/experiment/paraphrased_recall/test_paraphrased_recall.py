"""
Paraphrased Recall 實驗 — 量化「用戶用自己的話問，Brain 能不能找到」

與 baseline（標題搜自己 recall@3=100%）對比，本實驗使用改寫查詢：
- Level 1: 同義詞替換
- Level 2: 場景描述
- Level 3: 自然語言問題

結果量化 Brain FTS5 在真實使用場景的檢索品質。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest


DATASET_PATH = Path(__file__).parent / "dataset.jsonl"
REPORT_PATH = Path(__file__).parent / "report.json"


@dataclass
class QueryResult:
    query: str
    level: int
    lang: str
    seed_title: str
    seed_kind: str
    expected_id: str
    retrieved_ids: list[str]
    hit_at_3: bool
    hit_at_5: bool
    rank: int  # 0 = not found, 1-indexed if found
    elapsed_ms: int


@pytest.fixture(scope="module")
def brain_with_seeds(tmp_path_factory, monkeypatch_module):
    """Load dataset, seed Brain, return (brain, node_map, dataset)."""
    monkeypatch_module.setenv("BRAIN_RELEVANCE_SELECTOR", "keyword")
    monkeypatch_module.setenv("BRAIN_EMBED_PROVIDER", "none")
    monkeypatch_module.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch_module.setenv("OPENAI_API_KEY", "")

    tmp = tmp_path_factory.mktemp("paraphrased_recall")
    monkeypatch_module.setenv("BRAIN_WORKDIR", str(tmp))

    from project_brain.engine import ProjectBrain
    brain = ProjectBrain(str(tmp))

    # Load dataset
    dataset = []
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            dataset.append(json.loads(line))

    # Seed nodes
    node_map = {}  # seed_title -> node_id
    for entry in dataset:
        seed = entry["seed"]
        nid = brain.add_knowledge(
            title=seed["title"],
            content=seed["content"],
            kind=seed["kind"],
            confidence=0.9,
        )
        node_map[seed["title"]] = nid

    return brain, node_map, dataset


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


class TestParaphrasedRecall:
    """Execute paraphrased recall experiment and generate report."""

    def test_run_experiment(self, brain_with_seeds):
        brain, node_map, dataset = brain_with_seeds

        results: list[QueryResult] = []

        for entry in dataset:
            seed = entry["seed"]
            expected_id = node_map[seed["title"]]

            for q in entry["queries"]:
                t0 = time.monotonic()
                search_results = brain.db.search_nodes(q["text"], limit=5)
                elapsed = int((time.monotonic() - t0) * 1000)

                retrieved_ids = [r["id"] for r in search_results]
                rank = 0
                for i, rid in enumerate(retrieved_ids):
                    if rid == expected_id:
                        rank = i + 1
                        break

                results.append(QueryResult(
                    query=q["text"],
                    level=q["level"],
                    lang=q["lang"],
                    seed_title=seed["title"],
                    seed_kind=seed["kind"],
                    expected_id=expected_id,
                    retrieved_ids=retrieved_ids[:5],
                    hit_at_3=(rank > 0 and rank <= 3),
                    hit_at_5=(rank > 0 and rank <= 5),
                    rank=rank,
                    elapsed_ms=elapsed,
                ))

        # Compute metrics
        total = len(results)
        hits_3 = sum(1 for r in results if r.hit_at_3)
        hits_5 = sum(1 for r in results if r.hit_at_5)
        recall_3 = hits_3 / total if total else 0
        recall_5 = hits_5 / total if total else 0
        mrr = sum((1.0 / r.rank if r.rank > 0 else 0) for r in results) / total

        # By level
        by_level = {}
        for lvl in [1, 2, 3]:
            lvl_results = [r for r in results if r.level == lvl]
            lvl_hits = sum(1 for r in lvl_results if r.hit_at_3)
            by_level[f"level_{lvl}"] = {
                "total": len(lvl_results),
                "hits_at_3": lvl_hits,
                "recall_at_3": lvl_hits / len(lvl_results) if lvl_results else 0,
            }

        # By language
        by_lang = {}
        for lang in ["zh", "en", "mixed"]:
            lang_results = [r for r in results if r.lang == lang]
            if not lang_results:
                continue
            lang_hits = sum(1 for r in lang_results if r.hit_at_3)
            by_lang[lang] = {
                "total": len(lang_results),
                "hits_at_3": lang_hits,
                "recall_at_3": lang_hits / len(lang_results),
            }

        # By kind
        by_kind = {}
        for kind in ["Rule", "Decision", "Pitfall", "ADR", "Note"]:
            kind_results = [r for r in results if r.seed_kind == kind]
            if not kind_results:
                continue
            kind_hits = sum(1 for r in kind_results if r.hit_at_3)
            by_kind[kind] = {
                "total": len(kind_results),
                "hits_at_3": kind_hits,
                "recall_at_3": kind_hits / len(kind_results),
            }

        # Misses analysis
        misses = [r for r in results if not r.hit_at_3]
        miss_details = [
            {"query": r.query, "level": r.level, "lang": r.lang,
             "expected_title": r.seed_title[:60], "rank": r.rank}
            for r in misses[:20]
        ]

        # Build report
        report = {
            "experiment": "paraphrased_recall",
            "version": "v0.60.0",
            "search_mode": "fts5",
            "dataset_size": len(dataset),
            "total_queries": total,
            "metrics": {
                "recall_at_3": round(recall_3, 4),
                "recall_at_5": round(recall_5, 4),
                "mrr": round(mrr, 4),
                "avg_latency_ms": round(sum(r.elapsed_ms for r in results) / total, 1),
            },
            "by_level": by_level,
            "by_language": by_lang,
            "by_kind": by_kind,
            "misses": miss_details,
            "per_query": [
                {"query": r.query[:60], "level": r.level, "lang": r.lang,
                 "hit_at_3": r.hit_at_3, "rank": r.rank}
                for r in results
            ],
        }

        # Save report
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        # Print summary
        print(f"\n{'='*60}")
        print(f"  PARAPHRASED RECALL EXPERIMENT (FTS5 only)")
        print(f"{'='*60}")
        print(f"  Dataset: {len(dataset)} seed nodes × 3 queries = {total} queries")
        print(f"  Recall@3: {recall_3:.1%} ({hits_3}/{total})")
        print(f"  Recall@5: {recall_5:.1%} ({hits_5}/{total})")
        print(f"  MRR:      {mrr:.4f}")
        print(f"  Avg Latency: {report['metrics']['avg_latency_ms']:.1f} ms")
        print(f"\n  By Difficulty Level:")
        for lvl, data in by_level.items():
            print(f"    {lvl}: recall@3 = {data['recall_at_3']:.1%} ({data['hits_at_3']}/{data['total']})")
        print(f"\n  By Language:")
        for lang, data in by_lang.items():
            print(f"    {lang:6s}: recall@3 = {data['recall_at_3']:.1%} ({data['hits_at_3']}/{data['total']})")
        print(f"\n  By Knowledge Type:")
        for kind, data in by_kind.items():
            print(f"    {kind:10s}: recall@3 = {data['recall_at_3']:.1%} ({data['hits_at_3']}/{data['total']})")
        print(f"\n  Top Misses ({len(misses)} total):")
        for m in miss_details[:5]:
            print(f"    L{m['level']} [{m['lang']}] \"{m['query'][:40]}\" → rank={m['rank']}")
        print(f"{'='*60}")
        print(f"  Report saved: {REPORT_PATH}")

        # Assertions (記錄用，不設硬門檻)
        assert total == len(dataset) * 3, "Query count mismatch"
        assert 0.0 <= recall_3 <= 1.0, "recall@3 out of range"
        # FTS5 on paraphrased queries: expect > 0% (at least some hits)
        assert hits_3 > 0, "Zero hits — FTS5 found nothing at all"
