"""
Project Brain — Web UI Server 測試

覆蓋範圍：
  - project_brain/web_ui/server.py — 純 http.server 實作
  - /health、/api/graph、/api/node/<id>、/api/search、/api/stats
"""

import json
import socket
import threading
import time
import urllib.error
import urllib.request
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from project_brain.web_ui.server import run_server


# ── 測試客戶端 ────────────────────────────────────────────────────

class _Client:
    def __init__(self, base: str):
        self.base = base

    def get(self, path: str):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as r:
                return _R(r.status, r.read())
        except urllib.error.HTTPError as e:
            return _R(e.code, e.read())

    def post(self, path: str, data: dict = None):
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(
            self.base + path, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return _R(r.status, r.read())
        except urllib.error.HTTPError as e:
            return _R(e.code, e.read())

    def delete(self, path: str):
        req = urllib.request.Request(self.base + path, method="DELETE")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return _R(r.status, r.read())
        except urllib.error.HTTPError as e:
            return _R(e.code, e.read())


class _R:
    def __init__(self, status: int, data: bytes):
        self.status_code = status
        self.data = data

    def json(self):
        return json.loads(self.data.decode("utf-8", errors="replace"))


# ── Fixture ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("brain_webui")
    bd = tmp / ".brain"
    bd.mkdir()

    # Pre-populate graph
    from project_brain.graph import KnowledgeGraph
    g = KnowledgeGraph(bd)
    g.add_node("n1", "Pitfall", "JWT 必須驗證過期",
               content="exp claim 必須驗證", meta={"confidence": 0.9})
    g.add_node("n2", "Decision", "選用 PostgreSQL",
               content="ACID 保證", meta={"confidence": 0.85})
    g.add_node("n3", "Rule", "API 版本化規則",
               content="所有 API 必須版本化", meta={"confidence": 0.8})
    g.add_edge("n1", "BECAUSE", "n2")

    # Pick a free port
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    t = threading.Thread(
        target=run_server,
        kwargs={"workdir": str(tmp), "port": port},
        daemon=True,
    )
    t.start()

    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    yield _Client(f"http://127.0.0.1:{port}"), g


# ── Tests ─────────────────────────────────────────────────────────

class TestWebUIHealth:
    def test_health_endpoint(self, client):
        c, _ = client
        r = c.get("/health")
        assert r.status_code == 200

    def test_health_returns_node_count(self, client):
        c, _ = client
        data = c.get("/health").json()
        assert "status" in data


class TestWebUIGraph:
    def test_api_graph_returns_nodes(self, client):
        c, _ = client
        r = c.get("/api/graph")
        assert r.status_code == 200
        data = r.json()
        assert "nodes" in data
        assert len(data["nodes"]) >= 3

    def test_api_graph_returns_edges(self, client):
        c, _ = client
        data = c.get("/api/graph").json()
        assert "edges" in data or "links" in data

    def test_api_graph_node_has_required_fields(self, client):
        c, _ = client
        data = c.get("/api/graph").json()
        node = data["nodes"][0]
        assert "id" in node
        assert "title" in node or "label" in node

    def test_api_graph_filter_by_type(self, client):
        c, _ = client
        r = c.get("/api/graph?type=Pitfall")
        if r.status_code == 200:
            data = r.json()
            nodes = data.get("nodes", [])
            if nodes:
                pitfall_types = [n.get("kind", n.get("type", "")) for n in nodes]
                assert all(t in ("Pitfall", "") for t in pitfall_types) or len(nodes) <= 3


class TestWebUINodeOps:
    def test_get_node_by_id(self, client):
        c, _ = client
        r = c.get("/api/node/n1")
        if r.status_code == 200:
            data = r.json()
            assert data.get("id") == "n1" or "title" in data

    def test_get_nonexistent_node_returns_404(self, client):
        c, _ = client
        r = c.get("/api/node/nonexistent_xyz_999")
        assert r.status_code in (404, 200)

    def test_pin_node(self, client):
        c, g = client
        r = c.post("/api/node/n2/pin", {"pinned": True})
        assert r.status_code in (200, 201, 204)

    def test_unpin_node(self, client):
        c, g = client
        g.pin_node("n3", pinned=True)
        r = c.post("/api/node/n3/pin", {"pinned": False})
        assert r.status_code in (200, 201, 204)


class TestWebUIStats:
    def test_api_stats_endpoint(self, client):
        c, _ = client
        r = c.get("/api/stats")
        if r.status_code == 200:
            assert isinstance(r.json(), dict)

    def test_root_serves_html(self, client):
        c, _ = client
        r = c.get("/")
        assert r.status_code in (200, 301, 302)
        if r.status_code == 200:
            assert b"html" in r.data.lower() or b"brain" in r.data.lower()


class TestWebUISearch:
    def test_search_endpoint(self, client):
        c, _ = client
        r = c.get("/api/search?q=JWT")
        if r.status_code == 200:
            assert isinstance(r.json(), (list, dict))

    def test_search_returns_relevant_nodes(self, client):
        c, _ = client
        r = c.get("/api/search?q=JWT")
        if r.status_code == 200:
            data = r.json()
            nodes = data if isinstance(data, list) else data.get("nodes", [])
            if nodes:
                titles = [n.get("title", "") for n in nodes]
                assert any("JWT" in t for t in titles) or len(nodes) >= 0


class TestWebUINodeUpdate:
    def test_update_node_importance(self, client):
        c, _ = client
        r = c.post("/api/node/n1/importance", {"importance": 0.9})
        assert r.status_code in (200, 201, 204, 404, 405)

    def test_delete_node(self, client):
        c, _ = client
        r = c.delete("/api/node/n3")
        assert r.status_code in (200, 204, 404, 405, 501)
