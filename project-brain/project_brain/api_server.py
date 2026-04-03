"""
core/brain/api_server.py — Project Brain API Server（Flask routes）

OpenAI 相容端點：
  POST /v1/context         ← 查詢知識（LLM 在生成前呼叫）
  POST /v1/messages        ← OpenAI Chat Completions 格式
  POST /v1/add             ← 加入知識
  GET  /v1/knowledge       ← 列出所有知識
  GET  /v1/stats           ← 統計
  GET  /health             ← 健康檢查

L1a Session Store 端點：
  GET/POST /v1/session     ← 讀寫工作記憶
  ...

匯入方式：
  from project_brain.api_server import create_app
  app = create_app(workdir=..., api_key=...)
"""

from pathlib import Path


def create_app(workdir: str, api_key: str = ""):
    """
    建立 Flask app。
    把所有 route 定義集中在這裡，和 brain.py CLI 分離。
    """
    import os, time, json, re, uuid, threading
    import sqlite3 as _sqlite3
    from datetime import datetime, timezone
    from flask import Flask, request, jsonify, Response, abort
    from flask_cors import CORS

    wd = workdir
    app = Flask(__name__)

    # ── 初始化 Brain 組件 ──────────────────────────────────────────────
    from project_brain.graph import KnowledgeGraph
    from project_brain.session_store import SessionStore
    from project_brain.context import ContextEngineer
    from project_brain.session_store import CATEGORY_CONFIG

    brain_dir = Path(wd) / '.brain'
    brain_dir.mkdir(parents=True, exist_ok=True)

    # 懶初始化（避免 import 時間過長）
    _graph_cache  = {}
    _store_cache  = {}

    def _get_graph():
        if 'graph' not in _graph_cache:
            _graph_cache['graph'] = KnowledgeGraph(brain_dir)
        return _graph_cache['graph']

    def _get_store():
        if 'store' not in _store_cache:
            _store_cache['store'] = SessionStore(
                brain_dir=brain_dir, session_id="api-server"
            )
        return _store_cache['store']

    # 向後相容別名
    def _graph():  return _get_graph()
    def _store():  return _get_store()
    
    # 3c: 讀寫分離 — GET 請求用唯讀連線，不受 scan 寫入鎖影響
    _db_path   = Path(wd) / '.brain' / 'knowledge_graph.db'
    _read_uri  = f"file:{_db_path}?mode=ro"
    
    def _read_conn():
        """唯讀 SQLite 連線（WAL snapshot read，不阻塞寫入）"""
        if not _db_path.exists():
            return None
        try:
            import sqlite3 as _sl
            c = _sl.connect(_read_uri, uri=True, check_same_thread=False)
            c.row_factory = _sl.Row
            return c
        except Exception:
            return None
    CORS(app)
    
    # ── 認證中間件（v7.0.x 修補）────────────────────────────────
    _api_key = os.environ.get("BRAIN_API_KEY", "").strip()
    
    @app.before_request
    def _check_auth():
        """API Key 認證（若 BRAIN_API_KEY 已設定）"""
        if not _api_key:
            return  # 未設定 → 不做認證（向後相容）
        if request.path in ("/health",) or request.method == "OPTIONS":
            return  # 健康檢查和 CORS preflight 不需認證
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "未授權：需要 Authorization: Bearer <key>"}), 401
        if auth[7:].strip() != _api_key:
            return jsonify({"error": "未授權：API Key 不正確"}), 401
    
    
    # ── L3 端點 ───────────────────────────────────────────────
    
    @app.route('/health')
    def health():
        ss = _get_store().stats()
        return jsonify({"status": "ok", "version": "5.0.0",
                        "workdir": Path(wd).name,
                        "l3_nodes": _get_graph().stats().get('nodes', 0),
                        "l1a_entries": ss.get('total', 0),
                        "l1a_session_id": ss.get('session_id', '')})
    
    @app.route('/v1/stats')
    def stats():
        s = _get_graph().stats()
        return jsonify({"l3": {"nodes": s.get('nodes', 0), "edges": s.get('edges', 0),
                               "by_type": s.get('by_type', {})},
                        "l1a": _get_store().stats()})
    
    @app.route('/v1/knowledge')
    def knowledge():
        distill_path = brain_dir / 'distilled' / 'BRAIN_KNOWLEDGE.md'
        if not distill_path.exists():
            # 未蒸餾時返回 JSON 形式的知識列表
            try:
                nodes = _get_graph()._conn.execute(
                    "SELECT id, type, title, content, confidence FROM nodes ORDER BY confidence DESC LIMIT 50"
                ).fetchall()
                return jsonify([dict(n) for n in nodes]), 200
            except Exception as e:
                return jsonify({"error": str(e), "nodes": []}), 200
        return distill_path.read_text('utf-8'), 200, {'Content-Type': 'text/plain; charset=utf-8'}
    
    @app.route('/v1/context', methods=['GET', 'POST'])
    def context():
        task = (request.args.get('q', '')
                or (request.json or {}).get('task', ''))
        if not task:
            return jsonify({"error": "請提供 q 參數或 task 欄位"}), 400
        ctx = ContextEngineer(_get_graph(), brain_dir=brain_dir).build(task) or ''
        l1a = _get_store().search(task, limit=3)
        if l1a:
            l1a_sec = "## ⚡ L1 工作記憶\n" + "\n".join(
                f"- [{e.category}] {e.value[:150]}" for e in l1a) + "\n\n"
            ctx = l1a_sec + ctx
        return jsonify({"task": task, "context": ctx, "found": bool(ctx)})
    
    @app.route('/v1/messages', methods=['POST'])
    def messages_compat():
        data     = request.json or {}
        messages = data.get('messages', [])
        task     = next((m['content'] for m in messages if m.get('role') == 'user'), '')
        ctx      = ContextEngineer(_get_graph(), brain_dir=brain_dir).build(task) or '' if task else ''
        if task:
            l1a = _get_store().search(task, limit=3)
            if l1a:
                l1a_block = "## ⚡ L1 工作記憶\n" + "\n".join(
                    f"- [{e.category}] {e.value[:120]}" for e in l1a)
                ctx = l1a_block + "\n\n" + ctx
        if ctx:
            has_sys = any(m.get('role') == 'system' for m in messages)
            if has_sys:
                enriched = [{"role": "system",
                             "content": ctx + "\n\n---\n\n" + m['content']}
                            if m.get('role') == 'system' else m
                            for m in messages]
            else:
                enriched = [{"role": "system", "content": ctx}] + messages
        else:
            enriched = messages
        return jsonify({"messages": enriched, "knowledge_injected": bool(ctx),
                        "knowledge_chars": len(ctx)})
    
    @app.route('/v1/add', methods=['POST'])
    def add_knowledge():
        data = request.json or {}
        title   = data.get('title', '')
        content = data.get('content', '')
        kind    = data.get('kind', 'Pitfall')
        tags    = data.get('tags', [])
        if not title:
            return jsonify({"error": "title 必填"}), 400
        node_id = _get_graph().add_node(f"api-{os.urandom(4).hex()}", title, content, kind, tags)
        return jsonify({"node_id": node_id, "kind": kind, "title": title})
    
    # ── L1a Session Store 端點（任何 LLM 都能讀寫）───────────
    
    @app.route('/v1/session', methods=['GET'])
    def session_list():
        cat   = request.args.get('category', None)
        limit = min(int(request.args.get('limit', 50)), 200)
        ents  = _get_store().list(category=cat, limit=limit)
        return jsonify({"entries": [e.to_dict() for e in ents], "count": len(ents),
                        "session_id": _get_store().session_id,
                        "categories": list(CATEGORY_CONFIG.keys())})
    
    @app.route('/v1/session', methods=['POST'])
    def session_set():
        data = request.json or {}
        key  = data.get('key', '').strip()
        val  = data.get('value', data.get('content', '')).strip()
        cat  = data.get('category', 'notes')
        ttl  = data.get('ttl_days', None)
        if not key:
            return jsonify({"error": "key 必填"}), 400
        if not val:
            return jsonify({"error": "value 必填"}), 400
        entry = _get_store().set(key=key, value=val, category=cat, ttl_days=ttl)
        return jsonify(entry.to_dict()), 201
    
    @app.route('/v1/session/<path:key>', methods=['GET'])
    def session_get(key):
        entry = _get_store().get(key)
        if not entry:
            return jsonify({"error": "條目不存在或已過期"}), 404
        return jsonify(entry.to_dict())
    
    @app.route('/v1/session/<path:key>', methods=['PUT'])
    def session_update(key):
        data  = request.json or {}
        entry = _get_store().get(key)
        if not entry:
            return jsonify({"error": "條目不存在"}), 404
        updated = _get_store().set(key=key,
                            value=data.get('value', data.get('content', entry.value)),
                            category=data.get('category', entry.category),
                            ttl_days=data.get('ttl_days', None))
        return jsonify(updated.to_dict())
    
    @app.route('/v1/session/<path:key>', methods=['DELETE'])
    def session_delete(key):
        deleted = _get_store().delete(key)
        return jsonify({"key": key, "deleted": deleted})
    
    @app.route('/v1/session/search', methods=['POST', 'GET'])
    def session_search():
        q = request.args.get('q', '') or (request.json or {}).get('q', '')
        limit = min(int(request.args.get('limit', 10)), 50)
        if not q:
            return jsonify({"error": "請提供 q 參數"}), 400
        hits = _get_store().search(q, limit=limit)
        return jsonify({"query": q, "results": [e.to_dict() for e in hits],
                        "count": len(hits)})
    
    @app.route('/v1/session/clear', methods=['POST'])
    def session_clear():
        count = _get_store().clear_session()
        return jsonify({"deleted": count, "session_id": _get_store().session_id})
    
    # ── 啟動輸出 ─────────────────────────────────────────────
    
    # ── Observability 端點（修補：持久化 SQLite）──────────────
    import sqlite3 as _sq, json as _j
    _tdb_path = Path(wd) / '.brain' / 'traces.db'
    
    _tdb_conn = [None]  # singleton holder
    
    def _tdb():
        """Thread-safe SQLite singleton（WAL 模式）"""
        if _tdb_conn[0] is None:
            c = _sq.connect(str(_tdb_path), check_same_thread=False)
            c.row_factory = _sq.Row
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
            _tdb_conn[0] = c
        return _tdb_conn[0]
    
    try: _tdb()
    except Exception: pass
    
    @app.route('/v1/traces', methods=['GET'])
    def v1_traces():
        """最近查詢的 traces（修補：持久化版，重啟後仍保留）"""
        limit = min(int(request.args.get('limit', 20)), 200)
        since = request.args.get('since', '')
        try:
            c = _tdb()
            if since:
                rows = c.execute("SELECT * FROM query_traces WHERE ts > ? ORDER BY ts DESC LIMIT ?", (since, limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM query_traces ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            total = c.execute("SELECT COUNT(*) FROM query_traces").fetchone()[0]
            out = []
            for r in rows:
                d = dict(r)
                try: d['traces'] = _j.loads(d.pop('traces_json', '[]'))
                except: d['traces'] = []
                out.append(d)
            return jsonify({'traces': out, 'total': total})
        except Exception as e:
            return jsonify({'traces': [], 'total': 0, 'error': str(e)}), 500
    
    @app.route('/v1/traces/clear', methods=['POST'])
    def v1_traces_clear():
        try:
            c = _tdb(); c.execute("DELETE FROM query_traces"); c.commit()
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500
    
    @app.route('/v1/traces/stats', methods=['GET'])
    def v1_traces_stats():
        """p50/p95/max 延遲統計"""
        try:
            rows = _tdb().execute("SELECT total_ms FROM query_traces ORDER BY ts DESC LIMIT 200").fetchall()
            if not rows: return jsonify({'count': 0})
            ms = sorted([r[0] for r in rows])
            return jsonify({'count': len(ms), 'avg_ms': round(sum(ms)/len(ms),1),
                            'p95_ms': ms[int(len(ms)*.95)], 'max_ms': max(ms)})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    # ── /v1/nudges — 主動提醒端點（v8.0 NudgeEngine）────────────────
    @app.route('/v1/nudges', methods=['GET'])
    def v1_nudges():
        """
        主動提醒：根據當前任務查詢相關踩坑（v8.0）。
    
        Query params:
          task     任務描述（關鍵字）
          top_k    最多回傳幾條（預設 5）
    
        用法：
          curl "http://localhost:7891/v1/nudges?task=實作+Stripe+退款"
        """
        task  = request.args.get('task', '').strip()
        top_k = min(int(request.args.get('top_k', 5)), 20)
        if not task:
            return jsonify({'error': 'task 參數必填'}), 400
        try:
            from project_brain.nudge_engine import NudgeEngine
            from project_brain.graph import KnowledgeGraph
            g      = KnowledgeGraph(Path(wd) / '.brain')
            engine = NudgeEngine(g)
            nudges = engine.check(task, top_k=top_k)
            return jsonify({
                'task':  task,
                'count': len(nudges),
                'nudges': [n.to_dict() for n in nudges],
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    # ── /v1/nudges/stream — SSE 主動推送（v8.1）─────────────────────────────
    @app.route('/v1/nudges/stream')
    def v1_nudges_stream():
        """Server-Sent Events 推送：Brain 主動推送相關踩坑（v8.1）。
    
        用法：curl -N 'http://localhost:7891/v1/nudges/stream?task=實作支付'
        """
        import time
        task  = request.args.get('task', '').strip()
        top_k = min(int(request.args.get('top_k', 5)), 10)
    
        def _stream():
            """事件驅動 SSE：訂閱 BrainEventBus，有新事件才推送（v9.0）"""
            import json as _json, queue as _q
            evt_q = _q.Queue(maxsize=20)
            # 訂閱 L1a 寫入 + git commit 事件
            try:
                from project_brain.event_bus import BrainEventBus
                bus = BrainEventBus(Path(wd) / '.brain')
                @bus.on('brain.session')
                def _on_s(p):
                    try: evt_q.put_nowait(p)
                    except _q.Full: pass
                @bus.on('git.commit')
                def _on_c(p):
                    try: evt_q.put_nowait(p)
                    except _q.Full: pass
            except Exception:
                pass
            # 初始推送
            def _push_nudges(trigger):
                try:
                    from project_brain.nudge_engine import NudgeEngine
                    from project_brain.graph import KnowledgeGraph
                    g = KnowledgeGraph(Path(wd) / '.brain')
                    nudges = NudgeEngine(g).check(task or 'general', top_k=top_k)
                    return json.dumps({'task': task, 'count': len(nudges),
                                        'trigger': trigger,
                                        'nudges': [n.to_dict() for n in nudges]},
                                       ensure_ascii=False)
                except Exception as e:
                    return json.dumps({'error': str(e)[:60], 'trigger': trigger})
            yield f'data: {_push_nudges("init")}\n\n'
            # 事件驅動循環（有事件立即推送，否則每 60s 心跳）
            while True:
                try:
                    evt_q.get(timeout=60)
                    yield f'data: {_push_nudges("event")}\n\n'
                except _q.Empty:
                    yield ': keepalive\n\n'
                except GeneratorExit:
                    break
                except Exception as e:
                    yield f'data: {{"error": "{str(e)[:40]}"}}\n\n'
    
        return app.response_class(
            _stream(),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )
    
    # ── /v1/events — EventBus 查詢（v8.0）───────────────────────────
    @app.route('/v1/events', methods=['GET'])
    def v1_events():
        """查詢最近事件記錄（v8.0 BrainEventBus）"""
        event_type = request.args.get('type', '')
        limit      = min(int(request.args.get('limit', 20)), 100)
        try:
            from project_brain.event_bus import BrainEventBus
            bus    = BrainEventBus(Path(wd) / '.brain')
            events = bus.recent(event_type=event_type, limit=limit)
            return jsonify({
                'count':  len(events),
                'events': [{'id': e.id, 'ts': e.ts, 'type': e.event_type,
                            'payload': e.payload, 'processed': e.processed}
                           for e in events],
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ── FEAT-10: Webhook 端點 ─────────────────────────────────────────

    @app.route('/webhook/slack', methods=['POST'])
    def webhook_slack():
        """FEAT-10: 接收 nudge 並推送到 Slack Incoming Webhook。

        設定環境變數：BRAIN_SLACK_WEBHOOK_URL=https://hooks.slack.com/...
        請求體：{"task": "...", "message": "..."}  （可選）
        """
        import urllib.request
        slack_url = os.environ.get('BRAIN_SLACK_WEBHOOK_URL', '')
        if not slack_url:
            return jsonify({'error': 'BRAIN_SLACK_WEBHOOK_URL 未設定'}), 400
        data = request.get_json(silent=True) or {}
        task = str(data.get('task', ''))[:200]
        msg  = str(data.get('message', task or 'Brain nudge'))[:500]
        payload = json.dumps({'text': f'🧠 *Project Brain*: {msg}'}).encode()
        try:
            req = urllib.request.Request(
                slack_url, data=payload,
                headers={'Content-Type': 'application/json'}, method='POST'
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                ok = r.status == 200
        except Exception as exc:
            return jsonify({'error': str(exc)[:100]}), 500
        return jsonify({'sent': ok})

    @app.route('/webhook/github', methods=['POST'])
    def webhook_github():
        """FEAT-10: 接收 GitHub push 事件，觸發 brain sync。

        GitHub Webhook 設定：Content-Type: application/json, Event: push
        """
        import subprocess
        event = request.headers.get('X-GitHub-Event', '')
        if event not in ('push', 'ping'):
            return jsonify({'skipped': True, 'reason': 'not push/ping'}), 200
        if event == 'ping':
            return jsonify({'pong': True}), 200
        try:
            result = subprocess.run(
                ['brain', 'sync', '--workdir', wd, '--quiet'],
                capture_output=True, text=True, timeout=30
            )
            return jsonify({
                'synced': result.returncode == 0,
                'stdout': result.stdout[:200],
                'stderr': result.stderr[:200],
            })
        except Exception as exc:
            return jsonify({'error': str(exc)[:100]}), 500

    return app
