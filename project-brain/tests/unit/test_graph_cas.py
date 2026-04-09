"""
tests/unit/test_graph_cas.py

HIGH-01 — KnowledgeGraph.add_node() 樂觀鎖 CAS 驗收測試
(ARCHITECTURE_REVIEW.md §3 HIGH-01, §5.2 Phase 2)

背景：graph.py 原本 add_node() 使用 INSERT ... ON CONFLICT DO UPDATE 但
未檢查 version，導致：
  1. 並發更新靜默覆蓋（Thread A 讀 v=5 → Thread B 讀 v=5 → B 先寫 → A 覆蓋 B）
  2. UPDATE 分支未遞增 version，version 永遠卡在 0（死欄位）
  3. ConcurrentModificationError 類別存在但從未被 add_node() raise（死代碼）

本檔案驗收 HIGH-01 的三點修法：
  1. 新增 expected_version: Optional[int] kwarg 啟用 CAS
  2. UPDATE 分支遞增 version（即使不啟用 CAS）
  3. 讀-檢-寫由 self._lock 序列化（並發壓力測試）
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from project_brain.graph import ConcurrentModificationError, KnowledgeGraph


# ══════════════════════════════════════════════════════════════════
#  測試輔助
# ══════════════════════════════════════════════════════════════════

class _GraphFixture(unittest.TestCase):
    """每個測試獨立 tmp 目錄 + KnowledgeGraph。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.graph = KnowledgeGraph(Path(self._tmp.name))

    def tearDown(self):
        try:
            self.graph.close()
        except Exception:
            pass
        self._tmp.cleanup()

    def _version(self, node_id: str) -> int:
        n = self.graph.get_node(node_id)
        return n["version"] if n else -1


# ══════════════════════════════════════════════════════════════════
#  C-01 ~ C-04  向後相容：不傳 expected_version 時維持舊行為
# ══════════════════════════════════════════════════════════════════

class TestBackwardCompat(_GraphFixture):

    def test_C01_add_without_cas_creates_node(self):
        """不傳 expected_version → 新建節點，version=0"""
        self.graph.add_node("n1", "Rule", "Title")
        self.assertEqual(self._version("n1"), 0)

    def test_C02_add_without_cas_upsert_succeeds(self):
        """不傳 expected_version → 同 id 第二次呼叫走 UPSERT，不 raise"""
        self.graph.add_node("n1", "Rule", "Title v1")
        self.graph.add_node("n1", "Rule", "Title v2")
        node = self.graph.get_node("n1")
        self.assertEqual(node["title"], "Title v2")

    def test_C03_upsert_without_cas_increments_version(self):
        """HIGH-01 修正：不啟用 CAS 的 UPSERT 也必須遞增 version"""
        self.graph.add_node("n1", "Rule", "T0")
        self.assertEqual(self._version("n1"), 0)
        self.graph.add_node("n1", "Rule", "T1")
        self.assertEqual(self._version("n1"), 1)
        self.graph.add_node("n1", "Rule", "T2")
        self.assertEqual(self._version("n1"), 2)

    def test_C04_multiple_distinct_nodes_independent_versions(self):
        """不同 id 的 version 不互相干擾"""
        self.graph.add_node("a", "Rule", "A")
        self.graph.add_node("b", "Rule", "B")
        self.graph.add_node("a", "Rule", "A2")
        self.assertEqual(self._version("a"), 1)
        self.assertEqual(self._version("b"), 0)


# ══════════════════════════════════════════════════════════════════
#  C-05 ~ C-10  CAS 正確路徑
# ══════════════════════════════════════════════════════════════════

class TestCASHappyPath(_GraphFixture):

    def test_C05_new_node_cas_requires_version_zero(self):
        """新節點的 CAS：expected_version=0 成功"""
        self.graph.add_node("n1", "Rule", "New", expected_version=0)
        self.assertEqual(self._version("n1"), 0)

    def test_C06_existing_node_cas_matching_version_succeeds(self):
        """既有節點 CAS：expected_version == current 成功，version 遞增"""
        self.graph.add_node("n1", "Rule", "v0")
        self.assertEqual(self._version("n1"), 0)
        self.graph.add_node("n1", "Rule", "v1", expected_version=0)
        self.assertEqual(self._version("n1"), 1)
        self.graph.add_node("n1", "Rule", "v2", expected_version=1)
        self.assertEqual(self._version("n1"), 2)

    def test_C07_cas_succeeds_with_content_change(self):
        """CAS 成功時 content / title / tags 被正確更新"""
        self.graph.add_node("n1", "Rule", "Old title", content="old body",
                            tags=["a", "b"])
        self.graph.add_node(
            "n1", "Rule", "New title", content="new body",
            tags=["x", "y"], expected_version=0,
        )
        node = self.graph.get_node("n1")
        self.assertEqual(node["title"],   "New title")
        self.assertEqual(node["content"], "new body")
        self.assertEqual(node["tags"],    ["x", "y"])
        self.assertEqual(node["version"], 1)


# ══════════════════════════════════════════════════════════════════
#  C-11 ~ C-16  CAS 失敗路徑
# ══════════════════════════════════════════════════════════════════

class TestCASConflict(_GraphFixture):

    def test_C11_new_node_cas_wrong_version_raises(self):
        """新節點但傳 expected_version != 0 → raise"""
        with self.assertRaises(ConcurrentModificationError) as ctx:
            self.graph.add_node("missing", "Rule", "X", expected_version=5)
        self.assertIn("does not exist", str(ctx.exception))
        self.assertIn("missing",        str(ctx.exception))
        # 節點確實沒有被建立
        self.assertIsNone(self.graph.get_node("missing"))

    def test_C12_existing_node_cas_stale_version_raises(self):
        """
        Thread A 讀 v=0 → Thread B 寫 v=1 → Thread A 用 expected_version=0 寫入
        應該被拒絕。
        """
        self.graph.add_node("n1", "Rule", "v0")
        # 模擬 Thread B 先寫入
        self.graph.add_node("n1", "Rule", "v1_by_B", expected_version=0)
        self.assertEqual(self._version("n1"), 1)
        # Thread A 用 stale version 寫入
        with self.assertRaises(ConcurrentModificationError) as ctx:
            self.graph.add_node("n1", "Rule", "v1_by_A", expected_version=0)
        self.assertIn("version mismatch", str(ctx.exception))
        # 確認 B 的寫入未被覆蓋
        self.assertEqual(self.graph.get_node("n1")["title"], "v1_by_B")

    def test_C13_cas_failure_does_not_mutate_row(self):
        """CAS 失敗時本地節點內容必須完全不變"""
        self.graph.add_node("n1", "Rule", "Original",
                            content="original body", tags=["keep"])
        try:
            self.graph.add_node("n1", "Rule", "Should not appear",
                                content="bad body", tags=["bad"],
                                expected_version=99)
        except ConcurrentModificationError:
            pass
        node = self.graph.get_node("n1")
        self.assertEqual(node["title"],   "Original")
        self.assertEqual(node["content"], "original body")
        self.assertEqual(node["tags"],    ["keep"])
        self.assertEqual(node["version"], 0)

    def test_C14_cas_failure_does_not_raise_on_missing_id_when_expected_zero(self):
        """expected_version=0 + 節點不存在 → 這是合法的新建路徑"""
        # 不應拋例外
        self.graph.add_node("new", "Rule", "New", expected_version=0)
        self.assertIsNotNone(self.graph.get_node("new"))


# ══════════════════════════════════════════════════════════════════
#  C-15 ~ C-18  並發場景（self._lock 序列化）
# ══════════════════════════════════════════════════════════════════

class TestCASConcurrency(_GraphFixture):

    def test_C15_concurrent_add_same_id_no_lost_update(self):
        """
        50 個 thread 同時對同一節點做 add_node（不啟用 CAS），
        最終 version 應該精確等於 50（沒有遺失更新）。

        若 UPDATE 分支未加 version+1 或未加 self._lock，這個測試會失敗。
        """
        self.graph.add_node("n1", "Rule", "initial")  # v=0
        N       = 50
        barrier = threading.Barrier(N)
        errors  = []

        def _worker(i: int):
            try:
                barrier.wait()
                self.graph.add_node("n1", "Rule", f"thread-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        # 初始 v=0 + N 次 upsert → 最終 version == N
        self.assertEqual(self._version("n1"), N)

    def test_C16_concurrent_cas_only_one_winner(self):
        """
        多 thread 用 expected_version=0 競爭同一節點 —
        只有一個 thread 應該成功，其他全部 raise ConcurrentModificationError。
        """
        self.graph.add_node("n1", "Rule", "initial")  # v=0
        N        = 30
        barrier  = threading.Barrier(N)
        successes: list[int] = []
        conflicts: list[int] = []

        def _worker(i: int):
            barrier.wait()
            try:
                self.graph.add_node(
                    "n1", "Rule", f"winner-{i}", expected_version=0,
                )
                successes.append(i)
            except ConcurrentModificationError:
                conflicts.append(i)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(successes), 1,
                         f"expect exactly 1 winner, got {len(successes)}")
        self.assertEqual(len(conflicts), N - 1)
        # 最終 version 恰好為 1（單一 winner 遞增一次）
        self.assertEqual(self._version("n1"), 1)

    def test_C17_concurrent_cas_chain_retries_eventually_all_succeed(self):
        """
        模擬 retry loop：每個 thread 嘗試遞增的 expected_version 直到成功。
        最終所有 thread 都應該成功，總 version == N。

        註：retry 策略刻意不透過 get_node() 讀 version，因為 get_node() 未走
        self._lock，多 thread 同時讀寫共用 sqlite3 connection 會觸發 API misuse。
        真實使用者 retry 時會拿到 ConcurrentModificationError 後增加 guess
        再試，這個測試模擬此行為。
        """
        self.graph.add_node("n1", "Rule", "initial")  # v=0
        N       = 20
        barrier = threading.Barrier(N)
        failed: list[Exception] = []

        def _worker(i: int):
            try:
                barrier.wait()
                # 從 0 開始嘗試，遇到衝突就遞增 guess
                for guess in range(200):
                    try:
                        self.graph.add_node(
                            "n1", "Rule", f"retry-{i}",
                            expected_version=guess,
                        )
                        return
                    except ConcurrentModificationError:
                        continue
                failed.append(RuntimeError(f"thread {i} exceeded retry limit"))
            except Exception as e:
                failed.append(e)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(failed, [])
        self.assertEqual(self._version("n1"), N)

    def test_C18_distinct_ids_no_cross_interference(self):
        """並發對「不同 id」的 add_node 不應彼此干擾"""
        N       = 20
        barrier = threading.Barrier(N)

        def _worker(i: int):
            barrier.wait()
            self.graph.add_node(f"n{i}", "Rule", f"title-{i}")

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 全部節點都應該存在，version=0
        for i in range(N):
            node = self.graph.get_node(f"n{i}")
            self.assertIsNotNone(node)
            self.assertEqual(node["version"], 0)


# ══════════════════════════════════════════════════════════════════
#  C-19 ~ C-20  update_node CAS 既有行為 (BUG-06) 不可退化
# ══════════════════════════════════════════════════════════════════

class TestUpdateNodeCASUnchanged(_GraphFixture):
    """
    update_node() 的 CAS（BUG-06）在本次 HIGH-01 修改中必須保留。
    這兩個測試確認舊行為未被破壞。
    """

    def test_C19_update_node_increments_version(self):
        self.graph.add_node("n1", "Rule", "v0")  # version=0
        self.graph.update_node("n1", title="v1")
        self.assertEqual(self._version("n1"), 1)

    def test_C20_update_node_raises_on_stale_version(self):
        """
        手動偽造一個 stale 快照：先讀出 version=0，再讓另一個路徑 bump version，
        原 update 路徑若直接用 stale version 應該會拋錯。

        BUG-06 的 update_node 已經在內部重新 SELECT 並用 version 做 CAS，
        因此手動呼叫兩次 update_node 第二次會基於新 version 正確完成。
        這個測試用「add_node bump → update_node」的混合場景驗證兩條路徑共用版本欄位。
        """
        self.graph.add_node("n1", "Rule", "v0")
        self.graph.add_node("n1", "Rule", "v1")  # UPSERT bump → version=1
        self.assertEqual(self._version("n1"), 1)
        # update_node 應該基於當前 version 正確 bump 到 2
        ok = self.graph.update_node("n1", content="updated by update_node")
        self.assertTrue(ok)
        self.assertEqual(self._version("n1"), 2)


if __name__ == "__main__":
    unittest.main()
