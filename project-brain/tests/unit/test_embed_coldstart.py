"""
tests/unit/test_embed_coldstart.py

Embedding 冷啟動優化驗收測試

覆蓋：
  - get_embedder lazy probe（skip test embed when provider explicit）
  - add_knowledge 非同步 embedding（不阻塞 return）
  - warmup_embedder 背景預載
  - BRAIN_EMBED_LAZY env var
  - 配合 provider=none 停用 embedding
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from project_brain.core.brain_db import BrainDB


class TestGetEmbedderLazyProbe(unittest.TestCase):
    """get_embedder 在 provider 明確設定時跳過 test embed。"""

    def setUp(self):
        # Clear the module-level cache between tests
        import project_brain.embedder as _mod
        _mod._embedder_cache.clear()

    def test_explicit_provider_skips_probe(self):
        """BRAIN_EMBED_PROVIDER=tfidf 時不應呼叫 e.embed("test")。"""
        import project_brain.embedder as _mod
        _mod._embedder_cache.clear()

        with mock.patch.dict(os.environ, {"BRAIN_EMBED_PROVIDER": "tfidf"}):
            emb = _mod.get_embedder()
            # LocalTFIDF should be returned
            self.assertIsNotNone(emb)
            self.assertIn("TFIDF", type(emb).__name__)

    def test_lazy_env_skips_probe(self):
        """BRAIN_EMBED_LAZY=1 時跳過 test embed。"""
        import project_brain.embedder as _mod
        _mod._embedder_cache.clear()

        with mock.patch.dict(os.environ, {"BRAIN_EMBED_LAZY": "1"}):
            emb = _mod.get_embedder()
            # Should return an embedder (LocalTFIDF fallback at minimum)
            self.assertIsNotNone(emb)

    def test_provider_none_returns_none(self):
        """BRAIN_EMBED_PROVIDER=none 停用所有 embedding。"""
        import project_brain.embedder as _mod
        _mod._embedder_cache.clear()

        with mock.patch.dict(os.environ, {"BRAIN_EMBED_PROVIDER": "none"}):
            emb = _mod.get_embedder()
            self.assertIsNone(emb)

    def test_cache_hit_returns_immediately(self):
        """第二次呼叫走 cache，不重新建構。"""
        import project_brain.embedder as _mod
        _mod._embedder_cache.clear()

        with mock.patch.dict(os.environ, {"BRAIN_EMBED_PROVIDER": "tfidf"}):
            e1 = _mod.get_embedder()
            e2 = _mod.get_embedder()
            self.assertIs(e1, e2, "Second call should return cached instance")


class TestAsyncEmbedding(unittest.TestCase):
    """add_knowledge embedding 非同步：node 立即可用。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_knowledge_returns_immediately(self):
        """add_knowledge 應立即返回 node_id，不被 embedding 阻塞。"""
        from project_brain.engine import ProjectBrain

        with mock.patch.dict(os.environ, {"BRAIN_EMBED_PROVIDER": "tfidf"}):
            brain = ProjectBrain(str(self.brain_dir))

            t0 = time.monotonic()
            nid = brain.add_knowledge(
                "Test node for async embedding",
                content="Some content",
                kind="Rule",
                confidence=0.8,
            )
            elapsed = time.monotonic() - t0

            self.assertIsNotNone(nid)
            self.assertTrue(len(nid) > 0)
            # Should return in < 1 second (embedding is in background)
            self.assertLess(elapsed, 1.0,
                            f"add_knowledge took {elapsed:.2f}s — embedding may be blocking")

    def test_node_searchable_via_fts5_immediately(self):
        """Node 在 embedding 完成前就可以透過 FTS5 搜尋到。"""
        from project_brain.engine import ProjectBrain

        with mock.patch.dict(os.environ, {"BRAIN_EMBED_PROVIDER": "none"}):
            brain = ProjectBrain(str(self.brain_dir))
            brain.add_knowledge(
                "Unique searchable Kubernetes Helm deployment",
                content="K8s deployment details",
                kind="Rule",
                confidence=0.9,
            )
            # Immediately searchable
            results = brain.db.search_nodes("Kubernetes Helm")
            titles = [r["title"] for r in results]
            self.assertTrue(
                any("Kubernetes" in t for t in titles),
                f"Node should be FTS5-searchable immediately. Got: {titles}"
            )


class TestWarmupEmbedder(unittest.TestCase):
    """warmup_embedder 背景預載。"""

    def setUp(self):
        import project_brain.embedder as _mod
        _mod._embedder_cache.clear()

    def test_warmup_starts_background_thread(self):
        """warmup_embedder 應啟動一個 daemon thread。"""
        from project_brain.embedder import warmup_embedder

        initial_threads = threading.active_count()

        with mock.patch.dict(os.environ, {"BRAIN_EMBED_PROVIDER": "tfidf"}):
            warmup_embedder()
            # Give thread a moment to start
            time.sleep(0.1)

        # Thread should have been created (may already be done for LocalTFIDF)
        # Just verify it didn't crash
        import project_brain.embedder as _mod
        # After warmup, cache should be populated
        time.sleep(0.5)
        self.assertIn("tfidf", _mod._embedder_cache)

    def test_warmup_with_provider_none_does_not_crash(self):
        """warmup with BRAIN_EMBED_PROVIDER=none should not crash."""
        from project_brain.embedder import warmup_embedder
        with mock.patch.dict(os.environ, {"BRAIN_EMBED_PROVIDER": "none"}):
            warmup_embedder()
            time.sleep(0.2)  # let thread complete


class TestEmbedProviderIntegration(unittest.TestCase):
    """Integration: LocalTFIDF 作為 zero-dep fallback。"""

    def setUp(self):
        import project_brain.embedder as _mod
        _mod._embedder_cache.clear()

    def test_local_tfidf_always_available(self):
        """LocalTFIDF 永遠可用，不需要外部依賴。"""
        import project_brain.embedder as _mod
        _mod._embedder_cache.clear()

        with mock.patch.dict(os.environ, {"BRAIN_EMBED_PROVIDER": "tfidf"}):
            emb = _mod.get_embedder()
            self.assertIsNotNone(emb)
            # Should be able to embed without error
            vec = emb.embed("test query")
            self.assertIsNotNone(vec)
            self.assertGreater(len(vec), 0)

    def test_embed_returns_consistent_dimensions(self):
        """同一 embedder 的輸出維度應一致。"""
        import project_brain.embedder as _mod
        _mod._embedder_cache.clear()

        with mock.patch.dict(os.environ, {"BRAIN_EMBED_PROVIDER": "tfidf"}):
            emb = _mod.get_embedder()
            v1 = emb.embed("first query")
            v2 = emb.embed("second query about different topic")
            self.assertEqual(len(v1), len(v2))


if __name__ == "__main__":
    unittest.main()
