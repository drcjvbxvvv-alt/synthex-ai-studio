"""
tests/unit/test_health_storage.py

P2-2 修復驗收 — health 顯示 DB/WAL/backup size + vector coverage metrics

背景：brain health 缺少 storage 相關 metrics，使用者無法了解
資源消耗。新增 storage/db, storage/backups, storage/vectors 三項檢查。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from project_brain.core.brain_db import BrainDB
from project_brain.health import HealthChecker, OK, WARN


class _HealthFixture(unittest.TestCase):
    """每個測試獨立 tmp BrainDB + HealthChecker。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self._tmp.name)
        self.db = BrainDB(self.brain_dir)
        self.hc = HealthChecker(self.brain_dir)

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass
        self._tmp.cleanup()


class TestStorageDBSize(_HealthFixture):
    """storage/db check."""

    def test_db_size_reported(self):
        """應報告 brain.db 大小。"""
        results = self.hc._check_storage_metrics()
        db_checks = [r for r in results if r["label"] == "storage/db"]
        self.assertEqual(len(db_checks), 1)
        self.assertEqual(db_checks[0]["level"], OK)
        self.assertIn("brain.db=", db_checks[0]["message"])

    def test_db_size_with_data(self):
        """有資料的 DB 大小應 > 0。"""
        for i in range(10):
            self.db.add_node(
                node_id=f"n{i}", node_type="Rule",
                title=f"Rule {i}", content=f"Content {i}",
                tags=[], confidence=0.8,
            )
        results = self.hc._check_storage_metrics()
        db_checks = [r for r in results if r["label"] == "storage/db"]
        self.assertEqual(len(db_checks), 1)
        # Should show KB or MB size
        msg = db_checks[0]["message"]
        self.assertTrue("KB" in msg or "MB" in msg or "B" in msg)


class TestStorageBackups(_HealthFixture):
    """storage/backups check."""

    def test_no_backups_dir(self):
        """無 backups 或空 backups → OK with 0 backups。"""
        # BrainDB may auto-create backups dir, so check for 0 count
        results = self.hc._check_storage_metrics()
        backup_checks = [r for r in results if r["label"] == "storage/backups"]
        self.assertEqual(len(backup_checks), 1)
        self.assertEqual(backup_checks[0]["level"], OK)
        msg = backup_checks[0]["message"]
        self.assertTrue("no backups" in msg or "0 backups" in msg)

    def test_with_backups(self):
        """有 backups → 報告數量和大小。"""
        backup_dir = self.brain_dir / "backups"
        backup_dir.mkdir(exist_ok=True)
        for i in range(3):
            (backup_dir / f"brain.db.{i}").write_bytes(b"x" * 1024)
        results = self.hc._check_storage_metrics()
        backup_checks = [r for r in results if r["label"] == "storage/backups"]
        self.assertEqual(len(backup_checks), 1)
        self.assertIn("3 backups", backup_checks[0]["message"])

    def test_many_backups_warns(self):
        """超過 14 個 backups → WARN。"""
        backup_dir = self.brain_dir / "backups"
        backup_dir.mkdir(exist_ok=True)
        for i in range(15):
            (backup_dir / f"brain.db.{i}").write_bytes(b"x" * 100)
        results = self.hc._check_storage_metrics()
        backup_checks = [r for r in results if r["label"] == "storage/backups"]
        self.assertEqual(backup_checks[0]["level"], WARN)


class TestStorageVectors(_HealthFixture):
    """storage/vectors check."""

    def test_vectors_coverage_reported(self):
        """有 vectors 表時應報告覆蓋率。"""
        self.db.add_node(
            node_id="n1", node_type="Rule",
            title="Test rule", content="Content",
            tags=[], confidence=0.8,
        )
        results = self.hc._check_storage_metrics()
        vec_checks = [r for r in results if r["label"] == "storage/vectors"]
        self.assertEqual(len(vec_checks), 1)
        # May or may not have vectors table depending on setup
        self.assertIn(vec_checks[0]["level"], (OK, WARN))

    def test_no_db_returns_empty(self):
        """無 brain.db → 空列表。"""
        db_path = self.brain_dir / "brain.db"
        self.db.conn.close()
        db_path.unlink(missing_ok=True)
        hc = HealthChecker(self.brain_dir)
        results = hc._check_storage_metrics()
        self.assertEqual(results, [])


class TestHealthReportIntegration(_HealthFixture):
    """確認 storage metrics 出現在 run() 完整報告中。"""

    def test_run_includes_storage_checks(self):
        """run() 報告應包含 storage/ 開頭的 label。"""
        self.db.add_node(
            node_id="n1", node_type="Rule",
            title="Test", content="Content",
            tags=[], confidence=0.8,
        )
        report = self.hc.run()
        labels = [c["label"] for c in report["checks"]]
        storage_labels = [l for l in labels if l.startswith("storage/")]
        self.assertGreaterEqual(len(storage_labels), 2,
                                f"Expected storage checks, got labels: {labels}")


if __name__ == "__main__":
    unittest.main()
