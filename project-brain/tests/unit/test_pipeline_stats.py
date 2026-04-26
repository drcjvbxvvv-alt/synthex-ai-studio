"""
tests/unit/test_pipeline_stats.py

B-04 — Pipeline Metrics Dashboard 測試
(ROADMAP.md §B-04 Pipeline Metrics Dashboard)

驗收標準：
- 空 DB 回傳全 0 不 crash
- status/kind/action/model 聚合正確
- days filter 只統計時間窗口內的資料
- Prometheus text format 可解析
- JSON 輸出包含所有必要欄位
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from project_brain.core.brain_db import BrainDB
from project_brain.interfaces.cli_admin import _format_prometheus


# ══════════════════════════════════════════════════════════════════
#  測試輔助
# ══════════════════════════════════════════════════════════════════

class _StatsFixture(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self._tmp.name)
        self.db = BrainDB(self.brain_dir)

    def tearDown(self):
        try:
            self.db.close()
        except Exception:
            pass
        self._tmp.cleanup()

    def _add_signal(self, *, kind: str = "git_commit", status: str = "done",
                    days_ago: int = 0, sig_id: str | None = None) -> str:
        """Insert a signal_queue row."""
        import uuid
        sid = sig_id or str(uuid.uuid4())[:8]
        ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        self.db.conn.execute(
            "INSERT INTO signal_queue (id, kind, workdir, timestamp, summary, "
            "raw_content, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, kind, "/tmp", ts, f"test-{sid}", "{}", status, ts)
        )
        self.db.conn.commit()
        return sid

    def _add_metric(self, *, signal_id: str, node_id: str | None = None,
                    action: str = "added", model: str = "claude-haiku",
                    was_useful: int | None = None, days_ago: int = 0) -> None:
        """Insert a pipeline_metrics row."""
        import uuid
        nid = node_id or f"node-{uuid.uuid4().hex[:8]}"
        ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        self.db.conn.execute(
            "INSERT INTO pipeline_metrics (node_id, signal_id, action, llm_model, "
            "created_at, was_useful) VALUES (?, ?, ?, ?, ?, ?)",
            (nid, signal_id, action, model, ts, was_useful)
        )
        self.db.conn.commit()


# ══════════════════════════════════════════════════════════════════
#  Z-01 ~ Z-03  空 DB / 基本結構
# ══════════════════════════════════════════════════════════════════

class TestEmptyDB(_StatsFixture):

    def test_Z01_empty_db_returns_zeros(self):
        """空 DB 全部計數為 0"""
        stats = self.db.get_pipeline_stats(days=7)
        self.assertEqual(stats["signals"]["total"], 0)
        self.assertEqual(stats["pipeline"]["processed"], 0)
        self.assertEqual(stats["queue_depth"], 0)

    def test_Z02_return_has_all_required_keys(self):
        """回傳 dict 有所有必要鍵"""
        stats = self.db.get_pipeline_stats()
        self.assertIn("days", stats)
        self.assertIn("signals", stats)
        self.assertIn("pipeline", stats)
        self.assertIn("queue_depth", stats)
        self.assertIn("by_status", stats["signals"])
        self.assertIn("by_kind", stats["signals"])
        self.assertIn("by_action", stats["pipeline"])
        self.assertIn("by_model", stats["pipeline"])
        self.assertIn("feedback", stats["pipeline"])

    def test_Z03_json_serializable(self):
        """回傳值可 JSON 序列化"""
        stats = self.db.get_pipeline_stats()
        try:
            json.dumps(stats)
        except (TypeError, ValueError) as e:
            self.fail(f"Stats not JSON serializable: {e}")


# ══════════════════════════════════════════════════════════════════
#  A-01 ~ A-05  聚合正確性
# ══════════════════════════════════════════════════════════════════

class TestAggregation(_StatsFixture):

    def test_A01_total_signal_count(self):
        """total 計數正確"""
        self._add_signal(status="done", sig_id="s1")
        self._add_signal(status="failed", sig_id="s2")
        self._add_signal(status="pending", sig_id="s3")
        stats = self.db.get_pipeline_stats(days=7)
        self.assertEqual(stats["signals"]["total"], 3)

    def test_A02_by_status_breakdown(self):
        """by_status 分組正確"""
        self._add_signal(status="done", sig_id="s1")
        self._add_signal(status="done", sig_id="s2")
        self._add_signal(status="failed", sig_id="s3")
        stats = self.db.get_pipeline_stats(days=7)
        self.assertEqual(stats["signals"]["by_status"]["done"], 2)
        self.assertEqual(stats["signals"]["by_status"]["failed"], 1)

    def test_A03_by_kind_breakdown(self):
        """by_kind 分組正確"""
        self._add_signal(kind="git_commit", sig_id="s1")
        self._add_signal(kind="git_commit", sig_id="s2")
        self._add_signal(kind="mcp_tool_call", sig_id="s3")
        stats = self.db.get_pipeline_stats(days=7)
        self.assertEqual(stats["signals"]["by_kind"]["git_commit"], 2)
        self.assertEqual(stats["signals"]["by_kind"]["mcp_tool_call"], 1)

    def test_A04_pipeline_by_action(self):
        """pipeline by_action 分組正確"""
        s1 = self._add_signal(sig_id="s1")
        s2 = self._add_signal(sig_id="s2")
        s3 = self._add_signal(sig_id="s3")
        self._add_metric(signal_id=s1, action="added")
        self._add_metric(signal_id=s2, action="added")
        self._add_metric(signal_id=s3, action="skipped")
        stats = self.db.get_pipeline_stats(days=7)
        self.assertEqual(stats["pipeline"]["processed"], 3)
        self.assertEqual(stats["pipeline"]["by_action"]["added"], 2)
        self.assertEqual(stats["pipeline"]["by_action"]["skipped"], 1)

    def test_A05_pipeline_by_model(self):
        """pipeline by_model 分組正確"""
        s1 = self._add_signal(sig_id="s1")
        s2 = self._add_signal(sig_id="s2")
        self._add_metric(signal_id=s1, model="claude-haiku")
        self._add_metric(signal_id=s2, model="gemma4:27b")
        stats = self.db.get_pipeline_stats(days=7)
        self.assertEqual(stats["pipeline"]["by_model"]["claude-haiku"], 1)
        self.assertEqual(stats["pipeline"]["by_model"]["gemma4:27b"], 1)


# ══════════════════════════════════════════════════════════════════
#  F-01 ~ F-03  Feedback 統計
# ══════════════════════════════════════════════════════════════════

class TestFeedback(_StatsFixture):

    def test_F01_feedback_useful(self):
        s1 = self._add_signal(sig_id="s1")
        self._add_metric(signal_id=s1, was_useful=1)
        stats = self.db.get_pipeline_stats(days=7)
        self.assertEqual(stats["pipeline"]["feedback"]["useful"], 1)

    def test_F02_feedback_not_useful(self):
        s1 = self._add_signal(sig_id="s1")
        self._add_metric(signal_id=s1, was_useful=0)
        stats = self.db.get_pipeline_stats(days=7)
        self.assertEqual(stats["pipeline"]["feedback"]["not_useful"], 1)

    def test_F03_feedback_none(self):
        s1 = self._add_signal(sig_id="s1")
        self._add_metric(signal_id=s1, was_useful=None)
        stats = self.db.get_pipeline_stats(days=7)
        self.assertEqual(stats["pipeline"]["feedback"]["no_feedback"], 1)


# ══════════════════════════════════════════════════════════════════
#  D-01 ~ D-03  Days filter + queue depth
# ══════════════════════════════════════════════════════════════════

class TestDaysFilter(_StatsFixture):

    def test_D01_only_counts_within_window(self):
        """days=3 只統計最近 3 天的信號"""
        self._add_signal(sig_id="recent", days_ago=1)
        self._add_signal(sig_id="old", days_ago=10)
        stats = self.db.get_pipeline_stats(days=3)
        self.assertEqual(stats["signals"]["total"], 1)
        self.assertEqual(stats["days"], 3)

    def test_D02_days_clamped_to_1(self):
        """days <= 0 被夾到 1"""
        stats = self.db.get_pipeline_stats(days=0)
        self.assertEqual(stats["days"], 1)

    def test_D03_queue_depth_ignores_window(self):
        """queue_depth 是當前全域 pending 數，不受 days 限制"""
        self._add_signal(sig_id="old_pending", status="pending", days_ago=30)
        self._add_signal(sig_id="new_pending", status="pending", days_ago=0)
        stats = self.db.get_pipeline_stats(days=1)
        # queue_depth counts ALL pending, not just within window
        self.assertEqual(stats["queue_depth"], 2)


# ══════════════════════════════════════════════════════════════════
#  P-01 ~ P-04  Prometheus 格式
# ══════════════════════════════════════════════════════════════════

class TestPrometheus(_StatsFixture):

    def test_P01_prometheus_format_not_empty(self):
        """有資料時 Prometheus 輸出非空"""
        self._add_signal(status="done", sig_id="s1")
        stats = self.db.get_pipeline_stats(days=7)
        out = _format_prometheus(stats)
        self.assertTrue(len(out) > 0)

    def test_P02_prometheus_has_help_and_type(self):
        """Prometheus 輸出每個 metric 有 HELP 和 TYPE 行"""
        self._add_signal(status="done", sig_id="s1")
        stats = self.db.get_pipeline_stats(days=7)
        out = _format_prometheus(stats)
        self.assertIn("# HELP", out)
        self.assertIn("# TYPE", out)

    def test_P03_prometheus_gauge_for_queue_depth(self):
        """queue_depth 用 gauge 類型"""
        self._add_signal(status="pending", sig_id="s1")
        stats = self.db.get_pipeline_stats(days=7)
        out = _format_prometheus(stats)
        self.assertIn("# TYPE brain_signal_queue_depth gauge", out)
        self.assertIn("brain_signal_queue_depth 1", out)

    def test_P04_prometheus_counter_labels(self):
        """counter metrics 有正確的 label"""
        self._add_signal(status="done", sig_id="s1", kind="git_commit")
        stats = self.db.get_pipeline_stats(days=7)
        out = _format_prometheus(stats)
        self.assertIn('status="done"', out)
        self.assertIn('kind="git_commit"', out)

    def test_P05_empty_db_prometheus_still_valid(self):
        """空 DB 的 Prometheus 輸出仍然有效（有 queue depth gauge）"""
        stats = self.db.get_pipeline_stats(days=7)
        out = _format_prometheus(stats)
        self.assertIn("brain_signal_queue_depth 0", out)


if __name__ == "__main__":
    unittest.main()
