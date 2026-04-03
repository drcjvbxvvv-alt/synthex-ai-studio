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
_VERSION = "1.0"

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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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
            elif path == "/api/search":
                self._route_search(qs)
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
            else:
                self._json({"error": "not found"}, 404)
        except Exception:
            logger.exception("POST %s", self.path)
            self._json({"error": "內部錯誤"}, 500)

    # ── API: /api/graph ──────────────────────
    def _route_graph(self, qs):
        limit = min(MAX_NODES_RETURN, int(qs.get("limit", ["300"])[0]))
        kind = qs.get("kind", [None])[0]
        conn = self._db()
        try:
            cols = "id, kind, title, content, tags, created_at, confidence, is_pinned, scope"
            try:
                if kind:
                    sk = re.sub(r"[^a-zA-Z]", "", kind)[:20]
                    rows = conn.execute(
                        f"SELECT {cols} FROM nodes WHERE kind=? LIMIT ?", (
                            sk, limit)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"SELECT {cols} FROM nodes LIMIT ?", (limit,)
                    ).fetchall()
            except sqlite3.OperationalError:
                # legacy schema: 'type' instead of 'kind', no confidence/is_pinned
                cols2 = "id, type as kind, title, content, tags, created_at"
                if kind:
                    sk = re.sub(r"[^a-zA-Z]", "", kind)[:20]
                    rows = conn.execute(
                        f"SELECT {cols2} FROM nodes WHERE type=? LIMIT ?", (
                            sk, limit)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"SELECT {cols2} FROM nodes LIMIT ?", (limit,)
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
                try:
                    erows = conn.execute(
                        f"SELECT source_id, target_id, relation_type FROM edges "
                        f"WHERE source_id IN ({ph}) AND target_id IN ({ph})", ids * 2
                    ).fetchall()
                except sqlite3.OperationalError:
                    erows = conn.execute(
                        f"SELECT source_id, target_id, relation as relation_type FROM edges "
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
        self._json({
            "total_nodes":  total,
            "total_edges":  edges,
            "low_confidence": low_conf,
            "pinned":       pinned,
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

    # ── API: /api/search ─────────────────────
    def _route_search(self, qs):
        q = (qs.get("q", [""])[0] or "")[:MAX_QUERY_LEN].strip()
        if not q:
            self._json({"results": []})
            return
        conn = self._db()
        try:
            try:
                rows = conn.execute(
                    "SELECT id, kind, title, content, confidence FROM nodes "
                    "WHERE title LIKE ? OR content LIKE ? "
                    "ORDER BY confidence DESC LIMIT 20",
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
            try:
                row = conn.execute(
                    "SELECT id, kind, title, content, tags, created_at, "
                    "confidence, is_pinned, scope FROM nodes WHERE id=?", (
                        safe,)
                ).fetchone()
            except sqlite3.OperationalError:
                row = conn.execute(
                    "SELECT id, type as kind, title, content, tags, created_at "
                    "FROM nodes WHERE id=?", (safe,)
                ).fetchone()
            if not row:
                self._json({"error": "節點不存在"}, 404)
                return
            try:
                nbrs = conn.execute(
                    "SELECT n.id, n.kind, n.title, e.relation_type "
                    "FROM edges e JOIN nodes n ON e.target_id = n.id "
                    "WHERE e.source_id=? LIMIT 10", (safe,)
                ).fetchall()
            except sqlite3.OperationalError:
                nbrs = conn.execute(
                    "SELECT n.id, n.type as kind, n.title, e.relation as relation_type "
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
        <div class="stat-card warn"><div class="sv" id="s-low">—</div><div class="sk">低信心</div></div>
        <div class="stat-card ok"><div class="sv" id="s-pin">—</div><div class="sk">已釘選</div></div>
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
        <button class="node-btn" onclick="copyContent()">⎘ 複製</button>
      </div>
      <div id="neighbor-list"></div>
    </div>
  </div>

  <div id="main">
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

// ── Opacity (filter + search) ───────────────────
function applyOpacity() {{
  allNodes.forEach(nd => {{
    let vis = true;
    if (searchHits !== null) vis = searchHits.has(nd.id);
    nd._g.setAttribute('opacity', vis ? (nd.id===selectedId ? 1 : 0.88) : 0.08);
    nd._lbl.setAttribute('opacity', vis ? 0.42 : 0.04);
  }});
  allLinks.forEach(l => {{
    const vis = searchHits === null || (l._src && l._tgt && searchHits.has(l._src.id) && searchHits.has(l._tgt.id));
    l._el.setAttribute('opacity', vis ? (selectedId && (l._src?.id===selectedId||l._tgt?.id===selectedId) ? 1 : 0.5) : 0.04);
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
  const url = `/api/graph?limit=300${{currentFilter!=='all'?'&kind='+currentFilter:''}}`;
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

// ── Boot ─────────────────────────────────────────
loadStats();
loadGraph();
</script>
</body>
</html>"""


# ─────────────────────────────────────────────
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


# Backwards-compat shim for any code that still calls create_app()
def create_app(workdir, **_):
    """Deprecated: use run_server() instead. Returns a callable for CLI compatibility."""
    class _Compat:
        def __init__(self, wd): self._wd = wd
        def run(self, host=HOST, port=7890, **kw): run_server(self._wd, port)
    return _Compat(workdir)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--workdir", default=os.getcwd())
    p.add_argument("--port", type=int, default=7890)
    a = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    run_server(a.workdir, a.port)
