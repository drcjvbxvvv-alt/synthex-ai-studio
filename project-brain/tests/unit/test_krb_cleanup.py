"""
tests/unit/test_krb_cleanup.py

MEDIUM-04 — KnowledgeReviewBoard.cleanup_expired_staging() 驗收測試
(ARCHITECTURE_REVIEW.md §3 MEDIUM-04, §5.2 Phase 2 / §8.4 v0.34)

背景：review_board.py 原本沒有 staging 過期清理機制。
- rejected 節點永久保留於 staged_nodes 表
- 舊 pending 節點若無人審查，永遠累積
- brain.toml [review.staging_ttl_days] 已定義但 KRB 未讀取

修法：新增 cleanup_expired_staging(ttl_days) 方法：
- pending  + created_at < cutoff → skipped_stale
- rejected + created_at < cutoff → archived
- approved / needs_changes 不受影響
- ttl_days=None 時讀 brain.toml [review.staging_ttl_days]（預設 30）
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from project_brain.engines.review_board import KnowledgeReviewBoard
from project_brain.graph import KnowledgeGraph
from project_brain.core.brain_db import BrainDB


# ══════════════════════════════════════════════════════════════════
#  測試輔助
# ══════════════════════════════════════════════════════════════════

class _KRBFixture(unittest.TestCase):
    """每個測試獨立 tmp brain_dir + KnowledgeGraph + KRB.

    C-01: BrainDB created first; KG shares its connection.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self._tmp.name)
        self.bdb = BrainDB(self.brain_dir)
        self.graph = KnowledgeGraph(self.brain_dir, conn=self.bdb.conn)
        self.krb = KnowledgeReviewBoard(self.brain_dir, self.graph)

    def tearDown(self):
        try:
            self.krb.close()
            self.graph.close()
            self.bdb.close()
        except Exception:
            pass
        self._tmp.cleanup()

    def _age(self, staged_id: str, days: int) -> None:
        """直接 UPDATE created_at 把節點年齡設為 days 天前（測試輔助）。"""
        old_ts = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()
        conn = self.krb._conn_()
        conn.execute(
            "UPDATE staged_nodes SET created_at=? WHERE id=?",
            (old_ts, staged_id),
        )
        conn.commit()

    def _status(self, staged_id: str) -> str:
        row = self.krb._conn_().execute(
            "SELECT status FROM staged_nodes WHERE id=?", (staged_id,)
        ).fetchone()
        return row["status"] if row else ""


# ══════════════════════════════════════════════════════════════════
#  K-01 ~ K-04  基本清理行為
# ══════════════════════════════════════════════════════════════════

class TestCleanupBasic(_KRBFixture):

    def test_K01_empty_db_returns_zero(self):
        result = self.krb.cleanup_expired_staging(ttl_days=30)
        self.assertEqual(result["pending_skipped"],   0)
        self.assertEqual(result["rejected_archived"], 0)
        self.assertEqual(result["ttl_days"],          30)

    def test_K02_pending_old_marked_skipped_stale(self):
        sid = self.krb.submit("Old pending", "body", kind="Rule")
        self._age(sid, 100)
        result = self.krb.cleanup_expired_staging(ttl_days=30)
        self.assertEqual(result["pending_skipped"], 1)
        self.assertEqual(self._status(sid), "skipped_stale")

    def test_K03_rejected_old_marked_archived(self):
        sid = self.krb.submit("Old rejected", "body", kind="Rule")
        self.krb.reject(sid, reviewer="test")
        self._age(sid, 100)
        result = self.krb.cleanup_expired_staging(ttl_days=30)
        self.assertEqual(result["rejected_archived"], 1)
        self.assertEqual(self._status(sid), "archived")

    def test_K04_fresh_rows_untouched(self):
        s_pending  = self.krb.submit("Fresh pending", "body", kind="Rule")
        s_rejected = self.krb.submit("Fresh rejected", "body", kind="Rule")
        self.krb.reject(s_rejected, reviewer="test")
        # No aging — both are < 30 days old
        result = self.krb.cleanup_expired_staging(ttl_days=30)
        self.assertEqual(result["pending_skipped"],   0)
        self.assertEqual(result["rejected_archived"], 0)
        self.assertEqual(self._status(s_pending),  "pending")
        self.assertEqual(self._status(s_rejected), "rejected")


# ══════════════════════════════════════════════════════════════════
#  K-05 ~ K-08  其他狀態不受影響
# ══════════════════════════════════════════════════════════════════

class TestStatusIsolation(_KRBFixture):

    def test_K05_approved_old_untouched(self):
        """approved 節點即使超過 ttl 也不應被清理（已合進 L3，是事實記錄）"""
        sid = self.krb.submit("Old approved", "body for L3", kind="Rule")
        self.krb.approve(sid, reviewer="test")
        self._age(sid, 200)
        self.krb.cleanup_expired_staging(ttl_days=30)
        self.assertEqual(self._status(sid), "approved")

    def test_K06_needs_changes_old_untouched(self):
        sid = self.krb.submit("Old needs_changes", "body", kind="Rule")
        self.krb.request_changes(sid, reviewer="test", note="please add example")
        self._age(sid, 200)
        self.krb.cleanup_expired_staging(ttl_days=30)
        self.assertEqual(self._status(sid), "needs_changes")

    def test_K07_mixed_batch_correct_partition(self):
        """4 種狀態 × old/fresh 共 8 個節點，cleanup 只動 old pending + old rejected"""
        # old pending → skipped_stale
        s_op = self.krb.submit("op", "body", kind="Rule"); self._age(s_op, 100)
        # fresh pending → unchanged
        s_fp = self.krb.submit("fp", "body", kind="Rule")
        # old rejected → archived
        s_or = self.krb.submit("or", "body", kind="Rule"); self.krb.reject(s_or, reviewer="t"); self._age(s_or, 100)
        # fresh rejected → unchanged
        s_fr = self.krb.submit("fr", "body", kind="Rule"); self.krb.reject(s_fr, reviewer="t")
        # old approved → unchanged
        s_oa = self.krb.submit("oa", "body L3", kind="Rule"); self.krb.approve(s_oa, reviewer="t"); self._age(s_oa, 100)
        # fresh approved → unchanged
        s_fa = self.krb.submit("fa", "body L3", kind="Rule"); self.krb.approve(s_fa, reviewer="t")
        # old needs_changes → unchanged
        s_oc = self.krb.submit("oc", "body", kind="Rule"); self.krb.request_changes(s_oc, reviewer="t", note="x"); self._age(s_oc, 100)
        # fresh needs_changes → unchanged
        s_fc = self.krb.submit("fc", "body", kind="Rule"); self.krb.request_changes(s_fc, reviewer="t", note="x")

        result = self.krb.cleanup_expired_staging(ttl_days=30)
        self.assertEqual(result["pending_skipped"],   1)
        self.assertEqual(result["rejected_archived"], 1)

        self.assertEqual(self._status(s_op), "skipped_stale")
        self.assertEqual(self._status(s_fp), "pending")
        self.assertEqual(self._status(s_or), "archived")
        self.assertEqual(self._status(s_fr), "rejected")
        self.assertEqual(self._status(s_oa), "approved")
        self.assertEqual(self._status(s_fa), "approved")
        self.assertEqual(self._status(s_oc), "needs_changes")
        self.assertEqual(self._status(s_fc), "needs_changes")

    def test_K08_skipped_stale_not_re_processed(self):
        """已被 cleanup 的 skipped_stale 節點，再呼叫 cleanup 不應再被處理"""
        sid = self.krb.submit("Stale", "body", kind="Rule")
        self._age(sid, 100)
        first  = self.krb.cleanup_expired_staging(ttl_days=30)
        second = self.krb.cleanup_expired_staging(ttl_days=30)
        self.assertEqual(first["pending_skipped"],  1)
        self.assertEqual(second["pending_skipped"], 0)
        self.assertEqual(self._status(sid), "skipped_stale")


# ══════════════════════════════════════════════════════════════════
#  K-09 ~ K-12  ttl 邊界與設定
# ══════════════════════════════════════════════════════════════════

class TestTTLBoundary(_KRBFixture):

    def test_K09_exactly_at_ttl_not_cleaned(self):
        """
        cutoff 用 datetime.now() - ttl_days，比較是 created_at < cutoff (嚴格小於)。
        年齡剛好等於 ttl 的節點落在邊界，因為 _age 用幾乎相同的 datetime.now，
        實際 created_at 略晚於 cutoff → 不會被清。
        """
        sid = self.krb.submit("Boundary", "body", kind="Rule")
        # ttl=30, age=29 → 必定不清
        self._age(sid, 29)
        result = self.krb.cleanup_expired_staging(ttl_days=30)
        self.assertEqual(result["pending_skipped"], 0)
        self.assertEqual(self._status(sid), "pending")

    def test_K10_just_over_ttl_cleaned(self):
        sid = self.krb.submit("OverBoundary", "body", kind="Rule")
        self._age(sid, 31)
        result = self.krb.cleanup_expired_staging(ttl_days=30)
        self.assertEqual(result["pending_skipped"], 1)
        self.assertEqual(self._status(sid), "skipped_stale")

    def test_K11_ttl_min_clamped_to_1(self):
        """ttl_days <= 0 應被夾到 1（避免立即清空所有 staging）"""
        sid = self.krb.submit("Today", "body", kind="Rule")
        # ttl=0 應被夾到 1，今天的節點不會被清
        result = self.krb.cleanup_expired_staging(ttl_days=0)
        self.assertEqual(result["ttl_days"], 1)
        self.assertEqual(self._status(sid), "pending")

    def test_K12_default_ttl_from_brain_toml(self):
        """ttl_days=None 應從 brain.toml 讀取，預設 30"""
        sid = self.krb.submit("DefaultTTL", "body", kind="Rule")
        self._age(sid, 100)
        result = self.krb.cleanup_expired_staging()  # 不傳 ttl_days
        self.assertEqual(result["pending_skipped"], 1)
        # 預設 30
        self.assertEqual(result["ttl_days"], 30)

    def test_K13_brain_toml_override_ttl(self):
        """寫一個 brain.toml [review] staging_ttl_days=7，cleanup 應該用 7 天"""
        toml = self.brain_dir / "brain.toml"
        toml.write_text(
            "[review]\nstaging_ttl_days = 7\n",
            encoding="utf-8",
        )
        # 清掉模組級 cache 確保重新讀取
        try:
            from project_brain.brain_config import _CONFIG_CACHE  # type: ignore
            _CONFIG_CACHE.clear()
        except Exception:
            pass

        sid_old = self.krb.submit("8 days old", "body", kind="Rule")
        self._age(sid_old, 8)
        sid_new = self.krb.submit("3 days old", "body", kind="Rule")
        self._age(sid_new, 3)

        result = self.krb.cleanup_expired_staging()  # 讀 brain.toml
        self.assertEqual(result["ttl_days"], 7)
        self.assertEqual(self._status(sid_old), "skipped_stale")
        self.assertEqual(self._status(sid_new), "pending")


# ══════════════════════════════════════════════════════════════════
#  K-14 ~ K-15  返回值與計數正確性
# ══════════════════════════════════════════════════════════════════

class TestReturnValue(_KRBFixture):

    def test_K14_return_dict_has_expected_keys(self):
        result = self.krb.cleanup_expired_staging(ttl_days=30)
        for key in ("pending_skipped", "rejected_archived", "ttl_days"):
            self.assertIn(key, result)
        self.assertIsInstance(result["pending_skipped"],   int)
        self.assertIsInstance(result["rejected_archived"], int)
        self.assertIsInstance(result["ttl_days"],          int)

    def test_K15_counts_match_actual_changes(self):
        # 3 old pending + 5 old rejected
        for i in range(3):
            sid = self.krb.submit(f"op{i}", "body", kind="Rule")
            self._age(sid, 100)
        for i in range(5):
            sid = self.krb.submit(f"or{i}", "body", kind="Rule")
            self.krb.reject(sid, reviewer="test")
            self._age(sid, 100)
        result = self.krb.cleanup_expired_staging(ttl_days=30)
        self.assertEqual(result["pending_skipped"],   3)
        self.assertEqual(result["rejected_archived"], 5)


if __name__ == "__main__":
    unittest.main()
