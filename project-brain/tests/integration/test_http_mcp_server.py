"""
tests/integration/test_http_mcp_server.py — E-01 HTTP MCP Transport 測試

驗證：
  - AuthMiddleware：Bearer token 驗證、timing-safe 比較、/health 免驗
  - RateLimitMiddleware：每 IP 滑動視窗、429 拒絕、不同 IP 獨立
  - CORSMiddleware：preflight OPTIONS、origin 白名單、header 注入
  - HealthEndpoint：/health 200 JSON、非 /health 透傳
  - HTTPBrainServer：create_app 組裝、middleware 堆疊順序

執行：
  pytest tests/integration/test_http_mcp_server.py -v
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from project_brain.interfaces.http_transport import (
    AuthMiddleware,
    CORSMiddleware,
    HealthEndpoint,
    HTTPBrainServer,
    RateLimitMiddleware,
)


# ── Helpers ───────────────────────────────────────────────────────

def _make_scope(
    path: str = "/mcp",
    method: str = "POST",
    headers: dict[bytes, bytes] | None = None,
    client: tuple[str, int] | None = ("127.0.0.1", 12345),
) -> dict:
    """Build a minimal ASGI HTTP scope."""
    h = headers or {}
    return {
        "type": "http",
        "path": path,
        "method": method,
        "headers": list(h.items()),
        "client": client,
    }


class ResponseCapture:
    """Captures ASGI send() calls for inspection."""

    def __init__(self):
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int:
        for m in self.messages:
            if m["type"] == "http.response.start":
                return m["status"]
        return 0

    @property
    def body_json(self) -> dict:
        for m in self.messages:
            if m["type"] == "http.response.body":
                return json.loads(m["body"])
        return {}

    @property
    def headers_dict(self) -> dict[bytes, bytes]:
        for m in self.messages:
            if m["type"] == "http.response.start":
                return dict(m.get("headers", []))
        return {}


async def _noop_receive():
    return {"type": "http.request", "body": b""}


# A pass-through ASGI app that always returns 200
async def _ok_app(scope, receive, send):
    body = json.dumps({"ok": True}).encode()
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [[b"content-type", b"application/json"]],
    })
    await send({"type": "http.response.body", "body": body})


# ── TestAuthMiddleware ────────────────────────────────────────────

class TestAuthMiddleware:
    """Bearer token authentication."""

    @pytest.fixture
    def auth_app(self):
        return AuthMiddleware(_ok_app, auth_key="test-secret-key-123")

    def test_missing_auth_returns_401(self, auth_app):
        scope = _make_scope(headers={})
        send = ResponseCapture()
        asyncio.run(auth_app(scope, _noop_receive, send))
        assert send.status == 401
        assert "unauthorized" in send.body_json["error"]

    def test_wrong_token_returns_401(self, auth_app):
        scope = _make_scope(headers={
            b"authorization": b"Bearer wrong-key",
        })
        send = ResponseCapture()
        asyncio.run(auth_app(scope, _noop_receive, send))
        assert send.status == 401
        assert "Invalid" in send.body_json["message"]

    def test_valid_token_passes_through(self, auth_app):
        scope = _make_scope(headers={
            b"authorization": b"Bearer test-secret-key-123",
        })
        send = ResponseCapture()
        asyncio.run(auth_app(scope, _noop_receive, send))
        assert send.status == 200
        assert send.body_json == {"ok": True}

    def test_health_endpoint_bypasses_auth(self, auth_app):
        """GET /health should work without any auth header."""
        scope = _make_scope(path="/health", method="GET", headers={})
        send = ResponseCapture()
        asyncio.run(auth_app(scope, _noop_receive, send))
        assert send.status == 200

    def test_bearer_prefix_required(self, auth_app):
        """'Basic' auth scheme should be rejected."""
        scope = _make_scope(headers={
            b"authorization": b"Basic dGVzdDp0ZXN0",
        })
        send = ResponseCapture()
        asyncio.run(auth_app(scope, _noop_receive, send))
        assert send.status == 401

    def test_empty_bearer_token_rejected(self, auth_app):
        scope = _make_scope(headers={
            b"authorization": b"Bearer ",
        })
        send = ResponseCapture()
        asyncio.run(auth_app(scope, _noop_receive, send))
        assert send.status == 401

    def test_non_http_scope_passes_through(self, auth_app):
        """Websocket and lifespan scopes should not be auth-checked."""
        scope = {"type": "lifespan"}
        send = ResponseCapture()
        # Should call inner app without auth check
        calls = []
        async def mock_app(s, r, se):
            calls.append(s)
        auth_with_mock = AuthMiddleware(mock_app, auth_key="key")
        asyncio.run(auth_with_mock(scope, _noop_receive, send))
        assert len(calls) == 1

    def test_timing_safe_comparison(self, auth_app):
        """Auth should use hmac.compare_digest (timing-safe)."""
        import hmac as _hmac
        with patch.object(_hmac, 'compare_digest', return_value=True) as mock_cmp:
            scope = _make_scope(headers={
                b"authorization": b"Bearer any-token",
            })
            send = ResponseCapture()
            asyncio.run(auth_app(scope, _noop_receive, send))
            mock_cmp.assert_called_once_with("any-token", "test-secret-key-123")


# ── TestRateLimitMiddleware ───────────────────────────────────────

class TestRateLimitMiddleware:
    """Per-IP sliding-window rate limiting."""

    @pytest.fixture
    def rl_app(self):
        return RateLimitMiddleware(_ok_app, rpm=5)

    def test_under_limit_passes(self, rl_app):
        for _ in range(5):
            scope = _make_scope(client=("10.0.0.1", 1234))
            send = ResponseCapture()
            asyncio.run(rl_app(scope, _noop_receive, send))
            assert send.status == 200

    def test_over_limit_returns_429(self, rl_app):
        # Use up the quota
        for _ in range(5):
            scope = _make_scope(client=("10.0.0.2", 1234))
            send = ResponseCapture()
            asyncio.run(rl_app(scope, _noop_receive, send))

        # 6th request should be rejected
        scope = _make_scope(client=("10.0.0.2", 1234))
        send = ResponseCapture()
        asyncio.run(rl_app(scope, _noop_receive, send))
        assert send.status == 429
        assert "rate_limited" in send.body_json["error"]
        assert b"retry-after" in send.headers_dict

    def test_different_ips_independent(self, rl_app):
        """Rate limit per IP — different IPs don't share quota."""
        # Fill IP-A quota
        for _ in range(5):
            scope = _make_scope(client=("10.0.0.3", 1234))
            send = ResponseCapture()
            asyncio.run(rl_app(scope, _noop_receive, send))

        # IP-B should still have full quota
        scope = _make_scope(client=("10.0.0.4", 1234))
        send = ResponseCapture()
        asyncio.run(rl_app(scope, _noop_receive, send))
        assert send.status == 200

    def test_health_endpoint_not_rate_limited(self, rl_app):
        """GET /health should never be rate-limited."""
        # Fill quota
        for _ in range(5):
            scope = _make_scope(client=("10.0.0.5", 1234))
            send = ResponseCapture()
            asyncio.run(rl_app(scope, _noop_receive, send))

        # /health should still work
        scope = _make_scope(path="/health", method="GET", client=("10.0.0.5", 1234))
        send = ResponseCapture()
        asyncio.run(rl_app(scope, _noop_receive, send))
        assert send.status == 200

    def test_sliding_window_resets(self, rl_app):
        """After 60s window passes, quota resets."""
        # Fill quota
        for _ in range(5):
            scope = _make_scope(client=("10.0.0.6", 1234))
            send = ResponseCapture()
            asyncio.run(rl_app(scope, _noop_receive, send))

        # Simulate time passing by manipulating internal state
        with rl_app._lock:
            rl_app._window["10.0.0.6"] = [time.monotonic() - 120.0]

        # Should pass now (old entries expired)
        scope = _make_scope(client=("10.0.0.6", 1234))
        send = ResponseCapture()
        asyncio.run(rl_app(scope, _noop_receive, send))
        assert send.status == 200

    def test_reset_clears_all_state(self, rl_app):
        """reset() clears all rate limit state."""
        # Fill quota
        for _ in range(5):
            scope = _make_scope(client=("10.0.0.7", 1234))
            send = ResponseCapture()
            asyncio.run(rl_app(scope, _noop_receive, send))

        rl_app.reset()

        # Should pass again
        scope = _make_scope(client=("10.0.0.7", 1234))
        send = ResponseCapture()
        asyncio.run(rl_app(scope, _noop_receive, send))
        assert send.status == 200

    def test_non_http_passthrough(self, rl_app):
        """Non-HTTP scopes bypass rate limiting."""
        calls = []
        async def mock_app(s, r, se):
            calls.append(True)
        rl = RateLimitMiddleware(mock_app, rpm=1)
        scope = {"type": "websocket"}
        asyncio.run(rl(scope, _noop_receive, ResponseCapture()))
        assert len(calls) == 1


# ── TestCORSMiddleware ────────────────────────────────────────────

class TestCORSMiddleware:
    """CORS header handling."""

    @pytest.fixture
    def cors_app(self):
        return CORSMiddleware(
            _ok_app,
            allowed_origins=["http://localhost:3000", "https://brain.company.com"],
        )

    def test_preflight_allowed_origin(self, cors_app):
        scope = _make_scope(
            method="OPTIONS",
            headers={b"origin": b"http://localhost:3000"},
        )
        send = ResponseCapture()
        asyncio.run(cors_app(scope, _noop_receive, send))
        assert send.status == 204
        headers = send.headers_dict
        assert b"access-control-allow-origin" in headers
        assert headers[b"access-control-allow-origin"] == b"http://localhost:3000"

    def test_preflight_disallowed_origin(self, cors_app):
        """Disallowed origin should pass through to the inner app (no CORS headers)."""
        scope = _make_scope(
            method="OPTIONS",
            headers={b"origin": b"http://evil.com"},
        )
        send = ResponseCapture()
        asyncio.run(cors_app(scope, _noop_receive, send))
        # Falls through to inner app (200 from _ok_app)
        assert send.status == 200

    def test_regular_request_gets_cors_headers(self, cors_app):
        scope = _make_scope(
            method="POST",
            headers={b"origin": b"https://brain.company.com"},
        )
        send = ResponseCapture()
        asyncio.run(cors_app(scope, _noop_receive, send))
        assert send.status == 200
        headers = send.headers_dict
        assert b"access-control-allow-origin" in headers

    def test_no_origin_header_no_cors(self, cors_app):
        """Requests without Origin header should not get CORS headers."""
        scope = _make_scope(method="POST", headers={})
        send = ResponseCapture()
        asyncio.run(cors_app(scope, _noop_receive, send))
        assert send.status == 200
        headers = send.headers_dict
        assert b"access-control-allow-origin" not in headers

    def test_allow_all_mode(self):
        cors = CORSMiddleware(_ok_app, allow_all=True)
        scope = _make_scope(
            method="OPTIONS",
            headers={b"origin": b"http://any-origin.com"},
        )
        send = ResponseCapture()
        asyncio.run(cors(scope, _noop_receive, send))
        assert send.status == 204


# ── TestHealthEndpoint ────────────────────────────────────────────

class TestHealthEndpoint:
    """Health check endpoint."""

    @pytest.fixture
    def health_app(self):
        return HealthEndpoint(_ok_app, version="0.44.1")

    def test_health_returns_200_json(self, health_app):
        scope = _make_scope(path="/health", method="GET")
        send = ResponseCapture()
        asyncio.run(health_app(scope, _noop_receive, send))
        assert send.status == 200
        body = send.body_json
        assert body["status"] == "ok"
        assert body["version"] == "0.44.1"
        assert body["transport"] == "streamable-http"

    def test_health_trailing_slash(self, health_app):
        scope = _make_scope(path="/health/", method="GET")
        send = ResponseCapture()
        asyncio.run(health_app(scope, _noop_receive, send))
        assert send.status == 200

    def test_non_health_passes_through(self, health_app):
        scope = _make_scope(path="/mcp", method="POST")
        send = ResponseCapture()
        asyncio.run(health_app(scope, _noop_receive, send))
        assert send.status == 200
        assert send.body_json == {"ok": True}

    def test_non_http_passes_through(self, health_app):
        calls = []
        async def mock_app(s, r, se):
            calls.append(True)
        he = HealthEndpoint(mock_app)
        scope = {"type": "lifespan"}
        asyncio.run(he(scope, _noop_receive, ResponseCapture()))
        assert len(calls) == 1


# ── TestHTTPBrainServer ───────────────────────────────────────────

class TestHTTPBrainServer:
    """HTTPBrainServer integration tests."""

    @pytest.fixture
    def mock_brain_server(self):
        """A mock BrainServer that returns a mock FastMCP."""
        srv = MagicMock()
        mock_mcp = MagicMock()
        # streamable_http_app returns a dummy ASGI app
        mock_mcp.streamable_http_app.return_value = _ok_app
        mock_mcp.sse_app.return_value = _ok_app
        srv.create_mcp_server.return_value = mock_mcp
        return srv

    def test_create_app_with_auth(self, mock_brain_server):
        http = HTTPBrainServer(
            mock_brain_server,
            auth_key="my-key",
            port=3000,
        )
        app = http.create_app()
        assert app is not None

        # Unauthenticated request should fail
        scope = _make_scope(headers={})
        send = ResponseCapture()
        asyncio.run(app(scope, _noop_receive, send))
        assert send.status == 401

    def test_create_app_without_auth(self, mock_brain_server):
        http = HTTPBrainServer(mock_brain_server, port=3001)
        app = http.create_app()

        # Should pass through without auth
        scope = _make_scope(headers={})
        send = ResponseCapture()
        asyncio.run(app(scope, _noop_receive, send))
        assert send.status == 200

    def test_health_bypasses_all_middleware(self, mock_brain_server):
        http = HTTPBrainServer(
            mock_brain_server,
            auth_key="secret",
            rate_limit_rpm=1,
            port=3002,
        )
        app = http.create_app()

        # /health should work without auth and not be rate-limited
        for _ in range(5):
            scope = _make_scope(path="/health", method="GET", headers={})
            send = ResponseCapture()
            asyncio.run(app(scope, _noop_receive, send))
            assert send.status == 200

    def test_rate_limit_in_stack(self, mock_brain_server):
        http = HTTPBrainServer(
            mock_brain_server,
            rate_limit_rpm=2,
            port=3003,
        )
        app = http.create_app()

        # 2 requests OK
        for _ in range(2):
            scope = _make_scope(client=("10.0.0.99", 1234))
            send = ResponseCapture()
            asyncio.run(app(scope, _noop_receive, send))
            assert send.status == 200

        # 3rd should be 429
        scope = _make_scope(client=("10.0.0.99", 1234))
        send = ResponseCapture()
        asyncio.run(app(scope, _noop_receive, send))
        assert send.status == 429

    def test_cors_in_stack(self, mock_brain_server):
        http = HTTPBrainServer(
            mock_brain_server,
            allowed_origins=["http://localhost:8080"],
            port=3004,
        )
        app = http.create_app()

        scope = _make_scope(
            method="OPTIONS",
            headers={b"origin": b"http://localhost:8080"},
        )
        send = ResponseCapture()
        asyncio.run(app(scope, _noop_receive, send))
        assert send.status == 204

    def test_sse_transport(self, mock_brain_server):
        http = HTTPBrainServer(
            mock_brain_server,
            transport="sse",
            port=3005,
        )
        app = http.create_app()
        mock_brain_server.create_mcp_server.return_value.sse_app.assert_called()

    def test_create_app_is_idempotent(self, mock_brain_server):
        http = HTTPBrainServer(mock_brain_server, port=3006)
        app1 = http.create_app()
        app2 = http.create_app()
        assert app1 is app2

    def test_properties(self, mock_brain_server):
        http = HTTPBrainServer(
            mock_brain_server,
            bind="0.0.0.0",
            port=3007,
        )
        assert http.bind == "0.0.0.0"
        assert http.port == 3007

    def test_auth_plus_cors_plus_rate_limit(self, mock_brain_server):
        """Full middleware stack: CORS + Auth + RateLimit."""
        http = HTTPBrainServer(
            mock_brain_server,
            auth_key="full-stack-key",
            rate_limit_rpm=100,
            allowed_origins=["http://app.example.com"],
            port=3008,
        )
        app = http.create_app()

        # Authenticated request with CORS origin
        scope = _make_scope(
            method="POST",
            headers={
                b"authorization": b"Bearer full-stack-key",
                b"origin": b"http://app.example.com",
            },
        )
        send = ResponseCapture()
        asyncio.run(app(scope, _noop_receive, send))
        assert send.status == 200
        # Should have CORS header
        headers = send.headers_dict
        assert b"access-control-allow-origin" in headers


# ── TestMiddlewareStackOrder ──────────────────────────────────────

class TestMiddlewareStackOrder:
    """Verify the correct middleware ordering in the stack."""

    def test_auth_before_rate_limit(self):
        """Auth rejection should NOT consume rate limit quota."""
        call_count = 0

        async def counting_app(scope, receive, send):
            nonlocal call_count
            call_count += 1
            await _ok_app(scope, receive, send)

        # Build stack: RateLimit → Auth → app
        app = counting_app
        app = RateLimitMiddleware(app, rpm=2)
        app = AuthMiddleware(app, auth_key="secret")

        # Send 5 unauthenticated requests
        for _ in range(5):
            scope = _make_scope(headers={}, client=("10.0.0.50", 1234))
            send = ResponseCapture()
            asyncio.run(app(scope, _noop_receive, send))
            assert send.status == 401

        # But since auth rejects BEFORE rate limit, the inner app was never called
        assert call_count == 0

    def test_health_bypasses_auth_and_ratelimit(self):
        """Health endpoint should work even when auth is set and rate limit is exhausted."""
        # Stack: Health → CORS → Auth → RateLimit → app
        app = _ok_app
        app = RateLimitMiddleware(app, rpm=1)
        app = AuthMiddleware(app, auth_key="secret")
        app = HealthEndpoint(app, version="test")

        # Exhaust rate limit (won't actually work because auth blocks, but
        # the point is: health should ALWAYS work)
        for _ in range(10):
            scope = _make_scope(path="/health", method="GET",
                                headers={}, client=("10.0.0.51", 1234))
            send = ResponseCapture()
            asyncio.run(app(scope, _noop_receive, send))
            assert send.status == 200
            assert send.body_json["status"] == "ok"


# ── TestCreateHTTPServerFactory ───────────────────────────────────

class TestCreateHTTPServerFactory:
    """Test the create_http_server() factory in mcp_server.py."""

    def test_factory_returns_http_brain_server(self, tmp_path):
        """create_http_server() should return an HTTPBrainServer instance."""
        brain_dir = tmp_path / ".brain"
        brain_dir.mkdir()
        (brain_dir / "brain.db").touch()

        # We need a real brain dir for BrainServer init
        # But BrainServer validates workdir, so we need a proper setup
        # Use mock to avoid full brain initialization
        with patch("project_brain.interfaces.mcp_server.BrainServer") as MockBS:
            mock_srv = MagicMock()
            MockBS.return_value = mock_srv
            from project_brain.interfaces.mcp_server import create_http_server
            http = create_http_server(
                str(tmp_path),
                bind="127.0.0.1",
                port=4000,
                auth_key="test-key",
            )
            assert isinstance(http, HTTPBrainServer)
            assert http.port == 4000
            assert http.bind == "127.0.0.1"
            MockBS.assert_called_once_with(str(tmp_path))
