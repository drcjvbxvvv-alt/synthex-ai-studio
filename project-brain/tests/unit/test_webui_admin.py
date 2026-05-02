"""
E-06 WebUI Admin API Tests — Dashboard, Audit Log, Settings, Add Knowledge

Tests cover:
  - POST /api/node — add knowledge from WebUI
  - GET /api/admin/dashboard — system overview stats
  - GET /api/admin/audit-log — audit trail with filters
  - GET /api/admin/settings — system configuration display

Run:  pytest tests/unit/test_webui_admin.py -v
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def setup(tmp_path):
    """Create test Flask app with pre-populated data."""
    from project_brain.core.brain_db import BrainDB
    from project_brain.graph import KnowledgeGraph
    from project_brain.interfaces.web_ui.server import create_app

    bd = tmp_path / ".brain"
    bd.mkdir()
    brain_db = BrainDB(bd)
    g = KnowledgeGraph(bd, conn=brain_db.conn)

    g.add_node("n1", "Pitfall", "JWT 驗證過期", content="exp claim 必須檢查",
               meta={"confidence": 0.9})
    g.add_node("n2", "Decision", "選用 PostgreSQL", content="ACID 保證",
               meta={"confidence": 0.85})
    g.add_node("n3", "Rule", "API 版本化", content="所有 API 必須版本化",
               meta={"confidence": 0.2})  # low confidence
    g.add_edge("n1", "BECAUSE", "n2")
    brain_db.conn.commit()

    app = create_app(tmp_path)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, brain_db, bd, tmp_path


# ── POST /api/node ──────────────────────────────────────────────


class TestAddNode:
    def test_add_node_success(self, setup):
        c, db, bd, wd = setup
        r = c.post("/api/node", json={
            "title": "新規則",
            "content": "所有 API 必須加上 rate limiting",
            "kind": "Rule",
            "confidence": 0.8,
        })
        assert r.status_code == 201
        data = json.loads(r.data)
        assert data["ok"] is True
        assert data["id"].startswith("webui-")

    def test_add_node_defaults(self, setup):
        c, db, bd, wd = setup
        r = c.post("/api/node", json={
            "title": "簡單筆記",
            "content": "一些內容",
        })
        assert r.status_code == 201
        data = json.loads(r.data)
        assert data["ok"] is True

    def test_add_node_missing_title(self, setup):
        c, db, bd, wd = setup
        r = c.post("/api/node", json={"content": "only content"})
        assert r.status_code == 400
        data = json.loads(r.data)
        assert "標題" in data["error"]

    def test_add_node_missing_content(self, setup):
        c, db, bd, wd = setup
        r = c.post("/api/node", json={"title": "only title"})
        assert r.status_code == 400
        data = json.loads(r.data)
        assert "內容" in data["error"]

    def test_add_node_invalid_kind(self, setup):
        c, db, bd, wd = setup
        r = c.post("/api/node", json={
            "title": "test", "content": "test", "kind": "InvalidKind",
        })
        assert r.status_code == 400
        data = json.loads(r.data)
        assert "類型" in data["error"]

    def test_add_node_confidence_out_of_range(self, setup):
        c, db, bd, wd = setup
        r = c.post("/api/node", json={
            "title": "test", "content": "test", "confidence": 1.5,
        })
        assert r.status_code == 400
        assert "信心度" in json.loads(r.data)["error"]

    def test_add_node_confidence_negative(self, setup):
        c, db, bd, wd = setup
        r = c.post("/api/node", json={
            "title": "test", "content": "test", "confidence": -0.1,
        })
        assert r.status_code == 400

    def test_add_node_title_too_long(self, setup):
        c, db, bd, wd = setup
        r = c.post("/api/node", json={
            "title": "x" * 501, "content": "test",
        })
        assert r.status_code == 400
        assert "500" in json.loads(r.data)["error"]

    def test_add_node_persists_in_db(self, setup):
        """Verify the node actually exists in the database after creation."""
        c, db, bd, wd = setup
        r = c.post("/api/node", json={
            "title": "持久化測試", "content": "這是測試內容", "kind": "Pitfall",
        })
        data = json.loads(r.data)
        node_id = data["id"]
        # Verify by reading back
        r2 = c.get(f"/api/node/{node_id}")
        assert r2.status_code == 200
        node = json.loads(r2.data)
        assert node["title"] == "持久化測試"
        assert node["kind"] == "Pitfall"


# ── GET /api/admin/dashboard ────────────────────────────────────


class TestDashboard:
    def test_dashboard_returns_stats(self, setup):
        c, db, bd, wd = setup
        r = c.get("/api/admin/dashboard")
        assert r.status_code == 200
        d = json.loads(r.data)
        assert d["total_nodes"] == 3
        assert d["total_edges"] >= 1
        assert "kind_distribution" in d
        assert "Pitfall" in d["kind_distribution"]
        assert d["kind_distribution"]["Pitfall"] >= 1

    def test_dashboard_low_confidence(self, setup):
        c, db, bd, wd = setup
        r = c.get("/api/admin/dashboard")
        d = json.loads(r.data)
        # n3 has confidence 0.2 which is < 0.3
        assert d["low_confidence_count"] >= 1

    def test_dashboard_activity(self, setup):
        c, db, bd, wd = setup
        r = c.get("/api/admin/dashboard")
        d = json.loads(r.data)
        assert "activity" in d
        # All 3 nodes were created "now" so they count as today
        assert d["activity"]["today"] >= 3
        assert d["activity"]["week"] >= 3

    def test_dashboard_health(self, setup):
        c, db, bd, wd = setup
        r = c.get("/api/admin/dashboard")
        d = json.loads(r.data)
        assert "health" in d
        assert d["health"]["status"] in ("ok", "warn", "error")

    def test_dashboard_krb_and_signal(self, setup):
        c, db, bd, wd = setup
        r = c.get("/api/admin/dashboard")
        d = json.loads(r.data)
        assert "krb_pending" in d
        assert "signal_pending" in d


# ── GET /api/admin/audit-log ────────────────────────────────────


class TestAuditLog:
    def test_audit_log_empty(self, setup):
        """Fresh DB with no history should return empty entries."""
        c, db, bd, wd = setup
        r = c.get("/api/admin/audit-log")
        assert r.status_code == 200
        d = json.loads(r.data)
        assert "entries" in d
        assert "total" in d
        assert "page" in d
        assert d["page"] == 1

    def test_audit_log_with_history(self, setup):
        """After updating a node, audit log should contain the update."""
        c, db, bd, wd = setup
        # Make an update to generate node_history
        db.update_node("n1", title="JWT 驗證更新", changed_by="test-user",
                       change_note="更新標題")
        r = c.get("/api/admin/audit-log")
        d = json.loads(r.data)
        assert d["total"] >= 1
        entry = d["entries"][0]
        assert entry["actor"] == "test-user"
        assert entry["node_id"] == "n1"

    def test_audit_log_filter_by_author(self, setup):
        c, db, bd, wd = setup
        db.update_node("n1", title="Updated by Alice", changed_by="alice")
        db.update_node("n2", title="Updated by Bob", changed_by="bob")
        r = c.get("/api/admin/audit-log?author=alice")
        d = json.loads(r.data)
        for entry in d["entries"]:
            assert "alice" in entry["actor"].lower()

    def test_audit_log_filter_by_action(self, setup):
        c, db, bd, wd = setup
        db.update_node("n1", title="Updated", changed_by="test")
        r = c.get("/api/admin/audit-log?action=update")
        d = json.loads(r.data)
        for entry in d["entries"]:
            assert entry["action"] == "update"

    def test_audit_log_pagination(self, setup):
        c, db, bd, wd = setup
        r = c.get("/api/admin/audit-log?page=1&page_size=10")
        d = json.loads(r.data)
        assert d["page"] == 1
        assert d["page_size"] == 10
        assert "total_pages" in d


# ── GET /api/admin/settings ─────────────────────────────────────


class TestSettings:
    def test_settings_returns_structure(self, setup):
        c, db, bd, wd = setup
        r = c.get("/api/admin/settings")
        assert r.status_code == 200
        d = json.loads(r.data)
        assert "mode" in d
        assert "embedding" in d
        assert "llm" in d
        assert "schema_version" in d
        assert "services" in d
        assert "storage" in d

    def test_settings_mode_default(self, setup):
        c, db, bd, wd = setup
        r = c.get("/api/admin/settings")
        d = json.loads(r.data)
        assert d["mode"] == "standalone"

    def test_settings_schema_version(self, setup):
        c, db, bd, wd = setup
        r = c.get("/api/admin/settings")
        d = json.loads(r.data)
        assert d["schema_version"] > 0

    def test_settings_services_includes_brain_db(self, setup):
        c, db, bd, wd = setup
        r = c.get("/api/admin/settings")
        d = json.loads(r.data)
        svc_names = [s["name"] for s in d["services"]]
        assert "brain.db" in svc_names

    def test_settings_storage_info(self, setup):
        c, db, bd, wd = setup
        r = c.get("/api/admin/settings")
        d = json.loads(r.data)
        assert "brain_db" in d["storage"]

    def test_settings_returns_config(self, setup):
        c, db, bd, wd = setup
        r = c.get("/api/admin/settings")
        d = json.loads(r.data)
        assert "config" in d
        cfg = d["config"]
        assert "decay_enabled" in cfg
        assert "pipeline_enabled" in cfg
        assert "brain_max_context_tokens" in cfg
        assert "review_auto_approve_threshold" in cfg

    def test_save_settings_writes_toml(self, setup):
        c, db, bd, wd = setup
        r = c.post("/api/admin/settings", json={
            "config": {
                "decay_enabled": False,
                "brain_max_context_tokens": 4000,
                "review_auto_approve_threshold": 0.9,
            }
        })
        assert r.status_code == 200
        d = json.loads(r.data)
        assert d["ok"] is True
        # Verify TOML was written
        toml_path = bd / "brain.toml"
        assert toml_path.exists()
        content = toml_path.read_text(encoding="utf-8")
        assert "enabled = false" in content
        assert "max_context_tokens = 4000" in content

    def test_save_settings_then_read_back(self, setup):
        c, db, bd, wd = setup
        c.post("/api/admin/settings", json={
            "config": {"pipeline_enabled": False, "decay_interval_hours": 12}
        })
        r = c.get("/api/admin/settings")
        d = json.loads(r.data)
        assert d["config"]["pipeline_enabled"] is False
        assert d["config"]["decay_interval_hours"] == 12

    def test_save_settings_empty_config_rejected(self, setup):
        c, db, bd, wd = setup
        r = c.post("/api/admin/settings", json={"config": {}})
        assert r.status_code == 400
