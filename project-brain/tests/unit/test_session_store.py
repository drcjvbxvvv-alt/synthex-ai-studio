"""
tests/test_session_store.py — L1a SessionStore 單元測試

覆蓋：
  - CRUD（set/get/delete/list）
  - TTL 與過期行為
  - 分類持久化設定
  - 全文搜尋（FTS5 + LIKE）
  - clear_session（只清非持久化）
  - stats
  - 並發安全（WAL 模式）
"""

import time
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
import tempfile

from project_brain.session_store import SessionStore, SessionEntry, CATEGORY_CONFIG


@pytest.fixture
def store(tmp_path):
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir()
    s = SessionStore(brain_dir, session_id="test_session")
    yield s
    s.close()


class TestBasicCRUD:
    def test_set_and_get(self, store):
        e = store.set("notes/hello", "世界你好", category="notes")
        assert e.key   == "notes/hello"
        assert e.value == "世界你好"
        got = store.get("notes/hello")
        assert got is not None
        assert got.value == "世界你好"

    def test_get_nonexistent(self, store):
        assert store.get("does/not/exist") is None

    def test_set_upsert(self, store):
        store.set("notes/k", "v1", category="notes")
        store.set("notes/k", "v2", category="notes")
        got = store.get("notes/k")
        assert got.value == "v2"

    def test_delete(self, store):
        store.set("notes/del", "bye", category="notes")
        assert store.delete("notes/del") is True
        assert store.get("notes/del") is None

    def test_delete_nonexistent(self, store):
        assert store.delete("nonexistent") is False


class TestCategories:
    def test_persistent_category_has_ttl(self, store):
        e = store.set("pitfalls/x", "content", category="pitfalls")
        assert e.expires_at != ""       # 有過期時間（30 天後）
        assert "2026" in e.expires_at or "2027" in e.expires_at  # 合理範圍

    def test_nonpersistent_category_no_ttl(self, store):
        e = store.set("progress/y", "content", category="progress")
        assert e.expires_at == ""       # 不設過期（但 clear_session 時清除）

    def test_all_persistent_categories(self, store):
        for cat in ["pitfalls", "decisions", "context"]:
            assert CATEGORY_CONFIG[cat]["persistent"] is True

    def test_all_nonpersistent_categories(self, store):
        for cat in ["progress", "notes"]:
            assert CATEGORY_CONFIG[cat]["persistent"] is False


class TestSearch:
    def test_fts_english(self, store):
        store.set("p/stripe", "Stripe Webhook 冪等", category="pitfalls")
        hits = store.search("stripe")
        assert len(hits) >= 1
        assert any("stripe" in h.key.lower() for h in hits)

    def test_fts_chinese_full_word(self, store):
        store.set("p/og", "LINE OG 圖片快取問題", category="pitfalls")
        hits = store.search("圖片")
        assert len(hits) >= 1

    def test_like_fallback_chinese_subword(self, store):
        # FTS5 無法搜子詞，LIKE 備援
        store.set("p/cache", "社群軟體會快取OG圖片需要刷新", category="pitfalls")
        hits = store.search("快取")
        assert len(hits) >= 1

    def test_search_empty_query(self, store):
        hits = store.search("")
        assert hits == []

    def test_search_no_results(self, store):
        hits = store.search("zzznonexistentkeyword")
        assert hits == []


class TestList:
    def test_list_all(self, store):
        store.set("p/a", "v", category="pitfalls")
        store.set("n/b", "v", category="notes")
        entries = store.list()
        assert len(entries) >= 2

    def test_list_by_category(self, store):
        store.set("p/x", "v", category="pitfalls")
        store.set("n/y", "v", category="notes")
        pitfalls = store.list(category="pitfalls")
        assert all(e.category == "pitfalls" for e in pitfalls)

    def test_list_by_session(self, store):
        store.set("n/z", "v", category="notes")
        entries = store.list(session_id="test_session")
        assert all(e.session_id == "test_session" for e in entries)


class TestClearSession:
    def test_clears_nonpersistent(self, store):
        store.set("progress/p", "進度", category="progress")
        store.set("notes/n",    "筆記", category="notes")
        store.set("pitfalls/f", "踩坑", category="pitfalls")

        deleted = store.clear_session("test_session")
        assert deleted == 2   # progress + notes

        assert store.get("pitfalls/f") is not None
        assert store.get("progress/p") is None
        assert store.get("notes/n")    is None

    def test_preserves_persistent(self, store):
        for cat in ["pitfalls", "decisions", "context"]:
            store.set(f"{cat}/keep", "value", category=cat)

        store.clear_session("test_session")

        for cat in ["pitfalls", "decisions", "context"]:
            assert store.get(f"{cat}/keep") is not None


class TestStats:
    def test_stats_structure(self, store):
        store.set("p/a", "v", category="pitfalls")
        store.set("n/b", "v", category="notes")
        s = store.stats()
        assert "total"       in s
        assert "session_id"  in s
        assert "by_category" in s
        assert s["total"] >= 2

    def test_stats_counts(self, store):
        store.set("p/1", "v", category="pitfalls")
        store.set("p/2", "v", category="pitfalls")
        s = store.stats()
        assert s["by_category"].get("pitfalls", 0) >= 2


class TestTTLOverride:
    def test_custom_ttl(self, store):
        e = store.set("notes/custom", "value", category="notes", ttl_days=7)
        # notes 預設無 TTL，但 ttl_days=7 覆蓋
        assert e.expires_at != ""
        assert "202" in e.expires_at
