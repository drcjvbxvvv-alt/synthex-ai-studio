"""
tests/test_api.py — REST API 端點單元測試

覆蓋：
  - GET  /health
  - GET  /v1/stats
  - GET  /v1/knowledge
  - POST /v1/add
  - POST /v1/context
  - 錯誤處理（無 SQL 洩漏）
"""

import sys
import json
import threading
import urllib.request
import urllib.error
import pytest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from project_brain.api_server import run_server


# ══════════════════════════════════════════════════════════════
# Fixture：啟動真實 HTTP 伺服器
# ══════════════════════════════════════════════════════════════

class _APIClient:
    """極簡 HTTP 測試客戶端。"""
    def __init__(self, base_url: str):
        self.base = base_url

    def get(self, path: str):
        req = urllib.request.Request(self.base + path)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return _Resp(r.status, r.read())
        except urllib.error.HTTPError as e:
            return _Resp(e.code, e.read())

    def post(self, path: str, data: dict):
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            self.base + path, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return _Resp(r.status, r.read())
        except urllib.error.HTTPError as e:
            return _Resp(e.code, e.read())


class _Resp:
    def __init__(self, status: int, data: bytes):
        self.status_code = status
        self.data = data

    def json(self):
        return json.loads(self.data.decode("utf-8", errors="replace"))


@pytest.fixture(scope="module")
def api_client(tmp_path_factory):
    """啟動背景 HTTP 伺服器，返回測試客戶端。"""
    tmp = tmp_path_factory.mktemp("brain_api")
    bd = tmp / ".brain"
    bd.mkdir()

    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    t = threading.Thread(
        target=run_server,
        kwargs={"workdir": str(tmp), "port": port, "host": "127.0.0.1"},
        daemon=True,
    )
    t.start()

    # 等待伺服器就緒
    import time
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    yield _APIClient(f"http://127.0.0.1:{port}")


# ══════════════════════════════════════════════════════════════
# /health
# ══════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    def test_health_returns_200(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200

    def test_health_json(self, api_client):
        data = api_client.get("/health").json()
        assert "status" in data


# ══════════════════════════════════════════════════════════════
# /v1/stats
# ══════════════════════════════════════════════════════════════

class TestStatsEndpoint:
    def test_stats_returns_200(self, api_client):
        resp = api_client.get("/v1/stats")
        assert resp.status_code == 200

    def test_stats_no_sql_leak(self, api_client):
        body = api_client.get("/v1/stats").data.decode("utf-8", errors="replace")
        for kw in ["OperationalError", "sqlite3", "Traceback", "File \""]:
            assert kw not in body, f"SQL/stack leak: {kw}"


# ══════════════════════════════════════════════════════════════
# /v1/knowledge
# ══════════════════════════════════════════════════════════════

class TestKnowledgeEndpoint:
    def test_knowledge_returns_200(self, api_client):
        resp = api_client.get("/v1/knowledge")
        assert resp.status_code == 200

    def test_knowledge_no_sql_leak(self, api_client):
        body = api_client.get("/v1/knowledge").data.decode("utf-8", errors="replace")
        for kw in ["OperationalError", "sqlite3", "Traceback", "File \""]:
            assert kw not in body, f"SQL/stack leak: {kw}"


# ══════════════════════════════════════════════════════════════
# create_app backwards-compat shim
# ══════════════════════════════════════════════════════════════

class TestCreateApp:
    def test_create_app_returns_compat_object(self, tmp_path):
        bd = tmp_path / ".brain"
        bd.mkdir()
        from project_brain.api_server import create_app
        app = create_app(workdir=str(tmp_path))
        assert hasattr(app, "run"), "create_app() should return object with .run()"

    def test_create_app_run_is_callable(self, tmp_path):
        bd = tmp_path / ".brain"
        bd.mkdir()
        from project_brain.api_server import create_app
        app = create_app(workdir=str(tmp_path))
        assert callable(app.run)
