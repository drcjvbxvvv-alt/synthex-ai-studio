"""
P0 實驗：sentence-transformers e5-small Hybrid Search 效果驗證

對比 FTS5-only vs Hybrid (e5-small) 在兩個實驗場景的差異：
1. Paraphrased Recall（60 queries, 3 level 改寫）
2. FastAPI Discovery（20 tasks, 真實陷阱）

目的：量化 P0 措施（啟用 sentence-transformers）的實際收益。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

PARAPHRASED_DATASET = Path(__file__).parent / "paraphrased_recall" / "dataset.jsonl"
FASTAPI_PITFALLS = Path(__file__).parent / "fastapi_knowledge_discovery" / "pitfalls.jsonl"
FASTAPI_TASKS = Path(__file__).parent / "fastapi_knowledge_discovery" / "tasks.jsonl"
REPORT_PATH = Path(__file__).parent / "p0_semantic_report.json"


def _load_jsonl(path: Path) -> list[dict]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                items.append(json.loads(line))
    return items


class TestP0SemanticEmbedding:
    """P0: 量化 sentence-transformers e5-small 的改善幅度。"""

    def test_paraphrased_and_discovery(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BRAIN_RELEVANCE_SELECTOR", "keyword")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "")
        monkeypatch.delenv("BRAIN_SYNTHESIZE", raising=False)

        # Check embedder availability
        from project_brain.embedder import get_embedder
        monkeypatch.setenv("BRAIN_EMBED_PROVIDER", "multilingual")
        emb = get_embedder()
        if emb is None or type(emb).__name__ != "MultilingualEmbedder":
            pytest.skip("sentence-transformers not available")

        # ══════════════════════════════════════════════════════════
        # EXPERIMENT 1: Paraphrased Recall
        # ══════════════════════════════════════════════════════════

        dataset = _load_jsonl(PARAPHRASED_DATASET)

        # --- FTS5 baseline ---
        monkeypatch.setenv("BRAIN_EMBED_PROVIDER", "none")
        from project_brain.engine import ProjectBrain

        brain_fts5 = ProjectBrain(str(tmp_path / "para_fts5"))
        node_map_fts5 = {}
        for entry in dataset:
            s = entry["seed"]
            nid = brain_fts5.add_knowledge(title=s["title"], content=s["content"],
                                           kind=s["kind"], confidence=0.9)
            node_map_fts5[s["title"]] = nid

        fts5_hits = 0
        fts5_total = 0
        for entry in dataset:
            expected_id = node_map_fts5[entry["seed"]["title"]]
            for q in entry["queries"]:
                results = brain_fts5.db.search_nodes(q["text"], limit=3)
                if expected_id in [r["id"] for r in results]:
                    fts5_hits += 1
                fts5_total += 1

        # --- Hybrid (e5-small) ---
        monkeypatch.setenv("BRAIN_EMBED_PROVIDER", "multilingual")
        # Need fresh import to pick up new embedder
        brain_hybrid = ProjectBrain(str(tmp_path / "para_hybrid"))

        node_map_hybrid = {}
        for entry in dataset:
            s = entry["seed"]
            nid = brain_hybrid.add_knowledge(title=s["title"], content=s["content"],
                                             kind=s["kind"], confidence=0.9)
            node_map_hybrid[s["title"]] = nid

        hybrid_hits = 0
        hybrid_total = 0
        hybrid_by_level = {1: [0, 0], 2: [0, 0], 3: [0, 0]}  # [hits, total]

        for entry in dataset:
            expected_id = node_map_hybrid[entry["seed"]["title"]]
            for q in entry["queries"]:
                q_vec = emb.embed(q["text"])
                results = brain_hybrid.db.hybrid_search(
                    q["text"], query_vector=q_vec, limit=3,
                )
                hit = expected_id in [r["id"] for r in results]
                if hit:
                    hybrid_hits += 1
                hybrid_total += 1
                lvl = q["level"]
                hybrid_by_level[lvl][1] += 1
                if hit:
                    hybrid_by_level[lvl][0] += 1

        para_fts5_recall = fts5_hits / fts5_total
        para_hybrid_recall = hybrid_hits / hybrid_total

        # ══════════════════════════════════════════════════════════
        # EXPERIMENT 2: FastAPI Discovery
        # ══════════════════════════════════════════════════════════

        pitfalls = _load_jsonl(FASTAPI_PITFALLS)
        tasks = _load_jsonl(FASTAPI_TASKS)

        # --- FTS5 baseline ---
        monkeypatch.setenv("BRAIN_EMBED_PROVIDER", "none")
        brain_fapi_fts5 = ProjectBrain(str(tmp_path / "fapi_fts5"))
        pit_map_fts5 = {}
        for p in pitfalls:
            nid = brain_fapi_fts5.add_knowledge(
                title=p["title"], content=p["content"],
                kind=p["kind"], confidence=0.9)
            pit_map_fts5[p["id"]] = {"node_id": nid, **p}

        fapi_fts5_hits = 0
        for task_entry in tasks:
            expected_nids = {pit_map_fts5[pid]["node_id"]
                            for pid in task_entry["expected_pitfall_ids"]}
            results = brain_fapi_fts5.db.search_nodes(task_entry["task"], limit=5)
            found_ids = {r["id"] for r in results}
            if expected_nids & found_ids:
                fapi_fts5_hits += 1

        # --- Hybrid (e5-small) ---
        monkeypatch.setenv("BRAIN_EMBED_PROVIDER", "multilingual")
        brain_fapi_hybrid = ProjectBrain(str(tmp_path / "fapi_hybrid"))
        pit_map_hybrid = {}
        for p in pitfalls:
            nid = brain_fapi_hybrid.add_knowledge(
                title=p["title"], content=p["content"],
                kind=p["kind"], confidence=0.9)
            pit_map_hybrid[p["id"]] = {"node_id": nid, **p}

        fapi_hybrid_hits = 0
        fapi_by_cat = {}
        for task_entry in tasks:
            expected_nids = {pit_map_hybrid[pid]["node_id"]
                            for pid in task_entry["expected_pitfall_ids"]}
            q_vec = emb.embed(task_entry["task"])
            results = brain_fapi_hybrid.db.hybrid_search(
                task_entry["task"], query_vector=q_vec, limit=5,
            )
            found_ids = {r["id"] for r in results}
            hit = bool(expected_nids & found_ids)
            if hit:
                fapi_hybrid_hits += 1
            cat = task_entry["category"]
            if cat not in fapi_by_cat:
                fapi_by_cat[cat] = [0, 0]
            fapi_by_cat[cat][1] += 1
            if hit:
                fapi_by_cat[cat][0] += 1

        fapi_fts5_rate = fapi_fts5_hits / len(tasks)
        fapi_hybrid_rate = fapi_hybrid_hits / len(tasks)

        # ══════════════════════════════════════════════════════════
        # REPORT
        # ══════════════════════════════════════════════════════════

        report = {
            "experiment": "P0_semantic_embedding_validation",
            "embedder": "MultilingualEmbedder (intfloat/multilingual-e5-small, 384 dim)",
            "paraphrased_recall": {
                "fts5_recall_at_3": round(para_fts5_recall, 4),
                "hybrid_recall_at_3": round(para_hybrid_recall, 4),
                "improvement": round(para_hybrid_recall - para_fts5_recall, 4),
                "by_level": {
                    f"level_{k}": {
                        "hits": v[0], "total": v[1],
                        "recall": round(v[0] / v[1], 4) if v[1] else 0
                    }
                    for k, v in hybrid_by_level.items()
                },
            },
            "fastapi_discovery": {
                "fts5_discovery_rate": round(fapi_fts5_rate, 4),
                "hybrid_discovery_rate": round(fapi_hybrid_rate, 4),
                "improvement": round(fapi_hybrid_rate - fapi_fts5_rate, 4),
                "by_category": {
                    k: {"hits": v[0], "total": v[1],
                        "rate": round(v[0] / v[1], 4) if v[1] else 0}
                    for k, v in fapi_by_cat.items()
                },
            },
        }

        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        # Print results
        print(f"\n{'='*65}")
        print(f"  P0 SEMANTIC EMBEDDING EXPERIMENT (e5-small, 384 dim)")
        print(f"{'='*65}")
        print(f"")
        print(f"  ┌─────────────────────┬──────────┬──────────────────┬──────────┐")
        print(f"  │ Experiment          │ FTS5     │ Hybrid (e5-small)│ Δ        │")
        print(f"  ├─────────────────────┼──────────┼──────────────────┼──────────┤")
        print(f"  │ Paraphrased Recall  │ {para_fts5_recall:>6.1%}  │ {para_hybrid_recall:>6.1%}          │ {para_hybrid_recall-para_fts5_recall:>+5.1%}   │")
        print(f"  │ FastAPI Discovery   │ {fapi_fts5_rate:>6.1%}  │ {fapi_hybrid_rate:>6.1%}          │ {fapi_hybrid_rate-fapi_fts5_rate:>+5.1%}   │")
        print(f"  └─────────────────────┴──────────┴──────────────────┴──────────┘")
        print(f"")
        print(f"  Paraphrased by Level (Hybrid):")
        for lvl, v in hybrid_by_level.items():
            r = v[0] / v[1] if v[1] else 0
            print(f"    Level {lvl}: {r:.1%} ({v[0]}/{v[1]})")
        print(f"")
        print(f"  FastAPI by Category (Hybrid):")
        for cat, v in sorted(fapi_by_cat.items()):
            r = v[0] / v[1] if v[1] else 0
            print(f"    {cat:25s}: {r:.1%} ({v[0]}/{v[1]})")
        print(f"{'='*65}")
        print(f"  Report: {REPORT_PATH}")

        # Assertions
        assert para_hybrid_recall >= para_fts5_recall, \
            "Hybrid should be at least as good as FTS5"
        assert fapi_hybrid_hits > 0, "Hybrid found zero in FastAPI experiment"
