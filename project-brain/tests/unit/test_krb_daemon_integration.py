"""
tests/unit/test_krb_daemon_integration.py

B-01 — _run_maintenance_cycle() 整合測試
(ROADMAP.md §B-01 KRB Cleanup Daemon Integration)

驗收標準：
- _run_maintenance_cycle() 被呼叫時，cleanup_expired_staging() 一定會被呼叫
- decay 失敗不阻止 cleanup 執行
- cleanup 失敗不阻止 decay 執行，也不對外 raise
- 成功 cleanup 產生包含 pending_skipped/rejected_archived/ttl_days 的結構化 log
- 回傳 dict 在所有情境下有正確鍵值

注意：_run_maintenance_cycle 內用 "from project_brain.decay_engine import DecayEngine as _DE"
（函式內 local import），因此 patch target 是 "project_brain.decay_engine.DecayEngine"，
而非 "project_brain.interfaces.mcp_server.DecayEngine"。
"""
from __future__ import annotations

import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from project_brain.interfaces.mcp_server import _run_maintenance_cycle

# Patch target — DecayEngine is imported inside the function body, so we
# must patch the class on its home module, not the importer module.
_DECAY_ENGINE_PATCH = "project_brain.decay_engine.DecayEngine"


# ══════════════════════════════════════════════════════════════════
#  測試輔助
# ══════════════════════════════════════════════════════════════════

def _make_brain(
    *,
    cleanup_raises: Exception | None = None,
    cleanup_result: dict | None = None,
) -> SimpleNamespace:
    """回傳一個 mock brain，可設定 cleanup 的行為。"""
    brain = SimpleNamespace(
        graph=MagicMock(),
        workdir=Path("/tmp/test-brain"),
        db=MagicMock(),
        review_board=MagicMock(),
    )

    if cleanup_result is None:
        cleanup_result = {"pending_skipped": 0, "rejected_archived": 0, "ttl_days": 30}

    if cleanup_raises:
        brain.review_board.cleanup_expired_staging.side_effect = cleanup_raises
    else:
        brain.review_board.cleanup_expired_staging.return_value = cleanup_result

    return brain


# ══════════════════════════════════════════════════════════════════
#  D-01 ~ D-04  回傳 dict 結構
# ══════════════════════════════════════════════════════════════════

class TestReturnDict(unittest.TestCase):

    def test_D01_keys_always_present(self):
        """回傳 dict 必定有四個預期鍵，不管成功或失敗。"""
        brain = _make_brain()
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.return_value = None
            result = _run_maintenance_cycle(brain)
        for key in ("decay_ok", "decay_error", "cleanup", "cleanup_error"):
            self.assertIn(key, result)

    def test_D02_success_path_values(self):
        """兩步都成功：decay_ok=True, decay_error=None, cleanup=dict, cleanup_error=None"""
        cleanup_result = {"pending_skipped": 2, "rejected_archived": 1, "ttl_days": 30}
        brain = _make_brain(cleanup_result=cleanup_result)
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.return_value = None
            result = _run_maintenance_cycle(brain)
        self.assertTrue(result["decay_ok"])
        self.assertIsNone(result["decay_error"])
        self.assertEqual(result["cleanup"], cleanup_result)
        self.assertIsNone(result["cleanup_error"])

    def test_D03_decay_failure_values(self):
        """decay 失敗：decay_ok=False, decay_error 為字串"""
        brain = _make_brain()
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.side_effect = RuntimeError("decay boom")
            result = _run_maintenance_cycle(brain)
        self.assertFalse(result["decay_ok"])
        self.assertIsInstance(result["decay_error"], str)
        self.assertIn("decay boom", result["decay_error"])

    def test_D04_cleanup_failure_values(self):
        """cleanup 失敗：cleanup=None, cleanup_error 為字串"""
        brain = _make_brain(cleanup_raises=ValueError("cleanup boom"))
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.return_value = None
            result = _run_maintenance_cycle(brain)
        self.assertIsNone(result["cleanup"])
        self.assertIsInstance(result["cleanup_error"], str)
        self.assertIn("cleanup boom", result["cleanup_error"])


# ══════════════════════════════════════════════════════════════════
#  I-01 ~ I-04  隔離性：一步失敗不影響另一步
# ══════════════════════════════════════════════════════════════════

class TestStepIsolation(unittest.TestCase):

    def test_I01_decay_failure_does_not_prevent_cleanup(self):
        """decay 拋例外，cleanup 仍然被呼叫"""
        brain = _make_brain()
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.side_effect = RuntimeError("decay error")
            _run_maintenance_cycle(brain)
        brain.review_board.cleanup_expired_staging.assert_called_once()

    def test_I02_cleanup_failure_does_not_prevent_decay(self):
        """cleanup 拋例外，decay 仍然被呼叫且 decay_ok=True"""
        brain = _make_brain(cleanup_raises=OSError("cleanup error"))
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.return_value = None
            result = _run_maintenance_cycle(brain)
        self.assertTrue(result["decay_ok"])

    def test_I03_both_fail_no_exception_raised(self):
        """decay 和 cleanup 都失敗，_run_maintenance_cycle 不對外 raise"""
        brain = _make_brain(cleanup_raises=RuntimeError("cleanup boom"))
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.side_effect = RuntimeError("decay boom")
            try:
                _run_maintenance_cycle(brain)
            except Exception as exc:  # pragma: no cover
                self.fail(f"_run_maintenance_cycle should not raise, got: {exc}")

    def test_I04_cleanup_called_exactly_once_per_cycle(self):
        """每次呼叫 _run_maintenance_cycle，cleanup_expired_staging 只呼叫一次"""
        brain = _make_brain()
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.return_value = None
            _run_maintenance_cycle(brain)
            _run_maintenance_cycle(brain)
        self.assertEqual(
            brain.review_board.cleanup_expired_staging.call_count, 2
        )


# ══════════════════════════════════════════════════════════════════
#  L-01 ~ L-04  Logging 驗證
# ══════════════════════════════════════════════════════════════════

class TestLogging(unittest.TestCase):

    def test_L01_cleanup_success_logs_info_with_counts(self):
        """cleanup 成功時以 INFO level 記錄 pending_skipped/rejected_archived/ttl_days"""
        cleanup_result = {"pending_skipped": 3, "rejected_archived": 2, "ttl_days": 7}
        brain = _make_brain(cleanup_result=cleanup_result)
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.return_value = None
            with self.assertLogs("project_brain.interfaces.mcp_server", level="INFO") as cm:
                _run_maintenance_cycle(brain)

        b01_logs = [line for line in cm.output if "B-01" in line]
        self.assertTrue(b01_logs, "Expected at least one B-01 log line")
        combined = " ".join(b01_logs)
        self.assertIn("3", combined)   # pending_skipped
        self.assertIn("2", combined)   # rejected_archived
        self.assertIn("7", combined)   # ttl_days

    def test_L02_cleanup_failure_logs_warning(self):
        """cleanup 失敗時以 WARNING level 記錄"""
        brain = _make_brain(cleanup_raises=RuntimeError("disk full"))
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.return_value = None
            with self.assertLogs("project_brain.interfaces.mcp_server", level="WARNING") as cm:
                _run_maintenance_cycle(brain)

        warning_logs = [line for line in cm.output if "WARNING" in line and "B-01" in line]
        self.assertTrue(warning_logs, "Expected WARNING log for B-01 cleanup failure")
        self.assertIn("disk full", " ".join(warning_logs))

    def test_L03_decay_failure_logs_debug_not_error(self):
        """decay 失敗時記 DEBUG（非 ERROR），符合 FEAT-01 設計：不中斷 MCP"""
        brain = _make_brain()
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.side_effect = RuntimeError("decay fail")
            with self.assertLogs("project_brain.interfaces.mcp_server", level="DEBUG") as cm:
                _run_maintenance_cycle(brain)

        error_logs = [l for l in cm.output if "ERROR" in l and "FEAT-01" in l]
        self.assertEqual(error_logs, [], "decay failure should NOT be logged at ERROR level")

    def test_L04_decay_success_logs_info(self):
        """decay 成功時記 FEAT-01 INFO"""
        brain = _make_brain()
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.return_value = None
            with self.assertLogs("project_brain.interfaces.mcp_server", level="INFO") as cm:
                _run_maintenance_cycle(brain)

        feat01_info = [l for l in cm.output if "FEAT-01" in l and "INFO" in l]
        self.assertTrue(feat01_info, "Expected INFO log for FEAT-01 decay completed")


# ══════════════════════════════════════════════════════════════════
#  C-01 ~ C-02  Cleanup 呼叫語意
# ══════════════════════════════════════════════════════════════════

class TestCleanupCallSemantics(unittest.TestCase):

    def test_C01_cleanup_called_without_ttl_arg(self):
        """cleanup_expired_staging() 應不傳 ttl_days（讓 KRB 從 brain.toml 讀取）"""
        brain = _make_brain()
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.return_value = None
            _run_maintenance_cycle(brain)

        call_args = brain.review_board.cleanup_expired_staging.call_args
        self.assertEqual(call_args, call())

    def test_C02_cleanup_result_stored_in_return_dict(self):
        """cleanup 的回傳值必須原封不動存在 result['cleanup']"""
        custom_result = {"pending_skipped": 99, "rejected_archived": 42, "ttl_days": 14}
        brain = _make_brain(cleanup_result=custom_result)
        with patch(_DECAY_ENGINE_PATCH) as de:
            de.return_value.run.return_value = None
            result = _run_maintenance_cycle(brain)
        self.assertEqual(result["cleanup"], custom_result)


# ══════════════════════════════════════════════════════════════════
#  T-01 ~ T-02  執行緒安全
# ══════════════════════════════════════════════════════════════════

class TestThreadSafety(unittest.TestCase):

    def test_T01_concurrent_calls_all_complete(self):
        """20 個執行緒同時呼叫 _run_maintenance_cycle，沒有 exception 逃出"""
        errors: list[Exception] = []
        results: list[dict] = []
        lock = threading.Lock()

        def _worker():
            brain = _make_brain()
            with patch(_DECAY_ENGINE_PATCH) as de:
                de.return_value.run.return_value = None
                try:
                    r = _run_maintenance_cycle(brain)
                    with lock:
                        results.append(r)
                except Exception as exc:
                    with lock:
                        errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(errors, [], f"Unexpected errors: {errors}")
        self.assertEqual(len(results), 20)

    def test_T02_concurrent_calls_all_return_complete_dict(self):
        """並行呼叫回傳的每個 dict 都有四個必要鍵"""
        results: list[dict] = []
        lock = threading.Lock()

        def _worker():
            brain = _make_brain()
            with patch(_DECAY_ENGINE_PATCH) as de:
                de.return_value.run.return_value = None
                r = _run_maintenance_cycle(brain)
                with lock:
                    results.append(r)

        threads = [threading.Thread(target=_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        for r in results:
            for key in ("decay_ok", "decay_error", "cleanup", "cleanup_error"):
                self.assertIn(key, r)


if __name__ == "__main__":
    unittest.main()
