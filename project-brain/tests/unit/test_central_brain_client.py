"""
tests/unit/test_central_brain_client.py — E-03 CentralBrainClient 測試

覆蓋：
  - ping success / failure
  - search_knowledge returns results / empty
  - get_context returns string
  - connection error graceful degradation
  - SSE response parsing
"""
from __future__ import annotations

import json
import unittest
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

from project_brain.integrations.central_brain_client import CentralBrainClient


class _MockMCPHandler(BaseHTTPRequestHandler):
    """Mock MCP server for testing."""

    def log_message(self, fmt, *args):
        pass  # suppress request logs in test output

    def do_GET(self):
        if self.path in ("/health", "/health/"):
            self._json(200, {"status": "ok", "version": "0.49.0", "mode": "central"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/mcp":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            method = body.get("method", "")

            if method == "initialize":
                self._json(200, {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "test-brain", "version": "0.49.0"},
                    },
                })
            elif method == "notifications/initialized":
                self._json(200, {})
            elif method == "tools/call":
                tool_name = body.get("params", {}).get("name", "")
                arguments = body.get("params", {}).get("arguments", {})
                self._handle_tool_call(body.get("id"), tool_name, arguments)
            else:
                self._json(200, {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {},
                })
        else:
            self._json(404, {"error": "not found"})

    def _handle_tool_call(self, req_id, tool_name, arguments):
        if tool_name == "search_knowledge":
            results = [
                {"title": "Central Rule 1", "content": "Central content", "type": "Rule",
                 "similarity": 0.9, "tags": [], "source": "central"},
                {"title": "Central Pitfall 1", "content": "Central pitfall", "type": "Pitfall",
                 "similarity": 0.8, "tags": [], "source": "central"},
            ]
            self._json(200, {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(results)}],
                },
            })
        elif tool_name == "get_context":
            ctx = "## Central Knowledge\n- Rule: Central JWT rule\n- Pitfall: Central auth issue"
            self._json(200, {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": ctx}],
                },
            })
        else:
            self._json(200, {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": []},
            })

    def _json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_mock_server():
    """Start a mock MCP server on a random port."""
    server = HTTPServer(("127.0.0.1", 0), _MockMCPHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


class TestPing(unittest.TestCase):

    def test_ping_success(self):
        server, port = _start_mock_server()
        try:
            client = CentralBrainClient(f"http://127.0.0.1:{port}")
            self.assertTrue(client.ping())
        finally:
            server.shutdown()

    def test_ping_unreachable(self):
        client = CentralBrainClient("http://127.0.0.1:1", timeout=1)
        self.assertFalse(client.ping())


class TestSearchKnowledge(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = _start_mock_server()
        cls.client = CentralBrainClient(f"http://127.0.0.1:{cls.port}")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_search_returns_results(self):
        results = self.client.search_knowledge("JWT", top_k=5)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["title"], "Central Rule 1")

    def test_search_result_has_expected_fields(self):
        results = self.client.search_knowledge("JWT")
        for r in results:
            self.assertIn("title", r)
            self.assertIn("content", r)
            self.assertIn("type", r)


class TestGetContext(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = _start_mock_server()
        cls.client = CentralBrainClient(f"http://127.0.0.1:{cls.port}")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_get_context_returns_string(self):
        ctx = self.client.get_context("修復 JWT bug")
        self.assertIsInstance(ctx, str)
        self.assertIn("Central", ctx)

    def test_get_context_non_empty(self):
        ctx = self.client.get_context("any task")
        self.assertTrue(len(ctx) > 0)


class TestGracefulDegradation(unittest.TestCase):

    def test_search_on_unreachable_returns_empty(self):
        client = CentralBrainClient("http://127.0.0.1:1", timeout=1)
        results = client.search_knowledge("test")
        self.assertEqual(results, [])

    def test_get_context_on_unreachable_returns_empty(self):
        client = CentralBrainClient("http://127.0.0.1:1", timeout=1)
        ctx = client.get_context("test")
        self.assertEqual(ctx, "")


class TestSSEParsing(unittest.TestCase):

    def test_parse_sse_extracts_json(self):
        raw = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"content":[]}}\n\n'
        result = CentralBrainClient._parse_sse(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], 1)

    def test_parse_sse_empty_returns_none(self):
        result = CentralBrainClient._parse_sse("")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
