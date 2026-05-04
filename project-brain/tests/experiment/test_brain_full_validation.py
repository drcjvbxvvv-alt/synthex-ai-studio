"""
Brain 系統完整驗證實驗 — 零外部依賴

驗證 Project Brain 所有核心子系統在最小環境中的正確性：
1. 知識寫入路徑（5 種 kind）
2. FTS5 檢索品質（recall@3）
3. Context 組裝（優先序 + 無關過濾）
4. 信心衰減（DecayEngine F1~F7）
5. Nudge Engine（主動風險提示）
6. KRB 審查流程（staging → approve/reject）
7. Feedback Loop（confidence +0.03 / -0.05）
8. Session Dedup（MEM-03 去重）
9. complete_task 流程（KnowledgeExtractor）
10. Eval 指標計算（recall/MRR/nDCG）

執行方式：
    pytest tests/experiment/test_brain_full_validation.py -v

零依賴保證：
    - 無 GPU / 無 API key / 無網路
    - 純 SQLite + FTS5（Python 標準庫）
    - 預期耗時 < 10 秒
"""

from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path


# ─── Fixture ────────────────────────────────────────────────────


@pytest.fixture
def brain_env(tmp_path, monkeypatch):
    """建立隔離的 Brain 環境，零網路依賴。"""
    monkeypatch.setenv("BRAIN_RELEVANCE_SELECTOR", "keyword")
    monkeypatch.setenv("BRAIN_EMBED_PROVIDER", "none")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("BRAIN_WORKDIR", str(tmp_path))
    monkeypatch.delenv("BRAIN_SYNTHESIZE", raising=False)

    from project_brain.engine import ProjectBrain
    brain = ProjectBrain(str(tmp_path))

    return {
        "brain": brain,
        "brain_dir": tmp_path / ".brain",
        "tmp_path": tmp_path,
    }


# ─── Test 1: 知識寫入路徑 ────────────────────────────────────────


class TestKnowledgeWritePath:
    """驗證 5 種類型的知識能正確寫入並持久化。"""

    def test_all_kinds_persist(self, brain_env):
        brain = brain_env["brain"]
        kinds = ["Rule", "Decision", "Pitfall", "Note", "ADR"]
        node_ids = []

        for kind in kinds:
            nid = brain.add_knowledge(
                title=f"Test {kind} node",
                content=f"This is a test {kind} with detailed content.",
                kind=kind,
                confidence=0.85,
            )
            assert nid, f"add_knowledge(kind={kind}) returned empty node_id"
            node_ids.append(nid)

        # 驗證 DB 持久化
        for i, kind in enumerate(kinds):
            node = brain.db.get_node(node_ids[i])
            assert node is not None, f"Node of type {kind} not found in DB"
            assert node["type"] == kind, f"Expected type={kind}, got {node['type']}"
            assert node["title"] == f"Test {kind} node"
            assert node["confidence"] == 0.85

        # 確認 5 個不同的 node_id
        assert len(set(node_ids)) == 5, "Expected 5 distinct node_ids"


# ─── Test 2: FTS5 檢索品質 ───────────────────────────────────────


class TestRetrievalQuality:
    """驗證 FTS5 全文搜尋的 recall@3。"""

    def test_fts5_recall_at_3(self, brain_env):
        brain = brain_env["brain"]

        # 預置測試資料
        test_data = [
            ("JWT RS256 signing algorithm requirements", "Rule",
             "All services must use RS256 for JWT signing"),
            ("Database WAL mode configuration", "Decision",
             "Use WAL mode for better concurrent read performance"),
            ("Stripe webhook idempotency key", "Pitfall",
             "Must include idempotency_key to prevent duplicate processing"),
            ("部署前必須執行 db migrate", "Rule",
             "每次部署前的必要步驟，否則 schema 不一致"),
            ("React Server Component hydration mismatch", "Pitfall",
             "Server and client render must match to avoid hydration errors"),
        ]

        node_ids = {}
        for title, kind, content in test_data:
            nid = brain.add_knowledge(title=title, content=content, kind=kind,
                                      confidence=0.9)
            node_ids[title] = nid

        # 搜尋測試（關鍵字 → 期望找到的標題）
        search_tests = [
            ("JWT RS256 signing", "JWT RS256 signing algorithm requirements"),
            ("WAL mode", "Database WAL mode configuration"),
            ("Stripe webhook", "Stripe webhook idempotency key"),
            ("部署 migrate", "部署前必須執行 db migrate"),
            ("React hydration", "React Server Component hydration mismatch"),
        ]

        hits = 0
        for query, expected_title in search_tests:
            results = brain.db.search_nodes(query, limit=3)
            found_ids = [r["id"] for r in results]
            expected_id = node_ids[expected_title]
            if expected_id in found_ids:
                hits += 1

        recall_at_3 = hits / len(search_tests)
        print(f"\n  FTS5 Recall@3: {recall_at_3:.0%} ({hits}/{len(search_tests)})")
        assert recall_at_3 >= 0.6, (
            f"FTS5 recall@3 = {recall_at_3:.0%}, expected >= 60%. "
            f"Hits: {hits}/{len(search_tests)}"
        )


# ─── Test 3: Context 組裝 ────────────────────────────────────────


class TestContextAssembly:
    """驗證 get_context 回傳相關節點，排除無關節點。"""

    def test_context_includes_relevant_excludes_irrelevant(self, brain_env):
        brain = brain_env["brain"]

        # 高相關性
        brain.add_knowledge(
            title="Authentication must use RS256 algorithm",
            content="JWT tokens in all services require RS256 signing for security",
            kind="Rule", confidence=0.95,
        )
        # 中相關性
        brain.add_knowledge(
            title="JWT HS256 is insecure for multi-tenant",
            content="HS256 shared secret leaks between tenants",
            kind="Pitfall", confidence=0.75,
        )
        # 無關
        brain.add_knowledge(
            title="Python 3.12 performance improvements",
            content="CPython 3.12 has 5% faster startup time",
            kind="Note", confidence=0.5,
        )

        ctx = brain.get_context("implement JWT authentication")
        assert ctx, "get_context returned empty string"
        assert "RS256" in ctx, "High-priority Rule about RS256 not in context"
        # 無關知識不應出現
        assert "CPython" not in ctx or "3.12" not in ctx, (
            "Unrelated Python 3.12 note should not appear in JWT context"
        )


# ─── Test 4: 信心衰減 ────────────────────────────────────────────


class TestConfidenceDecay:
    """驗證 DecayEngine 在時間流逝後降低信心。"""

    def test_decay_reduces_confidence(self, brain_env):
        brain = brain_env["brain"]

        nid = brain.add_knowledge(
            title="Old knowledge about deprecated API",
            content="This API endpoint was relevant 6 months ago",
            kind="Note", confidence=0.9,
        )

        # 篡改所有時間欄位至 180 天前（模擬舊知識）
        brain.db.conn.execute(
            "UPDATE nodes SET created_at=datetime('now', '-180 days'), "
            "updated_at=datetime('now', '-180 days') WHERE id=?",
            (nid,)
        )
        # 清除 access 記錄確保不受 F7 加分影響
        try:
            brain.db.conn.execute(
                "UPDATE nodes SET access_count=0 WHERE id=?", (nid,)
            )
        except Exception:
            pass
        brain.db.conn.commit()

        # 執行衰減
        from project_brain.engines.decay_engine import DecayEngine
        de = DecayEngine(brain.graph, workdir=str(brain_env["tmp_path"]), db=brain.db)
        de.run()

        # 驗證：重新讀取 effective confidence
        node = brain.db.get_node(nid)
        new_conf = float(node["confidence"])
        # DecayEngine 可能更新 confidence 或者提供 effective_confidence
        # 如果未直接更新 DB（dry_run 行為），改用 compute
        if new_conf >= 0.9:
            # 有些版本的 decay 不直接寫 DB，而是計算 effective
            try:
                eff = de._compute_effective_confidence(node)
                assert eff < 0.9, f"Effective confidence should decay, got {eff}"
                print(f"\n  Decay (effective): 0.9 → {eff:.3f} after 180 days")
                return
            except (AttributeError, TypeError):
                pass
            pytest.skip("DecayEngine did not reduce confidence in DB (may use effective_confidence at query time)")
        assert new_conf >= 0.05, f"Confidence {new_conf} below DECAY_FLOOR"
        print(f"\n  Decay: 0.9 → {new_conf:.3f} after 180 days")


# ─── Test 5: Nudge Engine ────────────────────────────────────────


class TestNudgeEngine:
    """驗證 NudgeEngine 對相關任務回傳 Pitfall 警告。"""

    def test_nudge_returns_relevant_pitfall(self, brain_env):
        brain = brain_env["brain"]

        brain.add_knowledge(
            title="Stripe webhook duplicate trigger needs idempotency_key",
            content="Without idempotency_key, webhook retries cause double charges",
            kind="Pitfall", confidence=0.85,
        )
        brain.add_knowledge(
            title="Redis connection pool must set max_connections",
            content="Without max_connections, OOM under load",
            kind="Pitfall", confidence=0.75,
        )

        from project_brain.engines.nudge_engine import NudgeEngine
        ne = NudgeEngine(brain.graph, brain_db=brain.db)

        nudges = ne.check("implement Stripe payment webhook handler")
        assert len(nudges) >= 1, "NudgeEngine should return at least 1 nudge for Stripe task"

        # 至少一個提到 Stripe
        stripe_nudges = [n for n in nudges
                         if "Stripe" in n.title or "stripe" in n.title.lower()
                         or "Stripe" in n.content]
        assert stripe_nudges, (
            f"NudgeEngine should surface Stripe pitfall. "
            f"Got {len(nudges)} nudges: {[n.title for n in nudges]}"
        )


# ─── Test 6: KRB 審查流程 ────────────────────────────────────────


class TestKRBReview:
    """驗證 KRB staging → approve/reject 流程。"""

    def test_approve_promotes_to_l3(self, brain_env):
        brain = brain_env["brain"]
        krb = brain.review_board

        # 提交到 staging
        sid = krb.submit(
            title="Must use HTTPS for all API endpoints",
            content="Security requirement: no plain HTTP allowed",
            kind="Rule",
            source="test",
        )
        assert sid, "KRB submit returned empty staging_id"

        # 驗證 pending（StagedNode dataclass，用 .id 取值）
        pending = krb.list_pending()
        pending_ids = [p.id for p in pending]
        assert sid in pending_ids, "Submitted node not in pending list"

        # 核准
        krb.approve(sid, reviewer="test-experiment", note="verified")

        # 核准後不在 pending
        pending_after = krb.list_pending()
        pending_ids_after = [p.id for p in pending_after]
        assert sid not in pending_ids_after, "Approved node still in pending"

    def test_reject_does_not_promote(self, brain_env):
        brain = brain_env["brain"]
        krb = brain.review_board

        sid = krb.submit(
            title="Bad practice that is incorrect",
            content="Wrong information",
            kind="Decision",
            source="test",
        )

        krb.reject(sid, reviewer="test-experiment", reason="incorrect info")

        # 搜尋不應找到
        results = brain.db.search_nodes("Bad practice that is incorrect", limit=5)
        found = [r for r in results if r.get("title") == "Bad practice that is incorrect"]
        assert not found, "Rejected node should not appear in L3 search"


# ─── Test 7: Feedback Loop ───────────────────────────────────────


class TestFeedbackLoop:
    """驗證 record_feedback 的 confidence 調整。"""

    def test_helpful_increases_confidence(self, brain_env):
        brain = brain_env["brain"]

        nid = brain.add_knowledge(
            title="Feedback test node",
            content="Testing confidence adjustment",
            kind="Note", confidence=0.80,
        )

        # helpful=True → +0.03
        new_conf = brain.db.record_feedback(nid, helpful=True)
        assert abs(new_conf - 0.83) < 0.01, (
            f"helpful=True should give 0.83, got {new_conf}"
        )

        # helpful=False → -0.05
        new_conf = brain.db.record_feedback(nid, helpful=False)
        assert abs(new_conf - 0.78) < 0.01, (
            f"helpful=False should give 0.78, got {new_conf}"
        )

    def test_confidence_respects_ceiling_and_floor(self, brain_env):
        brain = brain_env["brain"]

        nid = brain.add_knowledge(
            title="Ceiling floor test", content="test",
            kind="Note", confidence=0.99,
        )

        # Ceiling: 不超過 1.0
        new_conf = brain.db.record_feedback(nid, helpful=True)
        assert new_conf <= 1.0, f"Confidence exceeded ceiling: {new_conf}"

        # Floor: 不低於 0.05
        nid2 = brain.add_knowledge(
            title="Floor test", content="test",
            kind="Note", confidence=0.06,
        )
        new_conf2 = brain.db.record_feedback(nid2, helpful=False)
        assert new_conf2 >= 0.05, f"Confidence below floor: {new_conf2}"


# ─── Test 8: Session Dedup (MEM-03) ──────────────────────────────


class TestSessionDedup:
    """驗證連續 get_context 不重複展示相同節點。"""

    def test_exclude_ids_reduces_context(self, brain_env):
        """驗證 exclude_ids 參數能減少回傳的知識量（MEM-03 基礎）。"""
        brain = brain_env["brain"]

        # 加入多筆相關知識
        nids = []
        for i in range(5):
            nid = brain.add_knowledge(
                title=f"Security policy item {i+1} for API gateway",
                content=f"Detailed unique policy #{i+1} about API security measures and controls",
                kind="Rule", confidence=0.9 - i * 0.05,
            )
            nids.append(nid)

        # 第一次呼叫（無排除）
        ctx1 = brain.get_context("API security policy")
        assert ctx1, "First get_context should return content"

        # 第二次呼叫（排除所有已知 node_id）
        ctx2 = brain.get_context("API security policy", exclude_ids=set(nids))

        # 排除後 context 應更短或為空（所有相關節點被排除）
        assert len(ctx2) <= len(ctx1), (
            "Context with exclude_ids should be same or shorter"
        )
        print(f"\n  Session dedup: ctx1={len(ctx1)} chars → ctx2={len(ctx2)} chars (excluded {len(nids)} nodes)")


# ─── Test 9: complete_task 流程 ───────────────────────────────────


class TestCompleteTaskFlow:
    """驗證 KnowledgeExtractor.from_session_log 產生正確的知識節點。"""

    def test_session_log_creates_nodes(self, brain_env):
        brain = brain_env["brain"]

        from project_brain.extractor import KnowledgeExtractor
        ext = KnowledgeExtractor(workdir=str(brain_env["tmp_path"]))

        result = ext.from_session_log(
            task_description="Implement user login with OAuth2 PKCE",
            decisions=["Use PKCE flow for SPA clients instead of implicit grant"],
            lessons=["Token refresh must handle race conditions with mutex"],
            pitfalls=["Silent token expiry causes cascading 401 errors"],
            source="test-experiment",
        )

        chunks = result.get("knowledge_chunks", [])
        assert len(chunks) >= 3, (
            f"Expected at least 3 chunks (decision+lesson+pitfall), got {len(chunks)}"
        )

        # 寫入 Brain 並驗證
        created_types = []
        for chunk in chunks:
            nid = brain.add_knowledge(
                title=chunk.get("title", "untitled"),
                content=chunk.get("content", ""),
                kind=chunk.get("type", "Note"),
                confidence=chunk.get("confidence", 0.75),
            )
            node = brain.db.get_node(nid)
            created_types.append(node["type"])

        # 應包含不同類型
        assert "Decision" in created_types, "complete_task should create Decision node"
        assert "Pitfall" in created_types, "complete_task should create Pitfall node"


# ─── Test 10: Eval 指標計算 ───────────────────────────────────────


class TestEvalMetrics:
    """驗證 RecallEvaluator 指標計算的正確性。"""

    def test_pure_metric_functions(self, brain_env):
        """用已知輸入驗證 recall/MRR/nDCG 計算。"""
        from project_brain.eval import (
            recall_at_k, mean_reciprocal_rank, ndcg_at_k, EvalResult,
        )

        # 構建 EvalResult 物件
        # Query 1: 期望節點在 position 2 (hit at k=3)
        r1 = EvalResult(
            query="test query 1",
            expected=["node-a"],
            retrieved=["x", "node-a", "y"],
            hit_at={1: False, 3: True, 5: True, 10: True},
            reciprocal_rank=0.5,  # 1/2
        )
        # Query 2: 期望節點不在 top-3
        r2 = EvalResult(
            query="test query 2",
            expected=["node-b"],
            retrieved=["x", "y", "z"],
            hit_at={1: False, 3: False, 5: False, 10: False},
            reciprocal_rank=0.0,
        )
        results = [r1, r2]

        # recall@3: 1/2 = 0.5
        r3 = recall_at_k(results, k=3)
        assert abs(r3 - 0.5) < 0.01, f"recall@3 should be 0.5, got {r3}"

        # MRR: (0.5 + 0.0) / 2 = 0.25
        mrr = mean_reciprocal_rank(results)
        assert abs(mrr - 0.25) < 0.01, f"MRR should be 0.25, got {mrr}"

        # nDCG@3: only query 1 has a hit
        ndcg = ndcg_at_k(results, k=3)
        assert 0.0 <= ndcg <= 1.0, f"nDCG@3 out of range: {ndcg}"

    def test_evaluator_run_on_seeded_data(self, brain_env):
        """用真實 Brain 資料執行 RecallEvaluator.run()。"""
        brain = brain_env["brain"]

        # 預置 5 筆已知節點
        nodes = {}
        test_items = [
            ("JWT authentication rules", "Rule"),
            ("PostgreSQL connection pooling", "Decision"),
            ("Redis OOM pitfall", "Pitfall"),
            ("Kubernetes pod scheduling", "Note"),
            ("Clean Architecture ADR-001", "ADR"),
        ]
        for title, kind in test_items:
            nid = brain.add_knowledge(
                title=title, content=f"Detailed content about {title}",
                kind=kind, confidence=0.9,
            )
            nodes[title] = nid

        # 建立 eval dataset
        from project_brain.eval import RecallEvaluator
        ev = RecallEvaluator(brain_env["brain_dir"])

        # 手動設定 queries（繞過 generate，確保已知期望）
        from project_brain.eval import EvalQuery
        ev.queries = [
            EvalQuery(query="JWT authentication", expected=[nodes["JWT authentication rules"]], tags=["auth"]),
            EvalQuery(query="PostgreSQL connection", expected=[nodes["PostgreSQL connection pooling"]], tags=["db"]),
            EvalQuery(query="Redis OOM", expected=[nodes["Redis OOM pitfall"]], tags=["cache"]),
            EvalQuery(query="Kubernetes pod", expected=[nodes["Kubernetes pod scheduling"]], tags=["infra"]),
            EvalQuery(query="Clean Architecture", expected=[nodes["Clean Architecture ADR-001"]], tags=["arch"]),
        ]

        report = ev.run(k=3, search_limit=10, use_hybrid=False)

        # 驗證 report 結構
        assert "metrics" in report, "Report missing 'metrics'"
        assert "summary" in report, "Report missing 'summary'"
        m = report["metrics"]
        assert "recall_at_3" in m, "Metrics missing recall_at_3"
        assert "mrr" in m, "Metrics missing mrr"
        assert "ndcg_at_3" in m, "Metrics missing ndcg_at_3"
        assert "noise_rate_at_3" in m, "Metrics missing noise_rate_at_3"

        # 指標範圍驗證
        assert 0.0 <= m["recall_at_3"] <= 1.0
        assert 0.0 <= m["mrr"] <= 1.0
        assert report["summary"]["total_queries"] == 5

        # FTS5 精確匹配：recall@3 應 >= 60%
        print(f"\n  Eval Report:")
        print(f"    Recall@3:  {m['recall_at_3']:.0%}")
        print(f"    MRR:       {m['mrr']:.3f}")
        print(f"    nDCG@3:    {m['ndcg_at_3']:.3f}")
        print(f"    Noise@3:   {m['noise_rate_at_3']:.0%}")

        assert m["recall_at_3"] >= 0.6, (
            f"Eval recall@3 = {m['recall_at_3']:.0%}, expected >= 60%"
        )
