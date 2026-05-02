"""
project_brain/integrations/central_brain_client.py — E-03: Central Brain HTTP Client

Lightweight HTTP client for querying a remote Central Brain via its MCP HTTP endpoint.
Uses only stdlib (urllib.request) — no external dependencies.

The client communicates using MCP JSON-RPC over HTTP (streamable-http transport).
It wraps the ``tools/call`` JSON-RPC method to invoke ``search_knowledge`` and
``get_context`` on the remote server.

Usage::

    from project_brain.integrations.central_brain_client import CentralBrainClient

    client = CentralBrainClient(
        url="http://brain.company.internal:3000",
        api_key="brn_c_xxxxxxxx",
    )
    if client.ping():
        results = client.search_knowledge("JWT 驗證規範", top_k=5)
        context = client.get_context("修復 JWT 過期驗證 bug")
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10  # seconds


class CentralBrainClient:
    """HTTP client for querying a remote Central Brain MCP server.

    All methods are fault-tolerant: network errors, timeouts, and malformed
    responses are caught and logged, returning empty results instead of raising.
    This ensures the local brain experience is never degraded by central brain
    availability issues.
    """

    def __init__(self, url: str, api_key: str = "", timeout: int = _DEFAULT_TIMEOUT) -> None:
        self._base_url = url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._session_id: str | None = None
        self._request_id = 0

    # ── Public API ──────────────────────────────────────────────

    def ping(self) -> bool:
        """Check if the central brain server is reachable.

        Calls GET /health (no auth required).
        """
        try:
            req = urllib.request.Request(f"{self._base_url}/health")
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read())
                return data.get("status") == "ok"
        except Exception as e:
            logger.debug("CentralBrainClient.ping failed: %s", e)
            return False

    def search_knowledge(self, query: str, top_k: int = 5,
                         kind: str = "") -> list[dict]:
        """Search the central brain's knowledge base.

        Returns a list of node dicts (title, content, type, similarity, tags, source).
        Returns empty list on any error.
        """
        result = self._call_tool("search_knowledge", {
            "query": query,
            "top_k": top_k,
            "kind": kind,
        })
        if isinstance(result, list):
            return result
        return []

    def get_context(self, task: str, current_file: str = "") -> str:
        """Get AI context from the central brain.

        Returns a markdown-formatted context string.
        Returns empty string on any error.
        """
        result = self._call_tool("get_context", {
            "task": task,
            "current_file": current_file,
            "detail_level": "full",
        })
        if isinstance(result, str):
            return result
        # Some MCP implementations return content as a list of text blocks
        if isinstance(result, list):
            parts = []
            for item in result:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(parts)
        return ""

    def add_knowledge(
        self,
        title: str,
        content: str,
        kind: str = "Note",
        confidence: float = 0.8,
        tags: list[str] | None = None,
        source: str = "",
    ) -> dict:
        """Push a knowledge node to the central brain via add_knowledge MCP tool.

        Returns the tool response dict (typically {"node_id": "...", "success": true})
        or an empty dict on error.
        """
        result = self._call_tool("add_knowledge", {
            "title": title,
            "content": content,
            "kind": kind,
            "confidence": confidence,
            "tags": tags or [],
            "source": source,
        })
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            try:
                import json as _json
                return _json.loads(result)
            except (ValueError, TypeError):
                return {"success": True, "raw": result}
        return {}

    # ── MCP JSON-RPC transport ──────────────────────────────────

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the central brain via MCP JSON-RPC.

        MCP streamable-http protocol:
          POST /mcp with JSON-RPC body
          The server may require an initialize handshake first.
        """
        # Step 1: ensure session is initialized
        if self._session_id is None:
            if not self._initialize_session():
                return None

        # Step 2: call tools/call
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
            "id": self._next_id(),
        }
        resp = self._post_mcp(payload)
        if resp is None:
            return None

        # Parse result — MCP tools/call returns {result: {content: [...]}}
        result = resp.get("result", {})
        content = result.get("content", [])
        if not content:
            return result

        # Extract text from content blocks
        if len(content) == 1 and isinstance(content[0], dict):
            text = content[0].get("text", "")
            # Try to parse as JSON (search_knowledge returns JSON list)
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text

        # Multiple content blocks
        texts = []
        for block in content:
            if isinstance(block, dict):
                texts.append(block.get("text", ""))
        return "\n".join(texts) if texts else None

    def _initialize_session(self) -> bool:
        """MCP streamable-http session initialization handshake."""
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "project-brain-client",
                    "version": "0.50.0",
                },
            },
            "id": self._next_id(),
        }
        resp = self._post_mcp(payload)
        if resp is None:
            return False

        # Send initialized notification
        notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        self._post_mcp(notif, expect_response=False)
        self._session_id = "active"
        return True

    def _post_mcp(self, payload: dict, *,
                  expect_response: bool = True) -> dict | None:
        """Send a JSON-RPC request to the MCP endpoint."""
        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self._base_url}/mcp",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                method="POST",
            )
            if self._api_key:
                req.add_header("Authorization", f"Bearer {self._api_key}")
            if self._session_id and self._session_id != "active":
                req.add_header("Mcp-Session-Id", self._session_id)

            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                # Check for session ID in response headers
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid

                if not expect_response:
                    return {}

                raw = resp.read().decode("utf-8")
                # streamable-http may return SSE or JSON
                if raw.startswith("event:") or raw.startswith("data:"):
                    return self._parse_sse(raw)
                return json.loads(raw)

        except urllib.error.HTTPError as e:
            logger.warning("CentralBrainClient HTTP %d: %s", e.code, e.reason)
            return None
        except Exception as e:
            logger.debug("CentralBrainClient request failed: %s", e)
            # Reset session on error (may need re-init)
            self._session_id = None
            return None

    @staticmethod
    def _parse_sse(raw: str) -> dict | None:
        """Parse a simple SSE response to extract the JSON-RPC result."""
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                data = line[5:].strip()
                if data:
                    try:
                        return json.loads(data)
                    except json.JSONDecodeError:
                        continue
        return None
