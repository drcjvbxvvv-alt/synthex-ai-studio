"""
tests/unit/test_health.py

B-03 — HealthChecker 診斷引擎測試
(ROADMAP.md §B-03 `brain health` diagnostic command)

驗收標準：
- 新初始化 DB 全通過 → overall=ok
- KG/BrainDB 不一致 → WARN
- KRB staging 過期 ��� WARN
- DB 不存在 → ERROR 但不 crash
- --json 輸出包含必要欄位
- 每個 check 失敗不影響其他 check
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from project_brain.health import HealthChecker, OK, WARN, ERROR


# ════���═════════════════════════════════════════════════════════════
#  測試輔助
# ══════════════════════════════════════════════════════════════════

class _HealthFixture(unittest.TestCase):
    """每個測試獨立 tmp brain_dir。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _init_brain(self):
        """初始化完整的 .brain — BrainDB + KnowledgeGraph + KRB。"""
        from project_brain.core.brain_db import BrainDB
        from project_brain.graph import KnowledgeGraph
        from project_brain.engines.review_board import KnowledgeReviewBoard

        self.db = BrainDB(self.brain_dir)
        self.graph = KnowledgeGraph(self.brain_dir)
        self.krb = KnowledgeReviewBoard(self.brain_dir, self.graph)
        return self.db, self.graph, self.krb

    def _close_all(self):
        for obj in ("krb", "graph", "db"):
            try:
                getattr(self, obj).close()
            except Exception:
                pass

    def _find_check(self, report: dict, label: str) -> dict | None:
        for c in report["checks"]:
            if c["label"] == label:
                return c
        return None


# ══════════════════════════════���═══════════════════════════════════
#  H-01 ~ H-04  Fresh DB（全 OK）
# ═══════════════════════��═════════════════════════════════��════════

class TestFreshDB(_HealthFixture):

    def test_H01_fresh_db_overall_ok(self):
        """新初始化的 brain，overall 應為 ok"""
        self._init_brain()
        self._close_all()
        report = HealthChecker(self.brain_dir).run()
        self.assertEqual(report["summary"]["overall"], OK)

    def test_H02_fresh_db_has_brain_db_check(self):
        self._init_brain()
        self._close_all()
        report = HealthChecker(self.brain_dir).run()
        c = self._find_check(report, "brain.db")
        self.assertIsNotNone(c)
        self.assertEqual(c["level"], OK)
        self.assertIn("accessible", c["message"])

    def test_H03_fresh_db_has_kg_check(self):
        self._init_brain()
        self._close_all()
        report = HealthChecker(self.brain_dir).run()
        c = self._find_check(report, "knowledge_graph.db")
        self.assertIsNotNone(c)
        self.assertEqual(c["level"], OK)

    def test_H04_fresh_db_sync_ok(self):
        """空 DB 時 KG/BrainDB sync 應為 ok（都是 0 nodes）"""
        self._init_brain()
        self._close_all()
        report = HealthChecker(self.brain_dir).run()
        c = self._find_check(report, "KG/BrainDB sync")
        self.assertIsNotNone(c)
        self.assertEqual(c["level"], OK)


# ══════════════════════════════════════════════════════════════════
#  W-01 ~ W-03  WARN 情境
# ═══════════════════════���═════════════════════════════════��════════

class TestWarnScenarios(_HealthFixture):

    def test_W01_kg_braindb_mismatch_warns(self):
        """KG 有節點但 BrainDB 沒有 → sync WARN"""
        self._init_brain()
        # Add node to KG only (bypass listener)
        self.graph._conn.execute(
            "INSERT INTO nodes (id, type, title, content, tags, confidence, "
            "created_at, updated_at, emotional_weight) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("orphan-001", "Rule", "orphan", "", "[]", 0.9,
             datetime.now(timezone.utc).isoformat(),
             datetime.now(timezone.utc).isoformat(), 0.5)
        )
        self.graph._conn.commit()
        self._close_all()

        report = HealthChecker(self.brain_dir).run()
        c = self._find_check(report, "KG/BrainDB sync")
        self.assertIsNotNone(c)
        self.assertEqual(c["level"], WARN)
        self.assertIn("KG only", c["message"])

    def test_W02_stale_staging_warns(self):
        """KRB 有 35 天前的 pending → WARN"""
        self._init_brain()
        sid = self.krb.submit("Old pending", "body", kind="Rule")
        # Age it to 35 days
        old_ts = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
        self.krb._conn_().execute(
            "UPDATE staged_nodes SET created_at=? WHERE id=?",
            (old_ts, sid),
        )
        self.krb._conn_().commit()
        self._close_all()

        report = HealthChecker(self.brain_dir).run()
        c = self._find_check(report, "KRB staging")
        self.assertIsNotNone(c)
        self.assertEqual(c["level"], WARN)
        self.assertIn("stale", c["message"])

    def test_W03_fresh_pending_no_warn(self):
        """KRB 有今天的 pending → OK（不是 stale）"""
        self._init_brain()
        self.krb.submit("Fresh pending", "body", kind="Rule")
        self._close_all()

        report = HealthChecker(self.brain_dir).run()
        c = self._find_check(report, "KRB staging")
        self.assertIsNotNone(c)
        self.assertEqual(c["level"], OK)
        self.assertIn("1 pending", c["message"])


# ══════════════════════════════════���═══════════════════════════════
#  E-01 ~ E-03  ERROR 情境
# ══════��═══════════════════════════════════��══════════════════════���

class TestErrorScenarios(_HealthFixture):

    def test_E01_no_brain_dir_has_errors(self):
        """brain_dir 存在但 DB 不存在 → ERROR"""
        # brain_dir exists (temp dir) but no DBs
        report = HealthChecker(self.brain_dir).run()
        self.assertEqual(report["summary"]["overall"], ERROR)
        c = self._find_check(report, "brain.db")
        self.assertIsNotNone(c)
        self.assertEqual(c["level"], ERROR)

    def test_E02_no_crash_on_missing_db(self):
        """DB 不存在不應 crash（不 raise）"""
        try:
            report = HealthChecker(self.brain_dir).run()
        except Exception as exc:
            self.fail(f"HealthChecker should not raise: {exc}")

    def test_E03_corrupt_db_shows_error(self):
        """brain.db 存在但損壞 → ERROR"""
        corrupt_db = self.brain_dir / "brain.db"
        corrupt_db.write_text("this is not a sqlite database")
        report = HealthChecker(self.brain_dir).run()
        c = self._find_check(report, "brain.db")
        self.assertIsNotNone(c)
        self.assertEqual(c["level"], ERROR)
        self.assertIn("read failed", c["message"])


# ══���══════════════════════════════════════��════════════════════════
#  J-01 ~ J-03  JSON 輸出格式
# ══════════════════════════════════════════════════════��═══════════

class TestJSONOutput(_HealthFixture):

    def test_J01_report_is_json_serializable(self):
        """report 可被 json.dumps ���列化"""
        self._init_brain()
        self._close_all()
        report = HealthChecker(self.brain_dir).run()
        try:
            out = json.dumps(report)
        except (TypeError, ValueError) as exc:
            self.fail(f"Report not JSON-serializable: {exc}")
        self.assertIsInstance(out, str)

    def test_J02_report_has_required_keys(self):
        """report 有 version, brain_dir, checks, summary"""
        self._init_brain()
        self._close_all()
        report = HealthChecker(self.brain_dir).run()
        for key in ("version", "brain_dir", "checks", "summary"):
            self.assertIn(key, report)
        for key in ("overall", "ok", "warn", "error"):
            self.assertIn(key, report["summary"])

    def test_J03_each_check_has_level_label_message(self):
        """每個 check 都有 level, label, message"""
        self._init_brain()
        self._close_all()
        report = HealthChecker(self.brain_dir).run()
        for check in report["checks"]:
            self.assertIn("level", check)
            self.assertIn("label", check)
            self.assertIn("message", check)
            self.assertIn(check["level"], (OK, WARN, ERROR))


# ═════════════════════════════��════════════════════════════════════
#  I-01 ~ I-03  隔離性
# ══════���═════════════════════════��═════════════════════════════════

class TestCheckIsolation(_HealthFixture):

    def test_I01_kg_missing_does_not_prevent_braindb_check(self):
        """knowledge_graph.db 不存在時，brain.db check 仍可正常運作"""
        from project_brain.core.brain_db import BrainDB
        self.db = BrainDB(self.brain_dir)
        self.db.close()
        # No KG created → knowledge_graph.db missing
        report = HealthChecker(self.brain_dir).run()
        brain_check = self._find_check(report, "brain.db")
        self.assertIsNotNone(brain_check)
        self.assertEqual(brain_check["level"], OK)

    def test_I02_braindb_missing_does_not_prevent_kg_check(self):
        """brain.db 不存在時，knowledge_graph.db check 仍可正常運作"""
        from project_brain.graph import KnowledgeGraph
        self.graph = KnowledgeGraph(self.brain_dir)
        self.graph.close()
        report = HealthChecker(self.brain_dir).run()
        kg_check = self._find_check(report, "knowledge_graph.db")
        self.assertIsNotNone(kg_check)
        self.assertEqual(kg_check["level"], OK)

    def test_I03_summary_counts_match_checks(self):
        """summary 的 ok/warn/error 計數與 checks 一致"""
        self._init_brain()
        self._close_all()
        report = HealthChecker(self.brain_dir).run()
        s = report["summary"]
        actual_ok   = sum(1 for c in report["checks"] if c["level"] == OK)
        actual_warn = sum(1 for c in report["checks"] if c["level"] == WARN)
        actual_err  = sum(1 for c in report["checks"] if c["level"] == ERROR)
        self.assertEqual(s["ok"], actual_ok)
        self.assertEqual(s["warn"], actual_warn)
        self.assertEqual(s["error"], actual_err)


# ═════════��══════════════════════════��═════════════════════════════
#  S-01 ~ S-03  Schema + Signal Queue + Benchmark
# ═════════════════════════════��════════════════════════════════��═══

class TestSchemaAndExtras(_HealthFixture):

    def test_S01_schema_version_ok(self):
        """正常 DB 的 schema check 為 ok"""
        self._init_brain()
        self._close_all()
        report = HealthChecker(self.brain_dir).run()
        c = self._find_check(report, "schema")
        self.assertIsNotNone(c)
        self.assertEqual(c["level"], OK)

    def test_S02_signal_queue_ok_on_fresh_db(self):
        """新 DB signal queue 為 ok"""
        self._init_brain()
        self._close_all()
        report = HealthChecker(self.brain_dir).run()
        c = self._find_check(report, "signal queue")
        self.assertIsNotNone(c)
        self.assertEqual(c["level"], OK)

    def test_S03_benchmark_missing_is_ok(self):
        """baseline.json 不存在 → ok（未設定，非 error）"""
        self._init_brain()
        self._close_all()
        report = HealthChecker(self.brain_dir).run()
        c = self._find_check(report, "benchmark")
        self.assertIsNotNone(c)
        self.assertEqual(c["level"], OK)

    def test_S04_old_benchmark_warns(self):
        """baseline.json 15 天前更新 → WARN"""
        self._init_brain()
        self._close_all()
        import os, time
        baseline = self.brain_dir / "baseline.json"
        baseline.write_text("{}")
        # Set mtime to 15 days ago
        old_time = time.time() - 15 * 86400
        os.utime(str(baseline), (old_time, old_time))
        report = HealthChecker(self.brain_dir).run()
        c = self._find_check(report, "benchmark")
        self.assertIsNotNone(c)
        self.assertEqual(c["level"], WARN)

    def test_S05_failed_signals_warn(self):
        """signal_queue 有 failed 記錄 → WARN"""
        self._init_brain()
        # Insert a failed signal
        self.db.conn.execute(
            "INSERT INTO signal_queue (id, kind, workdir, timestamp, summary, "
            "raw_content, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("sig-001", "git_commit", "/tmp", datetime.now(timezone.utc).isoformat(),
             "test", "{}", "failed")
        )
        self.db.conn.commit()
        self._close_all()

        report = HealthChecker(self.brain_dir).run()
        c = self._find_check(report, "signal queue")
        self.assertIsNotNone(c)
        self.assertEqual(c["level"], WARN)
        self.assertIn("failed", c["message"])


if __name__ == "__main__":
    unittest.main()
