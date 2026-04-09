"""
project_brain/api_server.py — Project Brain REST API Server

純 Python http.server 實作，無 Flask 依賴。

端點：
  GET  /health
  GET  /v1/stats
  GET  /v1/knowledge
  GET  /v1/knowledge/deprecated
  POST /v1/knowledge/<id>/outcome
  GET,POST /v1/context
  POST /v1/messages
  POST /v1/add
  GET  /v1/session
  POST /v1/session
  GET  /v1/session/<key>
  PUT  /v1/session/<key>
  DELETE /v1/session/<key>
  GET,POST /v1/session/search
  POST /v1/session/clear
  GET  /v1/traces
  POST /v1/traces/clear
  GET  /v1/traces/stats
  GET  /v1/nudges
  GET  /v1/nudges/stream    ← SSE
  GET  /v1/events
  POST /webhook/slack
  POST /webhook/github
  GET  /v1/metrics
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import sqlite3
import time
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_VERSION = "1.0.0"


# ─────────────────────────────────────────────────────────────
# Lazy singletons (per-workdir)
# ─────────────────────────────────────────────────────────────
_graph_cache: dict[str, Any] = {}
_store_cache: dict[str, Any] = {}
_tdb_cache:   dict[str, Any] = {}
_cache_lock = threading.Lock()


def _graph(workdir: str):
    with _cache_lock:
        if workdir not in _graph_cache:
            from project_brain.graph import KnowledgeGraph
            _graph_cache[workdir] = KnowledgeGraph(Path(workdir) / ".brain")
    return _graph_cache[workdir]


def _store(workdir: str):
    with _cache_lock:
        if workdir not in _store_cache:
            from project_brain.session_store import SessionStore
            _store_cache[workdir] = SessionStore(
                brain_dir=Path(workdir) / ".brain", session_id="api-server"
            )
    return _store_cache[workdir]


def _tdb(workdir: str):
    """Traces SQLite connection (WAL, thread-safe)."""
    with _cache_lock:
        if workdir not in _tdb_cache:
            p = Path(workdir) / ".brain" / "traces.db"
            c = sqlite3.connect(str(p), check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=3000")
            c.executescript("""
                CREATE TABLE IF NOT EXISTS query_traces (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          TEXT NOT NULL DEFAULT (datetime('now')),
                    query       TEXT NOT NULL DEFAULT '',
                    total_ms    INTEGER NOT NULL DEFAULT 0,
                    injected    INTEGER NOT NULL DEFAULT 0,
                    traces_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_qt_ts ON query_traces(ts DESC);
            """)
            c.commit()
            _tdb_cache[workdir] = c
    return _tdb_cache[workdir]


# ─────────────────────────────────────────────────────────────
# HTTP Handler
# ─────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    workdir: str = ""
    api_key: str = ""
    readonly: bool = False

    def log_message(self, fmt, *args):
        pass  # suppress per-request noise

    # ── Response helpers ───────────────────────────────────
    def _json(self, data, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, text: str, status: int = 200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except Exception:
            return {}

    # ── Auth ───────────────────────────────────────────────
    def _authorized(self, path: str) -> bool:
        key = self.__class__.api_key
        if not key:
            return True
        if path in ("/health",):
            return True
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._json({"error": "未授權：需要 Authorization: Bearer <key>"}, 401)
            return False
        if not hmac.compare_digest(auth[7:].strip(), key):
            self._json({"error": "未授權：API Key 不正確"}, 401)
            return False
        return True

    # ── CORS preflight ─────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    # ── Routing ────────────────────────────────────────────
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path   = parsed.path
            qs     = urllib.parse.parse_qs(parsed.query)
            body   = self._read_body() if method in ("POST", "PUT") else {}

            if not self._authorized(path):
                return

            # VISION-04: readonly mode — block all write operations
            if self.__class__.readonly and method in ("POST", "PUT", "DELETE"):
                _WRITE_SAFE = {"/v1/context", "/v1/messages", "/v1/session/search"}
                if path not in _WRITE_SAFE:
                    self._json({"error": "readonly mode — write operations disabled"}, 403)
                    return

            wd = self.__class__.workdir

            # Static routes
            if path == "/health" and method == "GET":
                return self._health(wd)
            if path == "/v1/stats" and method == "GET":
                return self._stats(wd)
            if path == "/v1/knowledge" and method == "GET":
                return self._knowledge(wd)
            if path == "/v1/knowledge/deprecated" and method == "GET":
                return self._knowledge_deprecated(wd, qs)
            # DEEP-05: POST /v1/knowledge/<id>/outcome — feedback loop
            m = re.fullmatch(r"/v1/knowledge/([^/]+)/outcome", path)
            if m and method == "POST":
                return self._knowledge_outcome(wd, urllib.parse.unquote(m.group(1)), body)
            if path == "/v1/context" and method in ("GET", "POST"):
                return self._context(wd, qs, body)
            if path == "/v1/messages" and method == "POST":
                return self._messages(wd, body)
            if path == "/v1/add" and method == "POST":
                return self._add(wd, body)
            # Traces
            if path == "/v1/traces" and method == "GET":
                return self._traces(wd, qs)
            if path == "/v1/traces/clear" and method == "POST":
                return self._traces_clear(wd)
            if path == "/v1/traces/stats" and method == "GET":
                return self._traces_stats(wd)
            # Nudges
            if path == "/v1/nudges" and method == "GET":
                return self._nudges(wd, qs)
            if path == "/v1/nudges/stream" and method == "GET":
                return self._nudges_stream(wd, qs)
            # Events
            if path == "/v1/events" and method == "GET":
                return self._events(wd, qs)
            # Metrics
            if path == "/v1/metrics" and method == "GET":
                return self._metrics(wd)
            # Webhooks
            if path == "/webhook/slack" and method == "POST":
                return self._webhook_slack(wd, body)
            if path == "/webhook/github" and method == "POST":
                return self._webhook_github(wd, body)

            # Session routes (with path params)
            if path == "/v1/session/search" and method in ("GET", "POST"):
                return self._session_search(wd, qs, body)
            if path == "/v1/session/clear" and method == "POST":
                return self._session_clear(wd)
            if path == "/v1/session" and method == "GET":
                return self._session_list(wd, qs)
            if path == "/v1/session" and method == "POST":
                return self._session_set(wd, body)
            m = re.fullmatch(r"/v1/session/(.+)", path)
            if m:
                key = urllib.parse.unquote(m.group(1))
                if method == "GET":    return self._session_get(wd, key)
                if method == "PUT":    return self._session_update(wd, key, body)
                if method == "DELETE": return self._session_delete(wd, key)

            self._json({"error": "not found"}, 404)
        except Exception as exc:
            logger.exception("%s %s", method, self.path)
            self._json({"error": "內部錯誤，請稍後再試"}, 500)

    # ── /health ────────────────────────────────────────────
    def _health(self, wd: str):
        try:
            ss = _store(wd).stats()
            l3 = _graph(wd).stats().get("nodes", 0)
        except Exception:
            ss = {}; l3 = 0
        self._json({
            "status": "ok", "version": _VERSION,
            "workdir": Path(wd).name,
            "l3_nodes": l3,
            "l1a_entries": ss.get("total", 0),
            "l1a_session_id": ss.get("session_id", ""),
        })

    # ── /v1/stats ──────────────────────────────────────────
    def _stats(self, wd: str):
        s = _graph(wd).stats()
        self._json({
            "l3":  {"nodes": s.get("nodes", 0), "edges": s.get("edges", 0),
                    "by_type": s.get("by_type", {})},
            "l1a": _store(wd).stats(),
        })

    # ── /v1/metrics ────────────────────────────────────────
    def _metrics(self, wd: str):
        """OBS-01: Prometheus-compatible metrics endpoint"""
        try:
            from project_brain.brain_db import BrainDB
            g  = _graph(wd)
            db = BrainDB(Path(wd) / ".brain")

            stats   = g.stats()
            n_total = stats.get("nodes", 0)

            # Count deprecated nodes via query
            n_dep = 0
            try:
                n_dep = g._conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE is_deprecated=1"
                ).fetchone()[0]
            except Exception as _e:
                logger.debug("deprecated nodes count query failed", exc_info=True)

            # Count by type
            by_type = stats.get("by_type", {})

            # Count decay events from brain_db events table
            try:
                decay_count = db.conn.execute(
                    "SELECT COUNT(*) FROM events WHERE event_type='decay_applied'"
                ).fetchone()[0]
            except Exception:
                decay_count = 0

            # Count nudge triggers
            try:
                nudge_count = db.conn.execute(
                    "SELECT COUNT(*) FROM events WHERE event_type='nudge_triggered'"
                ).fetchone()[0]
            except Exception:
                nudge_count = 0

            # Count federation imports
            try:
                fed_count = db.conn.execute(
                    "SELECT COUNT(*) FROM federation_imports"
                ).fetchone()[0]
            except Exception:
                fed_count = 0

            lines = [
                "# HELP brain_nodes_total Total knowledge nodes in L3",
                "# TYPE brain_nodes_total gauge",
                f"brain_nodes_total {n_total}",
                "# HELP brain_deprecated_nodes_total Deprecated knowledge nodes",
                "# TYPE brain_deprecated_nodes_total gauge",
                f"brain_deprecated_nodes_total {n_dep}",
                "# HELP brain_decay_events_total Total decay events applied",
                "# TYPE brain_decay_events_total counter",
                f"brain_decay_events_total {decay_count}",
                "# HELP brain_nudge_events_total Total nudge trigger events",
                "# TYPE brain_nudge_events_total counter",
                f"brain_nudge_events_total {nudge_count}",
                "# HELP brain_federation_imports_total Total federation import events",
                "# TYPE brain_federation_imports_total counter",
                f"brain_federation_imports_total {fed_count}",
            ]
            # Per-type breakdown
            for node_type, count in by_type.items():
                safe_type = node_type.lower().replace(" ", "_")
                lines.append(f'brain_nodes_by_type{{type="{safe_type}"}} {count}')

            self._text("\n".join(lines) + "\n")
        except Exception as exc:
            logger.warning("metrics error: %s", exc)
            self._json({"error": "metrics unavailable"}, 500)

    # ── /v1/knowledge ──────────────────────────────────────
    def _knowledge(self, wd: str):
        distill = Path(wd) / ".brain" / "distilled" / "BRAIN_KNOWLEDGE.md"
        if distill.exists():
            return self._text(distill.read_text("utf-8"))
        try:
            g  = _graph(wd)
            rows = g._conn.execute(
                "SELECT id, type, title, content, confidence "
                "FROM nodes ORDER BY confidence DESC LIMIT 50"
            ).fetchall()
            self._json([dict(r) for r in rows])
        except Exception as exc:
            logger.warning("knowledge list: %s", exc)
            self._json({"error": "無法取得知識列表，請稍後再試", "nodes": []})

    # ── /v1/knowledge/deprecated ───────────────────────────
    def _knowledge_deprecated(self, wd: str, qs: dict):
        """ARCH-05: 列出已棄用節點"""
        try:
            from project_brain.brain_db import BrainDB
            limit = int((qs.get("limit") or [50])[0])
            db    = BrainDB(Path(wd) / ".brain")
            rows  = db.get_deprecated_nodes(limit=limit)
            self._json({"count": len(rows), "nodes": rows})
        except Exception as exc:
            logger.warning("knowledge/deprecated: %s", exc)
            self._json({"error": "無法取得已棄用節點列表", "nodes": []}, 500)

    # ── /v1/knowledge/<id>/outcome ─────────────────────────
    def _knowledge_outcome(self, wd: str, node_id: str, body: dict):
        """
        DEEP-05: POST /v1/knowledge/<id>/outcome
        Close the F6 feedback loop — record whether a node was useful.

        Body: {"was_useful": true|false, "notes": "optional reason"}
        Returns: {"ok": true, "node_id": "...", "confidence": 0.85, "delta": 0.03}
        """
        was_useful = body.get("was_useful")
        if was_useful is None:
            self._json({"error": "was_useful (bool) required"}, 400); return
        notes = str(body.get("notes", ""))[:500]
        try:
            from project_brain.brain_db import BrainDB
            from project_brain.graph import KnowledgeGraph
            bd  = Path(wd) / ".brain"
            db  = BrainDB(bd)
            g   = KnowledgeGraph(bd)
            delta    = 0.03 if was_useful else -0.05
            new_conf = db.record_feedback(node_id, helpful=bool(was_useful))
            if was_useful:
                try:
                    g.increment_adoption(node_id)
                except Exception as _e:
                    logger.debug("increment_adoption failed in api_server", exc_info=True)
            if notes and not was_useful:
                try:
                    db.conn.execute(
                        "UPDATE nodes SET content = content || ? WHERE id=?",
                        (f"\n\n[Feedback: {notes}]", node_id)
                    )
                    db.conn.commit()
                except Exception as _e:
                    logger.debug("feedback note append failed in api_server", exc_info=True)
            self._json({
                "ok": True, "node_id": node_id,
                "was_useful": bool(was_useful),
                "confidence": round(new_conf, 3),
                "delta": delta,
            })
        except Exception as exc:
            logger.warning("knowledge_outcome: %s", exc)
            self._json({"error": str(exc)}, 500)

    # ── /v1/context ────────────────────────────────────────
    def _context(self, wd: str, qs: dict, body: dict):
        task = (qs.get("q", [""])[0] or body.get("task", "")).strip()
        if not task:
            self._json({"error": "請提供 q 參數或 task 欄位"}, 400); return
        from project_brain.context import ContextEngineer
        ctx = ContextEngineer(_graph(wd), brain_dir=Path(wd) / ".brain").build(task) or ""
        l1a = _store(wd).search(task, limit=3)
        if l1a:
            ctx = "## ⚡ L1 工作記憶\n" + "\n".join(
                f"- [{e.category}] {e.value[:150]}" for e in l1a
            ) + "\n\n" + ctx
        self._json({"task": task, "context": ctx, "found": bool(ctx)})

    # ── /v1/messages ───────────────────────────────────────
    def _messages(self, wd: str, body: dict):
        messages = body.get("messages", [])
        task = next((m["content"] for m in messages if m.get("role") == "user"), "")
        ctx  = ""
        if task:
            from project_brain.context import ContextEngineer
            ctx = ContextEngineer(_graph(wd), brain_dir=Path(wd) / ".brain").build(task) or ""
            l1a = _store(wd).search(task, limit=3)
            if l1a:
                ctx = "## ⚡ L1 工作記憶\n" + "\n".join(
                    f"- [{e.category}] {e.value[:120]}" for e in l1a
                ) + "\n\n" + ctx
        if ctx:
            has_sys = any(m.get("role") == "system" for m in messages)
            if has_sys:
                enriched = [
                    {"role": "system", "content": ctx + "\n\n---\n\n" + m["content"]}
                    if m.get("role") == "system" else m
                    for m in messages
                ]
            else:
                enriched = [{"role": "system", "content": ctx}] + messages
        else:
            enriched = messages
        self._json({"messages": enriched, "knowledge_injected": bool(ctx),
                    "knowledge_chars": len(ctx)})

    # ── /v1/add ────────────────────────────────────────────
    def _add(self, wd: str, body: dict):
        title   = body.get("title", "").strip()
        content = body.get("content", "")
        kind    = body.get("kind", "Pitfall")
        tags    = body.get("tags", [])
        if not title:
            self._json({"error": "title 必填"}, 400); return
        node_id = _graph(wd).add_node(
            f"api-{os.urandom(4).hex()}", title, content, kind, tags
        )
        self._json({"node_id": node_id, "kind": kind, "title": title})

    # ── /v1/session ────────────────────────────────────────
    def _session_list(self, wd: str, qs: dict):
        from project_brain.session_store import CATEGORY_CONFIG
        cat   = qs.get("category", [None])[0]
        limit = min(int(qs.get("limit", ["50"])[0]), 200)
        ents  = _store(wd).list(category=cat, limit=limit)
        self._json({
            "entries":    [e.to_dict() for e in ents],
            "count":      len(ents),
            "session_id": _store(wd).session_id,
            "categories": list(CATEGORY_CONFIG.keys()),
        })

    def _session_set(self, wd: str, body: dict):
        key = body.get("key", "").strip()
        val = body.get("value", body.get("content", "")).strip()
        cat = body.get("category", "notes")
        ttl = body.get("ttl_days", None)
        if not key:
            self._json({"error": "key 必填"}, 400); return
        if not val:
            self._json({"error": "value 必填"}, 400); return
        entry = _store(wd).set(key=key, value=val, category=cat, ttl_days=ttl)
        self._json(entry.to_dict(), 201)

    def _session_get(self, wd: str, key: str):
        entry = _store(wd).get(key)
        if not entry:
            self._json({"error": "條目不存在或已過期"}, 404); return
        self._json(entry.to_dict())

    def _session_update(self, wd: str, key: str, body: dict):
        entry = _store(wd).get(key)
        if not entry:
            self._json({"error": "條目不存在"}, 404); return
        updated = _store(wd).set(
            key=key,
            value=body.get("value", body.get("content", entry.value)),
            category=body.get("category", entry.category),
            ttl_days=body.get("ttl_days", None),
        )
        self._json(updated.to_dict())

    def _session_delete(self, wd: str, key: str):
        deleted = _store(wd).delete(key)
        self._json({"key": key, "deleted": deleted})

    def _session_search(self, wd: str, qs: dict, body: dict):
        q     = (qs.get("q", [""])[0] or body.get("q", "")).strip()
        limit = min(int(qs.get("limit", ["10"])[0]), 50)
        if not q:
            self._json({"error": "請提供 q 參數"}, 400); return
        hits = _store(wd).search(q, limit=limit)
        self._json({"query": q, "results": [e.to_dict() for e in hits],
                    "count": len(hits)})

    def _session_clear(self, wd: str):
        count = _store(wd).clear_session()
        self._json({"deleted": count, "session_id": _store(wd).session_id})

    # ── /v1/traces ─────────────────────────────────────────
    def _traces(self, wd: str, qs: dict):
        limit = min(int(qs.get("limit", ["20"])[0]), 200)
        since = qs.get("since", [""])[0]
        try:
            db = _tdb(wd)
            if since:
                rows = db.execute(
                    "SELECT * FROM query_traces WHERE ts > ? ORDER BY ts DESC LIMIT ?",
                    (since, limit)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM query_traces ORDER BY ts DESC LIMIT ?", (limit,)
                ).fetchall()
            total = db.execute("SELECT COUNT(*) FROM query_traces").fetchone()[0]
            out = []
            for r in rows:
                d = dict(r)
                try:    d["traces"] = json.loads(d.pop("traces_json", "[]"))
                except: d["traces"] = []
                out.append(d)
            self._json({"traces": out, "total": total})
        except Exception as exc:
            logger.warning("traces: %s", exc)
            self._json({"traces": [], "total": 0, "error": "無法取得追蹤記錄"}, 500)

    def _traces_clear(self, wd: str):
        try:
            db = _tdb(wd)
            db.execute("DELETE FROM query_traces")
            db.commit()
            self._json({"ok": True})
        except Exception as exc:
            logger.warning("traces clear: %s", exc)
            self._json({"ok": False, "error": "清除追蹤記錄時發生錯誤"}, 500)

    def _traces_stats(self, wd: str):
        try:
            rows = _tdb(wd).execute(
                "SELECT total_ms FROM query_traces ORDER BY ts DESC LIMIT 200"
            ).fetchall()
            if not rows:
                self._json({"count": 0}); return
            ms = sorted(r[0] for r in rows)
            self._json({
                "count":   len(ms),
                "avg_ms":  round(sum(ms) / len(ms), 1),
                "p95_ms":  ms[int(len(ms) * 0.95)],
                "max_ms":  max(ms),
            })
        except Exception as exc:
            logger.warning("traces stats: %s", exc)
            self._json({"error": "無法取得統計資料"}, 500)

    # ── /v1/nudges ─────────────────────────────────────────
    def _nudges(self, wd: str, qs: dict):
        task  = qs.get("task", [""])[0].strip()
        top_k = min(int(qs.get("top_k", ["5"])[0]), 20)
        if not task:
            self._json({"error": "task 參數必填"}, 400); return
        try:
            from project_brain.nudge_engine import NudgeEngine
            nudges = NudgeEngine(_graph(wd)).check(task, top_k=top_k)
            self._json({"task": task, "count": len(nudges),
                        "nudges": [n.to_dict() for n in nudges]})
        except Exception as exc:
            logger.warning("nudges: %s", exc)
            self._json({"error": "無法取得提醒，請稍後再試"}, 500)

    # ── /v1/nudges/stream (SSE) ────────────────────────────
    def _nudges_stream(self, wd: str, qs: dict):
        task  = qs.get("task", [""])[0].strip()
        top_k = min(int(qs.get("top_k", ["5"])[0]), 10)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def _push(trigger: str):
            try:
                from project_brain.nudge_engine import NudgeEngine
                nudges = NudgeEngine(_graph(wd)).check(task or "general", top_k=top_k)
                data = json.dumps({
                    "task": task, "count": len(nudges), "trigger": trigger,
                    "nudges": [n.to_dict() for n in nudges],
                }, ensure_ascii=False)
            except Exception as exc:
                data = json.dumps({"error": str(exc)[:100], "trigger": trigger})
            self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
            self.wfile.flush()

        try:
            import queue as _q
            evt_q: _q.Queue = _q.Queue(maxsize=20)
            try:
                from project_brain.event_bus import BrainEventBus
                bus = BrainEventBus(Path(wd) / ".brain")
                @bus.on("brain.session")
                def _on_s(p):
                    try: evt_q.put_nowait(p)
                    except _q.Full: pass
                @bus.on("git.commit")
                def _on_c(p):
                    try: evt_q.put_nowait(p)
                    except _q.Full: pass
            except Exception as _e:
                logger.debug("event bus subscription failed in SSE handler", exc_info=True)
            _push("init")
            while True:
                try:
                    evt_q.get(timeout=60)
                    _push("event")
                except _q.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ── /v1/events ─────────────────────────────────────────
    def _events(self, wd: str, qs: dict):
        event_type = qs.get("type", [""])[0]
        limit      = min(int(qs.get("limit", ["20"])[0]), 100)
        try:
            from project_brain.event_bus import BrainEventBus
            bus    = BrainEventBus(Path(wd) / ".brain")
            events = bus.recent(event_type=event_type, limit=limit)
            self._json({
                "count": len(events),
                "events": [
                    {"id": e.id, "ts": e.ts, "type": e.event_type,
                     "payload": e.payload, "processed": e.processed}
                    for e in events
                ],
            })
        except Exception as exc:
            logger.warning("events: %s", exc)
            self._json({"error": "無法取得事件記錄"}, 500)

    # ── /webhook/slack ─────────────────────────────────────
    def _webhook_slack(self, wd: str, body: dict):
        import urllib.request as _ur
        slack_url = os.environ.get("BRAIN_SLACK_WEBHOOK_URL", "")
        if not slack_url:
            self._json({"error": "BRAIN_SLACK_WEBHOOK_URL 未設定"}, 400); return
        task = str(body.get("task", ""))[:200]
        msg  = str(body.get("message", task or "Brain nudge"))[:500]
        payload = json.dumps({"text": f"🧠 *Project Brain*: {msg}"}).encode()
        try:
            req = _ur.Request(
                slack_url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST"
            )
            with _ur.urlopen(req, timeout=5) as r:
                ok = r.status == 200
        except Exception as exc:
            self._json({"error": str(exc)[:100]}, 500); return
        self._json({"sent": ok})

    # ── /webhook/github ────────────────────────────────────
    def _webhook_github(self, wd: str, body: dict):
        import subprocess
        event = self.headers.get("X-GitHub-Event", "")
        if event == "ping":
            self._json({"pong": True}); return
        if event != "push":
            self._json({"skipped": True, "reason": "not push/ping"}); return
        try:
            result = subprocess.run(
                ["brain", "sync", "--workdir", wd, "--quiet"],
                capture_output=True, text=True, timeout=30
            )
            self._json({
                "synced": result.returncode == 0,
                "stdout": result.stdout[:200],
                "stderr": result.stderr[:200],
            })
        except Exception as exc:
            self._json({"error": str(exc)[:100]}, 500)


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def run_server(workdir: str, port: int = 7891, host: str = "0.0.0.0",
               api_key: str = "", readonly: bool = False) -> None:
    """Start the REST API server (blocking). Ctrl+C to stop."""
    _Handler.workdir  = str(workdir)
    _Handler.api_key  = api_key
    _Handler.readonly = readonly
    if readonly:
        logger.info("Project Brain API server started in READONLY mode on %s:%s", host, port)
    server = HTTPServer((host, port), _Handler)
    # Pre-warm connections
    try:
        _tdb(str(workdir))
    except Exception as _e:
        logger.debug("pre-warm connection failed", exc_info=True)
    logger.info("Project Brain API server started on %s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def create_app(workdir: str, api_key: str = "", readonly: bool = False):
    """
    Backwards-compatible shim — returns an object with a .run() method.
    New code should call run_server() directly.
    """
    class _Compat:
        def __init__(self, wd, key, ro):
            self._wd  = wd
            self._key = key
            self._ro  = ro

        def run(self, host: str = "0.0.0.0", port: int = 7891, **_):
            run_server(self._wd, port, host, self._key, self._ro)

    return _Compat(workdir, api_key, readonly)
