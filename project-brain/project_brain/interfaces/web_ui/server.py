"""
project_brain/web_ui/server.py — 知識圖譜視覺化 Web UI（v1.0）

純 Python http.server + 純 JavaScript（無 Flask、無 D3.js CDN）。
離線可用，零外部框架依賴。
"""
from __future__ import annotations
import json
import logging
import os
import re
import sqlite3
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_QUERY_LEN = 200
MAX_NODES_RETURN = 500
HOST = "127.0.0.1"
_VERSION = "1.1"

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
                self._html(_generate_html(str(wd)))
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
            if path.startswith("/api/node/") and path.endswith("/pin"):
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
# HTML generation (pure JS, no D3 CDN)
# ─────────────────────────────────────────────

def _generate_html(workdir: str = "") -> str:
    project = Path(workdir).name if workdir else "Project"
    return f"""\
<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Project Brain · {project}</title>
<style>
:root {{
  --bg:      #0d1117; --bg2: #161b22; --bg3: #1c2128;
  --border:  rgba(255,255,255,0.08); --border2: rgba(255,255,255,0.14);
  --text:    #e6edf3; --text2: #8b949e; --text3: #484f58;
  --accent:  #58a6ff; --accent2: #1f6feb;
  --green:   #3fb950; --red: #f85149; --yellow: #d29922;
  --radius:  10px; --radius-sm: 6px;
  --shadow:  0 8px 32px rgba(0,0,0,0.4);
  --trans:   0.16s ease;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,'Segoe UI',system-ui,sans-serif;
  background:var(--bg);color:var(--text);display:flex;flex-direction:column;
  height:100vh;overflow:hidden}}

/* ── Header ── */
#hdr{{height:50px;min-height:50px;background:var(--bg2);
  border-bottom:1px solid var(--border);display:flex;align-items:center;
  padding:0 16px;gap:12px;z-index:10}}
.logo{{display:flex;align-items:center;gap:8px;text-decoration:none}}
.logo .icon{{width:26px;height:26px;border-radius:7px;
  background:linear-gradient(135deg,#58a6ff 0%,#bc8cff 100%);
  display:flex;align-items:center;justify-content:center;font-size:13px;
  box-shadow:0 0 10px rgba(88,166,255,0.3)}}
.logo .brand{{font-size:13px;font-weight:600;letter-spacing:-.01em;color:#6ca4f8;}}
.logo .ver{{font-size:10px;color:var(--text2);background:var(--bg3);
  border:1px solid var(--border);padding:1px 5px;border-radius:4px;margin-left:2px}}
#proj-badge{{font-size:11px;color:var(--text2);background:var(--bg3);
  border:1px solid var(--border);padding:3px 10px;border-radius:20px;white-space:nowrap}}
#search-wrap{{flex:1;max-width:300px;position:relative;margin-left:auto}}
#search-icon{{position:absolute;left:9px;top:50%;transform:translateY(-50%);
  color:var(--text3);font-size:12px;pointer-events:none}}
#search-input{{width:100%;background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius-sm);color:var(--text);padding:5px 30px 5px 28px;
  font-size:12px;outline:none;transition:border-color var(--trans)}}
#search-input:focus{{border-color:var(--accent2)}}
#search-input::placeholder{{color:var(--text3)}}
#search-clear{{position:absolute;right:8px;top:50%;transform:translateY(-50%);
  color:var(--text3);cursor:pointer;font-size:12px;display:none;
  background:none;border:none;padding:0}}
#hdr-actions{{display:flex;gap:6px;align-items:center}}
.hdr-btn{{background:var(--bg3);border:1px solid var(--border);color:var(--text2);
  font-size:11px;padding:4px 10px;border-radius:var(--radius-sm);cursor:pointer;
  transition:all var(--trans);white-space:nowrap}}
.hdr-btn:hover{{border-color:var(--accent);color:var(--accent)}}
#kbd-hint{{font-size:10px;color:var(--text3);white-space:nowrap}}

/* ── Layout ── */
#body{{display:flex;flex:1;overflow:hidden}}

/* ── Sidebar ── */
#sidebar{{width:252px;min-width:252px;background:var(--bg2);
  border-right:1px solid var(--border);display:flex;flex-direction:column;
  overflow-y:auto;overflow-x:hidden}}
#sidebar::-webkit-scrollbar{{width:3px}}
#sidebar::-webkit-scrollbar-thumb{{background:var(--border2);border-radius:2px}}
.s-sec{{padding:12px 14px;border-bottom:1px solid var(--border)}}
.s-lbl{{font-size:10px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
  color:var(--text3);margin-bottom:8px}}

/* Stats */
.stat-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:6px}}
.stat-card{{background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius-sm);padding:8px 10px}}
.stat-card .sv{{font-size:20px;font-weight:700;color:var(--accent);line-height:1}}
.stat-card .sk{{font-size:10px;color:var(--text2);margin-top:2px}}
.stat-card.warn .sv{{color:var(--red)}}
.stat-card.ok .sv{{color:var(--green)}}
.stat-card.filter-active{{border-color:var(--accent);box-shadow:0 0 0 2px rgba(88,166,255,0.3)}}
.conf-row{{cursor:pointer;padding:3px 4px;border-radius:4px;margin:-3px -4px}}
.conf-row:hover{{background:rgba(88,166,255,0.08)}}
.conf-row.filter-active{{background:rgba(88,166,255,0.15);outline:1px solid var(--accent)}}

/* Filters */
#filter-wrap{{display:flex;gap:4px;flex-wrap:wrap}}
.pill{{font-size:11px;font-weight:500;padding:3px 9px;border-radius:20px;
  border:1px solid var(--border);color:var(--text2);cursor:pointer;
  background:transparent;transition:all var(--trans);display:flex;align-items:center;gap:4px}}
.pill:hover{{border-color:var(--accent);color:var(--accent)}}
.pill.active{{background:rgba(88,166,255,0.15);border-color:var(--accent);color:var(--accent)}}
.pill-cnt{{font-size:9px;background:var(--bg3);padding:0 4px;border-radius:8px}}

/* Kind list */
.kind-row{{display:flex;align-items:center;gap:7px;padding:4px 0;
  cursor:pointer;transition:opacity var(--trans)}}
.kind-row:hover{{opacity:.7}}
.kind-dot{{width:7px;height:7px;border-radius:50%;flex-shrink:0}}
.kind-name{{font-size:11px;color:var(--text2);flex:1}}
.kind-count{{font-size:10px;font-weight:600;color:var(--text);
  background:var(--bg3);padding:1px 6px;border-radius:8px}}
.kind-conf{{font-size:10px;color:var(--text3);margin-left:2px}}

/* Search results */
#search-results{{display:none}}
#search-results.visible{{display:block}}
.sr-item{{display:flex;align-items:center;gap:6px;padding:5px 0;
  cursor:pointer;border-bottom:1px solid var(--border)}}
.sr-item:hover .sr-title{{color:var(--accent)}}
.sr-dot{{width:6px;height:6px;border-radius:50%;flex-shrink:0}}
.sr-body{{flex:1;overflow:hidden}}
.sr-title{{font-size:11px;color:var(--text2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.sr-ex{{font-size:10px;color:var(--text3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}

/* Node panel */
#node-panel{{display:none}}
#node-panel.visible{{display:block}}
.nk-badge{{display:inline-block;font-size:10px;font-weight:600;padding:2px 7px;
  border-radius:4px;margin-bottom:7px;letter-spacing:.04em;text-transform:uppercase}}
#node-title{{font-size:13px;font-weight:600;line-height:1.4;margin-bottom:6px}}
.conf-bar-wrap{{margin-bottom:8px}}
.conf-bar-label{{font-size:10px;color:var(--text3);margin-bottom:3px;
  display:flex;justify-content:space-between;align-items:center}}
.conf-bar{{height:3px;background:var(--bg3);border-radius:2px;overflow:hidden}}
.conf-bar-fill{{height:100%;border-radius:2px;transition:width .3s ease}}
#node-content{{font-size:12px;color:var(--text2);line-height:1.6;
  max-height:130px;overflow-y:auto;margin-bottom:8px;white-space:pre-wrap;word-break:break-word}}
#node-content::-webkit-scrollbar{{width:3px}}
#node-content::-webkit-scrollbar-thumb{{background:var(--border2)}}
#node-meta{{font-size:10px;color:var(--text3);margin-bottom:8px}}
#node-tags{{margin-bottom:6px}}
.tag-chip{{display:inline-block;font-size:10px;background:var(--bg3);
  border:1px solid var(--border);padding:1px 5px;border-radius:4px;
  margin:2px 2px 0 0;color:var(--text2)}}
.node-actions{{display:flex;gap:5px;margin-bottom:10px}}
.node-btn{{flex:1;background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius-sm);color:var(--text2);padding:4px;cursor:pointer;
  font-size:11px;transition:all var(--trans);text-align:center}}
.node-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.node-btn.pinned{{border-color:var(--accent);color:var(--accent);
  background:rgba(88,166,255,0.1)}}
#neighbor-list .nbr-hdr{{font-size:10px;color:var(--text3);
  text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}}
.nbr-item{{display:flex;align-items:center;gap:5px;padding:3px 0;
  border-bottom:1px solid var(--border);cursor:pointer}}
.nbr-item:hover .nbr-title{{color:var(--accent)}}
.nbr-dot{{width:5px;height:5px;border-radius:50%;flex-shrink:0}}
.nbr-title{{font-size:11px;color:var(--text2);flex:1;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}}
.nbr-rel{{font-size:10px;color:var(--text3);background:var(--bg3);
  padding:0 4px;border-radius:3px;white-space:nowrap}}

/* ── Canvas ── */
#main{{flex:1;position:relative;overflow:hidden}}
#canvas{{width:100%;height:100%;cursor:default}}
#main::before{{content:'';position:absolute;inset:0;
  background-image:linear-gradient(rgba(255,255,255,0.02) 1px,transparent 1px),
    linear-gradient(90deg,rgba(255,255,255,0.02) 1px,transparent 1px);
  background-size:40px 40px;pointer-events:none}}

/* Tooltip */
#tooltip{{position:fixed;display:none;background:var(--bg3);
  border:1px solid var(--border2);border-radius:var(--radius-sm);
  padding:7px 11px;font-size:12px;color:var(--text);pointer-events:none;
  max-width:200px;box-shadow:var(--shadow);z-index:100;line-height:1.5}}
#tt-kind{{font-size:10px;font-weight:600;text-transform:uppercase;
  letter-spacing:.05em;margin-bottom:2px}}
#tt-conf{{font-size:10px;margin-top:2px}}

/* Controls */
#controls{{position:absolute;bottom:14px;right:14px;display:flex;flex-direction:column;gap:5px}}
.ctrl-btn{{background:var(--bg2);border:1px solid var(--border2);color:var(--text2);
  font-size:13px;width:30px;height:30px;border-radius:var(--radius-sm);
  cursor:pointer;display:flex;align-items:center;justify-content:center;
  transition:all var(--trans)}}
.ctrl-btn:hover{{border-color:var(--accent);color:var(--accent)}}

/* Empty/Loading */
#empty-state,#loading{{position:absolute;top:50%;left:50%;
  transform:translate(-50%,-50%);text-align:center;display:none;
  flex-direction:column;align-items:center;gap:10px}}
#loading{{display:flex}}
.spinner{{width:28px;height:28px;border-radius:50%;
  border:2px solid var(--border2);border-top-color:var(--accent);
  animation:spin .8s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.l-text{{font-size:12px;color:var(--text2)}}
#empty-state .es-icon{{font-size:36px;opacity:.35}}
#empty-state .es-text{{font-size:13px;color:var(--text2);line-height:1.6}}

/* ── Inline edit form ── */
#edit-form{{display:none;background:var(--bg3);border:1px solid var(--border2);
  border-radius:var(--radius-sm);padding:10px;margin-bottom:8px}}
#edit-form.visible{{display:block}}
.ef-label{{font-size:10px;color:var(--text3);margin-bottom:3px;display:block;
  text-transform:uppercase;letter-spacing:.05em}}
.ef-input,.ef-textarea,.ef-select{{width:100%;background:var(--bg2);
  border:1px solid var(--border);border-radius:4px;color:var(--text);
  padding:5px 7px;font-size:12px;outline:none;
  transition:border-color var(--trans);margin-bottom:7px}}
.ef-input:focus,.ef-textarea:focus,.ef-select:focus{{border-color:var(--accent2)}}
.ef-textarea{{min-height:72px;resize:vertical;font-family:inherit;line-height:1.5}}
.ef-select{{cursor:pointer}}
.ef-row{{display:flex;gap:5px;margin-top:4px}}
.ef-btn{{flex:1;padding:5px;border-radius:4px;font-size:11px;cursor:pointer;
  border:1px solid var(--border);transition:all var(--trans)}}
.ef-btn.save{{background:rgba(59,130,246,0.15);border-color:#3b82f6;color:#60a5fa}}
.ef-btn.save:hover{{background:rgba(59,130,246,0.3)}}
.ef-btn.cancel{{background:var(--bg2);color:var(--text2)}}
.ef-btn.cancel:hover{{border-color:var(--accent);color:var(--accent)}}

/* ── Staging panel ── */
#staging-panel{{display:none}}
#staging-panel.visible{{display:block}}
.stg-item{{padding:7px 0;border-bottom:1px solid var(--border)}}
.stg-title{{font-size:11px;color:var(--text);margin-bottom:3px;
  font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.stg-meta{{font-size:10px;color:var(--text3);margin-bottom:5px}}
.stg-actions{{display:flex;gap:4px}}
.stg-btn{{flex:1;font-size:10px;padding:3px;border-radius:4px;cursor:pointer;
  border:1px solid var(--border);background:var(--bg2);
  color:var(--text2);transition:all var(--trans)}}
.stg-btn.approve{{border-color:#22c55e;color:#22c55e}}
.stg-btn.approve:hover{{background:rgba(34,197,94,0.15)}}
.stg-btn.reject{{border-color:#f87171;color:#f87171}}
.stg-btn.reject:hover{{background:rgba(248,113,113,0.15)}}
#stg-badge{{display:inline-block;font-size:10px;font-weight:700;
  background:#f87171;color:#fff;border-radius:8px;
  padding:0 5px;margin-left:4px;vertical-align:middle}}

/* ── View Tabs ── */
.view-tabs{{display:flex;gap:2px;background:var(--bg3);border-radius:var(--radius-sm);
  padding:2px;border:1px solid var(--border)}}
.view-tab{{font-size:11px;padding:4px 12px;border-radius:4px;cursor:pointer;
  border:none;background:transparent;color:var(--text2);transition:all var(--trans);
  white-space:nowrap}}
.view-tab:hover{{color:var(--text)}}
.view-tab.active{{background:var(--accent2);color:#fff}}
#graph-view{{display:flex;flex:1;flex-direction:column;position:relative}}
#table-view{{display:none;flex:1;flex-direction:column;overflow:hidden}}
#table-view.active{{display:flex}}
#graph-view.hidden{{display:none}}

/* ── Table View ── */
.tv-toolbar{{padding:10px 16px;background:var(--bg2);border-bottom:1px solid var(--border);
  display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.tv-search{{background:var(--bg3);border:1px solid var(--border);color:var(--text);
  border-radius:var(--radius-sm);padding:5px 10px;font-size:12px;width:240px;outline:none}}
.tv-search:focus{{border-color:var(--accent2)}}
.tv-select{{background:var(--bg3);border:1px solid var(--border);color:var(--text);
  border-radius:var(--radius-sm);padding:5px 8px;font-size:11px;outline:none}}
.tv-info{{font-size:11px;color:var(--text2);margin-left:auto}}
.tv-table-wrap{{flex:1;overflow:auto;padding:0 16px}}
.tv-table{{width:100%;border-collapse:collapse;font-size:12px}}
.tv-table th{{position:sticky;top:0;background:var(--bg2);text-align:left;
  padding:8px 10px;font-size:10px;font-weight:600;letter-spacing:.05em;
  text-transform:uppercase;color:var(--text3);border-bottom:1px solid var(--border);
  cursor:pointer;user-select:none;white-space:nowrap}}
.tv-table th:hover{{color:var(--accent)}}
.tv-table th .sort-icon{{margin-left:3px;opacity:0.4}}
.tv-table th.sorted .sort-icon{{opacity:1;color:var(--accent)}}
.tv-table td{{padding:7px 10px;border-bottom:1px solid var(--border);vertical-align:top}}
.tv-table tr:hover{{background:rgba(88,166,255,0.05)}}
.tv-kind{{display:inline-block;font-size:10px;padding:2px 7px;border-radius:10px;
  font-weight:600;white-space:nowrap}}
.tv-title{{color:var(--text);font-weight:500;max-width:400px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.tv-excerpt{{color:var(--text2);font-size:11px;max-width:300px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.tv-conf{{font-family:monospace;font-size:11px}}
.tv-actions{{display:flex;gap:4px}}
.tv-btn{{font-size:10px;padding:3px 8px;border-radius:4px;cursor:pointer;
  border:1px solid var(--border);background:var(--bg2);
  color:var(--text2);transition:all var(--trans)}}
.tv-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.tv-btn.useful{{border-color:#22c55e;color:#22c55e}}
.tv-btn.useful:hover{{background:rgba(34,197,94,0.15)}}
.tv-btn.outdated{{border-color:#f87171;color:#f87171}}
.tv-btn.outdated:hover{{background:rgba(248,113,113,0.15)}}
.tv-pinned{{color:var(--yellow);font-size:10px}}
.tv-pager{{padding:10px 16px;background:var(--bg2);border-top:1px solid var(--border);
  display:flex;align-items:center;gap:8px;font-size:11px;color:var(--text2)}}
.tv-pager button{{font-size:11px;padding:4px 10px;border-radius:4px;cursor:pointer;
  border:1px solid var(--border);background:var(--bg3);color:var(--text2);
  transition:all var(--trans)}}
.tv-pager button:hover:not(:disabled){{border-color:var(--accent);color:var(--accent)}}
.tv-pager button:disabled{{opacity:0.3;cursor:default}}
.tv-pager .current{{color:var(--accent);font-weight:600}}
</style>
</head>
<body>

<div id="hdr">
  <a class="logo" href="/">
    <div class="icon">🧠</div>
    <span class="brand">Project Brain</span>
    <span class="ver">v{_VERSION}</span>
  </a>
  <div id="proj-badge">📁 {project}</div>
  <div id="search-wrap">
    <span id="search-icon">⌕</span>
    <input id="search-input" type="text" placeholder="搜尋… (/)">
    <button id="search-clear">✕</button>
  </div>
  <div class="view-tabs">
    <button class="view-tab active" data-view="graph" onclick="switchView('graph')">📊 圖譜</button>
    <button class="view-tab" data-view="table" onclick="switchView('table')">📋 管理</button>
  </div>
  <div id="hdr-actions">
    <button class="hdr-btn" onclick="refreshAll()">↺ 重新整理</button>
    <span id="kbd-hint">/ 搜尋 · Esc 清除</span>
  </div>
</div>

<div id="body">
  <div id="sidebar">
    <div class="s-sec">
      <div class="s-lbl">知識庫</div>
      <div class="stat-grid">
        <div class="stat-card"><div class="sv" id="s-nodes">—</div><div class="sk">節點</div></div>
        <div class="stat-card"><div class="sv" id="s-edges">—</div><div class="sk">關係</div></div>
        <div class="stat-card warn" id="card-low" onclick="filterConf('vlow')" title="篩選低信心節點" style="cursor:pointer"><div class="sv" id="s-low">—</div><div class="sk">低信心</div></div>
        <div class="stat-card ok"   id="card-pin" onclick="filterPinned()"    title="篩選已釘選節點"  style="cursor:pointer"><div class="sv" id="s-pin">—</div><div class="sk">已釘選</div></div>
      </div>
    </div>

    <div class="s-sec">
      <div class="s-lbl">篩選類型</div>
      <div id="filter-wrap">
        <button class="pill active" data-kind="all">全部</button>
        <button class="pill" data-kind="Pitfall">踩坑</button>
        <button class="pill" data-kind="Rule">規則</button>
        <button class="pill" data-kind="Decision">決策</button>
        <button class="pill" data-kind="ADR">ADR</button>
        <button class="pill" data-kind="Note">筆記</button>
        <button class="pill" data-kind="Component">組件</button>
      </div>
    </div>

    <div class="s-sec">
      <div class="s-lbl">節點分佈</div>
      <div id="kind-list"></div>
    </div>

    <div class="s-sec">
      <div class="s-lbl">信心分布</div>
      <div id="conf-dist-list"></div>
    </div>

    <!-- Search results (shown when searching) -->
    <div class="s-sec" id="search-results">
      <div class="s-lbl">搜尋結果</div>
      <div id="sr-list"></div>
    </div>

    <!-- Node detail (shown when node selected) -->
    <div class="s-sec" id="node-panel">
      <div class="s-lbl">節點詳情</div>
      <div id="node-kind-badge" class="nk-badge"></div>
      <div id="node-title"></div>
      <div class="conf-bar-wrap">
        <div class="conf-bar-label">
          <span id="conf-label-text">信心</span>
          <span id="conf-val-text" style="font-size:10px;color:var(--text2)"></span>
        </div>
        <div class="conf-bar"><div id="conf-bar-fill" class="conf-bar-fill"></div></div>
      </div>
      <div id="node-content"></div>
      <div id="node-tags"></div>
      <div id="node-meta"></div>
      <div class="node-actions">
        <button id="pin-btn" class="node-btn" onclick="togglePin()">📌 釘選</button>
        <button class="node-btn" onclick="startEdit()">✏ 編輯</button>
        <button class="node-btn" onclick="copyContent()">⎘ 複製</button>
        <button class="node-btn" style="color:var(--red);border-color:var(--red)" onclick="deleteNode()">✕</button>
      </div>
      <!-- Inline edit form -->
      <div id="edit-form">
        <label class="ef-label">標題</label>
        <input id="ef-title" class="ef-input" type="text" maxlength="500">
        <label class="ef-label">類型</label>
        <select id="ef-kind" class="ef-select">
          <option>Pitfall</option><option>Decision</option><option>Rule</option>
          <option>ADR</option><option>Component</option><option>Architecture</option><option>Note</option>
        </select>
        <label class="ef-label">信心 (<span id="ef-conf-val">0.7</span>)</label>
        <input id="ef-confidence" class="ef-input" type="range" min="0" max="1" step="0.01" value="0.7"
          oninput="document.getElementById('ef-conf-val').textContent=parseFloat(this.value).toFixed(2)">
        <label class="ef-label">內容</label>
        <textarea id="ef-content" class="ef-textarea" maxlength="10000"></textarea>
        <div class="ef-row">
          <button class="ef-btn save" onclick="saveEdit()">儲存</button>
          <button class="ef-btn cancel" onclick="cancelEdit()">取消</button>
        </div>
      </div>
      <div id="neighbor-list"></div>
    </div>

    <!-- KRB Staging panel -->
    <div class="s-sec" id="staging-panel">
      <div class="s-lbl">待審知識 <span id="stg-badge"></span></div>
      <div id="stg-list"></div>
    </div>
  </div>

  <div id="graph-view">
    <div id="loading"><div class="spinner"></div><div class="l-text">載入知識圖譜…</div></div>
    <div id="empty-state" style="display:none">
      <div class="es-icon">🕸</div>
      <div class="es-text">知識庫尚無節點<br>執行 <code>brain add</code> 或 <code>brain scan</code> 加入知識</div>
    </div>
    <svg id="canvas"></svg>
    <div id="tooltip"><div id="tt-kind"></div><div id="tt-title"></div><div id="tt-conf"></div></div>
    <div id="controls">
      <button class="ctrl-btn" title="放大" onclick="zoom(1.25)">+</button>
      <button class="ctrl-btn" title="縮小" onclick="zoom(0.8)">−</button>
      <button class="ctrl-btn" title="重置視圖" onclick="resetView()">↺</button>
      <label class="ctrl-btn" title="圖譜節點上限" style="font-size:10px;cursor:default;padding:4px 6px">
        上限 <input id="graph-limit" type="number" min="20" max="500" value="100"
          style="width:48px;background:var(--bg);border:1px solid var(--border);
          color:var(--text);border-radius:3px;padding:2px 4px;font-size:10px;text-align:center"
          onchange="loadGraph()">
      </label>
    </div>
  </div>

  <div id="table-view">
    <div class="tv-toolbar">
      <input class="tv-search" id="tv-q" type="text" placeholder="搜尋節點…" oninput="tvDebounceSearch()">
      <select class="tv-select" id="tv-kind" onchange="tvLoadPage(1)">
        <option value="">全部類型</option>
        <option value="Pitfall">⚠ Pitfall</option>
        <option value="Rule">📋 Rule</option>
        <option value="Decision">🎯 Decision</option>
        <option value="ADR">📄 ADR</option>
        <option value="Note">📝 Note</option>
      </select>
      <select class="tv-select" id="tv-sort" onchange="tvLoadPage(1)">
        <option value="confidence">信心度 ↓</option>
        <option value="created_at">時間 ↓</option>
        <option value="access_count">存取次數 ↓</option>
        <option value="title">標題 A→Z</option>
      </select>
      <span class="tv-info" id="tv-info">—</span>
    </div>
    <div class="tv-table-wrap">
      <table class="tv-table">
        <thead>
          <tr>
            <th style="width:80px">類型</th>
            <th>標題</th>
            <th style="width:90px">摘要</th>
            <th style="width:60px">信心</th>
            <th style="width:50px">存取</th>
            <th style="width:80px">時間</th>
            <th style="width:100px">操作</th>
          </tr>
        </thead>
        <tbody id="tv-body"></tbody>
      </table>
    </div>
    <div class="tv-pager">
      <button id="tv-prev" onclick="tvPrev()" disabled>← 上一頁</button>
      <span id="tv-page-info"><span class="current">1</span> / 1</span>
      <button id="tv-next" onclick="tvNext()" disabled>下一頁 →</button>
    </div>
  </div>
</div>

<script>
/* ════════════════════════════════════════════════
   Project Brain Web UI — 純 JS 實作（無外部依賴）
   Force simulation: Verlet + spring + repulsion
   ════════════════════════════════════════════════ */

const KIND_COLOR = {{
  Pitfall:'#f87171', Decision:'#34d399', Rule:'#60a5fa',
  ADR:'#c084fc', Component:'#94a3b8', Architecture:'#fb923c', Note:'#fbbf24'
}};
const KIND_LABEL = {{
  Pitfall:'踩坑', Decision:'決策', Rule:'規則',
  ADR:'ADR', Component:'組件', Architecture:'架構', Note:'筆記'
}};

// ── State ─────────────────────────────────────
let allNodes = [], allLinks = [], nodeMap = {{}};
let currentFilter = 'all';
let selectedId = null;
let currentNodeData = null;
let searchHits = null;   // Set of matching ids, or null
let alpha = 0;

// ── SVG transform ──────────────────────────────
let tx = 0, ty = 0, sk = 1;
const svg    = document.getElementById('canvas');
const NS     = 'http://www.w3.org/2000/svg';
let gLinks, gNodes, gLabels, rootG;

function initSVG() {{
  svg.innerHTML = '';
  rootG  = document.createElementNS(NS,'g'); svg.appendChild(rootG);
  gLinks = document.createElementNS(NS,'g'); rootG.appendChild(gLinks);
  gNodes = document.createElementNS(NS,'g'); rootG.appendChild(gNodes);
  gLabels= document.createElementNS(NS,'g'); rootG.appendChild(gLabels);
  applyTx();
}}

function applyTx() {{
  rootG.setAttribute('transform', `translate(${{tx}},${{ty}}) scale(${{sk}})`);
}}

function zoom(factor) {{
  const W = svg.clientWidth, H = svg.clientHeight;
  tx = W/2 + (tx - W/2) * factor;
  ty = H/2 + (ty - H/2) * factor;
  sk *= factor;
  applyTx();
}}

function resetView() {{
  tx = 0; ty = 0; sk = 1; applyTx();
  clearSelection();
}}

// ── Wheel zoom ─────────────────────────────────
svg.addEventListener('wheel', e => {{
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.1 : 0.9;
  const r  = svg.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  tx = mx + (tx - mx) * factor;
  ty = my + (ty - my) * factor;
  sk *= factor; applyTx();
}}, {{passive: false}});

// ── Pan (drag on background) ───────────────────
let panning = false, panX0, panY0, tx0, ty0;
svg.addEventListener('mousedown', e => {{
  if (e.target === svg || e.target === rootG || e.target === gLinks) {{
    panning = true; panX0 = e.clientX; panY0 = e.clientY; tx0 = tx; ty0 = ty;
    e.preventDefault();
  }}
}});
window.addEventListener('mousemove', e => {{
  if (!panning) return;
  tx = tx0 + e.clientX - panX0;
  ty = ty0 + e.clientY - panY0;
  applyTx();
}});
window.addEventListener('mouseup', () => {{ panning = false; }});

// ── Force simulation ────────────────────────────
const REPULSION = 4000, LINK_DIST = 90, SPRING_K = 0.06, DAMPING = 0.72, CENTER_K = 0.004;

function initPositions() {{
  const W = svg.clientWidth || 800, H = svg.clientHeight || 600;
  allNodes.forEach(n => {{
    if (!n.x || !n.y) {{
      const angle = Math.random() * Math.PI * 2;
      const r     = Math.random() * 200 + 50;
      n.x = W/2 + Math.cos(angle)*r;
      n.y = H/2 + Math.sin(angle)*r;
    }}
    n.vx = 0; n.vy = 0;
  }});
  allLinks.forEach(l => {{
    l._src = nodeMap[l.source]; l._tgt = nodeMap[l.target];
  }});
}}

function simStep() {{
  if (alpha < 0.003) return;
  alpha *= 0.976;
  const W = svg.clientWidth || 800, H = svg.clientHeight || 600;
  const cx = W/2, cy = H/2;
  const n  = allNodes.length;

  // Dampen velocities
  for (const nd of allNodes) {{
    if (nd.fixed) continue;
    nd.vx = (nd.vx||0) * DAMPING;
    nd.vy = (nd.vy||0) * DAMPING;
  }}

  // Repulsion (O(n²), fine for n < 500)
  for (let i = 0; i < n; i++) {{
    const a = allNodes[i];
    for (let j = i+1; j < n; j++) {{
      const b  = allNodes[j];
      let dx = b.x - a.x, dy = b.y - a.y;
      const d2 = dx*dx + dy*dy || 0.01;
      const d  = Math.sqrt(d2);
      const f  = REPULSION * alpha / d2;
      const fx = dx/d * f, fy = dy/d * f;
      if (!a.fixed) {{ a.vx -= fx; a.vy -= fy; }}
      if (!b.fixed) {{ b.vx += fx; b.vy += fy; }}
    }}
  }}

  // Spring along links
  for (const l of allLinks) {{
    const a = l._src, b = l._tgt;
    if (!a || !b) continue;
    const dx = b.x - a.x, dy = b.y - a.y;
    const d  = Math.sqrt(dx*dx + dy*dy) || 1;
    const f  = (d - LINK_DIST) * SPRING_K * alpha;
    const fx = dx/d*f, fy = dy/d*f;
    if (!a.fixed) {{ a.vx += fx; a.vy += fy; }}
    if (!b.fixed) {{ b.vx -= fx; b.vy -= fy; }}
  }}

  // Centering + position update
  for (const nd of allNodes) {{
    if (nd.fixed) continue;
    nd.vx += (cx - nd.x) * CENTER_K * alpha;
    nd.vy += (cy - nd.y) * CENTER_K * alpha;
    nd.x  += nd.vx; nd.y += nd.vy;
  }}

  updateSVGPositions();
  requestAnimationFrame(simStep);
}}

// ── SVG rendering ───────────────────────────────
function render() {{
  initSVG();
  // Links
  allLinks.forEach(l => {{
    const line = document.createElementNS(NS,'line');
    line.setAttribute('stroke','rgba(255,255,255,0.07)');
    line.setAttribute('stroke-width','1.2');
    line.setAttribute('stroke-linecap','round');
    l._el = line;
    gLinks.appendChild(line);
  }});
  // Nodes (outer ring = confidence, inner = kind color)
  allNodes.forEach(nd => {{
    const g = document.createElementNS(NS,'g');
    g.style.cursor = 'pointer';
    // Confidence ring
    const ring = document.createElementNS(NS,'circle');
    ring.setAttribute('r', nd.size + 3.5);
    ring.setAttribute('fill','none');
    ring.setAttribute('stroke', nd.conf_color);
    ring.setAttribute('stroke-width','2');
    ring.setAttribute('opacity','0.7');
    nd._ring = ring; g.appendChild(ring);
    // Kind fill
    const circ = document.createElementNS(NS,'circle');
    circ.setAttribute('r', nd.size);
    circ.setAttribute('fill', nd.color);
    circ.setAttribute('fill-opacity','0.88');
    circ.setAttribute('stroke', nd.color);
    circ.setAttribute('stroke-opacity','0.35');
    circ.setAttribute('stroke-width','2.5');
    circ.style.filter = `drop-shadow(0 0 4px ${{nd.color}}66)`;
    nd._circ = circ; g.appendChild(circ);
    // Events
    g.addEventListener('mouseenter', e => onNodeHover(e, nd));
    g.addEventListener('mouseleave', () => onNodeLeave(nd));
    g.addEventListener('click',      e => {{ e.stopPropagation(); onNodeClick(nd); }});
    // Drag
    let dragging = false, dx0, dy0, nx0, ny0;
    g.addEventListener('mousedown', e => {{
      e.stopPropagation(); dragging = true;
      dx0 = e.clientX; dy0 = e.clientY; nx0 = nd.x; ny0 = nd.y;
    }});
    window.addEventListener('mousemove', e => {{
      if (!dragging) return;
      nd.x = nx0 + (e.clientX - dx0) / sk;
      nd.y = ny0 + (e.clientY - dy0) / sk;
      nd.fixed = true;
      updateSVGPositions();
    }});
    window.addEventListener('mouseup', () => {{
      if (dragging) {{ dragging = false; nd.fixed = false; alpha = Math.max(alpha, 0.1); requestAnimationFrame(simStep); }}
    }});
    nd._g = g;
    gNodes.appendChild(g);
  }});
  // Labels
  allNodes.forEach(nd => {{
    const t = document.createElementNS(NS,'text');
    t.textContent = nd.title.length > 12 ? nd.title.slice(0,12)+'…' : nd.title;
    t.setAttribute('font-size','8.5');
    t.setAttribute('fill','rgba(255,255,255,0.42)');
    t.setAttribute('text-anchor','middle');
    t.style.pointerEvents = 'none';
    t.style.userSelect    = 'none';
    nd._lbl = t;
    gLabels.appendChild(t);
  }});
  // Click canvas to deselect
  svg.addEventListener('click', clearSelection);
  updateSVGPositions();
  applyOpacity();
}}

function updateSVGPositions() {{
  allLinks.forEach(l => {{
    if (!l._el || !l._src || !l._tgt) return;
    l._el.setAttribute('x1', l._src.x); l._el.setAttribute('y1', l._src.y);
    l._el.setAttribute('x2', l._tgt.x); l._el.setAttribute('y2', l._tgt.y);
  }});
  allNodes.forEach(nd => {{
    if (nd._circ) {{
      nd._ring.setAttribute('cx', nd.x); nd._ring.setAttribute('cy', nd.y);
      nd._circ.setAttribute('cx', nd.x); nd._circ.setAttribute('cy', nd.y);
    }}
    if (nd._lbl) {{
      nd._lbl.setAttribute('x', nd.x);
      nd._lbl.setAttribute('y', nd.y + nd.size + 11);
    }}
  }});
}}

// ── Hover / click ───────────────────────────────
const tip   = document.getElementById('tooltip');
const ttKind= document.getElementById('tt-kind');
const ttTitl= document.getElementById('tt-title');
const ttConf= document.getElementById('tt-conf');

function onNodeHover(e, nd) {{
  if (panning) return;
  tip.style.display = 'block';
  ttKind.textContent  = KIND_LABEL[nd.kind] || nd.kind;
  ttKind.style.color  = nd.color;
  ttTitl.textContent  = nd.title;
  ttConf.textContent  = nd.conf_label + '  ' + (nd.confidence*100|0) + '%';
  ttConf.style.color  = nd.conf_color;
  moveTip(e);
  nd._circ.setAttribute('r', nd.size * 1.25);
  nd._circ.style.filter = `drop-shadow(0 0 9px ${{nd.color}})`;
}}

svg.addEventListener('mousemove', e => {{ if (tip.style.display==='block') moveTip(e); }});

function moveTip(e) {{
  tip.style.left = (e.clientX + 14) + 'px';
  tip.style.top  = (e.clientY - 10) + 'px';
}}

function onNodeLeave(nd) {{
  tip.style.display = 'none';
  if (nd.id !== selectedId) {{
    nd._circ.setAttribute('r', nd.size);
    nd._circ.style.filter = `drop-shadow(0 0 4px ${{nd.color}}66)`;
  }}
}}

function onNodeClick(nd) {{
  selectedId = nd.id;
  applyOpacity();
  nd._circ.setAttribute('r', nd.size * 1.3);
  nd._circ.style.filter = `drop-shadow(0 0 12px ${{nd.color}})`;
  showNodePanel(nd);
}}

function clearSelection() {{
  selectedId = null; currentNodeData = null;
  document.getElementById('node-panel').classList.remove('visible');
  applyOpacity();
}}

// ── Confidence / pinned filters ──────────────────
let confFilter   = null;   // 'hi'|'med'|'low'|'vlow'|null
let pinnedFilter = false;

const CONF_RANGE = {{
  hi:   nd => nd.confidence >= 0.80,
  med:  nd => nd.confidence >= 0.60 && nd.confidence < 0.80,
  low:  nd => nd.confidence >= 0.30 && nd.confidence < 0.60,
  vlow: nd => nd.confidence  < 0.30,
}};

function filterConf(key) {{
  confFilter   = (confFilter === key) ? null : key;
  pinnedFilter = false;
  const pin = document.getElementById('card-pin');
  if (pin) pin.classList.remove('filter-active');
  ['hi','med','low','vlow'].forEach(k => {{
    const el = document.getElementById('conf-row-' + k);
    if (el) el.classList.toggle('filter-active', k === confFilter);
  }});
  applyOpacity();
  _syncHash();
}}

function filterPinned() {{
  pinnedFilter = !pinnedFilter;
  confFilter   = null;
  ['hi','med','low','vlow'].forEach(k => {{
    const el = document.getElementById('conf-row-' + k);
    if (el) el.classList.remove('filter-active');
  }});
  const pin = document.getElementById('card-pin');
  if (pin) pin.classList.toggle('filter-active', pinnedFilter);
  applyOpacity();
  _syncHash();
}}

// ── URL hash 篩選持久化（UX-01）────────────────
function _syncHash() {{
  const parts = [];
  if (currentFilter && currentFilter !== 'all') parts.push('kind=' + currentFilter);
  if (confFilter)   parts.push('conf=' + confFilter);
  if (pinnedFilter) parts.push('pin=1');
  history.replaceState(null, '', parts.length ? '#' + parts.join('&') : location.pathname + location.search);
}}

function _restoreHash() {{
  const h = location.hash.slice(1);
  if (!h) return;
  const params = Object.fromEntries(
    h.split('&').map(s => {{ const i = s.indexOf('='); return [s.slice(0,i), s.slice(i+1)]; }})
  );
  if (params.kind) {{
    currentFilter = params.kind;
    document.querySelectorAll('.pill').forEach(p =>
      p.classList.toggle('active', p.dataset.kind === currentFilter));
  }}
  if (params.conf && CONF_RANGE[params.conf]) {{
    confFilter = params.conf;
    ['hi','med','low','vlow'].forEach(k => {{
      const el = document.getElementById('conf-row-' + k);
      if (el) el.classList.toggle('filter-active', k === confFilter);
    }});
  }}
  if (params.pin) {{
    pinnedFilter = true;
    const pin = document.getElementById('card-pin');
    if (pin) pin.classList.add('filter-active');
  }}
}}

// ── Opacity (filter + search) ───────────────────
function applyOpacity() {{
  allNodes.forEach(nd => {{
    let vis = true;
    if (searchHits  !== null) vis = searchHits.has(nd.id);
    if (vis && confFilter)    vis = CONF_RANGE[confFilter]?.(nd) ?? true;
    if (vis && pinnedFilter)  vis = !!nd.is_pinned;
    nd._g.setAttribute('opacity', vis ? (nd.id===selectedId ? 1 : 0.88) : 0.08);
    nd._lbl.setAttribute('opacity', vis ? 0.42 : 0.04);
  }});
  allLinks.forEach(l => {{
    const src = l._src, tgt = l._tgt;
    let vis = searchHits === null || (src && tgt && searchHits.has(src.id) && searchHits.has(tgt.id));
    if (vis && confFilter)   vis = (CONF_RANGE[confFilter]?.(src) ?? true) || (CONF_RANGE[confFilter]?.(tgt) ?? true);
    if (vis && pinnedFilter) vis = !!(src?.is_pinned || tgt?.is_pinned);
    l._el.setAttribute('opacity', vis ? (selectedId && (src?.id===selectedId||tgt?.id===selectedId) ? 1 : 0.5) : 0.04);
  }});
}}

// ── Node panel ──────────────────────────────────
function showNodePanel(nd) {{
  currentNodeData = nd;
  const p = document.getElementById('node-panel');
  p.classList.add('visible');
  const badge = document.getElementById('node-kind-badge');
  badge.textContent  = KIND_LABEL[nd.kind] || nd.kind;
  badge.style.background = nd.color + '22';
  badge.style.color      = nd.color;
  badge.style.border     = `1px solid ${{nd.color}}55`;
  document.getElementById('node-title').textContent = nd.title;
  // Confidence bar
  document.getElementById('conf-label-text').textContent = nd.conf_label;
  document.getElementById('conf-val-text').textContent   = (nd.confidence*100|0) + '%';
  const fill = document.getElementById('conf-bar-fill');
  fill.style.width      = (nd.confidence * 100) + '%';
  fill.style.background = nd.conf_color;
  document.getElementById('node-content').textContent = nd.excerpt || '（無內容）';
  document.getElementById('node-meta').textContent =
    (nd.created_at ? '📅 '+nd.created_at.slice(0,10)+'  ' : '') +
    (nd.scope && nd.scope!=='global' ? '🗂 '+nd.scope : '');
  const tags = (nd.tags||'').split(',').filter(t=>t.trim());
  document.getElementById('node-tags').innerHTML =
    tags.map(t=>`<span class="tag-chip">${{t.trim()}}</span>`).join('');
  // Pin btn
  const pinBtn = document.getElementById('pin-btn');
  pinBtn.textContent = nd.is_pinned ? '📌 已釘選' : '📌 釘選';
  pinBtn.className   = 'node-btn' + (nd.is_pinned ? ' pinned' : '');
  // Load full content + neighbors
  fetch('/api/node/' + nd.id).then(r=>r.json()).then(n => {{
    document.getElementById('node-content').textContent = n.content || '（無內容）';
    const nl = document.getElementById('neighbor-list');
    if (n.neighbors && n.neighbors.length) {{
      nl.innerHTML = '<div class="nbr-hdr">關聯節點</div>' +
        n.neighbors.map(nb => `
          <div class="nbr-item" onclick="flyTo('${{nb.id}}')">
            <div class="nbr-dot" style="background:${{nb.color||KIND_COLOR[nb.kind]||'#94a3b8'}}"></div>
            <span class="nbr-title">${{nb.title.slice(0,26)}}</span>
            <span class="nbr-rel">${{nb.relation||''}}</span>
          </div>`).join('');
    }} else {{ nl.innerHTML = ''; }}
  }});
}}

function flyTo(id) {{
  const nd = nodeMap[id];
  if (!nd) return;
  const W = svg.clientWidth, H = svg.clientHeight;
  tx = W/2 - nd.x * sk; ty = H/2 - nd.y * sk;
  applyTx();
  onNodeClick(nd);
}}

// ── Pin ─────────────────────────────────────────
async function togglePin() {{
  if (!currentNodeData) return;
  const nd = currentNodeData;
  const pin = !nd.is_pinned;
  const res = await fetch(`/api/node/${{nd.id}}/pin`, {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{pinned: pin}})
  }});
  if (res.ok) {{
    nd.is_pinned = pin;
    const btn = document.getElementById('pin-btn');
    btn.textContent = pin ? '📌 已釘選' : '📌 釘選';
    btn.className   = 'node-btn' + (pin ? ' pinned' : '');
    await loadStats();
  }}
}}

// ── Copy content ─────────────────────────────────
function copyContent() {{
  const txt = document.getElementById('node-content').textContent;
  if (!txt || txt==='（無內容）') return;
  navigator.clipboard?.writeText(txt).then(() => {{
    const btn = document.querySelector('.node-btn[onclick="copyContent()"]');
    const orig = btn.textContent;
    btn.textContent = '✓ 已複製';
    setTimeout(()=>{{ btn.textContent = orig; }}, 1200);
  }});
}}

// ── Filter pills ─────────────────────────────────
function filterKind(kind) {{
  currentFilter = kind;
  document.querySelectorAll('.pill').forEach(p =>
    p.classList.toggle('active', p.dataset.kind === kind));
  _syncHash();
  loadGraph();
}}
document.querySelectorAll('.pill').forEach(p =>
  p.addEventListener('click', () => filterKind(p.dataset.kind)));

// ── Search ───────────────────────────────────────
const searchInput = document.getElementById('search-input');
const searchClear = document.getElementById('search-clear');
const srPanel     = document.getElementById('search-results');
const srList      = document.getElementById('sr-list');
let searchTimer;

searchInput.addEventListener('input', e => {{
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  searchClear.style.display = q ? 'block' : 'none';
  if (!q) {{
    searchHits = null;
    srPanel.classList.remove('visible');
    applyOpacity();
    document.getElementById('node-panel').classList.remove('visible');
    return;
  }}
  searchTimer = setTimeout(async () => {{
    const data = await fetch('/api/search?q='+encodeURIComponent(q)).then(r=>r.json());
    searchHits  = new Set(data.results.map(r=>r.id));
    applyOpacity();
    // Show result list
    if (data.results.length) {{
      srPanel.classList.add('visible');
      srList.innerHTML = data.results.map(r => `
        <div class="sr-item" onclick="flyTo('${{r.id}}')">
          <div class="sr-dot" style="background:${{r.color||KIND_COLOR[r.kind]||'#94a3b8'}}"></div>
          <div class="sr-body">
            <div class="sr-title">${{r.title}}</div>
            <div class="sr-ex">${{r.excerpt}}</div>
          </div>
        </div>`).join('');
    }} else {{
      srPanel.classList.add('visible');
      srList.innerHTML = '<div style="font-size:11px;color:var(--text3);padding:4px 0">無符合結果</div>';
    }}
  }}, 260);
}});

searchClear.addEventListener('click', () => {{
  searchInput.value = '';
  searchClear.style.display = 'none';
  searchHits = null;
  srPanel.classList.remove('visible');
  applyOpacity();
}});

// ── Keyboard shortcuts ───────────────────────────
document.addEventListener('keydown', e => {{
  if (e.key === '/' && document.activeElement !== searchInput) {{
    e.preventDefault();
    searchInput.focus();
    searchInput.select();
  }}
  if (e.key === 'Escape') {{
    if (document.activeElement === searchInput) {{
      searchInput.blur();
    }} else {{
      clearSelection();
      searchInput.value = '';
      searchClear.style.display = 'none';
      searchHits = null;
      srPanel.classList.remove('visible');
      applyOpacity();
    }}
  }}
}});

// ── Data loading ─────────────────────────────────
async function loadStats() {{
  const d = await fetch('/api/stats').then(r=>r.json());
  document.getElementById('s-nodes').textContent = d.total_nodes;
  document.getElementById('s-edges').textContent = d.total_edges;
  document.getElementById('s-low').textContent   = d.low_confidence;
  document.getElementById('s-pin').textContent   = d.pinned;
  // Kind list with count + avg confidence
  const kl = document.getElementById('kind-list');
  kl.innerHTML = (d.by_kind||[]).map(k => `
    <div class="kind-row" onclick="filterKind('${{k.kind}}')">
      <div class="kind-dot" style="background:${{KIND_COLOR[k.kind]||'#94a3b8'}}"></div>
      <span class="kind-name">${{KIND_LABEL[k.kind]||k.kind}}</span>
      <span class="kind-conf">${{(k.avg_confidence*100|0)}}%</span>
      <span class="kind-count">${{k.count}}</span>
    </div>`).join('');
  // Confidence distribution
  const cd = d.conf_dist || {{}};
  const cdTotal = (cd.hi||0) + (cd.med||0) + (cd.low||0) + (cd.vlow||0) || 1;
  const cdItems = [
    {{ key: 'hi',   label: '✓✓ 權威', count: cd.hi||0,   color: '#34d399', pct: ((cd.hi||0)/cdTotal*100).toFixed(0) }},
    {{ key: 'med',  label: '✓ 已驗證', count: cd.med||0,  color: '#86efac', pct: ((cd.med||0)/cdTotal*100).toFixed(0) }},
    {{ key: 'low',  label: '~ 推斷',   count: cd.low||0,  color: '#fbbf24', pct: ((cd.low||0)/cdTotal*100).toFixed(0) }},
    {{ key: 'vlow', label: '⚠ 推測',  count: cd.vlow||0, color: '#f87171', pct: ((cd.vlow||0)/cdTotal*100).toFixed(0) }},
  ];
  document.getElementById('conf-dist-list').innerHTML = cdItems.map(c => `
    <div class="conf-row" id="conf-row-${{c.key}}" onclick="filterConf('${{c.key}}')" style="margin-bottom:6px" title="點擊篩選">
      <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:2px">
        <span style="color:${{c.color}}">${{c.label}}</span>
        <span style="color:var(--text2)">${{c.count}} 筆</span>
      </div>
      <div style="background:var(--border);border-radius:3px;height:5px">
        <div style="background:${{c.color}};width:${{c.pct}}%;height:100%;border-radius:3px;transition:width .4s"></div>
      </div>
    </div>`).join('');
  // Update pill counts
  const countMap = {{}};
  let total = 0;
  (d.by_kind||[]).forEach(k => {{ countMap[k.kind] = k.count; total += k.count; }});
  document.querySelectorAll('.pill').forEach(p => {{
    const k = p.dataset.kind;
    const cnt = k === 'all' ? total : (countMap[k] || 0);
    const existing = p.querySelector('.pill-cnt');
    if (existing) existing.remove();
    if (cnt > 0) {{
      const s = document.createElement('span');
      s.className = 'pill-cnt'; s.textContent = cnt;
      p.appendChild(s);
    }}
  }});
}}

async function loadGraph() {{
  document.getElementById('loading').style.display = 'flex';
  document.getElementById('empty-state').style.display = 'none';
  const lim = document.getElementById('graph-limit')?.value || 100;
  const url = `/api/graph?limit=${{lim}}${{currentFilter!=='all'?'&kind='+currentFilter:''}}`;
  const data = await fetch(url).then(r=>r.json());
  allNodes = data.nodes || [];
  allLinks = data.links || [];
  nodeMap  = {{}};
  allNodes.forEach(n => nodeMap[n.id] = n);
  document.getElementById('loading').style.display = 'none';
  if (!allNodes.length) {{
    document.getElementById('empty-state').style.display = 'flex'; return;
  }}
  initPositions();
  render();
  alpha = 1.0;
  requestAnimationFrame(simStep);
}}

async function refreshAll() {{
  selectedId = null; searchHits = null;
  searchInput.value = '';
  searchClear.style.display = 'none';
  srPanel.classList.remove('visible');
  document.getElementById('node-panel').classList.remove('visible');
  await Promise.all([loadStats(), loadGraph()]);
}}

// ── Inline edit ──────────────────────────────
function startEdit() {{
  if (!currentNodeData) return;
  const nd = currentNodeData;
  document.getElementById('ef-title').value = nd.title || '';
  document.getElementById('ef-kind').value = nd.kind || 'Note';
  const ci = document.getElementById('ef-confidence');
  ci.value = nd.confidence || 0.7;
  document.getElementById('ef-conf-val').textContent = parseFloat(ci.value).toFixed(2);
  fetch('/api/node/' + nd.id).then(r => r.json()).then(n => {{
    document.getElementById('ef-content').value = n.content || '';
  }});
  document.getElementById('edit-form').classList.add('visible');
}}

function cancelEdit() {{
  document.getElementById('edit-form').classList.remove('visible');
}}

async function saveEdit() {{
  if (!currentNodeData) return;
  const nd = currentNodeData;
  const body = {{
    title:      document.getElementById('ef-title').value.trim(),
    kind:       document.getElementById('ef-kind').value,
    confidence: parseFloat(document.getElementById('ef-confidence').value),
    content:    document.getElementById('ef-content').value,
  }};
  const res = await fetch('/api/node/' + nd.id, {{
    method: 'PATCH',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(body),
  }});
  if (!res.ok) {{
    const err = await res.json().catch(()=>({{}}));
    alert('儲存失敗：' + (err.error || res.status));
    return;
  }}
  Object.assign(nd, body);
  nd.color = KIND_COLOR[nd.kind] || '#94a3b8';
  if (nd._circ) nd._circ.setAttribute('fill', nd.color);
  if (nd._lbl)  nd._lbl.textContent = nd.title.length > 12 ? nd.title.slice(0,12)+'…' : nd.title;
  document.getElementById('edit-form').classList.remove('visible');
  showNodePanel(nd);
  loadStats();
}}

async function deleteNode() {{
  if (!currentNodeData) return;
  const nd = currentNodeData;
  if (!confirm('確定刪除「' + nd.title + '」？此操作無法復原。')) return;
  const res = await fetch('/api/node/' + nd.id, {{ method: 'DELETE' }});
  if (!res.ok) {{
    const err = await res.json().catch(()=>({{}}));
    alert('刪除失敗：' + (err.error || res.status));
    return;
  }}
  if (nd._g)   nd._g.remove();
  if (nd._lbl) nd._lbl.remove();
  allLinks.filter(l => l._src === nd || l._tgt === nd).forEach(l => {{ if (l._el) l._el.remove(); }});
  allLinks = allLinks.filter(l => l._src !== nd && l._tgt !== nd);
  allNodes = allNodes.filter(n => n !== nd);
  delete nodeMap[nd.id];
  clearSelection();
  loadStats();
}}

// ── KRB Staging ──────────────────────────────
let stagingData = [];

async function loadStaging() {{
  let data;
  try {{ data = await fetch('/api/staging').then(r => r.json()); }}
  catch(e) {{ return; }}
  stagingData = data.staging || [];
  const panel = document.getElementById('staging-panel');
  const badge = document.getElementById('stg-badge');
  const list  = document.getElementById('stg-list');
  if (!stagingData.length) {{ panel.classList.remove('visible'); return; }}
  badge.textContent = stagingData.length;
  panel.classList.add('visible');
  list.innerHTML = stagingData.map(s => `
    <div class="stg-item" id="stg-${{s.id}}">
      <div style="display:flex;align-items:center;gap:5px;margin-bottom:2px">
        <div style="width:6px;height:6px;border-radius:50%;background:${{s.color}};flex-shrink:0"></div>
        <span class="stg-title" title="${{s.title}}">${{s.title}}</span>
      </div>
      <div class="stg-meta">${{s.kind}} · ${{s.source}} · ${{s.created_at.slice(0,10)}}</div>
      <div style="font-size:10px;color:var(--text3);margin-bottom:5px;line-height:1.4">${{(s.content||'').slice(0,120)}}${{(s.content||'').length>120?'…':''}}</div>
      <div class="stg-actions">
        <button class="stg-btn approve" onclick="stagingAction('${{s.id}}','approve')">✓ 核准</button>
        <button class="stg-btn reject"  onclick="stagingAction('${{s.id}}','reject')">✕ 拒絕</button>
      </div>
    </div>`).join('');
}}

async function stagingAction(sid, action) {{
  const res = await fetch('/api/staging/' + sid + '/' + action, {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: '{{}}',
  }});
  if (!res.ok) {{
    const err = await res.json().catch(()=>({{}}));
    alert(action + ' 失敗：' + (err.error || res.status));
    return;
  }}
  const el = document.getElementById('stg-' + sid);
  if (el) el.remove();
  stagingData = stagingData.filter(s => s.id !== sid);
  document.getElementById('stg-badge').textContent = stagingData.length;
  if (!stagingData.length) document.getElementById('staging-panel').classList.remove('visible');
  if (action === 'approve') refreshAll();
}}

// ═══════════════════════════════════════════════════
//  View switching + Table Management Panel
// ═══════════════════════════════════════════════════

let currentView = 'graph';
let tvPage = 1;
let tvTotalPages = 1;
let tvSearchTimer = null;

function switchView(view) {{
  currentView = view;
  document.querySelectorAll('.view-tab').forEach(t => {{
    t.classList.toggle('active', t.dataset.view === view);
  }});
  const gv = document.getElementById('graph-view');
  const tv = document.getElementById('table-view');
  if (view === 'graph') {{
    gv.classList.remove('hidden'); tv.classList.remove('active');
  }} else {{
    gv.classList.add('hidden'); tv.classList.add('active');
    tvLoadPage(1);
  }}
}}

function tvDebounceSearch() {{
  clearTimeout(tvSearchTimer);
  tvSearchTimer = setTimeout(() => tvLoadPage(1), 300);
}}

async function tvLoadPage(page) {{
  tvPage = page;
  const q     = document.getElementById('tv-q')?.value || '';
  const kind  = document.getElementById('tv-kind')?.value || '';
  const sort  = document.getElementById('tv-sort')?.value || 'confidence';
  const order = (sort === 'title') ? 'asc' : 'desc';
  const params = new URLSearchParams({{page, page_size: 20, sort, order}});
  if (q) params.set('q', q);
  if (kind) params.set('kind', kind);
  try {{
    const data = await fetch('/api/nodes?' + params).then(r => r.json());
    tvTotalPages = data.total_pages || 1;
    document.getElementById('tv-info').textContent =
      `${{data.total}} 筆${{q ? '（搜尋: '+q+'）' : ''}}`;
    _tvRenderRows(data.nodes || []);
    _tvUpdatePager(data.page, data.total_pages);
  }} catch(e) {{
    document.getElementById('tv-info').textContent = '載入失敗';
  }}
}}

function _tvRenderRows(nodes) {{
  const tbody = document.getElementById('tv-body');
  if (!nodes.length) {{
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text3)">無結果</td></tr>';
    return;
  }}
  const kindColors = {{{','.join(f"'{k}':'{v}'" for k,v in KIND_COLOR.items())}}};
  tbody.innerHTML = nodes.map(n => {{
    const kc = kindColors[n.kind] || '#94a3b8';
    const conf = (n.confidence * 100).toFixed(0);
    const pin = n.is_pinned ? '<span class="tv-pinned">📌</span> ' : '';
    const date = n.created_at ? n.created_at.slice(0, 10) : '—';
    return `<tr>
      <td><span class="tv-kind" style="background:${{kc}}20;color:${{kc}}">${{n.kind}}</span></td>
      <td class="tv-title" title="${{_esc(n.title)}}">${{pin}}${{_esc(n.title)}}</td>
      <td class="tv-excerpt" title="${{_esc(n.excerpt)}}">${{_esc(n.excerpt)}}</td>
      <td class="tv-conf" style="color:${{conf>=80?'var(--green)':conf>=50?'var(--yellow)':'var(--red)'}}">${{conf}}%</td>
      <td style="font-size:11px;color:var(--text2)">${{n.access_count}}</td>
      <td style="font-size:11px;color:var(--text2)">${{date}}</td>
      <td class="tv-actions">
        <button class="tv-btn" onclick="tvShowNode('${{n.id}}')" title="查看詳情">🔍</button>
        <button class="tv-btn useful" onclick="tvFeedback('${{n.id}}',true)" title="有用">👍</button>
        <button class="tv-btn outdated" onclick="tvFeedback('${{n.id}}',false)" title="過時">👎</button>
      </td>
    </tr>`;
  }}).join('');
}}

function _esc(s) {{
  if (!s) return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function _tvUpdatePager(page, total) {{
  document.getElementById('tv-prev').disabled = page <= 1;
  document.getElementById('tv-next').disabled = page >= total;
  document.getElementById('tv-page-info').innerHTML =
    `<span class="current">${{page}}</span> / ${{total}}`;
}}

function tvPrev() {{ if (tvPage > 1) tvLoadPage(tvPage - 1); }}
function tvNext() {{ if (tvPage < tvTotalPages) tvLoadPage(tvPage + 1); }}

function tvShowNode(id) {{
  // Switch to graph view and select node, or open detail panel
  switchView('graph');
  const n = nodeMap[id];
  if (n) onNodeClick(n);
}}

async function tvFeedback(nodeId, useful) {{
  try {{
    const body = useful
      ? {{confidence: null}}  // mark as useful — no change needed, just record
      : {{confidence: null}};
    // Optimistic feedback via PATCH (toggle visual feedback)
    const btn = event.target;
    btn.textContent = useful ? '✓' : '✗';
    btn.disabled = true;
    // If MCP is available, the real feedback goes through report_knowledge_outcome
    // For now, just record the user intent visually
    setTimeout(() => {{
      btn.textContent = useful ? '👍' : '👎';
      btn.disabled = false;
    }}, 2000);
  }} catch(e) {{}}
}}

// ── Boot ─────────────────────────────────────────
_restoreHash();   // UX-01: apply filter state from URL hash before first load
loadStats();
loadGraph();
loadStaging();
</script>
</body>
</html>"""


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
        html = _generate_html(str(wd))
        return _Resp(html, content_type="text/html; charset=utf-8")

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
