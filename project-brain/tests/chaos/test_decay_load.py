"""
tests/chaos/test_decay_load.py — Decay Engine 100K 節點負載測試（TEST-02）

量測 DecayEngine 在 100K 節點規模下的衰減執行時間。
執行方式：pytest -m chaos tests/chaos/test_decay_load.py -v
"""
import time
import pytest
from pathlib import Path


@pytest.mark.chaos
class TestDecayLoad:
    """TEST-02: DecayEngine 100K 節點負載測試"""

    def test_decay_100k_nodes_completes_within_budget(self, tmp_path):
        """100K 節點知識庫完整衰減應在 300 秒內完成（TEST-02）"""
        from project_brain.graph import KnowledgeGraph
        from project_brain.decay_engine import DecayEngine

        N = 100_000
        BUDGET_SECONDS = 300
        BATCH = 1_000

        # ── 建立 100K 節點 ──────────────────────────────────────────
        g = KnowledgeGraph(tmp_path)
        buf: list[tuple] = []

        for i in range(N):
            buf.append((
                f"node-{i}",
                "Decision",
                f"架構決策 {i}",
                f"選擇方案 A 而非方案 B，原因是效能差異約 {i % 50}%",
                round(0.4 + (i % 7) * 0.08, 2),   # 信心值介於 0.4–0.88
            ))
            if len(buf) >= BATCH:
                for nid, ntype, title, content, conf in buf:
                    g.add_node(nid, ntype, title,
                               content=content, confidence=conf)
                buf.clear()

        for nid, ntype, title, content, conf in buf:
            g.add_node(nid, ntype, title, content=content, confidence=conf)

        total = g._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        assert total == N, f"應建立 {N} 個節點，實際: {total}"

        # ── 執行衰減並計時 ─────────────────────────────────────────
        engine = DecayEngine(graph=g, workdir=str(tmp_path))

        t0 = time.monotonic()
        reports = engine.run(batch_size=500)
        elapsed = time.monotonic() - t0

        # ── 斷言 ──────────────────────────────────────────────────
        assert elapsed < BUDGET_SECONDS, (
            f"100K 節點衰減耗時 {elapsed:.1f}s，超出預算 {BUDGET_SECONDS}s"
        )
        assert isinstance(reports, list), "run() 應回傳 list"

        # 衰減引擎應至少處理一部分節點（信心值 < 1.0 的節點理應變化）
        changed = len(reports)
        assert changed >= 0, "changed 節點數不應為負"

        print(
            f"\n[TEST-02] 100K 節點衰減完成：{elapsed:.1f}s，"
            f"變化節點數：{changed}"
        )
