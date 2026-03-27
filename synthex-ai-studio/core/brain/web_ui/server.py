"""
core/brain/web_ui/server.py — 知識圖譜視覺化 Web UI（v4.0）

功能：
  一個本地 Flask Web Server，提供：
  1. D3.js 力導向圖（Force-directed Graph）— 視覺化知識圖譜節點和關係
  2. 節點衰減熱力圖 — 信心分數用顏色渲染（高信心=綠，低信心=紅）
  3. 即時搜尋 — 在圖上高亮相關節點
  4. ADR 詳情面板 — 點擊節點查看完整知識
  5. 統計儀表板 — 知識庫健康狀態

啟動方式：
  python -m core.brain.web_ui.server --workdir /your/project --port 7890
  → 瀏覽器開啟 http://localhost:7890

API 端點：
  GET  /api/graph          → D3.js 所需的 nodes + links JSON
  GET  /api/stats          → 知識庫統計
  GET  /api/search?q=...   → 搜尋節點
  GET  /api/node/:id       → 節點詳情
  POST /api/validate       → 觸發知識驗證
  GET  /api/decay          → 衰減報告

安全設計：
  - 只綁定 localhost（不對外暴露）
  - 所有 SQL 使用參數化查詢（防 SQL Injection）
  - 輸入長度限制（防 DoS）
  - 無需認證（本地開發工具）
  - CORS 只允許 localhost
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

# ── 安全常數 ──────────────────────────────────────────────────
MAX_QUERY_LEN  = 200
MAX_NODES_RETURN = 500     # D3.js 建議不超過 500 節點（效能）
HOST           = "127.0.0.1"   # 只綁定 localhost

# ── 顏色映射（信心分數 → 顏色） ──────────────────────────────
def _confidence_to_color(conf: float) -> str:
    """高信心=綠色，低信心=紅色，中間=黃色"""
    c = max(0.0, min(1.0, conf))
    if c >= 0.75:
        return "#22c55e"   # green-500
    elif c >= 0.50:
        return "#86efac"   # green-300
    elif c >= 0.30:
        return "#fbbf24"   # amber-400
    elif c >= 0.15:
        return "#f97316"   # orange-500
    else:
        return "#ef4444"   # red-500

# ── 節點類型 → 圖形形狀 ──────────────────────────────────────
NODE_SHAPE: dict[str, str] = {
    "Component": "circle",
    "Decision":  "diamond",
    "Pitfall":   "triangle",
    "Rule":      "rect",
    "ADR":       "hexagon",
    "Commit":    "square",
    "Person":    "circle",
}

NODE_BASE_SIZE: dict[str, int] = {
    "Component": 16,
    "Decision":  14,
    "Pitfall":   12,
    "Rule":      10,
    "ADR":       14,
    "Commit":    8,
    "Person":    10,
}


def create_app(workdir: Path) -> Any:
    """
    建立並回傳 Flask app 實例。
    使用工廠模式，方便測試。
    """
    try:
        from flask import Flask, jsonify, request, send_from_directory, Response
        from flask_cors import CORS
    except ImportError:
        print("⚠ 需要安裝 Web UI 依賴：pip install flask flask-cors")
        sys.exit(1)

    brain_dir = workdir / ".brain"
    db_path   = brain_dir / "knowledge_graph.db"

    if not db_path.exists():
        raise FileNotFoundError(f"知識圖譜不存在：{db_path}（請先執行 brain init）")

    app = Flask(__name__, static_folder=str(Path(__file__).parent / "static"))
    CORS(app, origins=["http://localhost:*", "http://127.0.0.1:*"])

    def _db() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Routes ────────────────────────────────────────────────

    @app.route("/")
    def index():
        """回傳 D3.js 視覺化主頁"""
        html_path = Path(__file__).parent / "static" / "graph.html"
        if html_path.exists():
            return html_path.read_text(encoding="utf-8")
        return "<h1>Project Brain v4.0 Web UI</h1><p>請確認 static/graph.html 存在</p>"

    @app.route("/api/graph")
    def api_graph():
        """D3.js 所需的 nodes + links JSON"""
        limit  = min(MAX_NODES_RETURN, int(request.args.get("limit", 200)))
        kind   = request.args.get("kind", None)  # 可過濾特定類型
        min_conf = float(request.args.get("min_conf", 0.0))

        conn = _db()
        try:
            # 節點
            if kind:
                safe_kind = re.sub(r'[^a-zA-Z]', '', kind)[:20]
                rows = conn.execute(
                    "SELECT id, kind, title, content, description, "
                    "confidence, created_at, tags FROM nodes "
                    "WHERE kind=? AND confidence>=? "
                    "AND (is_invalidated IS NULL OR is_invalidated=0) "
                    "ORDER BY confidence DESC LIMIT ?",
                    (safe_kind, min_conf, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, kind, title, content, description, "
                    "confidence, created_at, tags FROM nodes "
                    "WHERE confidence>=? "
                    "AND (is_invalidated IS NULL OR is_invalidated=0) "
                    "ORDER BY confidence DESC LIMIT ?",
                    (min_conf, limit)
                ).fetchall()

            node_ids = {r["id"] for r in rows}
            nodes    = []
            for r in rows:
                conf = float(r["confidence"] or 0.5)
                nodes.append({
                    "id":       r["id"],
                    "kind":     r["kind"],
                    "title":    r["title"],
                    "color":    _confidence_to_color(conf),
                    "size":     NODE_BASE_SIZE.get(r["kind"], 10),
                    "shape":    NODE_SHAPE.get(r["kind"], "circle"),
                    "confidence": round(conf, 3),
                    "tags":     r["tags"] or "",
                    "excerpt":  (r["content"] or r["description"] or "")[:120],
                })

            # 關係（只保留兩端節點都在當前集合內的邊）
            edge_rows = conn.execute(
                "SELECT source_id, target_id, relation_type FROM edges "
                "WHERE source_id IN ({}) AND target_id IN ({})".format(
                    ",".join("?" * len(node_ids)),
                    ",".join("?" * len(node_ids)),
                ),
                list(node_ids) * 2
            ).fetchall()

            links = [
                {
                    "source": r["source_id"],
                    "target": r["target_id"],
                    "type":   r["relation_type"],
                }
                for r in edge_rows
            ]

        finally:
            conn.close()

        return jsonify({"nodes": nodes, "links": links,
                        "total_nodes": len(nodes), "total_links": len(links)})

    @app.route("/api/stats")
    def api_stats():
        """知識庫統計"""
        conn = _db()
        try:
            total   = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            by_kind = conn.execute(
                "SELECT kind, COUNT(*) as cnt, AVG(confidence) as avg_conf "
                "FROM nodes GROUP BY kind"
            ).fetchall()
            low_conf = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE confidence < 0.3"
            ).fetchone()[0]
            edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        finally:
            conn.close()

        return jsonify({
            "total_nodes":       total,
            "total_edges":       edges,
            "low_confidence":    low_conf,
            "health_score":      round(1.0 - (low_conf / max(1, total)), 2),
            "by_kind":           [
                {"kind": r["kind"], "count": r["cnt"],
                 "avg_confidence": round(float(r["avg_conf"] or 0), 2)}
                for r in by_kind
            ],
        })

    @app.route("/api/search")
    def api_search():
        """全文搜尋節點"""
        q = request.args.get("q", "")[:MAX_QUERY_LEN]
        if not q.strip():
            return jsonify({"results": []})

        conn = _db()
        try:
            # 嘗試 FTS5
            try:
                rows = conn.execute(
                    "SELECT n.id, n.kind, n.title, n.confidence "
                    "FROM nodes n "
                    "JOIN nodes_fts f ON n.rowid = f.rowid "
                    "WHERE nodes_fts MATCH ? LIMIT 20",
                    (q,)
                ).fetchall()
            except sqlite3.OperationalError:
                # FTS5 不可用時 fallback
                rows = conn.execute(
                    "SELECT id, kind, title, confidence FROM nodes "
                    "WHERE title LIKE ? OR content LIKE ? LIMIT 20",
                    (f"%{q}%", f"%{q}%")
                ).fetchall()
        finally:
            conn.close()

        return jsonify({
            "query":   q,
            "count":   len(rows),
            "results": [
                {"id": r["id"], "kind": r["kind"], "title": r["title"],
                 "confidence": round(float(r["confidence"] or 0), 2),
                 "color": _confidence_to_color(float(r["confidence"] or 0))}
                for r in rows
            ],
        })

    @app.route("/api/node/<node_id>")
    def api_node(node_id: str):
        """節點詳情（含相鄰節點）"""
        safe_id = re.sub(r'[^a-zA-Z0-9_-]', '', node_id)[:64]
        conn    = _db()
        try:
            row = conn.execute(
                "SELECT * FROM nodes WHERE id=?", (safe_id,)
            ).fetchone()
            if not row:
                return jsonify({"error": "節點不存在"}), 404

            neighbors = conn.execute(
                "SELECT n.id, n.kind, n.title, e.relation_type "
                "FROM edges e JOIN nodes n ON e.target_id = n.id "
                "WHERE e.source_id=? LIMIT 10",
                (safe_id,)
            ).fetchall()
        finally:
            conn.close()

        return jsonify({
            "id":         row["id"],
            "kind":       row["kind"],
            "title":      row["title"],
            "content":    row["content"] or row["description"] or "",
            "confidence": round(float(row["confidence"] or 0), 3),
            "tags":       row["tags"] or "",
            "created_at": row["created_at"] or "",
            "color":      _confidence_to_color(float(row["confidence"] or 0)),
            "neighbors":  [
                {"id": n["id"], "kind": n["kind"],
                 "title": n["title"], "relation": n["relation_type"]}
                for n in neighbors
            ],
        })

    @app.route("/api/decay")
    def api_decay():
        """低信心節點列表（衰減報告）"""
        threshold = float(request.args.get("threshold", 0.3))
        conn      = _db()
        try:
            rows = conn.execute(
                "SELECT id, kind, title, confidence, created_at "
                "FROM nodes WHERE confidence < ? "
                "AND (is_invalidated IS NULL OR is_invalidated=0) "
                "ORDER BY confidence ASC LIMIT 50",
                (threshold,)
            ).fetchall()
        finally:
            conn.close()

        return jsonify({
            "threshold": threshold,
            "count":     len(rows),
            "nodes": [
                {"id": r["id"], "kind": r["kind"], "title": r["title"],
                 "confidence": round(float(r["confidence"] or 0), 3),
                 "color": _confidence_to_color(float(r["confidence"] or 0))}
                for r in rows
            ],
        })

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "version": "4.0.0"})

    return app


def _generate_graph_html() -> str:
    """生成 D3.js 力導向圖 HTML"""
    return """\
<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>Project Brain v4.0 — 知識圖譜</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, sans-serif; background: #0f0f0f; color: #e0e0e0; display: flex; height: 100vh; }
  #sidebar { width: 280px; min-width: 280px; background: #1a1a1a; border-right: 1px solid #2d2d2d; overflow-y: auto; display: flex; flex-direction: column; }
  #main { flex: 1; display: flex; flex-direction: column; }
  #toolbar { padding: 8px 12px; background: #111; border-bottom: 1px solid #2d2d2d; display: flex; gap: 8px; align-items: center; }
  #search-input { background: #222; border: 1px solid #333; color: #e0e0e0; padding: 4px 8px; border-radius: 4px; flex: 1; font-size: 13px; }
  #canvas { flex: 1; }
  .panel { padding: 12px; border-bottom: 1px solid #2d2d2d; }
  .panel h3 { font-size: 11px; text-transform: uppercase; color: #666; margin-bottom: 8px; letter-spacing: 0.05em; }
  .stat-row { display: flex; justify-content: space-between; font-size: 12px; padding: 2px 0; }
  .stat-val { font-weight: 600; color: #22c55e; }
  .node-detail { display: none; }
  .node-detail.active { display: block; }
  .tag { background: #2d2d2d; padding: 2px 6px; border-radius: 3px; font-size: 10px; margin: 2px; display: inline-block; }
  .kind-badge { padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 600; }
  .kind-Pitfall   { background: #7f1d1d; color: #fca5a5; }
  .kind-Rule      { background: #1e3a5f; color: #93c5fd; }
  .kind-Decision  { background: #14532d; color: #86efac; }
  .kind-ADR       { background: #3b0764; color: #d8b4fe; }
  .kind-Component { background: #292524; color: #d6d3d1; }
  #legend { display: flex; gap: 8px; flex-wrap: wrap; }
  .legend-item { display: flex; align-items: center; gap: 4px; font-size: 11px; color: #999; }
  .legend-dot { width: 10px; height: 10px; border-radius: 50%; }
  button { background: #222; border: 1px solid #333; color: #ccc; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; }
  button:hover { background: #2d2d2d; }
  #filter-btns { display: flex; gap: 4px; flex-wrap: wrap; padding: 8px 12px; border-bottom: 1px solid #2d2d2d; }
  .filter-btn.active { border-color: #22c55e; color: #22c55e; }
  .conf-bar { height: 4px; background: #2d2d2d; border-radius: 2px; margin-top: 4px; }
  .conf-fill { height: 100%; border-radius: 2px; transition: width 0.3s; }
</style>
</head>
<body>
<div id="sidebar">
  <div class="panel">
    <h3>Project Brain v4.0</h3>
    <div id="stats">
      <div class="stat-row"><span>載入中...</span></div>
    </div>
  </div>
  <div class="panel">
    <h3>信心分數圖例</h3>
    <div id="legend">
      <div class="legend-item"><div class="legend-dot" style="background:#22c55e"></div>75%+</div>
      <div class="legend-item"><div class="legend-dot" style="background:#86efac"></div>50-75%</div>
      <div class="legend-item"><div class="legend-dot" style="background:#fbbf24"></div>30-50%</div>
      <div class="legend-item"><div class="legend-dot" style="background:#f97316"></div>15-30%</div>
      <div class="legend-item"><div class="legend-dot" style="background:#ef4444"></div>&lt;15%</div>
    </div>
  </div>
  <div class="panel node-detail" id="node-panel">
    <h3>節點詳情</h3>
    <div id="node-kind" class="kind-badge" style="margin-bottom:6px"></div>
    <div id="node-title" style="font-size:13px;font-weight:600;margin-bottom:4px"></div>
    <div class="conf-bar"><div class="conf-fill" id="node-conf-bar"></div></div>
    <div id="node-conf" style="font-size:11px;color:#666;margin:4px 0 8px"></div>
    <div id="node-content" style="font-size:12px;color:#ccc;line-height:1.5;max-height:120px;overflow-y:auto"></div>
    <div id="node-tags" style="margin-top:8px"></div>
  </div>
</div>
<div id="main">
  <div id="toolbar">
    <input id="search-input" type="text" placeholder="搜尋知識節點...">
    <button onclick="resetView()">重置</button>
  </div>
  <div id="filter-btns">
    <button class="filter-btn active" onclick="filterKind('all')">全部</button>
    <button class="filter-btn" onclick="filterKind('Pitfall')">踩坑</button>
    <button class="filter-btn" onclick="filterKind('Rule')">規則</button>
    <button class="filter-btn" onclick="filterKind('Decision')">決策</button>
    <button class="filter-btn" onclick="filterKind('ADR')">ADR</button>
    <button class="filter-btn" onclick="filterKind('Component')">組件</button>
  </div>
  <svg id="canvas"></svg>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<script>
let simulation, allNodes = [], allLinks = [], currentFilter = 'all';

async function loadGraph() {
  const url = `/api/graph?limit=300${currentFilter !== 'all' ? '&kind=' + currentFilter : ''}`;
  const data = await fetch(url).then(r => r.json());
  allNodes = data.nodes || [];
  allLinks = data.links || [];
  renderGraph(allNodes, allLinks);
}

async function loadStats() {
  const d = await fetch('/api/stats').then(r => r.json());
  document.getElementById('stats').innerHTML = `
    <div class="stat-row"><span>總節點</span><span class="stat-val">${d.total_nodes}</span></div>
    <div class="stat-row"><span>關係</span><span class="stat-val">${d.total_edges}</span></div>
    <div class="stat-row"><span>低信心</span><span class="stat-val" style="color:#f97316">${d.low_confidence}</span></div>
    <div class="stat-row"><span>健康分數</span><span class="stat-val">${Math.round(d.health_score * 100)}%</span></div>
  ` + (d.by_kind || []).map(k =>
    `<div class="stat-row"><span>${k.kind}</span><span>${k.count} (${Math.round(k.avg_confidence*100)}%)</span></div>`
  ).join('');
}

function renderGraph(nodes, links) {
  const svg = d3.select('#canvas');
  svg.selectAll('*').remove();
  const W = svg.node().clientWidth, H = svg.node().clientHeight;

  const g = svg.append('g');
  svg.call(d3.zoom().on('zoom', e => g.attr('transform', e.transform)));

  simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(60))
    .force('charge', d3.forceManyBody().strength(-120))
    .force('center', d3.forceCenter(W/2, H/2))
    .force('collision', d3.forceCollide(20));

  const link = g.append('g').selectAll('line')
    .data(links).join('line')
    .attr('stroke', '#2d2d2d').attr('stroke-width', 1);

  const node = g.append('g').selectAll('circle')
    .data(nodes).join('circle')
    .attr('r', d => d.size)
    .attr('fill', d => d.color)
    .attr('stroke', '#111').attr('stroke-width', 1.5)
    .style('cursor', 'pointer')
    .on('click', (e, d) => showNodeDetail(d))
    .call(d3.drag()
      .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
    );

  const label = g.append('g').selectAll('text')
    .data(nodes).join('text')
    .text(d => d.title.slice(0, 12) + (d.title.length > 12 ? '…' : ''))
    .attr('font-size', 9).attr('fill', '#888')
    .attr('text-anchor', 'middle').attr('dy', d => d.size + 10)
    .style('pointer-events', 'none');

  simulation.on('tick', () => {
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    node.attr('cx', d => d.x).attr('cy', d => d.y);
    label.attr('x', d => d.x).attr('y', d => d.y);
  });
}

function showNodeDetail(d) {
  document.getElementById('node-panel').classList.add('active');
  document.getElementById('node-kind').textContent  = d.kind;
  document.getElementById('node-kind').className    = 'kind-badge kind-' + d.kind;
  document.getElementById('node-title').textContent = d.title;
  document.getElementById('node-content').textContent = d.excerpt;
  document.getElementById('node-conf').textContent  = `信心分數：${Math.round(d.confidence * 100)}%`;
  const bar = document.getElementById('node-conf-bar');
  bar.style.width = (d.confidence * 100) + '%';
  bar.style.background = d.color;
  document.getElementById('node-tags').innerHTML = d.tags
    ? d.tags.split(',').map(t => `<span class="tag">${t.trim()}</span>`).join('') : '';
}

function filterKind(kind) {
  currentFilter = kind;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  loadGraph();
}

function resetView() {
  d3.select('#canvas').call(d3.zoom().transform, d3.zoomIdentity);
}

let searchTimeout;
document.getElementById('search-input').addEventListener('input', e => {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(async () => {
    const q = e.target.value.trim();
    if (!q) { d3.selectAll('circle').attr('opacity', 1); return; }
    const res = await fetch('/api/search?q=' + encodeURIComponent(q)).then(r => r.json());
    const hitIds = new Set(res.results.map(r => r.id));
    d3.selectAll('circle').attr('opacity', d => hitIds.has(d.id) ? 1 : 0.15);
  }, 300);
});

loadStats();
loadGraph();
</script>
</body>
</html>"""


def run_server(workdir: Path, port: int = 7890) -> None:
    """啟動 Web UI Server"""
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    html_path = static_dir / "graph.html"
    html_path.write_text(_generate_graph_html(), encoding="utf-8")

    app = create_app(workdir)
    print(f"\n🧠 Project Brain v4.0 Web UI")
    print(f"   知識圖譜：{workdir / '.brain'}")
    print(f"   瀏覽器：  http://{HOST}:{port}")
    print(f"   停止：    Ctrl+C\n")
    app.run(host=HOST, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", default=os.getcwd())
    parser.add_argument("--port",    type=int, default=7890)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    run_server(Path(args.workdir), args.port)
