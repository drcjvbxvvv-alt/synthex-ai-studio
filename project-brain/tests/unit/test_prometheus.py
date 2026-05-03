"""
E-06 Prometheus /metrics Endpoint Tests

Tests cover:
  - HealthEndpoint responds to /metrics with Prometheus text format
  - Metrics include brain_nodes_total, brain_staging_pending, etc.
  - /health still works alongside /metrics

Run:  pytest tests/unit/test_prometheus.py -v
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def brain_dir(tmp_path):
    """Create a .brain directory with a populated brain.db."""
    from project_brain.core.brain_db import BrainDB
    bd = tmp_path / ".brain"
    bd.mkdir()
    db = BrainDB(bd)
    db.add_node("p1", "Pitfall", "Bug in auth", content="token expired")
    db.add_node("p2", "Pitfall", "Bug in DB", content="deadlock")
    db.add_node("r1", "Rule", "Use HTTPS", content="always use TLS")
    db.add_node("d1", "Decision", "Use SQLite", content="for simplicity")
    db.conn.commit()
    return bd


@pytest.fixture
def health_endpoint(brain_dir):
    """Create a HealthEndpoint instance with a dummy inner app."""
    from project_brain.interfaces.http_transport import HealthEndpoint

    async def dummy_app(scope, receive, send):
        payload = b'{"passthrough": true}'
        await send({
            "type": "http.response.start", "status": 200,
            "headers": [[b"content-type", b"application/json"],
                         [b"content-length", str(len(payload)).encode()]],
        })
        await send({"type": "http.response.body", "body": payload})

    return HealthEndpoint(dummy_app, version="0.53.0", mode="standalone",
                          brain_dir=brain_dir)


def _run_asgi(app, path, method="GET"):
    """Helper to run an ASGI app synchronously for testing."""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
    }
    response_started = {}
    body_parts = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(msg):
        if msg["type"] == "http.response.start":
            response_started["status"] = msg["status"]
            response_started["headers"] = {
                h[0].decode(): h[1].decode()
                for h in msg.get("headers", [])
            }
        elif msg["type"] == "http.response.body":
            body_parts.append(msg.get("body", b""))

    asyncio.run(app(scope, receive, send))
    return response_started, b"".join(body_parts)


class TestPrometheusMetrics:
    def test_metrics_endpoint_returns_200(self, health_endpoint):
        resp, body = _run_asgi(health_endpoint, "/metrics")
        assert resp["status"] == 200

    def test_metrics_content_type(self, health_endpoint):
        resp, body = _run_asgi(health_endpoint, "/metrics")
        assert "text/plain" in resp["headers"]["content-type"]

    def test_metrics_contains_brain_info(self, health_endpoint):
        resp, body = _run_asgi(health_endpoint, "/metrics")
        text = body.decode("utf-8")
        assert "brain_info" in text
        assert 'version="0.53.0"' in text

    def test_metrics_contains_nodes_total(self, health_endpoint):
        resp, body = _run_asgi(health_endpoint, "/metrics")
        text = body.decode("utf-8")
        assert "brain_nodes_total" in text
        assert 'kind="Pitfall"' in text
        assert 'kind="Rule"' in text
        assert 'kind="Decision"' in text

    def test_metrics_node_counts_correct(self, health_endpoint):
        resp, body = _run_asgi(health_endpoint, "/metrics")
        text = body.decode("utf-8")
        # We added 2 Pitfalls, 1 Rule, 1 Decision
        for line in text.splitlines():
            if 'brain_nodes_total{kind="Pitfall"}' in line:
                assert line.strip().endswith("2")
            elif 'brain_nodes_total{kind="Rule"}' in line:
                assert line.strip().endswith("1")
            elif 'brain_nodes_total{kind="Decision"}' in line:
                assert line.strip().endswith("1")

    def test_metrics_contains_staging_pending(self, health_endpoint):
        resp, body = _run_asgi(health_endpoint, "/metrics")
        text = body.decode("utf-8")
        assert "brain_staging_pending" in text

    def test_metrics_contains_api_keys(self, health_endpoint):
        resp, body = _run_asgi(health_endpoint, "/metrics")
        text = body.decode("utf-8")
        assert "brain_api_keys_active" in text

    def test_metrics_contains_db_size(self, health_endpoint):
        resp, body = _run_asgi(health_endpoint, "/metrics")
        text = body.decode("utf-8")
        assert "brain_db_size_bytes" in text

    def test_metrics_contains_signal_queue(self, health_endpoint):
        resp, body = _run_asgi(health_endpoint, "/metrics")
        text = body.decode("utf-8")
        assert "brain_signal_queue_pending" in text

    def test_health_still_works(self, health_endpoint):
        """Ensure /health is not broken by the metrics addition."""
        resp, body = _run_asgi(health_endpoint, "/health")
        assert resp["status"] == 200
        data = json.loads(body)
        assert data["status"] == "ok"
        assert data["version"] == "0.53.0"

    def test_other_paths_pass_through(self, health_endpoint):
        """Non-health/metrics paths should pass through to inner app."""
        resp, body = _run_asgi(health_endpoint, "/mcp")
        assert resp["status"] == 200
        data = json.loads(body)
        assert data["passthrough"] is True


class TestMetricsWithoutBrainDir:
    def test_metrics_without_brain_dir(self):
        """Metrics endpoint works even without brain_dir (returns minimal output)."""
        from project_brain.interfaces.http_transport import HealthEndpoint

        async def dummy_app(scope, receive, send):
            pass

        endpoint = HealthEndpoint(dummy_app, version="0.53.0")
        resp, body = _run_asgi(endpoint, "/metrics")
        assert resp["status"] == 200
        text = body.decode("utf-8")
        assert "brain_info" in text
        # Should NOT contain node counts since no brain_dir
        assert "brain_nodes_total" not in text
