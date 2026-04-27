"""
D-02 Web UI 行內編輯 + KRB Staging API 測試

覆蓋：
  - PATCH /api/node/<id>  — 欄位更新、白名單驗證
  - DELETE /api/node/<id> — 節點刪除、邊清理
  - GET /api/staging       — 列出 pending staging
  - POST /api/staging/<id>/approve|reject

執行：
  pytest tests/unit/test_web_ui_edit.py -v
"""

import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def app_and_brain(tmp_path):
    """建立含正確 unified schema 的測試 Flask app。"""
    from project_brain.core.brain_db import BrainDB
    from project_brain.graph import KnowledgeGraph
    from project_brain.interfaces.web_ui.server import create_app

    bd = tmp_path / ".brain"
    bd.mkdir()
    # BrainDB first → correct unified schema (kind/scope columns)
    brain_db = BrainDB(bd)
    g = KnowledgeGraph(bd, conn=brain_db.conn)

    g.add_node("n1", "Pitfall", "JWT 必須驗證過期", content="exp claim 必須驗證",
               meta={"confidence": 0.9})
    g.add_node("n2", "Decision", "選用 PostgreSQL", content="ACID 保證",
               meta={"confidence": 0.85})
    g.add_node("n3", "Rule", "API 版本化規則", content="所有 API 必須版本化",
               meta={"confidence": 0.8})
    g.add_edge("n1", "BECAUSE", "n2")
    brain_db.conn.commit()

    app = create_app(tmp_path)
    app.config["TESTING"] = True
    return app, brain_db, bd


@pytest.fixture
def client(app_and_brain):
    app, brain_db, bd = app_and_brain
    with app.test_client() as c:
        yield c, brain_db, bd


# ─────────────────────────────────────────────
# PATCH /api/node/<id>
# ─────────────────────────────────────────────

class TestNodePatch:
    def test_patch_title(self, client):
        c, _, _ = client
        r = c.patch("/api/node/n1",
                    data=json.dumps({"title": "新標題"}),
                    content_type="application/json")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["ok"] is True

    def test_patch_title_reflected_in_get(self, client):
        c, _, _ = client
        c.patch("/api/node/n1",
                data=json.dumps({"title": "更新後標題"}),
                content_type="application/json")
        r = c.get("/api/node/n1")
        node = json.loads(r.data)
        assert node["title"] == "更新後標題"

    def test_patch_confidence(self, client):
        c, _, _ = client
        r = c.patch("/api/node/n2",
                    data=json.dumps({"confidence": 0.55}),
                    content_type="application/json")
        assert r.status_code == 200
        node = json.loads(c.get("/api/node/n2").data)
        assert abs(node["confidence"] - 0.55) < 0.01

    def test_patch_kind(self, client):
        # 'kind' in API maps to 'type' column in DB; GET returns it as 'kind'
        c, _, _ = client
        r = c.patch("/api/node/n1",
                    data=json.dumps({"kind": "Rule"}),
                    content_type="application/json")
        assert r.status_code == 200
        assert json.loads(r.data)["ok"] is True
        # GET /api/node/<id> returns kind aliased from type column
        node = json.loads(c.get("/api/node/n1").data)
        assert node["kind"] == "Rule"

    def test_patch_content(self, client):
        c, _, _ = client
        r = c.patch("/api/node/n3",
                    data=json.dumps({"content": "更新後的詳細說明"}),
                    content_type="application/json")
        assert r.status_code == 200
        node = json.loads(c.get("/api/node/n3").data)
        assert node["content"] == "更新後的詳細說明"

    def test_patch_multiple_fields(self, client):
        c, _, _ = client
        r = c.patch("/api/node/n1",
                    data=json.dumps({"title": "多欄更新", "confidence": 0.6}),
                    content_type="application/json")
        assert r.status_code == 200
        node = json.loads(c.get("/api/node/n1").data)
        assert node["title"] == "多欄更新"
        assert abs(node["confidence"] - 0.6) < 0.01

    def test_patch_rejects_unknown_field(self, client):
        c, _, _ = client
        r = c.patch("/api/node/n1",
                    data=json.dumps({"is_pinned": True, "hacked": "bad"}),
                    content_type="application/json")
        assert r.status_code == 400
        err = json.loads(r.data)
        assert "error" in err

    def test_patch_rejects_empty_title(self, client):
        c, _, _ = client
        r = c.patch("/api/node/n1",
                    data=json.dumps({"title": "   "}),
                    content_type="application/json")
        assert r.status_code == 400

    def test_patch_rejects_invalid_confidence_range(self, client):
        c, _, _ = client
        r = c.patch("/api/node/n1",
                    data=json.dumps({"confidence": 1.5}),
                    content_type="application/json")
        assert r.status_code == 400

    def test_patch_rejects_non_numeric_confidence(self, client):
        c, _, _ = client
        r = c.patch("/api/node/n1",
                    data=json.dumps({"confidence": "high"}),
                    content_type="application/json")
        assert r.status_code == 400

    def test_patch_rejects_invalid_kind(self, client):
        c, _, _ = client
        r = c.patch("/api/node/n1",
                    data=json.dumps({"kind": "NotARealKind"}),
                    content_type="application/json")
        assert r.status_code == 400

    def test_patch_nonexistent_node(self, client):
        c, _, _ = client
        r = c.patch("/api/node/ghost",
                    data=json.dumps({"title": "X"}),
                    content_type="application/json")
        assert r.status_code == 404

    def test_patch_empty_body(self, client):
        c, _, _ = client
        r = c.patch("/api/node/n1",
                    data=json.dumps({}),
                    content_type="application/json")
        assert r.status_code == 400

    def test_patch_fts_updated(self, client):
        """After PATCH, search should find the new title."""
        c, _, _ = client
        c.patch("/api/node/n1",
                data=json.dumps({"title": "FTS更新測試唯一標題"}),
                content_type="application/json")
        r = c.get("/api/search?q=FTS更新測試唯一標題")
        results = json.loads(r.data)["results"]
        assert any(res["id"] == "n1" for res in results)


# ─────────────────────────────────────────────
# DELETE /api/node/<id>
# ─────────────────────────────────────────────

class TestNodeDelete:
    def test_delete_existing_node(self, client):
        c, _, _ = client
        r = c.delete("/api/node/n3")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["ok"] is True

    def test_delete_node_not_in_graph(self, client):
        c, _, _ = client
        c.delete("/api/node/n2")
        r = c.get("/api/graph")
        nodes = json.loads(r.data)["nodes"]
        assert not any(n["id"] == "n2" for n in nodes)

    def test_delete_node_removes_edges(self, client):
        """Deleting n1 should remove the n1→n2 edge."""
        c, brain_db, _ = client
        c.delete("/api/node/n1")
        # edge should be gone
        row = brain_db.conn.execute(
            "SELECT COUNT(*) FROM edges WHERE source_id='n1' OR target_id='n1'"
        ).fetchone()[0]
        assert row == 0

    def test_delete_nonexistent_node(self, client):
        c, _, _ = client
        r = c.delete("/api/node/ghost_node")
        assert r.status_code == 404

    def test_delete_node_404_on_second_delete(self, client):
        c, _, _ = client
        c.delete("/api/node/n3")
        r = c.delete("/api/node/n3")
        assert r.status_code == 404

    def test_delete_decrements_stats(self, client):
        c, _, _ = client
        before = json.loads(c.get("/api/stats").data)["total_nodes"]
        c.delete("/api/node/n1")
        after = json.loads(c.get("/api/stats").data)["total_nodes"]
        assert after == before - 1


# ─────────────────────────────────────────────
# GET /api/staging
# ─────────────────────────────────────────────

class TestStagingList:
    def test_staging_returns_empty_when_no_review_board(self, client):
        """No review_board.db → returns empty list (no crash)."""
        c, _, bd = client
        rb = bd / "review_board.db"
        assert not rb.exists()
        r = c.get("/api/staging")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["staging"] == []
        assert data["total"] == 0

    def test_staging_returns_pending_items(self, client):
        """With review_board.db populated, pending items are returned."""
        c, _, bd = client
        import sqlite3
        import uuid
        rb_path = bd / "review_board.db"
        conn = sqlite3.connect(str(rb_path))
        conn.execute("""
            CREATE TABLE staged_nodes (
                id TEXT PRIMARY KEY, kind TEXT DEFAULT 'Rule', title TEXT,
                content TEXT DEFAULT '', tags TEXT DEFAULT '',
                source TEXT DEFAULT 'manual', submitter TEXT DEFAULT 'user',
                status TEXT DEFAULT 'pending', reviewer TEXT DEFAULT '',
                review_note TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')),
                reviewed_at TEXT DEFAULT '', l3_node_id TEXT DEFAULT '',
                applicability_condition TEXT DEFAULT '',
                invalidation_condition TEXT DEFAULT '',
                confidence REAL DEFAULT 0.7
            )
        """)
        sid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO staged_nodes (id, kind, title, content, confidence) VALUES (?,?,?,?,?)",
            (sid, "Rule", "待審規則 A", "規則內容", 0.7)
        )
        conn.commit()
        conn.close()

        r = c.get("/api/staging")
        data = json.loads(r.data)
        assert data["total"] == 1
        assert data["staging"][0]["id"] == sid
        assert data["staging"][0]["title"] == "待審規則 A"

    def test_staging_excludes_non_pending(self, client):
        """Approved/rejected entries should not appear."""
        c, _, bd = client
        import sqlite3, uuid
        rb_path = bd / "review_board.db"
        conn = sqlite3.connect(str(rb_path))
        conn.execute("""
            CREATE TABLE staged_nodes (
                id TEXT PRIMARY KEY, kind TEXT DEFAULT 'Rule', title TEXT,
                content TEXT DEFAULT '', tags TEXT DEFAULT '',
                source TEXT DEFAULT 'manual', submitter TEXT DEFAULT 'user',
                status TEXT DEFAULT 'pending', reviewer TEXT DEFAULT '',
                review_note TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')),
                reviewed_at TEXT DEFAULT '', l3_node_id TEXT DEFAULT '',
                applicability_condition TEXT DEFAULT '',
                invalidation_condition TEXT DEFAULT '',
                confidence REAL DEFAULT 0.7
            )
        """)
        conn.execute(
            "INSERT INTO staged_nodes (id, kind, title, status) VALUES (?,?,?,?)",
            (str(uuid.uuid4()), "Rule", "已核准的規則", "approved")
        )
        conn.execute(
            "INSERT INTO staged_nodes (id, kind, title, status) VALUES (?,?,?,?)",
            (str(uuid.uuid4()), "Rule", "待審規則 B", "pending")
        )
        conn.commit()
        conn.close()

        r = c.get("/api/staging")
        data = json.loads(r.data)
        assert data["total"] == 1
        assert data["staging"][0]["title"] == "待審規則 B"


# ─────────────────────────────────────────────
# _validate_node_patch (unit test for helper)
# ─────────────────────────────────────────────

class TestValidateNodePatch:
    def test_valid_title(self):
        from project_brain.interfaces.web_ui.server import _validate_node_patch
        cols, vals, err = _validate_node_patch({"title": "New Title"})
        assert err is None
        assert "title" in cols

    def test_valid_confidence_boundary(self):
        from project_brain.interfaces.web_ui.server import _validate_node_patch
        for val in [0.0, 1.0, 0.5]:
            cols, vals, err = _validate_node_patch({"confidence": val})
            assert err is None

    def test_invalid_confidence_over_1(self):
        from project_brain.interfaces.web_ui.server import _validate_node_patch
        _, _, err = _validate_node_patch({"confidence": 1.01})
        assert err is not None

    def test_invalid_confidence_negative(self):
        from project_brain.interfaces.web_ui.server import _validate_node_patch
        _, _, err = _validate_node_patch({"confidence": -0.1})
        assert err is not None

    def test_unknown_field_rejected(self):
        from project_brain.interfaces.web_ui.server import _validate_node_patch
        _, _, err = _validate_node_patch({"malicious": "DROP TABLE nodes"})
        assert err is not None

    def test_valid_kind(self):
        from project_brain.interfaces.web_ui.server import _validate_node_patch
        for k in ["Pitfall", "Decision", "Rule", "ADR", "Component", "Architecture", "Note"]:
            cols, vals, err = _validate_node_patch({"kind": k})
            assert err is None, f"Expected no error for kind={k}"

    def test_invalid_kind(self):
        from project_brain.interfaces.web_ui.server import _validate_node_patch
        _, _, err = _validate_node_patch({"kind": "BadKind"})
        assert err is not None

    def test_empty_title_rejected(self):
        from project_brain.interfaces.web_ui.server import _validate_node_patch
        _, _, err = _validate_node_patch({"title": ""})
        assert err is not None

    def test_whitespace_title_rejected(self):
        from project_brain.interfaces.web_ui.server import _validate_node_patch
        _, _, err = _validate_node_patch({"title": "   "})
        assert err is not None

    def test_empty_body_returns_empty_cols(self):
        from project_brain.interfaces.web_ui.server import _validate_node_patch
        cols, vals, err = _validate_node_patch({})
        assert err is None
        assert cols == []
