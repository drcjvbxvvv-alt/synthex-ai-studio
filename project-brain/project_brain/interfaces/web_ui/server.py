"""
project_brain/web_ui/server.py — 知識圖譜視覺化 Web UI（v2.0）

純 Python http.server + 純 JavaScript（無 Flask、無 D3.js CDN）。
離線可用，零外部框架依賴。

v2.0 重構：前端分離為獨立檔案
  - templates/index.html — HTML 骨架
  - static/style.css     — 所有 CSS
  - static/app.js        — 所有 JS
  - server.py            — 僅 Python API 路由 + 靜態檔案服務
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_QUERY_LEN = 200
MAX_NODES_RETURN = 500
HOST = "127.0.0.1"
_VERSION = "2.0"

ALLOWED_EDIT_FIELDS = {"title", "content", "confidence", "kind"}
VALID_KINDS = {"Pitfall", "Decision", "Rule", "ADR", "Component", "Architecture", "Note"}

KIND_COLOR = {
    "Pitfall":      "#f87171",
    "Decision":     "#34d399",
    "Rule":         "#60a5fa",
    "ADR":          "#c084fc",
    "Component":    "#94a3b8",
    "Architecture": "#fb923c",
    "Note":         "#fbbf24",
}

NODE_SIZE = {
    "Component": 14, "Decision": 13, "Pitfall": 12,
    "Rule": 10, "ADR": 13, "Architecture": 13,
    "Note": 9, "Commit": 7,
}

_STATIC_MIME = {
    ".css": "text/css; charset=utf-8",
    ".js":  "application/javascript; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


def _render_template(workdir: str = "") -> str:
    """Load templates/index.html and substitute placeholders."""
    project = Path(workdir).name if workdir else "Project"
    tpl_path = _TEMPLATE_DIR / "index.html"
    if not tpl_path.exists():
        raise FileNotFoundError(f"WebUI template not found: {tpl_path}")
    html = tpl_path.read_text(encoding="utf-8")
    html = html.replace("{{PROJECT}}", project)
    html = html.replace("{{VERSION}}", _VERSION)
    return html


def _conf_color(c: float) -> str:
    if c >= 0.75:
        return "#34d399"
    if c >= 0.50:
        return "#86efac"
    if c >= 0.30:
        return "#fbbf24"
    if c >= 0.15:
        return "#f97316"
    return "#f87171"


def _conf_label(c: float) -> str:
    if c >= 0.80:
        return "✓✓ 權威"
    if c >= 0.60:
        return "✓ 已驗證"
    if c >= 0.30:
        return "~ 推斷"
    return "⚠ 推測"


# ─────────────────────────────────────────────
# HTTP handler
# ─────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    workdir: Path = None   # set by run_server()

    def log_message(self, fmt, *args):
        pass  # suppress per-request noise

    # ── DB ──────────────────────────────────
    def _db(self) -> sqlite3.Connection:
        bd = self.__class__.workdir / ".brain"
        for name in ("brain.db", "knowledge_graph.db"):
            p = bd / name
            if p.exists():
                conn = sqlite3.connect(str(p), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                return conn
        raise FileNotFoundError(f"找不到資料庫：{bd}/brain.db（請先執行 brain setup）")

    def _col(self, row, key: str, default=None):
        """Safe column access compatible with both DB schemas."""
        try:
            return row[key]
        except (IndexError, KeyError):
            return default

    # ── Response helpers ────────────────────
    def _json(self, data, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── Routing ─────────────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)
            if path == "/":
                wd = self.__class__.workdir
                self._html(_render_template(str(wd)))
            elif path.startswith("/static/"):
                self._route_static(path[len("/static/"):])
            elif path == "/api/graph":
                self._route_graph(qs)
            elif path == "/api/stats":
                self._route_stats()
            elif path == "/api/analytics":
                self._route_analytics()
            elif path == "/api/nodes":
                self._route_nodes(qs)
            elif path == "/api/search":
                self._route_search(qs)
            elif path == "/api/staging":
                self._route_staging()
            elif path == "/api/admin/dashboard":
                self._route_admin_dashboard()
            elif path == "/api/admin/audit-log":
                self._route_admin_audit_log(qs)
            elif path == "/api/admin/settings":
                self._route_admin_settings()
            elif path.startswith("/api/node/") and not path.endswith("/pin"):
                nid = path[len("/api/node/"):]
                self._route_node(nid)
            elif path == "/health":
                self._json({"status": "ok", "version": _VERSION})
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:
            logger.exception("GET %s", self.path)
            self._json({"error": "內部錯誤"}, 500)

    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)
                              or b"{}") if length else {}
            if path == "/api/node":
                self._route_add_node(body)
            elif path == "/api/admin/settings":
                self._route_save_settings(body)
            elif path.startswith("/api/node/") and path.endswith("/pin"):
                nid = path[len("/api/node/"):-len("/pin")]
                self._route_pin(nid, body)
            elif path.startswith("/api/staging/") and path.endswith("/approve"):
                sid = path[len("/api/staging/"):-len("/approve")]
                self._route_staging_action(sid, "approve", body)
            elif path.startswith("/api/staging/") and path.endswith("/reject"):
                sid = path[len("/api/staging/"):-len("/reject")]
                self._route_staging_action(sid, "reject", body)
            else:
                self._json({"error": "not found"}, 404)
        except Exception:
            logger.exception("POST %s", self.path)
            self._json({"error": "內部錯誤"}, 500)

    def do_PATCH(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)
                              or b"{}") if length else {}
            if path.startswith("/api/node/"):
                nid = path[len("/api/node/"):]
                self._route_patch_node(nid, body)
            else:
                self._json({"error": "not found"}, 404)
        except Exception:
            logger.exception("PATCH %s", self.path)
            self._json({"error": "內部錯誤"}, 500)

    def do_DELETE(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if path.startswith("/api/node/"):
                nid = path[len("/api/node/"):]
                self._route_delete_node(nid)
            else:
                self._json({"error": "not found"}, 404)
        except Exception:
            logger.exception("DELETE %s", self.path)
            self._json({"error": "內部錯誤"}, 500)

    # ── Static files ────────────────────────
    def _route_static(self, filename: str):
        safe = re.sub(r"[^a-zA-Z0-9._-]", "", filename)[:64]
        static_dir = Path(__file__).parent / "static"
        fpath = static_dir / safe
        if not fpath.exists() or not fpath.is_file():
            self._json({"error": "not found"}, 404)
            return
        mime = _STATIC_MIME.get(fpath.suffix, "application/octet-stream")
        body = fpath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    # ── API: /api/graph ──────────────────────
    def _route_graph(self, qs):
        limit = min(MAX_NODES_RETURN, int(qs.get("limit", ["100"])[0]))
        kind = qs.get("kind", [None])[0]
        conn = self._db()
        try:
            # Detect available columns once per request
            _has_col = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
            kind_col = "kind" if "kind" in _has_col else "type"
            scope_expr = "scope" if "scope" in _has_col else "'global' as scope"
            cols = f"id, {kind_col} as kind, title, content, tags, created_at, confidence, is_pinned, {scope_expr}"
            if kind:
                sk = re.sub(r"[^a-zA-Z]", "", kind)[:20]
                rows = conn.execute(
                    f"SELECT {cols} FROM nodes WHERE {kind_col}=? LIMIT ?", (
                        sk, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {cols} FROM nodes LIMIT ?", (limit,)
                ).fetchall()

            nodes, node_ids = [], set()
            for r in rows:
                k = self._col(r, "kind") or "Note"
                conf = float(self._col(r, "confidence") or 0.7)
                nodes.append({
                    "id":        r["id"],
                    "kind":      k,
                    "title":     r["title"] or "",
                    "color":     KIND_COLOR.get(k, "#94a3b8"),
                    "size":      NODE_SIZE.get(k, 10),
                    "confidence":  conf,
                    "conf_color":  _conf_color(conf),
                    "conf_label":  _conf_label(conf),
                    "is_pinned": bool(self._col(r, "is_pinned") or False),
                    "scope":     self._col(r, "scope") or "global",
                    "tags":      r["tags"] or "",
                    "excerpt":   (r["content"] or "")[:200],
                    "created_at": r["created_at"] or "",
                })
                node_ids.add(r["id"])

            links = []
            if node_ids:
                ph = ",".join("?" * len(node_ids))
                ids = list(node_ids)
                _edge_cols = {r[1] for r in conn.execute("PRAGMA table_info(edges)").fetchall()}
                rel_col = "relation_type" if "relation_type" in _edge_cols else "relation"
                erows = conn.execute(
                    f"SELECT source_id, target_id, {rel_col} as relation_type FROM edges "
                    f"WHERE source_id IN ({ph}) AND target_id IN ({ph})", ids * 2
                ).fetchall()
                links = [{"source": r["source_id"], "target": r["target_id"],
                          "type": r["relation_type"]} for r in erows]
        finally:
            conn.close()
        self._json({"nodes": nodes, "links": links,
                    "total_nodes": len(nodes), "total_links": len(links)})

    # ── API: /api/stats ──────────────────────
    def _route_stats(self):
        conn = self._db()
        try:
            total = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            try:
                edges = conn.execute(
                    "SELECT COUNT(*) FROM edges").fetchone()[0]
            except Exception:
                edges = 0
            # low_conf / pinned 獨立查詢，不受 kind 欄位不存在影響
            try:
                low_conf = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE confidence < 0.3"
                ).fetchone()[0]
            except Exception:
                low_conf = 0
            try:
                pinned = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE is_pinned = 1"
                ).fetchone()[0]
            except Exception:
                pinned = 0
            _has_col = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
            kind_col = "kind" if "kind" in _has_col else "type"
            by_kind = conn.execute(
                f"SELECT {kind_col} as kind, COUNT(*) cnt, AVG(confidence) avg_conf "
                f"FROM nodes GROUP BY {kind_col} ORDER BY cnt DESC"
            ).fetchall()
            try:
                conf_dist = conn.execute("""
                    SELECT
                        SUM(CASE WHEN confidence >= 0.80 THEN 1 ELSE 0 END) as hi,
                        SUM(CASE WHEN confidence >= 0.60 AND confidence < 0.80 THEN 1 ELSE 0 END) as med,
                        SUM(CASE WHEN confidence >= 0.30 AND confidence < 0.60 THEN 1 ELSE 0 END) as low,
                        SUM(CASE WHEN confidence < 0.30 THEN 1 ELSE 0 END) as vlow
                    FROM nodes
                """).fetchone()
            except Exception:
                conf_dist = None
        finally:
            conn.close()
        self._json({
            "total_nodes":  total,
            "total_edges":  edges,
            "low_confidence": low_conf,
            "pinned":       pinned,
            "conf_dist": {
                "hi":   int(conf_dist["hi"]  or 0) if conf_dist else 0,
                "med":  int(conf_dist["med"] or 0) if conf_dist else 0,
                "low":  int(conf_dist["low"] or 0) if conf_dist else 0,
                "vlow": int(conf_dist["vlow"] or 0) if conf_dist else 0,
            },
            "by_kind": [
                {
                    "kind":  r["kind"] or "Note",
                    "count": r["cnt"],
                    "avg_confidence": round(float(self._col(r, "avg_conf") or 0.7), 2),
                }
                for r in by_kind
            ],
        })

    # ── API: /api/analytics ─────────────────────
    def _route_analytics(self):
        """PH2-01: ROI dashboard metrics — powered by AnalyticsEngine."""
        conn = self._db()
        try:
            try:
                from project_brain.analytics_engine import AnalyticsEngine
                engine = AnalyticsEngine(conn)
                report = engine.generate_report(period_days=7)
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
                return
        finally:
            conn.close()
        self._json(report)

    # ── API: /api/nodes (paginated, searchable, sortable) ──────
    def _route_nodes(self, qs):
        page = max(1, int(qs.get("page", ["1"])[0]))
        page_size = min(100, max(1, int(qs.get("page_size", ["20"])[0])))
        q = (qs.get("q", [""])[0] or "")[:MAX_QUERY_LEN].strip()
        kind = qs.get("kind", [""])[0].strip()
        sort = qs.get("sort", ["confidence"])[0]
        order = qs.get("order", ["desc"])[0].lower()

        conn = self._db()
        try:
            _has_col = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
            kind_col = "kind" if "kind" in _has_col else "type"
            scope_expr = "scope" if "scope" in _has_col else "'global' as scope"

            # Build WHERE clause
            conditions = []
            params: list = []
            if q:
                conditions.append("(title LIKE ? OR content LIKE ?)")
                params.extend([f"%{q}%", f"%{q}%"])
            if kind and kind in VALID_KINDS:
                conditions.append(f"{kind_col} = ?")
                params.append(kind)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            # Sort column validation
            valid_sorts = {"confidence", "created_at", "access_count", "title"}
            sort_col = sort if sort in valid_sorts else "confidence"
            order_dir = "ASC" if order == "asc" else "DESC"

            # Count total
            total = conn.execute(
                f"SELECT COUNT(*) FROM nodes {where}", params
            ).fetchone()[0]

            # Fetch page
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT id, {kind_col} as kind, title, content, confidence, "
                f"access_count, created_at, is_pinned, {scope_expr}, tags "
                f"FROM nodes {where} "
                f"ORDER BY {sort_col} {order_dir} "
                f"LIMIT ? OFFSET ?",
                params + [page_size, offset]
            ).fetchall()
        finally:
            conn.close()

        nodes = []
        for r in rows:
            conf = float(r["confidence"] or 0.7)
            nodes.append({
                "id":           r["id"],
                "kind":         r["kind"] or "Note",
                "title":        r["title"] or "",
                "excerpt":      (r["content"] or "")[:120],
                "confidence":   conf,
                "access_count": int(r["access_count"] or 0),
                "created_at":   r["created_at"] or "",
                "is_pinned":    bool(r["is_pinned"] or False),
                "scope":        r["scope"] if "scope" in r.keys() else "global",
                "tags":         r["tags"] or "[]",
                "color":        KIND_COLOR.get(r["kind"] or "Note", "#94a3b8"),
            })

        self._json({
            "nodes": nodes,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size else 1,
        })

    # ── API: /api/search ─────────────────────
    def _route_search(self, qs):
        q = (qs.get("q", [""])[0] or "")[:MAX_QUERY_LEN].strip()
        if not q:
            self._json({"results": []})
            return
        conn = self._db()
        try:
            _has_col = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
            kind_col = "kind" if "kind" in _has_col else "type"
            rows = conn.execute(
                f"SELECT id, {kind_col} as kind, title, content, confidence FROM nodes "
                "WHERE title LIKE ? OR content LIKE ? "
                "ORDER BY confidence DESC LIMIT 20",
                (f"%{q}%", f"%{q}%")
            ).fetchall()
        finally:
            conn.close()
        self._json({"results": [
            {
                "id":      r["id"],
                "kind":    r["kind"] or "Note",
                "title":   r["title"] or "",
                "excerpt": (r["content"] or "")[:80],
                "confidence": float(self._col(r, "confidence") or 0.7),
                "color":   KIND_COLOR.get(r["kind"] or "Note", "#94a3b8"),
            }
            for r in rows
        ]})

    # ── API: /api/node/<id> ──────────────────
    def _route_node(self, node_id: str):
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", node_id)[:64]
        conn = self._db()
        try:
            _has_col = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
            kind_col = "kind" if "kind" in _has_col else "type"
            scope_expr = "scope" if "scope" in _has_col else "'global' as scope"
            row = conn.execute(
                f"SELECT id, {kind_col} as kind, title, content, tags, created_at, "
                f"confidence, is_pinned, {scope_expr} FROM nodes WHERE id=?", (safe,)
            ).fetchone()
            if not row:
                self._json({"error": "節點不存在"}, 404)
                return
            _edge_cols = {r[1] for r in conn.execute("PRAGMA table_info(edges)").fetchall()}
            rel_col = "relation_type" if "relation_type" in _edge_cols else "relation"
            nbrs = conn.execute(
                f"SELECT n.id, n.{kind_col} as kind, n.title, e.{rel_col} as relation_type "
                "FROM edges e JOIN nodes n ON e.target_id = n.id "
                "WHERE e.source_id=? LIMIT 10", (safe,)
            ).fetchall()
        finally:
            conn.close()
        conf = float(self._col(row, "confidence") or 0.7)
        k = row["kind"] or "Note"
        self._json({
            "id":          row["id"],
            "kind":        k,
            "title":       row["title"] or "",
            "content":     row["content"] or "",
            "confidence":  conf,
            "conf_label":  _conf_label(conf),
            "conf_color":  _conf_color(conf),
            "tags":        row["tags"] or "",
            "created_at":  row["created_at"] or "",
            "is_pinned":   bool(self._col(row, "is_pinned") or False),
            "scope":       self._col(row, "scope") or "global",
            "color":       KIND_COLOR.get(k, "#94a3b8"),
            "neighbors": [
                {
                    "id":       n["id"],
                    "kind":     n["kind"] or "Note",
                    "title":    n["title"] or "",
                    "relation": n["relation_type"] or "",
                    "color":    KIND_COLOR.get(n["kind"] or "Note", "#94a3b8"),
                }
                for n in nbrs
            ],
        })

    # ── API: POST /api/node/<id>/pin ─────────
    def _route_pin(self, node_id: str, body: dict):
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", node_id)[:64]
        pinned = bool(body.get("pinned", True))
        conn = self._db()
        try:
            cur = conn.execute(
                "UPDATE nodes SET is_pinned=? WHERE id=?", (
                    1 if pinned else 0, safe)
            )
            conn.commit()
            if cur.rowcount == 0:
                self._json({"error": "節點不存在"}, 404)
                return
            self._json({"ok": True, "id": safe, "pinned": pinned})
        finally:
            conn.close()

    # ── API: PATCH /api/node/<id> ────────────
    def _route_patch_node(self, node_id: str, body: dict):
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", node_id)[:64]
        updates, values, err = _validate_node_patch(body)
        if err:
            self._json({"error": err}, 400)
            return
        if not updates:
            self._json({"error": "沒有可更新的欄位"}, 400)
            return
        conn = self._db()
        try:
            set_clause = ", ".join(f"{col}=?" for col in updates)
            cur = conn.execute(
                f"UPDATE nodes SET {set_clause} WHERE id=?", values + [safe]
            )
            if cur.rowcount == 0:
                self._json({"error": "節點不存在"}, 404)
                conn.commit()
                return
            _sync_fts(conn, safe)
            conn.commit()
            self._json({"ok": True, "id": safe})
        finally:
            conn.close()

    # ── API: DELETE /api/node/<id> ───────────
    def _route_delete_node(self, node_id: str):
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", node_id)[:64]
        conn = self._db()
        try:
            cur = conn.execute("DELETE FROM nodes WHERE id=?", (safe,))
            if cur.rowcount == 0:
                self._json({"error": "節點不存在"}, 404)
                conn.commit()
                return
            try:
                conn.execute("DELETE FROM nodes_fts WHERE id=?", (safe,))
            except Exception:
                pass
            conn.execute(
                "DELETE FROM edges WHERE source_id=? OR target_id=?", (safe, safe)
            )
            conn.commit()
            self._json({"ok": True, "id": safe})
        finally:
            conn.close()

    # ── API: POST /api/node (E-06 Step 1) ────
    def _route_add_node(self, body: dict):
        title = str(body.get("title", "")).strip()
        if not title:
            self._json({"error": "標題為必填欄位"}, 400)
            return
        if len(title) > 500:
            self._json({"error": "標題最長 500 字"}, 400)
            return
        content = str(body.get("content", "")).strip()
        if not content:
            self._json({"error": "內容為必填欄位"}, 400)
            return
        if len(content) > 10000:
            self._json({"error": "內容最長 10000 字"}, 400)
            return
        kind = str(body.get("kind", "Note"))
        if kind not in VALID_KINDS:
            self._json({"error": f"類型必須是：{', '.join(sorted(VALID_KINDS))}"}, 400)
            return
        try:
            confidence = float(body.get("confidence", 0.7))
        except (TypeError, ValueError):
            self._json({"error": "信心度必須是數字"}, 400)
            return
        if not (0.0 <= confidence <= 1.0):
            self._json({"error": "信心度必須在 0.0~1.0 之間"}, 400)
            return

        node_id = f"webui-{hashlib.sha256(f'{title}{time.time()}'.encode()).hexdigest()[:12]}"
        conn = self._db()
        try:
            conn.execute(
                "INSERT INTO nodes (id, type, title, content, confidence, "
                "is_pinned, created_at, access_count, tags, author) "
                "VALUES (?, ?, ?, ?, ?, 0, datetime('now'), 0, '[]', 'web-ui')",
                (node_id, kind, title, content, round(confidence, 4))
            )
            try:
                from project_brain.core.brain_db import BrainDB
                conn.execute(
                    "INSERT INTO nodes_fts(id, title, content, tags) VALUES (?,?,?,?)",
                    (node_id, BrainDB._ngram(title), BrainDB._ngram(content), "[]")
                )
            except Exception:
                pass
            conn.commit()
        except Exception as exc:
            logger.exception("add_node failed")
            self._json({"error": f"新增失敗：{exc}"}, 500)
            return
        finally:
            conn.close()
        self._json({"ok": True, "id": node_id}, 201)

    # ── API: GET /api/admin/dashboard (E-06 Step 2) ──
    def _route_admin_dashboard(self):
        conn = self._db()
        try:
            _has_col = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
            kind_col = "kind" if "kind" in _has_col else "type"

            total = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            try:
                edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            except Exception:
                edges = 0

            by_kind = conn.execute(
                f"SELECT {kind_col} as kind, COUNT(*) cnt FROM nodes GROUP BY {kind_col} ORDER BY cnt DESC"
            ).fetchall()
            kind_dist = {r["kind"] or "Note": r["cnt"] for r in by_kind}

            try:
                low_conf = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE confidence < 0.3"
                ).fetchone()[0]
            except Exception:
                low_conf = 0
            try:
                conflicts = conn.execute(
                    "SELECT COUNT(*) FROM edges WHERE relation_type = 'CONTRADICTS'"
                ).fetchone()[0]
            except Exception:
                conflicts = 0

            # Recent activity
            now_utc = datetime.now(timezone.utc).isoformat()
            activity = {"today": 0, "week": 0, "month": 0}
            try:
                activity["today"] = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE created_at >= date('now')"
                ).fetchone()[0]
                activity["week"] = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE created_at >= date('now', '-7 days')"
                ).fetchone()[0]
                activity["month"] = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE created_at >= date('now', '-30 days')"
                ).fetchone()[0]
            except Exception:
                pass

            # KRB pending
            krb_pending = 0
            try:
                rb_path = self.__class__.workdir / ".brain" / "review_board.db"
                if rb_path.exists():
                    rb_conn = sqlite3.connect(str(rb_path))
                    krb_pending = rb_conn.execute(
                        "SELECT COUNT(*) FROM staged_nodes WHERE status='pending'"
                    ).fetchone()[0]
                    rb_conn.close()
            except Exception:
                pass

            # Signal queue
            signal_pending = 0
            try:
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}
                if "signal_queue" in tables:
                    signal_pending = conn.execute(
                        "SELECT COUNT(*) FROM signal_queue WHERE status='pending'"
                    ).fetchone()[0]
            except Exception:
                pass

            # Health summary
            health_errors = 0
            health_warnings = 0
            if low_conf > 0:
                health_warnings += 1
            if conflicts > 0:
                health_warnings += 1

        finally:
            conn.close()

        self._json({
            "total_nodes": total,
            "total_edges": edges,
            "kind_distribution": kind_dist,
            "low_confidence_count": low_conf,
            "conflicts": conflicts,
            "activity": activity,
            "krb_pending": krb_pending,
            "signal_pending": signal_pending,
            "health": {
                "status": "error" if health_errors > 0 else ("warn" if health_warnings > 0 else "ok"),
                "errors": health_errors,
                "warnings": health_warnings,
            },
        })

    # ── API: GET /api/admin/audit-log (E-06 Step 3) ──
    def _route_admin_audit_log(self, qs):
        days = min(365, max(1, int(qs.get("days", ["30"])[0])))
        author = (qs.get("author", [""])[0] or "").strip()[:100]
        action = (qs.get("action", [""])[0] or "").strip()[:20]
        page = max(1, int(qs.get("page", ["1"])[0]))
        page_size = min(100, max(1, int(qs.get("page_size", ["50"])[0])))

        entries: list[dict] = []
        conn = self._db()
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}

            # Source 1: node_history
            if "node_history" in tables:
                nh_cols = {r[1] for r in conn.execute("PRAGMA table_info(node_history)").fetchall()}
                change_type_col = "change_type" if "change_type" in nh_cols else "'update' as change_type"
                changed_by_col = "changed_by" if "changed_by" in nh_cols else "'' as changed_by"
                change_note_col = "change_note" if "change_note" in nh_cols else "'' as change_note"
                rows = conn.execute(
                    f"SELECT node_id, title, {change_type_col}, "
                    f"{changed_by_col}, {change_note_col}, snapshot_at "
                    f"FROM node_history "
                    f"WHERE snapshot_at >= datetime('now', '-{days} days') "
                    f"ORDER BY snapshot_at DESC"
                ).fetchall()
                for r in rows:
                    actor = r["changed_by"] or ""
                    if author and author.lower() not in actor.lower():
                        continue
                    act = r["change_type"] or "update"
                    if action and action != act:
                        continue
                    entries.append({
                        "time": r["snapshot_at"] or "",
                        "actor": actor,
                        "action": act,
                        "node_id": r["node_id"],
                        "title": r["title"] or "",
                        "detail": r["change_note"] or "",
                        "source": "node_history",
                    })

            # Source 2: staged_nodes (KRB)
            rb_path = self.__class__.workdir / ".brain" / "review_board.db"
            if rb_path.exists():
                try:
                    rb_conn = sqlite3.connect(str(rb_path))
                    rb_conn.row_factory = sqlite3.Row
                    rb_rows = rb_conn.execute(
                        "SELECT id, kind, title, status, submitter, reviewer, "
                        "created_at, reviewed_at, review_note "
                        "FROM staged_nodes ORDER BY created_at DESC"
                    ).fetchall()
                    rb_conn.close()
                    for r in rb_rows:
                        # Submit event
                        sub = r["submitter"] or ""
                        if not (author and author.lower() not in sub.lower()):
                            if not (action and action != "submit"):
                                entries.append({
                                    "time": r["created_at"] or "",
                                    "actor": sub,
                                    "action": "submit",
                                    "node_id": r["id"],
                                    "title": r["title"] or "",
                                    "detail": f"kind={r['kind']}, status={r['status']}",
                                    "source": "krb",
                                })
                        # Review event
                        if r["reviewed_at"]:
                            rev = r["reviewer"] or ""
                            if not (author and author.lower() not in rev.lower()):
                                act_type = "approve" if r["status"] == "approved" else "reject"
                                if not (action and action != act_type):
                                    entries.append({
                                        "time": r["reviewed_at"],
                                        "actor": rev,
                                        "action": act_type,
                                        "node_id": r["id"],
                                        "title": r["title"] or "",
                                        "detail": r["review_note"] or "",
                                        "source": "krb",
                                    })
                except Exception:
                    pass

            # Sort all entries by time descending
            entries.sort(key=lambda e: e.get("time", ""), reverse=True)
        finally:
            conn.close()

        total = len(entries)
        offset = (page - 1) * page_size
        page_entries = entries[offset:offset + page_size]

        self._json({
            "entries": page_entries,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size else 1,
        })

    # ── API: GET /api/admin/settings (E-06 Step 4) ──
    def _route_admin_settings(self):
        bd = self.__class__.workdir / ".brain"
        result: dict = {
            "mode": "standalone",
            "embedding": "LocalTFIDF",
            "llm": "未設定",
            "schema_version": 0,
            "services": [],
            "storage": {},
            "config": {},
            "has_toml": False,
        }

        # Read brain.toml for config
        toml_path = bd / "brain.toml"
        if toml_path.exists():
            result["has_toml"] = True
            try:
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib  # type: ignore[no-redef]
                cfg = tomllib.loads(toml_path.read_text(encoding="utf-8"))
                result["mode"] = cfg.get("mode", "standalone")
                result["embedding"] = cfg.get("embedding", {}).get("provider", "LocalTFIDF")
                result["llm"] = cfg.get("llm", {}).get("provider", "未設定")
                # Editable config sections
                result["config"] = {
                    "decay_enabled": cfg.get("decay", {}).get("enabled", True),
                    "decay_interval_hours": cfg.get("decay", {}).get("run_interval_hours", 24),
                    "pipeline_enabled": cfg.get("pipeline", {}).get("enabled", True),
                    "pipeline_worker_interval": cfg.get("pipeline", {}).get("worker_interval_seconds", 60),
                    "pipeline_max_auto_confidence": cfg.get("pipeline", {}).get("max_auto_confidence", 0.85),
                    "review_auto_approve_threshold": cfg.get("review", {}).get("auto_approve_threshold", 0.80),
                    "review_staging_ttl_days": cfg.get("review", {}).get("staging_ttl_days", 30),
                    "brain_max_context_tokens": cfg.get("brain", {}).get("max_context_tokens", 6000),
                    "brain_freshness_warn_days": cfg.get("brain", {}).get("freshness_warn_days", 30),
                    "brain_dedup_threshold": cfg.get("brain", {}).get("dedup_threshold", 0.85),
                }
            except Exception:
                pass
        else:
            # Defaults when no toml exists
            result["config"] = {
                "decay_enabled": True, "decay_interval_hours": 24,
                "pipeline_enabled": True, "pipeline_worker_interval": 60,
                "pipeline_max_auto_confidence": 0.85,
                "review_auto_approve_threshold": 0.80, "review_staging_ttl_days": 30,
                "brain_max_context_tokens": 6000, "brain_freshness_warn_days": 30,
                "brain_dedup_threshold": 0.85,
            }

        db_path = bd / "brain.db"
        if not db_path.exists():
            result["services"].append({"name": "brain.db", "status": "error", "detail": "not found"})
            self._json(result)
            return

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            # Schema version
            try:
                row = conn.execute(
                    "SELECT value FROM brain_meta WHERE key='schema_version'"
                ).fetchone()
                if row:
                    result["schema_version"] = int(row[0])
            except Exception:
                pass

            # Node count
            try:
                nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                result["services"].append({
                    "name": "brain.db",
                    "status": "ok",
                    "detail": f"{nodes} nodes",
                })
            except Exception as e:
                result["services"].append({"name": "brain.db", "status": "error", "detail": str(e)})

            # Central Brain status
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if "api_keys" in tables:
                try:
                    active = conn.execute(
                        "SELECT COUNT(*) FROM api_keys WHERE is_revoked=0"
                    ).fetchone()[0]
                    result["services"].append({
                        "name": "Central Brain",
                        "status": "ok" if active > 0 else "warn",
                        "detail": f"{active} active keys",
                    })
                except Exception:
                    pass
            else:
                result["services"].append({
                    "name": "Central Brain",
                    "status": "ok",
                    "detail": "未設定",
                })
        finally:
            conn.close()

        # Storage
        try:
            result["storage"]["brain_db"] = _fmt_file_size(db_path.stat().st_size)
            backup_dir = bd / "backups"
            if backup_dir.exists():
                backups = list(backup_dir.glob("brain.db.*"))
                total_size = sum(f.stat().st_size for f in backups)
                result["storage"]["backups"] = f"{len(backups)} 份 / {_fmt_file_size(total_size)}"
            else:
                result["storage"]["backups"] = "無備份"
        except Exception:
            pass

        self._json(result)

    # ── API: POST /api/admin/settings (E-06 save) ──
    def _route_save_settings(self, body: dict):
        bd = self.__class__.workdir / ".brain"
        toml_path = bd / "brain.toml"

        # Read existing TOML or start fresh
        existing: dict = {}
        if toml_path.exists():
            try:
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib  # type: ignore[no-redef]
                existing = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        cfg = body.get("config", {})
        if not cfg:
            self._json({"error": "沒有要儲存的設定"}, 400)
            return

        # Apply changes to dict
        if "decay_enabled" in cfg or "decay_interval_hours" in cfg:
            existing.setdefault("decay", {})
            if "decay_enabled" in cfg:
                existing["decay"]["enabled"] = bool(cfg["decay_enabled"])
            if "decay_interval_hours" in cfg:
                existing["decay"]["run_interval_hours"] = max(1, int(cfg["decay_interval_hours"]))

        if "pipeline_enabled" in cfg or "pipeline_worker_interval" in cfg or "pipeline_max_auto_confidence" in cfg:
            existing.setdefault("pipeline", {})
            if "pipeline_enabled" in cfg:
                existing["pipeline"]["enabled"] = bool(cfg["pipeline_enabled"])
            if "pipeline_worker_interval" in cfg:
                existing["pipeline"]["worker_interval_seconds"] = max(10, int(cfg["pipeline_worker_interval"]))
            if "pipeline_max_auto_confidence" in cfg:
                existing["pipeline"]["max_auto_confidence"] = max(0.0, min(1.0, float(cfg["pipeline_max_auto_confidence"])))

        if "review_auto_approve_threshold" in cfg or "review_staging_ttl_days" in cfg:
            existing.setdefault("review", {})
            if "review_auto_approve_threshold" in cfg:
                existing["review"]["auto_approve_threshold"] = max(0.0, min(1.0, float(cfg["review_auto_approve_threshold"])))
            if "review_staging_ttl_days" in cfg:
                existing["review"]["staging_ttl_days"] = max(1, int(cfg["review_staging_ttl_days"]))

        if "brain_max_context_tokens" in cfg or "brain_freshness_warn_days" in cfg or "brain_dedup_threshold" in cfg:
            existing.setdefault("brain", {})
            if "brain_max_context_tokens" in cfg:
                existing["brain"]["max_context_tokens"] = max(500, int(cfg["brain_max_context_tokens"]))
            if "brain_freshness_warn_days" in cfg:
                existing["brain"]["freshness_warn_days"] = max(1, int(cfg["brain_freshness_warn_days"]))
            if "brain_dedup_threshold" in cfg:
                existing["brain"]["dedup_threshold"] = max(0.0, min(1.0, float(cfg["brain_dedup_threshold"])))

        # Write TOML
        try:
            toml_path.write_text(_dict_to_toml(existing), encoding="utf-8")
        except Exception as exc:
            self._json({"error": f"儲存失敗：{exc}"}, 500)
            return

        self._json({"ok": True})

    # ── API: GET /api/staging ────────────────
    def _route_staging(self):
        items = _load_staging(self.__class__.workdir)
        self._json({"staging": items, "total": len(items)})

    # ── API: POST /api/staging/<id>/approve|reject ──
    def _route_staging_action(self, staging_id: str, action: str, body: dict):
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", staging_id)[:64]
        note = str(body.get("note", ""))[:500]
        try:
            from project_brain.engines.review_board import KnowledgeReviewBoard
            from project_brain.graph import KnowledgeGraph
            wd = self.__class__.workdir
            bd = wd / ".brain"
            g = KnowledgeGraph(bd)
            krb = KnowledgeReviewBoard(bd, g)
            if action == "approve":
                krb.approve(safe, reviewer="web-ui", note=note)
            else:
                krb.reject(safe, reviewer="web-ui", reason=note or "web-ui reject")
            self._json({"ok": True, "id": safe, "action": action})
        except Exception as exc:
            logger.exception("staging action %s %s", action, safe)
            self._json({"error": str(exc)}, 500)


# ─────────────────────────────────────────────
# Shared helpers (used by both _Handler and create_app)
# ─────────────────────────────────────────────

def _validate_node_patch(body: dict) -> tuple[list[str], list, str | None]:
    """Validate PATCH body. Returns (sql_columns, values, error_or_None).

    Note: 'kind' in the API maps to the 'type' column in the nodes table
    (brain_db uses 'type'; web UI aliases it to 'kind' for display).
    """
    unknown = set(body) - ALLOWED_EDIT_FIELDS
    if unknown:
        return [], [], f"不允許的欄位：{', '.join(sorted(unknown))}"
    cols, vals = [], []
    if "title" in body:
        t = str(body["title"]).strip()
        if not t:
            return [], [], "title 不能為空"
        cols.append("title"); vals.append(t[:500])
    if "content" in body:
        cols.append("content"); vals.append(str(body["content"])[:10000])
    if "confidence" in body:
        try:
            c = float(body["confidence"])
        except (TypeError, ValueError):
            return [], [], "confidence 必須是數字"
        if not (0.0 <= c <= 1.0):
            return [], [], "confidence 必須在 0.0~1.0 之間"
        cols.append("confidence"); vals.append(round(c, 4))
    if "kind" in body:
        k = str(body["kind"])
        if k not in VALID_KINDS:
            return [], [], f"kind 必須是：{', '.join(sorted(VALID_KINDS))}"
        # nodes table uses 'type' column; 'kind' is an alias used in SELECT
        cols.append("type"); vals.append(k)
    return cols, vals, None


def _dict_to_toml(d: dict, prefix: str = "") -> str:
    """Minimal dict-to-TOML serializer (flat sections only, no nested tables)."""
    lines: list[str] = []
    scalars = {}
    tables = {}
    for k, v in d.items():
        if isinstance(v, dict):
            tables[k] = v
        else:
            scalars[k] = v
    for k, v in scalars.items():
        lines.append(f"{k} = {_toml_val(v)}")
    for section, vals in tables.items():
        lines.append(f"\n[{prefix}{section}]")
        for k, v in vals.items():
            if isinstance(v, dict):
                # One level of nesting
                lines.append(f"\n[{prefix}{section}.{k}]")
                for k2, v2 in v.items():
                    lines.append(f"{k2} = {_toml_val(v2)}")
            else:
                lines.append(f"{k} = {_toml_val(v)}")
    return "\n".join(lines) + "\n"


def _toml_val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".")
    if isinstance(v, str):
        return f'"{v}"'
    return str(v)


def _fmt_file_size(n: int) -> str:
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _sync_fts(conn: sqlite3.Connection, node_id: str) -> None:
    """Re-sync FTS5 index for a node after update (standalone FTS5 mode).

    P1-3 fix: use BrainDB._ngram() for CJK tokenization consistency.
    Without n-gram tokenization, Chinese/Japanese/Korean text edited via
    WebUI would become unsearchable by sub-word queries.
    """
    try:
        from project_brain.core.brain_db import BrainDB
        conn.execute("DELETE FROM nodes_fts WHERE id=?", (node_id,))
        row = conn.execute(
            "SELECT id, title, content, tags FROM nodes WHERE id=?", (node_id,)
        ).fetchone()
        if row:
            conn.execute(
                "INSERT INTO nodes_fts(id, title, content, tags) VALUES (?,?,?,?)",
                (row["id"],
                 BrainDB._ngram(row["title"] or ""),
                 BrainDB._ngram(row["content"] or ""),
                 row["tags"] or ""),
            )
    except Exception:
        pass  # FTS5 sync is best-effort; main nodes table is authoritative


def _load_staging(workdir: "Path") -> list[dict]:
    """Read pending entries from review_board.db (returns [] if not found)."""
    rb_path = workdir / ".brain" / "review_board.db"
    if not rb_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(rb_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, kind, title, content, confidence, source, submitter, "
            "created_at, review_note FROM staged_nodes WHERE status='pending' "
            "ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        conn.close()
        return [
            {
                "id":         r["id"],
                "kind":       r["kind"] or "Note",
                "title":      r["title"] or "",
                "content":    (r["content"] or "")[:300],
                "confidence": float(r["confidence"] if r["confidence"] is not None else 0.7),
                "source":     r["source"] or "manual",
                "submitter":  r["submitter"] or "",
                "created_at": r["created_at"] or "",
                "color":      KIND_COLOR.get(r["kind"] or "Note", "#94a3b8"),
            }
            for r in rows
        ]
    except Exception:
        return []


# ─────────────────────────────────────────────
# HTML generation — delegates to templates/index.html
# ─────────────────────────────────────────────

def _generate_html(workdir: str = "") -> str:
    """Backward-compatible HTML generator.

    Delegates to _render_template() which reads templates/index.html.
    Kept for test imports and legacy callers.
    """
    return _render_template(workdir)


# ─────────────────────────────────────────────
# Alias for backwards compatibility / test imports (BUG-08 fix)
_generate_graph_html = _generate_html

# Public API
# ─────────────────────────────────────────────

def run_server(workdir, port: int = 7890) -> None:
    """Start the web UI server (blocking, Ctrl+C to stop)."""
    wd = Path(workdir)
    bd = wd / ".brain"
    if not bd.exists():
        raise FileNotFoundError(f"Brain 尚未初始化：{bd}（請先執行 brain setup）")
    _Handler.workdir = wd
    server = HTTPServer((HOST, port), _Handler)
    print(f"\n  🧠  Project Brain Web UI  v{_VERSION}")
    print(f"  知識庫：{bd}")
    print(f"  瀏覽器：\033[96mhttp://{HOST}:{port}\033[0m")
    print(f"  停止：  Ctrl+C\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def create_app(workdir, **_):
    """Return a Flask WSGI app exposing the same endpoints as run_server().

    Primarily useful for testing (``app.test_client()``) and programmatic
    embedding.  Falls back to a thin compatibility shim if Flask is not
    installed.
    """
    try:
        from flask import Flask, jsonify, request, Response as _Resp
    except ImportError:  # Flask not available — legacy shim
        class _Compat:  # type: ignore[no-redef]
            def __init__(self, wd): self._wd = wd
            def run(self, host=HOST, port=7890, **kw): run_server(self._wd, port)
        return _Compat(workdir)

    wd = Path(workdir)
    app = Flask(__name__)

    # ── DB helper ───────────────────────────────────────────────────────
    def _get_db():
        bd = wd / ".brain"
        for name in ("brain.db", "knowledge_graph.db"):
            p = bd / name
            if p.exists():
                conn = sqlite3.connect(str(p), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                return conn
        raise FileNotFoundError(f"找不到資料庫：{bd}/brain.db（請先執行 brain setup）")

    def _col(row, key, default=None):
        try:
            return row[key]
        except (IndexError, KeyError):
            return default

    # ── Routes ──────────────────────────────────────────────────────────
    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "version": _VERSION})

    @app.route("/")
    def index():
        html = _render_template(str(wd))
        return _Resp(html, content_type="text/html; charset=utf-8")

    @app.route("/static/<path:filename>")
    def static_files(filename):
        safe = re.sub(r"[^a-zA-Z0-9._-]", "", filename)[:64]
        fpath = _STATIC_DIR / safe
        if not fpath.exists() or not fpath.is_file():
            return jsonify({"error": "not found"}), 404
        mime = _STATIC_MIME.get(fpath.suffix, "application/octet-stream")
        return _Resp(fpath.read_bytes(), content_type=mime)

    @app.route("/api/graph")
    def api_graph():
        limit = min(MAX_NODES_RETURN, int(request.args.get("limit", 300)))
        kind = request.args.get("kind")
        conn = _get_db()
        try:
            cols = "id, kind, title, content, tags, created_at, confidence, is_pinned, scope"
            try:
                if kind:
                    sk = re.sub(r"[^a-zA-Z]", "", kind)[:20]
                    rows = conn.execute(
                        f"SELECT {cols} FROM nodes WHERE kind=? LIMIT ?", (sk, limit)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"SELECT {cols} FROM nodes LIMIT ?", (limit,)
                    ).fetchall()
            except sqlite3.OperationalError:
                cols2 = "id, type as kind, title, content, tags, created_at, confidence, is_pinned, scope"
                if kind:
                    sk = re.sub(r"[^a-zA-Z]", "", kind)[:20]
                    rows = conn.execute(
                        f"SELECT {cols2} FROM nodes WHERE type=? LIMIT ?", (sk, limit)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"SELECT {cols2} FROM nodes LIMIT ?", (limit,)
                    ).fetchall()

            nodes, node_ids = [], set()
            for r in rows:
                k = _col(r, "kind") or "Note"
                conf = float(_col(r, "confidence") or 0.7)
                nodes.append({
                    "id": r["id"], "kind": k, "title": r["title"] or "",
                    "confidence": conf, "color": KIND_COLOR.get(k, "#94a3b8"),
                    "size": NODE_SIZE.get(k, 9),
                    "is_pinned": bool(_col(r, "is_pinned") or False),
                })
                node_ids.add(r["id"])

            try:
                edge_rows = conn.execute(
                    "SELECT source_id, target_id, relation_type FROM edges LIMIT 2000"
                ).fetchall()
            except sqlite3.OperationalError:
                try:
                    edge_rows = conn.execute(
                        "SELECT source_id, target_id, relation as relation_type FROM edges LIMIT 2000"
                    ).fetchall()
                except Exception:
                    edge_rows = []
        finally:
            conn.close()

        links = [
            {"source": e["source_id"], "target": e["target_id"],
             "relation": _col(e, "relation_type") or "RELATES_TO"}
            for e in edge_rows
            if e["source_id"] in node_ids and e["target_id"] in node_ids
        ]
        return jsonify({"nodes": nodes, "links": links, "edges": links,
                        "total_nodes": len(nodes), "total_links": len(links)})

    @app.route("/api/stats")
    def api_stats():
        conn = _get_db()
        try:
            total = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            try:
                edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            except Exception:
                edges = 0
            try:
                by_kind = conn.execute(
                    "SELECT kind, COUNT(*) cnt, AVG(confidence) avg_conf "
                    "FROM nodes GROUP BY kind ORDER BY cnt DESC"
                ).fetchall()
                low_conf = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE confidence < 0.3"
                ).fetchone()[0]
                pinned = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE is_pinned = 1"
                ).fetchone()[0]
            except sqlite3.OperationalError:
                by_kind = conn.execute(
                    "SELECT type as kind, COUNT(*) cnt FROM nodes GROUP BY type ORDER BY cnt DESC"
                ).fetchall()
                low_conf = pinned = 0
        finally:
            conn.close()
        return jsonify({
            "total_nodes": total, "total_edges": edges,
            "low_confidence": low_conf, "pinned": pinned,
            "by_kind": [
                {"kind": r["kind"] or "Note", "count": r["cnt"],
                 "avg_confidence": round(float(_col(r, "avg_conf") or 0.7), 2)}
                for r in by_kind
            ],
        })

    @app.route("/api/search")
    def api_search():
        q = (request.args.get("q", "") or "")[:MAX_QUERY_LEN].strip()
        if not q:
            return jsonify({"results": []})
        conn = _get_db()
        try:
            try:
                rows = conn.execute(
                    "SELECT id, kind, title, content, confidence FROM nodes "
                    "WHERE title LIKE ? OR content LIKE ? ORDER BY confidence DESC LIMIT 20",
                    (f"%{q}%", f"%{q}%")
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT id, type as kind, title, content FROM nodes "
                    "WHERE title LIKE ? OR content LIKE ? LIMIT 20",
                    (f"%{q}%", f"%{q}%")
                ).fetchall()
        finally:
            conn.close()
        return jsonify({"results": [
            {"id": r["id"], "kind": r["kind"] or "Note", "title": r["title"] or "",
             "excerpt": (r["content"] or "")[:80],
             "confidence": float(_col(r, "confidence") or 0.7),
             "color": KIND_COLOR.get(r["kind"] or "Note", "#94a3b8")}
            for r in rows
        ]})

    @app.route("/api/node/<node_id>")
    def api_node(node_id):
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", node_id)[:64]
        conn = _get_db()
        try:
            try:
                row = conn.execute(
                    "SELECT id, kind, title, content, tags, created_at, "
                    "confidence, is_pinned, scope FROM nodes WHERE id=?", (safe,)
                ).fetchone()
            except sqlite3.OperationalError:
                row = conn.execute(
                    "SELECT id, type as kind, title, content, tags, created_at, "
                    "confidence, is_pinned, scope FROM nodes WHERE id=?", (safe,)
                ).fetchone()
            if not row:
                return jsonify({"error": "節點不存在"}), 404
            try:
                nbrs = conn.execute(
                    "SELECT n.id, n.kind, n.title, e.relation_type "
                    "FROM edges e JOIN nodes n ON e.target_id = n.id "
                    "WHERE e.source_id=? LIMIT 10", (safe,)
                ).fetchall()
            except sqlite3.OperationalError:
                try:
                    nbrs = conn.execute(
                        "SELECT n.id, n.type as kind, n.title, e.relation as relation_type "
                        "FROM edges e JOIN nodes n ON e.target_id = n.id "
                        "WHERE e.source_id=? LIMIT 10", (safe,)
                    ).fetchall()
                except Exception:
                    nbrs = []
        finally:
            conn.close()
        conf = float(_col(row, "confidence") or 0.7)
        k = row["kind"] or "Note"
        return jsonify({
            "id": row["id"], "kind": k, "title": row["title"] or "",
            "content": row["content"] or "", "confidence": conf,
            "conf_label": _conf_label(conf), "conf_color": _conf_color(conf),
            "tags": row["tags"] or "", "created_at": row["created_at"] or "",
            "is_pinned": bool(_col(row, "is_pinned") or False),
            "scope": _col(row, "scope") or "global",
            "color": KIND_COLOR.get(k, "#94a3b8"),
            "neighbors": [
                {"id": n["id"], "kind": n["kind"] or "Note",
                 "title": n["title"] or "", "relation": n["relation_type"] or "",
                 "color": KIND_COLOR.get(n["kind"] or "Note", "#94a3b8")}
                for n in nbrs
            ],
        })

    @app.route("/api/node/<node_id>/pin", methods=["POST"])
    def api_pin(node_id):
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", node_id)[:64]
        body = request.get_json(silent=True) or {}
        pinned = bool(body.get("pinned", True))
        conn = _get_db()
        try:
            cur = conn.execute(
                "UPDATE nodes SET is_pinned=? WHERE id=?", (1 if pinned else 0, safe)
            )
            conn.commit()
            if cur.rowcount == 0:
                return jsonify({"error": "節點不存在"}), 404
        finally:
            conn.close()
        return jsonify({"ok": True, "id": safe, "pinned": pinned})

    @app.route("/api/node/<node_id>", methods=["PATCH"])
    def api_patch_node(node_id):
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", node_id)[:64]
        body = request.get_json(silent=True) or {}
        cols, vals, err = _validate_node_patch(body)
        if err:
            return jsonify({"error": err}), 400
        if not cols:
            return jsonify({"error": "沒有可更新的欄位"}), 400
        conn = _get_db()
        try:
            set_clause = ", ".join(f"{c}=?" for c in cols)
            cur = conn.execute(
                f"UPDATE nodes SET {set_clause} WHERE id=?", vals + [safe]
            )
            if cur.rowcount == 0:
                conn.commit()
                return jsonify({"error": "節點不存在"}), 404
            _sync_fts(conn, safe)
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True, "id": safe})

    @app.route("/api/node/<node_id>", methods=["DELETE"])
    def api_delete_node(node_id):
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", node_id)[:64]
        conn = _get_db()
        try:
            cur = conn.execute("DELETE FROM nodes WHERE id=?", (safe,))
            if cur.rowcount == 0:
                conn.commit()
                return jsonify({"error": "節點不存在"}), 404
            try:
                conn.execute("DELETE FROM nodes_fts WHERE id=?", (safe,))
            except Exception:
                pass
            conn.execute(
                "DELETE FROM edges WHERE source_id=? OR target_id=?", (safe, safe)
            )
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True, "id": safe})

    @app.route("/api/node", methods=["POST"])
    def api_add_node():
        body = request.get_json(silent=True) or {}
        title = str(body.get("title", "")).strip()
        if not title:
            return jsonify({"error": "標題為必填欄位"}), 400
        if len(title) > 500:
            return jsonify({"error": "標題最長 500 字"}), 400
        content = str(body.get("content", "")).strip()
        if not content:
            return jsonify({"error": "內容為必填欄位"}), 400
        if len(content) > 10000:
            return jsonify({"error": "內容最長 10000 字"}), 400
        kind = str(body.get("kind", "Note"))
        if kind not in VALID_KINDS:
            return jsonify({"error": f"類型必須是：{', '.join(sorted(VALID_KINDS))}"}), 400
        try:
            confidence = float(body.get("confidence", 0.7))
        except (TypeError, ValueError):
            return jsonify({"error": "信心度必須是數字"}), 400
        if not (0.0 <= confidence <= 1.0):
            return jsonify({"error": "信心度必須在 0.0~1.0 之間"}), 400

        node_id = f"webui-{hashlib.sha256(f'{title}{time.time()}'.encode()).hexdigest()[:12]}"
        conn = _get_db()
        try:
            conn.execute(
                "INSERT INTO nodes (id, type, title, content, confidence, "
                "is_pinned, created_at, access_count, tags, author) "
                "VALUES (?, ?, ?, ?, ?, 0, datetime('now'), 0, '[]', 'web-ui')",
                (node_id, kind, title, content, round(confidence, 4))
            )
            try:
                from project_brain.core.brain_db import BrainDB
                conn.execute(
                    "INSERT INTO nodes_fts(id, title, content, tags) VALUES (?,?,?,?)",
                    (node_id, BrainDB._ngram(title), BrainDB._ngram(content), "[]")
                )
            except Exception:
                pass
            conn.commit()
        except Exception as exc:
            return jsonify({"error": f"新增失敗：{exc}"}), 500
        finally:
            conn.close()
        return jsonify({"ok": True, "id": node_id}), 201

    @app.route("/api/admin/dashboard")
    def api_admin_dashboard():
        conn = _get_db()
        try:
            total = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            try:
                edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            except Exception:
                edges = 0
            try:
                by_kind = conn.execute(
                    "SELECT kind, COUNT(*) cnt FROM nodes GROUP BY kind ORDER BY cnt DESC"
                ).fetchall()
            except sqlite3.OperationalError:
                by_kind = conn.execute(
                    "SELECT type as kind, COUNT(*) cnt FROM nodes GROUP BY type ORDER BY cnt DESC"
                ).fetchall()
            kind_dist = {r["kind"] or "Note": r["cnt"] for r in by_kind}
            try:
                low_conf = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE confidence < 0.3"
                ).fetchone()[0]
            except Exception:
                low_conf = 0
            try:
                conflicts = conn.execute(
                    "SELECT COUNT(*) FROM edges WHERE relation_type = 'CONTRADICTS'"
                ).fetchone()[0]
            except Exception:
                conflicts = 0
            activity = {"today": 0, "week": 0, "month": 0}
            try:
                activity["today"] = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE created_at >= date('now')"
                ).fetchone()[0]
                activity["week"] = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE created_at >= date('now', '-7 days')"
                ).fetchone()[0]
                activity["month"] = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE created_at >= date('now', '-30 days')"
                ).fetchone()[0]
            except Exception:
                pass
            krb_pending = 0
            try:
                rb_path = wd / ".brain" / "review_board.db"
                if rb_path.exists():
                    rb_conn = sqlite3.connect(str(rb_path))
                    krb_pending = rb_conn.execute(
                        "SELECT COUNT(*) FROM staged_nodes WHERE status='pending'"
                    ).fetchone()[0]
                    rb_conn.close()
            except Exception:
                pass
            signal_pending = 0
            try:
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}
                if "signal_queue" in tables:
                    signal_pending = conn.execute(
                        "SELECT COUNT(*) FROM signal_queue WHERE status='pending'"
                    ).fetchone()[0]
            except Exception:
                pass
            health_warnings = (1 if low_conf > 0 else 0) + (1 if conflicts > 0 else 0)
        finally:
            conn.close()
        return jsonify({
            "total_nodes": total, "total_edges": edges,
            "kind_distribution": kind_dist,
            "low_confidence_count": low_conf, "conflicts": conflicts,
            "activity": activity,
            "krb_pending": krb_pending, "signal_pending": signal_pending,
            "health": {
                "status": "warn" if health_warnings > 0 else "ok",
                "errors": 0, "warnings": health_warnings,
            },
        })

    @app.route("/api/admin/audit-log")
    def api_admin_audit_log():
        days = min(365, max(1, int(request.args.get("days", 30))))
        author_q = (request.args.get("author", "") or "").strip()[:100]
        action_q = (request.args.get("action", "") or "").strip()[:20]
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(100, max(1, int(request.args.get("page_size", 50))))

        entries: list[dict] = []
        conn = _get_db()
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if "node_history" in tables:
                nh_cols = {r[1] for r in conn.execute("PRAGMA table_info(node_history)").fetchall()}
                ct_col = "change_type" if "change_type" in nh_cols else "'update' as change_type"
                cb_col = "changed_by" if "changed_by" in nh_cols else "'' as changed_by"
                cn_col = "change_note" if "change_note" in nh_cols else "'' as change_note"
                rows = conn.execute(
                    f"SELECT node_id, title, {ct_col}, {cb_col}, {cn_col}, snapshot_at "
                    f"FROM node_history WHERE snapshot_at >= datetime('now', '-{days} days') "
                    f"ORDER BY snapshot_at DESC"
                ).fetchall()
                for r in rows:
                    actor = r["changed_by"] or ""
                    if author_q and author_q.lower() not in actor.lower():
                        continue
                    act = r["change_type"] or "update"
                    if action_q and action_q != act:
                        continue
                    entries.append({
                        "time": r["snapshot_at"] or "", "actor": actor,
                        "action": act, "node_id": r["node_id"],
                        "title": r["title"] or "",
                        "detail": r["change_note"] or "", "source": "node_history",
                    })
        finally:
            conn.close()

        # KRB staged_nodes
        rb_path = wd / ".brain" / "review_board.db"
        if rb_path.exists():
            try:
                rb_conn = sqlite3.connect(str(rb_path))
                rb_conn.row_factory = sqlite3.Row
                rb_rows = rb_conn.execute(
                    "SELECT id, kind, title, status, submitter, reviewer, "
                    "created_at, reviewed_at, review_note FROM staged_nodes "
                    "ORDER BY created_at DESC"
                ).fetchall()
                rb_conn.close()
                for r in rb_rows:
                    sub = r["submitter"] or ""
                    if not (author_q and author_q.lower() not in sub.lower()):
                        if not (action_q and action_q != "submit"):
                            entries.append({
                                "time": r["created_at"] or "", "actor": sub,
                                "action": "submit", "node_id": r["id"],
                                "title": r["title"] or "",
                                "detail": f"kind={r['kind']}, status={r['status']}",
                                "source": "krb",
                            })
                    if r["reviewed_at"]:
                        rev = r["reviewer"] or ""
                        if not (author_q and author_q.lower() not in rev.lower()):
                            act_type = "approve" if r["status"] == "approved" else "reject"
                            if not (action_q and action_q != act_type):
                                entries.append({
                                    "time": r["reviewed_at"], "actor": rev,
                                    "action": act_type, "node_id": r["id"],
                                    "title": r["title"] or "",
                                    "detail": r["review_note"] or "",
                                    "source": "krb",
                                })
            except Exception:
                pass

        entries.sort(key=lambda e: e.get("time", ""), reverse=True)
        total = len(entries)
        offset = (page - 1) * page_size
        return jsonify({
            "entries": entries[offset:offset + page_size],
            "total": total, "page": page, "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size else 1,
        })

    @app.route("/api/admin/settings")
    def api_admin_settings():
        bd = wd / ".brain"
        result: dict = {
            "mode": "standalone", "embedding": "LocalTFIDF",
            "llm": "\u672a\u8a2d\u5b9a", "schema_version": 0,
            "services": [], "storage": {}, "config": {}, "has_toml": False,
        }
        _default_cfg = {
            "decay_enabled": True, "decay_interval_hours": 24,
            "pipeline_enabled": True, "pipeline_worker_interval": 60,
            "pipeline_max_auto_confidence": 0.85,
            "review_auto_approve_threshold": 0.80, "review_staging_ttl_days": 30,
            "brain_max_context_tokens": 6000, "brain_freshness_warn_days": 30,
            "brain_dedup_threshold": 0.85,
        }
        toml_path = bd / "brain.toml"
        if toml_path.exists():
            result["has_toml"] = True
            try:
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib  # type: ignore[no-redef]
                cfg = tomllib.loads(toml_path.read_text(encoding="utf-8"))
                result["mode"] = cfg.get("mode", "standalone")
                result["embedding"] = cfg.get("embedding", {}).get("provider", "LocalTFIDF")
                result["llm"] = cfg.get("llm", {}).get("provider", "\u672a\u8a2d\u5b9a")
                result["config"] = {
                    "decay_enabled": cfg.get("decay", {}).get("enabled", True),
                    "decay_interval_hours": cfg.get("decay", {}).get("run_interval_hours", 24),
                    "pipeline_enabled": cfg.get("pipeline", {}).get("enabled", True),
                    "pipeline_worker_interval": cfg.get("pipeline", {}).get("worker_interval_seconds", 60),
                    "pipeline_max_auto_confidence": cfg.get("pipeline", {}).get("max_auto_confidence", 0.85),
                    "review_auto_approve_threshold": cfg.get("review", {}).get("auto_approve_threshold", 0.80),
                    "review_staging_ttl_days": cfg.get("review", {}).get("staging_ttl_days", 30),
                    "brain_max_context_tokens": cfg.get("brain", {}).get("max_context_tokens", 6000),
                    "brain_freshness_warn_days": cfg.get("brain", {}).get("freshness_warn_days", 30),
                    "brain_dedup_threshold": cfg.get("brain", {}).get("dedup_threshold", 0.85),
                }
            except Exception:
                result["config"] = dict(_default_cfg)
        else:
            result["config"] = dict(_default_cfg)
        db_path = bd / "brain.db"
        if not db_path.exists():
            result["services"].append({"name": "brain.db", "status": "error", "detail": "not found"})
            return jsonify(result)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            try:
                row = conn.execute(
                    "SELECT value FROM brain_meta WHERE key='schema_version'"
                ).fetchone()
                if row:
                    result["schema_version"] = int(row[0])
            except Exception:
                pass
            try:
                nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                result["services"].append({"name": "brain.db", "status": "ok", "detail": f"{nodes} nodes"})
            except Exception as e:
                result["services"].append({"name": "brain.db", "status": "error", "detail": str(e)})
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if "api_keys" in tables:
                try:
                    active = conn.execute(
                        "SELECT COUNT(*) FROM api_keys WHERE is_revoked=0"
                    ).fetchone()[0]
                    result["services"].append({
                        "name": "Central Brain", "status": "ok" if active > 0 else "warn",
                        "detail": f"{active} active keys",
                    })
                except Exception:
                    pass
            else:
                result["services"].append({"name": "Central Brain", "status": "ok", "detail": "\u672a\u8a2d\u5b9a"})
        finally:
            conn.close()
        try:
            result["storage"]["brain_db"] = _fmt_file_size(db_path.stat().st_size)
            backup_dir = bd / "backups"
            if backup_dir.exists():
                backups = list(backup_dir.glob("brain.db.*"))
                total_size = sum(f.stat().st_size for f in backups)
                result["storage"]["backups"] = f"{len(backups)} \u4efd / {_fmt_file_size(total_size)}"
            else:
                result["storage"]["backups"] = "\u7121\u5099\u4efd"
        except Exception:
            pass
        return jsonify(result)

    @app.route("/api/admin/settings", methods=["POST"])
    def api_save_settings():
        bd = wd / ".brain"
        toml_path = bd / "brain.toml"
        existing: dict = {}
        if toml_path.exists():
            try:
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib  # type: ignore[no-redef]
                existing = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        body = request.get_json(silent=True) or {}
        cfg = body.get("config", {})
        if not cfg:
            return jsonify({"error": "\u6c92\u6709\u8981\u5132\u5b58\u7684\u8a2d\u5b9a"}), 400
        # Apply
        for section, key, cfgkey, conv in [
            ("decay", "enabled", "decay_enabled", bool),
            ("decay", "run_interval_hours", "decay_interval_hours", int),
            ("pipeline", "enabled", "pipeline_enabled", bool),
            ("pipeline", "worker_interval_seconds", "pipeline_worker_interval", int),
            ("pipeline", "max_auto_confidence", "pipeline_max_auto_confidence", float),
            ("review", "auto_approve_threshold", "review_auto_approve_threshold", float),
            ("review", "staging_ttl_days", "review_staging_ttl_days", int),
            ("brain", "max_context_tokens", "brain_max_context_tokens", int),
            ("brain", "freshness_warn_days", "brain_freshness_warn_days", int),
            ("brain", "dedup_threshold", "brain_dedup_threshold", float),
        ]:
            if cfgkey in cfg:
                existing.setdefault(section, {})[key] = conv(cfg[cfgkey])
        try:
            toml_path.write_text(_dict_to_toml(existing), encoding="utf-8")
        except Exception as exc:
            return jsonify({"error": f"儲存失敗：{exc}"}), 500
        return jsonify({"ok": True})

    @app.route("/api/staging")
    def api_staging():
        items = _load_staging(wd)
        return jsonify({"staging": items, "total": len(items)})

    @app.route("/api/staging/<staging_id>/approve", methods=["POST"])
    def api_staging_approve(staging_id):
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", staging_id)[:64]
        body = request.get_json(silent=True) or {}
        note = str(body.get("note", ""))[:500]
        try:
            from project_brain.engines.review_board import KnowledgeReviewBoard
            from project_brain.graph import KnowledgeGraph
            bd = wd / ".brain"
            g = KnowledgeGraph(bd)
            krb = KnowledgeReviewBoard(bd, g)
            krb.approve(safe, reviewer="web-ui", note=note)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify({"ok": True, "id": safe, "action": "approve"})

    @app.route("/api/staging/<staging_id>/reject", methods=["POST"])
    def api_staging_reject(staging_id):
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", staging_id)[:64]
        body = request.get_json(silent=True) or {}
        note = str(body.get("note", ""))[:500]
        try:
            from project_brain.engines.review_board import KnowledgeReviewBoard
            from project_brain.graph import KnowledgeGraph
            bd = wd / ".brain"
            g = KnowledgeGraph(bd)
            krb = KnowledgeReviewBoard(bd, g)
            krb.reject(safe, reviewer="web-ui", reason=note or "web-ui reject")
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify({"ok": True, "id": safe, "action": "reject"})

    return app


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--workdir", default=os.getcwd())
    p.add_argument("--port", type=int, default=7890)
    a = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    run_server(a.workdir, a.port)
