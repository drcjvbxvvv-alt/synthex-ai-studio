"""
project_brain/interfaces/http_transport.py — E-01 HTTP MCP Transport

讓遠端 Claude Code / Cursor 透過 HTTP 連接 Project Brain MCP Server。

架構：
  Request → CORS → AuthMiddleware → RateLimitMiddleware → FastMCP Starlette App

安全設計：
  - Bearer token 認證（hmac.compare_digest 防 timing attack）
  - /health 端點不需認證（供負載均衡 + 監控）
  - 每 IP 滑動視窗 Rate Limiting（in-memory，多實例需換 Redis backend）
  - CORS 白名單控制

使用方式：
  brain serve --mcp --auth-key $BRAIN_API_KEY --port 3000
  brain serve --mcp --auth-key $BRAIN_API_KEY --bind 0.0.0.0 --port 3000
"""

from __future__ import annotations

import hmac
import json
import logging
import time
import threading
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


# ── Auth Middleware ────────────────────────────────────────────────

class AuthMiddleware:
    """Starlette ASGI middleware for Bearer token authentication.

    Validates ``Authorization: Bearer <key>`` header against a known API key
    using timing-safe comparison.  The ``/health`` endpoint is exempt.
    """

    # Paths that bypass authentication
    EXEMPT_PATHS = frozenset({"/health", "/health/"})

    def __init__(self, app: Any, auth_key: str) -> None:
        self.app = app
        self._auth_key = auth_key

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        # Extract Bearer token from headers
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")

        if not auth_header.startswith("Bearer "):
            await self._send_json_response(send, 401, {
                "error": "unauthorized",
                "message": "Missing or invalid Authorization header. Use: Bearer <api-key>",
            })
            return

        token = auth_header[7:]  # strip "Bearer "
        if not hmac.compare_digest(token, self._auth_key):
            await self._send_json_response(send, 401, {
                "error": "unauthorized",
                "message": "Invalid API key",
            })
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _send_json_response(send: Any, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(payload)).encode()],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": payload,
        })


# ── Rate Limit Middleware ─────────────────────────────────────────

class RateLimitMiddleware:
    """Per-IP sliding-window rate limiter (ASGI middleware).

    In-memory implementation — suitable for single-instance deployment.
    For multi-instance (E-02 Central Brain), replace with Redis backend
    via the ``RateLimitBackend`` protocol.

    Exempt paths (e.g. /health) are not rate-limited.
    """

    EXEMPT_PATHS = frozenset({"/health", "/health/"})

    def __init__(self, app: Any, rpm: int = 60) -> None:
        self.app = app
        self._rpm = rpm
        self._window: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        client_ip = self._extract_ip(scope)
        if not self._allow(client_ip):
            payload = json.dumps({
                "error": "rate_limited",
                "message": f"Rate limit exceeded: {self._rpm} requests/minute",
            }).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(payload)).encode()],
                    [b"retry-after", b"60"],
                ],
            })
            await send({"type": "http.response.body", "body": payload})
            return

        await self.app(scope, receive, send)

    def _allow(self, client_ip: str) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        with self._lock:
            times = self._window[client_ip]
            times[:] = [t for t in times if t > cutoff]
            if len(times) >= self._rpm:
                return False
            times.append(now)
            return True

    @staticmethod
    def _extract_ip(scope: dict) -> str:
        client = scope.get("client")
        if client:
            return client[0]
        return "unknown"

    def reset(self) -> None:
        """Clear all rate limit state (for testing)."""
        with self._lock:
            self._window.clear()


# ── Health Endpoint ───────────────────────────────────────────────

class HealthEndpoint:
    """ASGI app that handles /health requests and delegates everything else.

    Returns a simple JSON health check response for GET /health.
    All other requests pass through to the wrapped app.
    """

    def __init__(self, app: Any, version: str = "0.0.0") -> None:
        self.app = app
        self._version = version

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope.get("path") in ("/health", "/health/"):
            method = scope.get("method", "GET")
            if method == "GET":
                payload = json.dumps({
                    "status": "ok",
                    "version": self._version,
                    "transport": "streamable-http",
                }).encode("utf-8")
                await send({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        [b"content-type", b"application/json"],
                        [b"content-length", str(len(payload)).encode()],
                    ],
                })
                await send({"type": "http.response.body", "body": payload})
                return

        await self.app(scope, receive, send)


# ── CORS Middleware ───────────────────────────────────────────────

class CORSMiddleware:
    """Lightweight CORS middleware for ASGI.

    Handles preflight OPTIONS requests and adds Access-Control headers.
    """

    def __init__(
        self,
        app: Any,
        allowed_origins: list[str] | None = None,
        allow_all: bool = False,
    ) -> None:
        self.app = app
        self._allow_all = allow_all
        self._origins = set(allowed_origins or [])

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers_dict = dict(scope.get("headers", []))
        origin = headers_dict.get(b"origin", b"").decode("utf-8", errors="ignore")

        # Preflight
        if scope.get("method") == "OPTIONS" and origin:
            cors_headers = self._cors_headers(origin)
            if cors_headers is not None:
                await send({
                    "type": "http.response.start",
                    "status": 204,
                    "headers": cors_headers,
                })
                await send({"type": "http.response.body", "body": b""})
                return

        # Regular request — inject CORS headers into response
        if origin and self._is_allowed(origin):
            original_send = send

            async def send_with_cors(message: dict) -> None:
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append([b"access-control-allow-origin", origin.encode()])
                    headers.append([b"access-control-allow-credentials", b"true"])
                    message = {**message, "headers": headers}
                await original_send(message)

            await self.app(scope, receive, send_with_cors)
        else:
            await self.app(scope, receive, send)

    def _is_allowed(self, origin: str) -> bool:
        if self._allow_all:
            return True
        return origin in self._origins

    def _cors_headers(self, origin: str) -> list[list[bytes]] | None:
        if not self._is_allowed(origin):
            return None
        return [
            [b"access-control-allow-origin", origin.encode()],
            [b"access-control-allow-methods", b"GET, POST, PUT, DELETE, OPTIONS"],
            [b"access-control-allow-headers", b"Authorization, Content-Type"],
            [b"access-control-max-age", b"86400"],
            [b"access-control-allow-credentials", b"true"],
        ]


# ── HTTPBrainServer ───────────────────────────────────────────────

class HTTPBrainServer:
    """Wraps a BrainServer's FastMCP with HTTP transport + auth + rate limiting.

    Usage::

        from project_brain.interfaces.mcp_server import BrainServer
        srv = BrainServer("/path/to/project")
        http = HTTPBrainServer(
            brain_server=srv,
            bind="0.0.0.0",
            port=3000,
            auth_key="my-secret-key",
        )
        http.run()   # blocking — starts uvicorn

    For testing, use ``http.create_app()`` to get the ASGI app without
    starting uvicorn.
    """

    def __init__(
        self,
        brain_server: Any,
        *,
        bind: str = "127.0.0.1",
        port: int = 3000,
        auth_key: str | None = None,
        rate_limit_rpm: int = 60,
        allowed_origins: list[str] | None = None,
        transport: str = "streamable-http",
    ) -> None:
        self._srv = brain_server
        self._bind = bind
        self._port = port
        self._auth_key = auth_key
        self._rate_limit_rpm = rate_limit_rpm
        self._allowed_origins = allowed_origins
        self._transport = transport
        self._app: Any = None

    @property
    def bind(self) -> str:
        return self._bind

    @property
    def port(self) -> int:
        return self._port

    def create_app(self) -> Any:
        """Build the ASGI application with middleware stack.

        Middleware order (outermost first):
          1. HealthEndpoint — /health bypass (no auth needed)
          2. CORS — cross-origin headers
          3. Auth — Bearer token validation
          4. RateLimit — per-IP sliding window
          5. FastMCP Starlette app — actual MCP protocol handling

        Returns the ASGI app (Starlette-compatible).
        """
        if self._app is not None:
            return self._app

        # Get version from pyproject.toml
        version = _get_version()

        # Build the FastMCP server and get its Starlette app
        mcp = self._srv.create_mcp_server()
        if self._transport == "sse":
            base_app = mcp.sse_app()
        else:
            base_app = mcp.streamable_http_app()

        # Build middleware stack (innermost first, outermost wraps)
        app = base_app

        # 4. Rate limiting (innermost)
        app = RateLimitMiddleware(app, rpm=self._rate_limit_rpm)
        self._rate_limiter = app

        # 3. Auth (requires key if configured)
        if self._auth_key:
            app = AuthMiddleware(app, auth_key=self._auth_key)

        # 2. CORS
        if self._allowed_origins:
            app = CORSMiddleware(app, allowed_origins=self._allowed_origins)

        # 1. Health endpoint (outermost — accessible without auth)
        app = HealthEndpoint(app, version=version)

        self._app = app
        return app

    def run(self) -> None:
        """Start the HTTP MCP server (blocking).

        Uses uvicorn as the ASGI server. For production deployment,
        consider running behind nginx/caddy as TLS termination proxy.
        """
        import uvicorn

        app = self.create_app()

        logger.warning(
            "E-01: HTTP MCP Server starting on %s:%d (transport=%s, auth=%s)",
            self._bind, self._port, self._transport,
            "enabled" if self._auth_key else "disabled",
        )

        config = uvicorn.Config(
            app,
            host=self._bind,
            port=self._port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        server.run()


def _get_version() -> str:
    """Read version from pyproject.toml (best-effort)."""
    try:
        from pathlib import Path
        pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
        if pyproject.exists():
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib  # type: ignore[no-redef]
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            return data.get("project", {}).get("version", "0.0.0")
    except Exception:
        pass
    return "0.0.0"
