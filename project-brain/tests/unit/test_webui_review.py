"""
I-03 KRB 審查流程整合 WebUI 驗收測試。

驗證：
1. /api/review/queue 端點正常運作（排序、篩選）
2. /api/review/batch-approve 端點正常運作
3. 審查操作即時反映
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


def _setup_brain_dir(tmp_path: Path) -> Path:
    """Create a minimal .brain/ with review_board.db containing test staging items."""
    bd = tmp_path / ".brain"
    bd.mkdir()
    # Create brain.db (minimal)
    brain_db = sqlite3.connect(str(bd / "brain.db"))
    brain_db.execute("CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, title TEXT, type TEXT, content TEXT, confidence REAL, created_at TEXT, updated_at TEXT, scope TEXT, access_count INTEGER DEFAULT 0)")
    brain_db.execute("CREATE TABLE IF NOT EXISTS brain_meta (key TEXT PRIMARY KEY, value TEXT)")
    brain_db.commit()
    brain_db.close()

    # Create review_board.db with test data
    rb_db = sqlite3.connect(str(bd / "review_board.db"))
    rb_db.execute("""
        CREATE TABLE staged_nodes (
            id TEXT PRIMARY KEY,
            kind TEXT,
            title TEXT,
            content TEXT,
            confidence REAL,
            source TEXT,
            submitter TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'pending',
            review_note TEXT
        )
    """)
    test_items = [
        ("stg-001", "Rule", "JWT must use RS256", "Security requirement", 0.9, "cli", "alice", "2026-05-01T10:00:00"),
        ("stg-002", "Pitfall", "Mock tests can miss migrations", "Integration issue", 0.7, "agent", "bob", "2026-05-02T10:00:00"),
        ("stg-003", "Decision", "Use PostgreSQL for ACID", "Database choice", 0.85, "manual", "carol", "2026-05-03T10:00:00"),
        ("stg-004", "Note", "Deploy needs VPN", "Operations note", 0.6, "telegram", "dave", "2026-05-04T10:00:00"),
    ]
    rb_db.executemany(
        "INSERT INTO staged_nodes (id, kind, title, content, confidence, source, submitter, created_at, status) VALUES (?,?,?,?,?,?,?,?,'pending')",
        test_items,
    )
    rb_db.commit()
    rb_db.close()
    return tmp_path


class TestReviewQueueEndpoint(unittest.TestCase):
    """Test /api/review/queue endpoint."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        _setup_brain_dir(self.tmp)

    def _get_app(self):
        from project_brain.interfaces.web_ui.server import create_app
        app = create_app(str(self.tmp))
        app.config["TESTING"] = True
        return app.test_client()

    def test_review_queue_returns_all_pending(self):
        client = self._get_app()
        resp = client.get("/api/review/queue")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["total"], 4)
        self.assertEqual(len(data["items"]), 4)

    def test_review_queue_filter_by_kind(self):
        client = self._get_app()
        resp = client.get("/api/review/queue?kind=Rule")
        data = resp.get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["kind"], "Rule")

    def test_review_queue_sort_by_confidence(self):
        client = self._get_app()
        resp = client.get("/api/review/queue?sort=confidence")
        data = resp.get_json()
        confs = [i["confidence"] for i in data["items"]]
        self.assertEqual(confs, sorted(confs))


class TestBatchApproveEndpoint(unittest.TestCase):
    """Test /api/review/batch-approve endpoint."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        _setup_brain_dir(self.tmp)

    def _get_app(self):
        from project_brain.interfaces.web_ui.server import create_app
        app = create_app(str(self.tmp))
        app.config["TESTING"] = True
        return app.test_client()

    @patch("project_brain.interfaces.web_ui.server.KnowledgeReviewBoard", create=True)
    @patch("project_brain.interfaces.web_ui.server.KnowledgeGraph", create=True)
    def test_batch_approve_filters_by_threshold(self, mock_graph, mock_krb):
        """Batch approve should only approve items >= threshold."""
        # Mock the KRB
        mock_krb_instance = MagicMock()
        mock_krb.return_value = mock_krb_instance

        client = self._get_app()
        resp = client.post(
            "/api/review/batch-approve",
            data=json.dumps({"threshold": 0.85}),
            content_type="application/json",
        )
        data = resp.get_json()
        self.assertTrue(data["ok"])
        # With threshold 0.85, items stg-001 (0.9) and stg-003 (0.85) qualify
        self.assertEqual(data["total_candidates"], 2)


class TestReviewUIElements(unittest.TestCase):
    """Verify frontend elements exist."""

    def test_review_tab_in_html(self):
        """HTML template has a review tab button."""
        tpl_path = Path(__file__).parent.parent.parent / "project_brain/interfaces/web_ui/templates/index.html"
        html = tpl_path.read_text()
        self.assertIn('data-view="review"', html)
        self.assertIn("review-view", html)
        self.assertIn("review-body", html)

    def test_review_js_functions_exist(self):
        """app.js has review functions."""
        js_path = Path(__file__).parent.parent.parent / "project_brain/interfaces/web_ui/static/app.js"
        js = js_path.read_text()
        self.assertIn("loadReview", js)
        self.assertIn("reviewAction", js)
        self.assertIn("reviewBatchApprove", js)
        self.assertIn("/api/review/queue", js)

    def test_review_css_styles_exist(self):
        """style.css has review-specific styles."""
        css_path = Path(__file__).parent.parent.parent / "project_brain/interfaces/web_ui/static/style.css"
        css = css_path.read_text()
        self.assertIn(".rv-btn", css)
        self.assertIn(".conf-high", css)


if __name__ == "__main__":
    unittest.main()
