"""
core/brain/web_ui/server.py — 知識圖譜視覺化 Web UI（v1.0）
"""
from __future__ import annotations
import os
import re
import sys
import json
import time
import logging
import argparse
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
MAX_QUERY_LEN = 200
MAX_NODES_RETURN = 500
HOST = "127.0.0.1"

KIND_COLOR = {
    "Pitfall":   "#f87171",   # red-400
    "Decision":  "#34d399",   # emerald-400
    "Rule":      "#60a5fa",   # blue-400
    "ADR":       "#c084fc",   # purple-400
    "Component": "#94a3b8",   # slate-400
    "Architecture": "#fb923c",  # orange-400
}


def _confidence_to_color(conf: float) -> str:
    c = max(0.0, min(1.0, conf))
    if c >= 0.75:
        return "#34d399"
    elif c >= 0.50:
        return "#86efac"
    elif c >= 0.30:
        return "#fbbf24"
    elif c >= 0.15:
        return "#f97316"
    else:
        return "#f87171"


NODE_BASE_SIZE: dict[str, int] = {
    "Component": 14, "Decision": 13, "Pitfall": 12,
    "Rule": 10, "ADR": 13, "Architecture": 13, "Commit": 7, "Person": 9,
}


def create_app(workdir) -> Any:
    workdir = Path(workdir)  # accept str or Path
    try:
        from flask import Flask, jsonify, request, Response
        from flask_cors import CORS
    except ImportError:
        print("⚠ 需要安裝：pip install flask flask-cors")
        sys.exit(1)

    brain_dir = workdir / ".brain"
    db_path = brain_dir / "knowledge_graph.db"
    if not db_path.exists():
        # v10.4: fallback to brain.db
        alt = brain_dir / "brain.db"
        if alt.exists():
            db_path = alt
        else:
            raise FileNotFoundError(
                f"知識庫不存在：{brain_dir}（請先執行 brain setup）"
            )

    app = Flask(__name__)
    CORS(app, origins=["http://localhost:*", "http://127.0.0.1:*"])

    def _db():
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @app.route("/")
    def index():
        # BUG-08 fix: pass resolved POSIX path for cross-platform consistency
        return _generate_graph_html(workdir.resolve().as_posix())

    @app.route("/api/graph")
    def api_graph():
        limit = min(MAX_NODES_RETURN, int(request.args.get("limit", 300)))
        kind = request.args.get("kind", None)
        conn = _db()
        try:
            if kind:
                safe_kind = re.sub(r'[^a-zA-Z]', '', kind)[:20]
                rows = conn.execute(
                    "SELECT id, type as kind, title, content, tags, created_at "
                    "FROM nodes WHERE type=? LIMIT ?", (safe_kind, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, type as kind, title, content, tags, created_at "
                    "FROM nodes LIMIT ?", (limit,)
                ).fetchall()

            node_ids = {r["id"] for r in rows}
            nodes = []
            for r in rows:
                conf = 0.7
                color = KIND_COLOR.get(r["kind"], "#94a3b8")
                nodes.append({
                    "id": r["id"], "kind": r["kind"], "title": r["title"],
                    "color": color, "size": NODE_BASE_SIZE.get(r["kind"], 10),
                    "confidence": conf, "tags": r["tags"] or "",
                    "excerpt": (r["content"] or "")[:200],
                    "created_at": r["created_at"] or "",
                })

            edge_rows = []
            if node_ids:
                ph = ",".join("?" * len(node_ids))
                ids = list(node_ids)
                edge_rows = conn.execute(
                    f"SELECT source_id, target_id, relation as relation_type FROM edges "
                    f"WHERE source_id IN ({ph}) AND target_id IN ({ph})",
                    ids * 2
                ).fetchall()

            links = [{"source": r["source_id"], "target": r["target_id"],
                      "type": r["relation_type"]} for r in edge_rows]
        finally:
            conn.close()

        return jsonify({"nodes": nodes, "links": links,
                        "total_nodes": len(nodes), "total_links": len(links)})

    @app.route("/api/stats")
    def api_stats():
        conn = _db()
        try:
            total = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            by_kind = conn.execute(
                "SELECT type as kind, COUNT(*) as cnt FROM nodes GROUP BY type"
            ).fetchall()
        finally:
            conn.close()
        return jsonify({
            "total_nodes": total, "total_edges": edges,
            "low_confidence": 0, "health_score": 0.85,
            "by_kind": [{"kind": r["kind"], "count": r["cnt"],
                         "avg_confidence": 0.7} for r in by_kind],
        })

    @app.route("/api/search")
    def api_search():
        q = (request.args.get("q", "") or "")[:MAX_QUERY_LEN].strip()
        if not q:
            return jsonify({"results": []})
        conn = _db()
        try:
            rows = conn.execute(
                "SELECT id, type as kind, title, content FROM nodes "
                "WHERE title LIKE ? OR content LIKE ? LIMIT 20",
                (f"%{q}%", f"%{q}%")
            ).fetchall()
        finally:
            conn.close()
        return jsonify({"results": [
            {"id": r["id"], "kind": r["kind"], "title": r["title"],
             "excerpt": (r["content"] or "")[:80]} for r in rows
        ]})

    @app.route("/api/node/<node_id>")
    def api_node(node_id: str):
        safe_id = re.sub(r'[^a-zA-Z0-9_-]', '', node_id)[:64]
        conn = _db()
        try:
            row = conn.execute(
                "SELECT id, type as kind, title, content, tags, created_at "
                "FROM nodes WHERE id=?", (safe_id,)
            ).fetchone()
            if not row:
                return jsonify({"error": "節點不存在"}), 404
            neighbors = conn.execute(
                "SELECT n.id, n.type as kind, n.title, e.relation as relation_type "
                "FROM edges e JOIN nodes n ON e.target_id = n.id "
                "WHERE e.source_id=? LIMIT 10", (safe_id,)
            ).fetchall()
        finally:
            conn.close()
        return jsonify({
            "id": row["id"], "kind": row["kind"], "title": row["title"],
            "content": row["content"] or "", "confidence": 0.7,
            "tags": row["tags"] or "", "created_at": row["created_at"] or "",
            "color": KIND_COLOR.get(row["kind"], "#94a3b8"),
            "neighbors": [{"id": n["id"], "kind": n["kind"],
                           "title": n["title"], "relation": n["relation_type"]}
                          for n in neighbors],
        })

    @app.route("/api/timeline")
    def api_timeline():
        """FEAT-09: 時間軸端點 — 依創建時間排序節點，供時間軸滑桿視覺化使用。"""
        limit = min(MAX_NODES_RETURN, int(request.args.get("limit", 200)))
        kind  = request.args.get("kind", None)
        conn  = _db()
        try:
            if kind:
                safe_kind = re.sub(r"[^a-zA-Z]", "", kind)[:20]
                rows = conn.execute(
                    "SELECT id, type as kind, title, confidence, created_at "
                    "FROM nodes WHERE type=? ORDER BY created_at ASC LIMIT ?",
                    (safe_kind, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, type as kind, title, confidence, created_at "
                    "FROM nodes ORDER BY created_at ASC LIMIT ?",
                    (limit,)
                ).fetchall()
        finally:
            conn.close()
        nodes = [
            {
                "id":          r["id"],
                "title":       r["title"],
                "type":        r["kind"],
                "confidence":  r["confidence"] if r["confidence"] is not None else 0.8,
                "created_at":  r["created_at"] or "",
                "color":       KIND_COLOR.get(r["kind"], "#94a3b8"),
            }
            for r in rows
        ]
        return jsonify({"nodes": nodes, "count": len(nodes)})

    @app.route("/api/decay")
    def api_decay():
        conn = _db()
        try:
            rows = conn.execute(
                "SELECT id, type as kind, title FROM nodes ORDER BY rowid DESC LIMIT 50"
            ).fetchall()
        finally:
            conn.close()
        return jsonify({"threshold": 0.3, "count": len(rows),
                        "nodes": [{"id": r["id"], "kind": r["kind"],
                                   "title": r["title"], "confidence": 0.7} for r in rows]})

    @app.route("/api/node/<node_id>/pin", methods=["POST"])
    def api_pin(node_id: str):
        """釘選 / 取消釘選節點（v6.0）"""
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", node_id)[:64]
        data = request.json or {}
        pinned = bool(data.get("pinned", True))
        imp = data.get("importance", None)
        conn = _db()
        try:
            cur = conn.execute(
                "UPDATE nodes SET is_pinned=? WHERE id=?",
                (1 if pinned else 0, safe_id)
            )
            if imp is not None:
                imp_val = max(0.0, min(1.0, float(imp)))
                conn.execute(
                    "UPDATE nodes SET importance=? WHERE id=?",
                    (imp_val, safe_id)
                )
            conn.commit()
            if cur.rowcount == 0:
                return jsonify({"error": "節點不存在"}), 404
            return jsonify({"ok": True, "id": safe_id, "pinned": pinned})
        finally:
            conn.close()

    @app.route("/api/node/<node_id>/importance", methods=["POST"])
    def api_importance(node_id: str):
        """設定節點重要性分數（v6.0）"""
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", node_id)[:64]
        data = request.json or {}
        imp = max(0.0, min(1.0, float(data.get("importance", 0.5))))
        conn = _db()
        try:
            cur = conn.execute(
                "UPDATE nodes SET importance=? WHERE id=?", (imp, safe_id)
            )
            conn.commit()
            if cur.rowcount == 0:
                return jsonify({"error": "節點不存在"}), 404
            return jsonify({"ok": True, "id": safe_id, "importance": imp})
        finally:
            conn.close()

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "version": "4.0.0"})

    return app


def _generate_graph_html(workdir: str = "") -> str:
    project_name = Path(workdir).name if workdir else "Project"
    return f"""\
<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Project Brain · {project_name}</title>
<style>
:root {{
  --bg:         #0d1117;
  --bg2:        #161b22;
  --bg3:        #1c2128;
  --border:     rgba(255,255,255,0.08);
  --border2:    rgba(255,255,255,0.14);
  --text:       #e6edf3;
  --text2:      #8b949e;
  --text3:      #484f58;
  --accent:     #58a6ff;
  --accent2:    #1f6feb;
  --green:      #3fb950;
  --red:        #f85149;
  --yellow:     #d29922;
  --purple:     #bc8cff;
  --radius:     10px;
  --radius-sm:  6px;
  --shadow:     0 8px 32px rgba(0,0,0,0.4);
  --trans:      0.18s ease;
}}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  display: flex; flex-direction: column; height: 100vh;
  overflow: hidden;
}}

/* ── Header ── */
#header {{
  height: 52px; min-height: 52px;
  background: var(--bg2);
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; padding: 0 20px;
  gap: 16px; z-index: 10;
  backdrop-filter: blur(8px);
}}
#header-logo {{
  display: flex; align-items: center; gap: 10px;
  text-decoration: none;
}}
#header-logo .brain-icon {{
  width: 28px; height: 28px; border-radius: 8px;
  background: linear-gradient(135deg, #58a6ff 0%, #bc8cff 100%);
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; box-shadow: 0 0 12px rgba(88,166,255,0.35);
}}
#header-logo .brand {{
  font-size: 14px; font-weight: 600; color: var(--text);
  letter-spacing: -0.01em;
}}
#header-logo .version {{
  font-size: 11px; color: var(--text2);
  background: var(--bg3); border: 1px solid var(--border);
  padding: 1px 6px; border-radius: 4px; margin-left: 2px;
}}
#header-project {{
  font-size: 12px; color: var(--text2);
  background: var(--bg3); border: 1px solid var(--border);
  padding: 3px 10px; border-radius: 20px;
}}
#search-wrap {{
  flex: 1; max-width: 320px; position: relative; margin-left: auto;
}}
#search-icon {{
  position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
  color: var(--text3); font-size: 13px; pointer-events: none;
}}
#search-input {{
  width: 100%; background: var(--bg3);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  color: var(--text); padding: 6px 10px 6px 30px;
  font-size: 13px; outline: none; transition: border-color var(--trans);
}}
#search-input:focus {{ border-color: var(--accent2); }}
#search-input::placeholder {{ color: var(--text3); }}

/* ── Layout ── */
#body {{ display: flex; flex: 1; overflow: hidden; }}

/* ── Sidebar ── */
#sidebar {{
  width: 256px; min-width: 256px;
  background: var(--bg2);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
  overflow-y: auto; overflow-x: hidden;
}}
#sidebar::-webkit-scrollbar {{ width: 4px; }}
#sidebar::-webkit-scrollbar-thumb {{ background: var(--border2); border-radius: 2px; }}

.side-section {{ padding: 14px 16px; border-bottom: 1px solid var(--border); }}
.side-label {{
  font-size: 10px; font-weight: 600; letter-spacing: .08em;
  text-transform: uppercase; color: var(--text3); margin-bottom: 10px;
}}

/* Stats */
.stat-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
.stat-card {{
  background: var(--bg3); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 10px 12px;
}}
.stat-card .sv {{ font-size: 22px; font-weight: 700; color: var(--accent); line-height: 1; }}
.stat-card .sk {{ font-size: 10px; color: var(--text2); margin-top: 3px; }}

/* Kind list */
.kind-row {{
  display: flex; align-items: center; gap: 8px;
  padding: 5px 0; cursor: pointer;
  transition: opacity var(--trans);
}}
.kind-row:hover {{ opacity: 0.75; }}
.kind-dot {{
  width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
}}
.kind-name {{ font-size: 12px; color: var(--text2); flex: 1; }}
.kind-count {{
  font-size: 11px; font-weight: 600; color: var(--text);
  background: var(--bg3); padding: 1px 7px; border-radius: 10px;
}}

/* Filter pills */
#filter-wrap {{ display: flex; gap: 5px; flex-wrap: wrap; }}
.pill {{
  font-size: 11px; font-weight: 500;
  padding: 3px 10px; border-radius: 20px;
  border: 1px solid var(--border); color: var(--text2);
  cursor: pointer; background: transparent;
  transition: all var(--trans);
}}
.pill:hover {{ border-color: var(--accent); color: var(--accent); }}
.pill.active {{
  background: rgba(88,166,255,0.15);
  border-color: var(--accent); color: var(--accent);
}}

/* Node detail */
#node-panel {{ display: none; }}
#node-panel.visible {{ display: block; }}
.node-kind-badge {{
  display: inline-block; font-size: 10px; font-weight: 600;
  padding: 2px 8px; border-radius: 4px; margin-bottom: 8px;
  letter-spacing: .04em; text-transform: uppercase;
}}
#node-title {{
  font-size: 13px; font-weight: 600; color: var(--text);
  line-height: 1.4; margin-bottom: 8px;
}}
#node-content {{
  font-size: 12px; color: var(--text2); line-height: 1.6;
  max-height: 140px; overflow-y: auto; margin-bottom: 8px;
}}
#node-content::-webkit-scrollbar {{ width: 3px; }}
#node-content::-webkit-scrollbar-thumb {{ background: var(--border2); }}
#node-meta {{ font-size: 10px; color: var(--text3); }}
.tag-chip {{
  display: inline-block; font-size: 10px;
  background: var(--bg3); border: 1px solid var(--border);
  padding: 1px 6px; border-radius: 4px; margin: 2px 2px 0 0;
  color: var(--text2);
}}
#neighbor-list {{ margin-top: 10px; }}
.neighbor-item {{
  display: flex; align-items: center; gap: 6px;
  padding: 4px 0; border-bottom: 1px solid var(--border); cursor: pointer;
}}
.neighbor-item:hover .neighbor-title {{ color: var(--accent); }}
.neighbor-kind {{ width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }}
.neighbor-title {{ font-size: 11px; color: var(--text2); }}
.neighbor-rel {{
  font-size: 10px; color: var(--text3); margin-left: auto;
}}

/* ── Main canvas ── */
#main {{ flex: 1; position: relative; overflow: hidden; }}
#canvas {{ width: 100%; height: 100%; }}

/* Grid bg */
#main::before {{
  content: '';
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events: none;
}}

/* Empty state */
#empty-state {{
  position: absolute; top: 50%; left: 50%;
  transform: translate(-50%,-50%);
  text-align: center; display: none;
}}
#empty-state .es-icon {{ font-size: 40px; margin-bottom: 12px; opacity: .4; }}
#empty-state .es-text {{ font-size: 14px; color: var(--text2); }}

/* Tooltip */
#tooltip {{
  position: fixed; display: none;
  background: var(--bg3); border: 1px solid var(--border2);
  border-radius: var(--radius-sm); padding: 8px 12px;
  font-size: 12px; color: var(--text); pointer-events: none;
  max-width: 220px; box-shadow: var(--shadow); z-index: 100;
  line-height: 1.5;
}}
#tooltip .tt-kind {{
  font-size: 10px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .05em; margin-bottom: 3px;
}}

/* Reset btn */
#reset-btn {{
  position: absolute; bottom: 16px; right: 16px;
  background: var(--bg2); border: 1px solid var(--border2);
  color: var(--text2); font-size: 12px; padding: 6px 14px;
  border-radius: var(--radius-sm); cursor: pointer;
  transition: all var(--trans); z-index: 5;
}}
#reset-btn:hover {{ border-color: var(--accent); color: var(--accent); }}

/* Animated glow pulse */
@keyframes pulse-glow {{
  0%, 100% {{ filter: drop-shadow(0 0 4px currentColor); }}
  50%        {{ filter: drop-shadow(0 0 10px currentColor); }}
}}
.node-selected {{ animation: pulse-glow 1.8s ease-in-out infinite; }}

/* Loading */
#loading {{
  position: absolute; top: 50%; left: 50%;
  transform: translate(-50%,-50%);
  display: flex; flex-direction: column; align-items: center; gap: 12px;
}}
.spinner {{
  width: 32px; height: 32px; border-radius: 50%;
  border: 2px solid var(--border2);
  border-top-color: var(--accent);
  animation: spin 0.8s linear infinite;
}}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
#loading .l-text {{ font-size: 13px; color: var(--text2); }}
</style>
</head>
<body>

<div id="header">
  <div id="header-logo">
    <div class="brain-icon">🧠</div>
    <span class="brand">Project Brain</span>
    <span class="version">v1.0</span>
  </div>
  <div id="header-project">📁 {project_name}</div>
  <div id="search-wrap">
    <span id="search-icon">⌕</span>
    <input id="search-input" type="text" placeholder="搜尋知識節點...">
  </div>
</div>

<div id="body">
  <div id="sidebar">
    <div class="side-section">
      <div class="side-label">知識庫</div>
      <div class="stat-grid">
        <div class="stat-card"><div class="sv" id="s-nodes">—</div><div class="sk">節點</div></div>
        <div class="stat-card"><div class="sv" id="s-edges">—</div><div class="sk">關係</div></div>
      </div>
    </div>

    <div class="side-section">
      <div class="side-label">篩選類型</div>
      <div id="filter-wrap">
        <button class="pill active" data-kind="all">全部</button>
        <button class="pill" data-kind="Pitfall">踩坑</button>
        <button class="pill" data-kind="Rule">規則</button>
        <button class="pill" data-kind="Decision">決策</button>
        <button class="pill" data-kind="ADR">ADR</button>
        <button class="pill" data-kind="Component">組件</button>
      </div>
    </div>

    <div class="side-section">
      <div class="side-label">節點分佈</div>
      <div id="kind-list"></div>
    </div>

    <div class="side-section" id="node-panel">
      <div class="side-label">節點詳情</div>
      <div id="node-kind-badge" class="node-kind-badge"></div>
      <div id="node-title"></div>
      <div id="node-content"></div>
      <div id="node-tags"></div>
      <div id="node-meta"></div>
      <button id="pin-btn" style="margin-top:8px;width:100%;background:var(--bg3);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:5px;cursor:pointer;font-size:11px;transition:all .18s">📌 釘選</button>
      <div id="neighbor-list"></div>
    </div>
  </div>

  <div id="main">
    <div id="loading">
      <div class="spinner"></div>
      <div class="l-text">載入知識圖譜...</div>
    </div>
    <div id="empty-state">
      <div class="es-icon">🕸</div>
      <div class="es-text">知識庫尚無節點<br>執行 brain add 或 brain scan 加入知識</div>
    </div>
    <svg id="canvas"></svg>
    <div id="tooltip"><div class="tt-kind" id="tt-kind"></div><div id="tt-title"></div></div>
    <button id="reset-btn" onclick="resetView()">↺ 重置視圖</button>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<script>
const KIND_COLOR = {{
  Pitfall:'#f87171', Decision:'#34d399', Rule:'#60a5fa',
  ADR:'#c084fc', Component:'#94a3b8', Architecture:'#fb923c'
}};
const KIND_LABEL = {{
  Pitfall:'踩坑', Decision:'決策', Rule:'規則',
  ADR:'ADR', Component:'組件', Architecture:'架構'
}};

let simulation, allNodes=[], allLinks=[], currentFilter='all', selectedId=null;
const tooltip = document.getElementById('tooltip');

async function loadStats() {{
  const d = await fetch('/api/stats').then(r=>r.json());
  document.getElementById('s-nodes').textContent = d.total_nodes;
  document.getElementById('s-edges').textContent = d.total_edges;
  const kl = document.getElementById('kind-list');
  kl.innerHTML = (d.by_kind||[]).map(k => `
    <div class="kind-row" onclick="filterKind('${{k.kind}}')">
      <div class="kind-dot" style="background:${{KIND_COLOR[k.kind]||'#94a3b8'}}"></div>
      <span class="kind-name">${{KIND_LABEL[k.kind]||k.kind}}</span>
      <span class="kind-count">${{k.count}}</span>
    </div>`).join('');
}}

async function loadGraph() {{
  document.getElementById('loading').style.display='flex';
  const url = `/api/graph?limit=300${{currentFilter!=='all'?'&kind='+currentFilter:''}}`;
  const data = await fetch(url).then(r=>r.json());
  allNodes = data.nodes||[];
  allLinks = data.links||[];
  document.getElementById('loading').style.display='none';
  if (!allNodes.length) {{ document.getElementById('empty-state').style.display='block'; return; }}
  document.getElementById('empty-state').style.display='none';
  renderGraph(allNodes, allLinks);
}}

function renderGraph(nodes, links) {{
  const svg = d3.select('#canvas');
  svg.selectAll('*').remove();
  const W=svg.node().clientWidth, H=svg.node().clientHeight;
  const g = svg.append('g');

  svg.call(d3.zoom().scaleExtent([0.2,4])
    .on('zoom', e => g.attr('transform', e.transform)));

  simulation = d3.forceSimulation(nodes)
    .force('link',  d3.forceLink(links).id(d=>d.id).distance(70).strength(0.4))
    .force('charge',d3.forceManyBody().strength(-200).distanceMax(300))
    .force('center',d3.forceCenter(W/2, H/2))
    .force('collide',d3.forceCollide(d => d.size + 8).strength(0.8));

  // Links
  const link = g.append('g').selectAll('line')
    .data(links).join('line')
    .attr('stroke','rgba(255,255,255,0.06)')
    .attr('stroke-width',1.2)
    .attr('stroke-linecap','round');

  // Glow filters
  const defs = svg.append('defs');
  Object.entries(KIND_COLOR).forEach(([k,c])=>{{
    const f = defs.append('filter').attr('id','glow-'+k).attr('x','-50%').attr('y','-50%').attr('width','200%').attr('height','200%');
    f.append('feGaussianBlur').attr('stdDeviation','3').attr('result','blur');
    const m = f.append('feMerge');
    m.append('feMergeNode').attr('in','blur');
    m.append('feMergeNode').attr('in','SourceGraphic');
  }});

  // Node circles
  const node = g.append('g').selectAll('circle')
    .data(nodes).join('circle')
    .attr('r', d=>d.size)
    .attr('fill', d=>d.color)
    .attr('fill-opacity', 0.9)
    .attr('stroke', d=>d.color)
    .attr('stroke-opacity', 0.4)
    .attr('stroke-width', 3)
    .style('cursor','pointer')
    .style('filter', d=>`drop-shadow(0 0 4px ${{d.color}}66)`)
    .on('mouseover', (e,d)=>{{
      tooltip.style.display='block';
      document.getElementById('tt-kind').textContent = KIND_LABEL[d.kind]||d.kind;
      document.getElementById('tt-kind').style.color = d.color;
      document.getElementById('tt-title').textContent = d.title;
      d3.select(e.currentTarget).attr('r', d.size*1.25).style('filter',`drop-shadow(0 0 10px ${{d.color}})`);
    }})
    .on('mousemove', e=>{{
      tooltip.style.left=(e.clientX+14)+'px'; tooltip.style.top=(e.clientY-10)+'px';
    }})
    .on('mouseout', (e,d)=>{{
      tooltip.style.display='none';
      if(d.id!==selectedId) d3.select(e.currentTarget).attr('r',d.size).style('filter',`drop-shadow(0 0 4px ${{d.color}}66)`);
    }})
    .on('click', (e,d)=>{{
      e.stopPropagation();
      selectedId=d.id;
      node.attr('r',d2=>d2.size).attr('opacity',d2=>d2.id===d.id?1:0.35);
      link.attr('opacity',l=>l.source.id===d.id||l.target.id===d.id?1:0.1);
      d3.select(e.currentTarget).attr('r',d.size*1.3).attr('opacity',1)
        .style('filter',`drop-shadow(0 0 12px ${{d.color}})`);
      showNodeDetail(d);
    }})
    .call(d3.drag()
      .on('start',(e,d)=>{{ if(!e.active) simulation.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; }})
      .on('drag', (e,d)=>{{ d.fx=e.x; d.fy=e.y; }})
      .on('end',  (e,d)=>{{ if(!e.active) simulation.alphaTarget(0); d.fx=null; d.fy=null; }})
    );

  // Labels
  const label = g.append('g').selectAll('text')
    .data(nodes).join('text')
    .text(d=>d.title.slice(0,14)+(d.title.length>14?'…':''))
    .attr('font-size',9).attr('fill','rgba(255,255,255,0.45)')
    .attr('text-anchor','middle').attr('dy',d=>d.size+11)
    .style('pointer-events','none')
    .style('user-select','none');

  simulation.on('tick',()=>{{
    link.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y)
        .attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
    node.attr('cx',d=>d.x).attr('cy',d=>d.y);
    label.attr('x',d=>d.x).attr('y',d=>d.y);
  }});

  svg.on('click',()=>{{
    selectedId=null;
    node.attr('r',d=>d.size).attr('opacity',1).style('filter',d=>`drop-shadow(0 0 4px ${{d.color}}66)`);
    link.attr('opacity',1);
    document.getElementById('node-panel').classList.remove('visible');
  }});
}}

function showNodeDetail(d) {{
  const p = document.getElementById('node-panel');
  p.classList.add('visible');
  const badge = document.getElementById('node-kind-badge');
  badge.textContent = KIND_LABEL[d.kind]||d.kind;
  badge.style.background = d.color+'25';
  badge.style.color = d.color;
  badge.style.border = `1px solid ${{d.color}}55`;
  document.getElementById('node-title').textContent = d.title;
  document.getElementById('node-content').textContent = d.excerpt || '（無內容）';
  document.getElementById('node-meta').textContent = d.created_at ? '📅 '+d.created_at.slice(0,10) : '';
  // v6.0 Pin button
  const pinBtn = document.getElementById('pin-btn');
  const isPinned = d.is_pinned || false;
  pinBtn.textContent = isPinned ? '📌 已釘選' : '📌 釘選';
  pinBtn.style.opacity = isPinned ? '1' : '0.6';
  pinBtn.onclick = () => togglePin(d.id, !isPinned, d);

  const tags = (d.tags||'').split(',').filter(t=>t.trim());
  document.getElementById('node-tags').innerHTML =
    tags.map(t=>`<span class="tag-chip">${{t.trim()}}</span>`).join('');

  // Load full node
  fetch('/api/node/'+d.id).then(r=>r.json()).then(n=>{{
    document.getElementById('node-content').textContent = n.content || '（無內容）';
    const nl = document.getElementById('neighbor-list');
    if(n.neighbors&&n.neighbors.length) {{
      nl.innerHTML = '<div style="font-size:10px;color:var(--text3);margin-bottom:4px;text-transform:uppercase;letter-spacing:.06em">關聯節點</div>' +
        n.neighbors.map(nb=>`
          <div class="neighbor-item">
            <div class="neighbor-kind" style="background:${{KIND_COLOR[nb.kind]||'#94a3b8'}}"></div>
            <span class="neighbor-title">${{nb.title.slice(0,24)}}</span>
            <span class="neighbor-rel">${{nb.relation||''}}</span>
          </div>`).join('');
    }} else nl.innerHTML='';
  }});
}}

function filterKind(kind) {{
  currentFilter=kind;
  document.querySelectorAll('.pill').forEach(p=>{{
    p.classList.toggle('active', p.dataset.kind===kind);
  }});
  loadGraph();
}}

function resetView() {{
  selectedId=null;
  d3.select('#canvas').transition().duration(400).call(
    d3.zoom().transform, d3.zoomIdentity
  );
}}

document.querySelectorAll('.pill').forEach(p=>{{
  p.addEventListener('click',()=>filterKind(p.dataset.kind));
}});

let st;
document.getElementById('search-input').addEventListener('input',e=>{{
  clearTimeout(st);
  st=setTimeout(async()=>{{
    const q=e.target.value.trim();
    if(!q){{ d3.selectAll('circle').attr('opacity',1); return; }}
    const res=await fetch('/api/search?q='+encodeURIComponent(q)).then(r=>r.json());
    const hits=new Set(res.results.map(r=>r.id));
    d3.selectAll('circle').attr('opacity',d=>hits.has(d.id)?1:0.1);
  }},280);
}});

async function togglePin(nodeId, pin, d) {{
  const res = await fetch(`/api/node/${{nodeId}}/pin`, {{
    method: 'POST',
    headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{pinned: pin}})
  }});
  if (res.ok) {{
    const btn = document.getElementById('pin-btn');
    btn.textContent = pin ? '📌 已釘選' : '📌 釘選';
    btn.style.opacity = pin ? '1' : '0.6';
    btn.style.borderColor = pin ? '#60a5fa' : '';
    d.is_pinned = pin;
  }}
}}


loadStats();
loadGraph();
</script>
</body>
</html>"""


def run_server(workdir: Path, port: int = 7890) -> None:
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app = create_app(workdir)
    print(f"\n  🧠  Project Brain Web UI")
    print(f"  知識圖譜：{workdir / '.brain'}")
    print(f"  瀏覽器：  \033[96mhttp://{HOST}:{port}\033[0m")
    print(f"  停止：    Ctrl+C\n")
    app.run(host=HOST, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", default=os.getcwd())
    parser.add_argument("--port", type=int, default=7890)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    run_server(Path(args.workdir), args.port)
