"""
project_brain/brain_db.py -- Unified BrainDB (v10.0)

Single brain.db replaces 6 scattered SQLite files.
L2 temporal memory replaces FalkorDB with pure SQLite.
"""
from __future__ import annotations
import hashlib, json, logging, sqlite3, threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1

_SYNONYM_MAP = {
    "token":    ["jwt","bearer","auth"],
    "jwt":      ["token","bearer","rs256","hs256","auth"],
    "auth":     ["jwt","token","authentication"],
    "webhook":  ["idempotency","callback","stripe"],
    "stripe":   ["webhook","payment","charge"],
    "db":       ["database","postgres","postgresql","mysql"],
    "database": ["db","postgres","postgresql","sql"],
    "cache":    ["redis","memcached","ttl"],
    "error":    ["exception","bug","failure","crash"],
    "test":     ["unittest","pytest","mock"],
}


class BrainDB:
    """Single SQLite database holding all Project Brain data."""

    def __init__(self, brain_dir: Path):
        self.brain_dir = Path(brain_dir)
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.brain_dir / "brain.db"
        self._local  = threading.local()
        self._setup()

    @property
    def conn(self) -> sqlite3.Connection:
        if not getattr(self._local, "conn", None):
            c = sqlite3.connect(str(self.db_path), check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=5000")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return self._local.conn

    def _setup(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS brain_meta (
                key TEXT PRIMARY KEY, value TEXT
            );
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL,
                content TEXT DEFAULT '', tags TEXT DEFAULT '[]',
                source_url TEXT DEFAULT '', author TEXT DEFAULT '',
                meta TEXT DEFAULT '{}',
                confidence REAL NOT NULL DEFAULT 0.8,
                importance REAL NOT NULL DEFAULT 0.5,
                is_pinned INTEGER NOT NULL DEFAULT 0,
                applicability_condition TEXT DEFAULT '',
                invalidation_condition  TEXT DEFAULT '',
                perspective TEXT DEFAULT '',
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed TEXT DEFAULT '',
                emotional_weight REAL NOT NULL DEFAULT 0.5,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                scope      TEXT NOT NULL DEFAULT 'global'
            );
            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL, relation TEXT NOT NULL, target_id TEXT NOT NULL,
                note TEXT DEFAULT '', causal_direction TEXT DEFAULT 'CORRELATES',
                FOREIGN KEY(source_id) REFERENCES nodes(id) ON DELETE CASCADE,
                FOREIGN KEY(target_id) REFERENCES nodes(id) ON DELETE CASCADE
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                id, title, content, tags,
                tokenize='unicode61'
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL, key TEXT NOT NULL,
                value TEXT NOT NULL, category TEXT DEFAULT 'general',
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(session_id, key)
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_sid ON sessions(session_id);
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY, content TEXT NOT NULL,
                source TEXT DEFAULT '', ref_time TEXT DEFAULT (datetime('now')),
                confidence REAL DEFAULT 0.5,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS node_vectors (
                node_id TEXT PRIMARY KEY,
                vector  BLOB NOT NULL,
                dim     INTEGER NOT NULL DEFAULT 768,
                model   TEXT DEFAULT 'nomic-embed-text',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS temporal_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL, relation TEXT NOT NULL, target_id TEXT NOT NULL,
                valid_from TEXT DEFAULT (datetime('now')),
                valid_until TEXT DEFAULT NULL, content TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_te_source ON temporal_edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_te_valid  ON temporal_edges(valid_from, valid_until);
            CREATE TABLE IF NOT EXISTS traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
                query TEXT, results TEXT DEFAULT '[]',
                latency_ms REAL DEFAULT 0, created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL, payload TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        """)
        # P1-A: scope column migration for existing databases
        try:
            self.conn.execute("ALTER TABLE nodes ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'")
        except Exception:
            pass  # column already exists
        # A-22: episode confidence column
        try:
            self.conn.execute("ALTER TABLE episodes ADD COLUMN confidence REAL DEFAULT 0.5")
        except Exception:
            pass
        # Phase 1: node_vectors table migration
        try:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS node_vectors (
                    node_id TEXT PRIMARY KEY,
                    vector  BLOB NOT NULL,
                    dim     INTEGER NOT NULL DEFAULT 768,
                    model   TEXT DEFAULT 'nomic-embed-text',
                    created_at TEXT DEFAULT (datetime('now'))
                )"""
            )
        except Exception:
            pass

        self.conn.execute(
            "INSERT OR IGNORE INTO brain_meta(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),)
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO brain_meta(key,value) VALUES('created_at',datetime('now'))"
        )
        self.conn.commit()

    # -- helpers --

    @staticmethod
    def _ngram(text: str) -> str:
        import re
        return re.sub(r"([\u4e00-\u9fff])", r" \1 ", text or "")

    def _expand_terms(self, query: str) -> list:
        import re
        raw   = re.findall(r"[a-zA-Z0-9_]+", query.lower())
        cjk   = re.findall(r"[\u4e00-\u9fff]+", query)
        ngrams = []
        for seg in cjk:
            for n in (2, 3):
                ngrams += [seg[i:i+n].lower() for i in range(len(seg)-n+1)]
        expanded, seen = [], set()
        def add(w):
            w = re.sub(r"[^\w\u4e00-\u9fff]", "", w)
            if w and len(w) >= 2 and w not in seen:
                seen.add(w); expanded.append(w)
        for w in raw + ngrams + [query.lower()]:
            add(w)
            for syn in _SYNONYM_MAP.get(w, []):
                add(syn)
        return expanded[:25]

    # -- L3: knowledge nodes --

    def add_node(self, node_id: str, node_type: str, title: str,
                 content: str = "", tags=None, scope: str = "global", **kw) -> str:
        tags_json  = json.dumps(tags or [], ensure_ascii=False)
        meta       = kw.get("meta", {})
        confidence = float(kw.get("confidence",
                           meta.get("confidence", 0.8) if isinstance(meta, dict) else 0.8))
        self.conn.execute("""
            INSERT OR REPLACE INTO nodes
                (id,type,title,content,tags,confidence,importance,
                 emotional_weight,source_url,author,meta,scope)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (node_id, node_type, title, content, tags_json,
              confidence,
              float(kw.get("importance", 0.5)),
              float(kw.get("emotional_weight", 0.5)),
              kw.get("source_url",""), kw.get("author",""),
              json.dumps(meta if isinstance(meta, dict) else {}, ensure_ascii=False),
              scope))
        try:
            self.conn.execute("DELETE FROM nodes_fts WHERE id=?", (node_id,))
            self.conn.execute(
                "INSERT INTO nodes_fts(id,title,content,tags) VALUES(?,?,?,?)",
                (node_id, self._ngram(title), self._ngram(content), tags_json)
            )
        except Exception:
            pass
        self.conn.commit()
        return node_id

    def update_node(self, node_id: str, title=None, content=None,
                    confidence=None, importance=None) -> bool:
        ex = self.get_node(node_id)
        if not ex:
            return False
        ups, params = [], []
        if title      is not None: ups.append("title=?");      params.append(title)
        if content    is not None: ups.append("content=?");    params.append(content)
        if confidence is not None: ups.append("confidence=?"); params.append(confidence)
        if importance is not None: ups.append("importance=?"); params.append(importance)
        if not ups:
            return True
        ups.append("updated_at=datetime('now')")
        params.append(node_id)
        self.conn.execute(f"UPDATE nodes SET {', '.join(ups)} WHERE id=?", params)
        if title is not None or content is not None:
            nt = title   if title   is not None else ex["title"]
            nc = content if content is not None else ex["content"]
            try:
                self.conn.execute("DELETE FROM nodes_fts WHERE id=?", (node_id,))
                self.conn.execute(
                    "INSERT INTO nodes_fts(id,title,content,tags) VALUES(?,?,?,?)",
                    (node_id, self._ngram(nt), self._ngram(nc), ex.get("tags","[]"))
                )
            except Exception:
                pass
        self.conn.commit()
        return True

    def get_node(self, node_id: str):
        r = self.conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return dict(r) if r else None

    def search_nodes(self, query: str, node_type=None, limit: int = 8, scope: str = None) -> list:
        terms = self._expand_terms(query)
        if not terms:
            return []
        fts_q = " OR ".join(f'"{t}"' for t in terms)
        try:
            # P1-A: scope-aware search
            # matching scope first (0), global second (1), other scopes excluded
            if scope and scope != "global":
                sf  = "AND (n.scope=? OR n.scope='global')"
                sp  = [scope]
            else:
                sf, sp = "", []
            _s = scope or "global"
            sort_clause = "CASE WHEN n.scope=? THEN 0 ELSE 1 END, n.is_pinned DESC, n.confidence DESC"
            if node_type:
                rows = self.conn.execute(
                    f"SELECT n.* FROM nodes_fts f JOIN nodes n ON f.id=n.id"
                    f" WHERE nodes_fts MATCH ? AND n.type=? {sf}"
                    f" ORDER BY {sort_clause} LIMIT ?",
                    (fts_q, node_type, *sp, _s, limit)).fetchall()
            else:
                rows = self.conn.execute(
                    f"SELECT n.* FROM nodes_fts f JOIN nodes n ON f.id=n.id"
                    f" WHERE nodes_fts MATCH ? {sf}"
                    f" ORDER BY {sort_clause} LIMIT ?",
                    (fts_q, *sp, _s, limit)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def record_access(self, node_id: str) -> None:
        self.conn.execute(
            "UPDATE nodes SET access_count=access_count+1,"
            " last_accessed=datetime('now') WHERE id=?", (node_id,)
        )
        self.conn.commit()

    def record_feedback(self, node_id: str, helpful: bool) -> float:
        """
        Confidence feedback loop — called after an Agent actually uses a node.

        helpful=True  → confidence += BOOST   (capped at 1.0)
        helpful=False → confidence -= PENALTY  (floored at DECAY_FLOOR=0.05)

        Returns the updated confidence value.
        """
        BOOST   = 0.03   # +3% per positive signal
        PENALTY = 0.05   # -5% per negative signal
        FLOOR   = 0.05

        row = self.conn.execute(
            "SELECT confidence FROM nodes WHERE id=?", (node_id,)
        ).fetchone()
        if not row:
            return 0.0

        current = float(row[0])
        if helpful:
            new_conf = min(1.0, current + BOOST)
        else:
            new_conf = max(FLOOR, current - PENALTY)

        self.conn.execute(
            "UPDATE nodes SET confidence=?, updated_at=datetime('now') WHERE id=?",
            (new_conf, node_id)
        )
        self.conn.commit()
        return new_conf

    def pin_node(self, node_id: str, pinned: bool = True) -> bool:
        r = self.conn.execute(
            "UPDATE nodes SET is_pinned=? WHERE id=?", (int(pinned), node_id)
        )
        self.conn.commit()
        return r.rowcount > 0

    def delete_node(self, node_id: str) -> bool:
        r = self.conn.execute("DELETE FROM nodes WHERE id=?", (node_id,))
        self.conn.commit()
        return r.rowcount > 0

    def all_nodes(self, node_type=None, limit: int = 500) -> list:
        if node_type:
            rows = self.conn.execute(
                "SELECT * FROM nodes WHERE type=? ORDER BY confidence DESC LIMIT ?",
                (node_type, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM nodes ORDER BY confidence DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def add_edge(self, source_id: str, relation: str, target_id: str, note: str = "") -> int:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO edges(source_id,relation,target_id,note) VALUES(?,?,?,?)",
            (source_id, relation, target_id, note)
        )
        self.conn.commit()
        return cur.lastrowid or 0

    def stats(self) -> dict:
        rows  = self.conn.execute("SELECT type,COUNT(*) c FROM nodes GROUP BY type").fetchall()
        total = self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        eps   = self.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        sess  = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        return {"total": total, "by_type": {r["type"]: r["c"] for r in rows},
                "episodes": eps, "sessions": sess}

    # -- L2: temporal memory (pure SQLite, replaces FalkorDB) --

    # ── Phase 1: Vector Storage ───────────────────────────────────

    def add_vector(self, node_id: str, vector: list, model: str = 'nomic-embed-text') -> bool:
        """Store embedding vector for a node (Phase 1)."""
        try:
            import struct
            blob = struct.pack(f'{len(vector)}f', *vector)
            self.conn.execute(
                "INSERT OR REPLACE INTO node_vectors(node_id,vector,dim,model) VALUES(?,?,?,?)",
                (node_id, blob, len(vector), model)
            )
            self.conn.commit()
            return True
        except Exception as e:
            import logging; logging.getLogger(__name__).debug('add_vector failed: %s', e)
            return False

    @staticmethod
    def _cosine_similarity(a: list, b: list) -> float:
        """Pure-Python cosine similarity between two equal-length float lists."""
        import math
        dot  = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def search_nodes_by_vector(self, query_vector: list, threshold: float = 0.30,
                               limit: int = 8, scope: str = None) -> list:
        """
        Phase 1: Semantic search via cosine similarity.

        Tries sqlite-vec C extension first (faster), then falls back to
        pure-Python cosine similarity (always works, zero extra deps).

        threshold: cosine *similarity* threshold (higher = more similar)
                   0.0 = orthogonal, 1.0 = identical
                   good practical values: 0.3 (loose) to 0.7 (tight)
        """
        if not query_vector:
            return []

        # ── Path A: sqlite-vec C extension ────────────────────────
        try:
            import struct, sqlite_vec as sv
            conn2 = self.conn
            conn2.enable_load_extension(True)
            sv.load(conn2)
            conn2.enable_load_extension(False)

            dim  = len(query_vector)
            blob = struct.pack(f'{dim}f', *query_vector)

            # sqlite-vec uses cosine *distance* (0=identical, 2=opposite)
            # convert our similarity threshold: dist_max = 1 - threshold
            dist_threshold = 1.0 - threshold

            rows = conn2.execute("""
                SELECT n.*, vec_distance_cosine(nv.vector, ?) as dist
                FROM node_vectors nv
                JOIN nodes n ON nv.node_id = n.id
                WHERE nv.dim = ?
                ORDER BY dist ASC
                LIMIT ?
            """, (blob, dim, limit * 2)).fetchall()

            results = []
            for r in rows:
                if r['dist'] > dist_threshold:
                    continue
                if scope and scope != 'global':
                    if r['scope'] not in (scope, 'global'):
                        continue
                results.append(dict(r))
                if len(results) >= limit:
                    break
            return results

        except Exception:
            pass  # fall through to pure-Python path

        # ── Path B: pure-Python cosine similarity ─────────────────
        try:
            import struct
            dim  = len(query_vector)

            rows = self.conn.execute("""
                SELECT n.*, nv.vector, nv.dim
                FROM node_vectors nv
                JOIN nodes n ON nv.node_id = n.id
                WHERE nv.dim = ?
            """, (dim,)).fetchall()

            scored = []
            for r in rows:
                stored = list(struct.unpack(f'{dim}f', r['vector']))
                sim    = self._cosine_similarity(query_vector, stored)
                if sim < threshold:
                    continue
                if scope and scope != 'global':
                    if r['scope'] not in (scope, 'global'):
                        continue
                scored.append((sim, dict(r)))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [n for _, n in scored[:limit]]

        except Exception as e:
            import logging; logging.getLogger(__name__).debug('vector search failed: %s', e)
            return []

    def hybrid_search(self, query: str, query_vector: list = None,
                      scope: str = None, limit: int = 8) -> list:
        """
        Phase 1: Hybrid search = vector × 0.6 + FTS5 × 0.4.
        If no vector available, falls back to FTS5 only.
        """
        # FTS5 results
        fts_results = self.search_nodes(query, scope=scope, limit=limit)
        if not query_vector:
            return fts_results  # pure FTS5 fallback

        # Vector results
        vec_results = self.search_nodes_by_vector(
            query_vector, threshold=0.8, limit=limit, scope=scope
        )

        # Merge: assign scores, deduplicate
        scored: dict[str, tuple[dict, float]] = {}
        for i, n in enumerate(fts_results):
            nid = n['id']
            fts_score = (limit - i) / limit  # rank-based score 0.0–1.0
            scored[nid] = (n, fts_score * 0.4)
        for i, n in enumerate(vec_results):
            nid = n['id']
            vec_score = (1.0 - n.get('dist', 0.5))  # convert distance to similarity
            if nid in scored:
                scored[nid] = (scored[nid][0], scored[nid][1] + vec_score * 0.6)
            else:
                scored[nid] = (n, vec_score * 0.6)

        # Sort by combined score
        merged = sorted(scored.values(), key=lambda x: x[1], reverse=True)
        return [n for n, _ in merged[:limit]]

    def get_nodes_without_vectors(self, limit: int = 100) -> list:
        """Return nodes that don't have embeddings yet (for batch indexing)."""
        rows = self.conn.execute("""
            SELECT n.id, n.title, n.content FROM nodes n
            LEFT JOIN node_vectors nv ON n.id = nv.node_id
            WHERE nv.node_id IS NULL
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def link_episode_to_nodes(self, episode_id: str,
                              episode_content: str,
                              threshold: float = 0.80) -> int:
        """
        Phase 4: Auto-link L2 episode to semantically similar L3 nodes.
        Builds DERIVES_FROM edges so context.py can deduplicate output.

        Returns: number of links created
        """
        # Strategy A: vector similarity (requires Phase 1 embedding)
        linked = 0
        try:
            from .embedder import get_embedder
            _emb = get_embedder()
            if _emb:
                ep_vec = _emb.embed(episode_content[:1000])
                if ep_vec:
                    similar = self.search_nodes_by_vector(
                        ep_vec, threshold=threshold, limit=3
                    )
                    for node in similar:
                        self.add_temporal_edge(
                            episode_id, 'DERIVES_FROM', node['id'],
                            content='auto-linked (vector similarity)'
                        )
                        linked += 1
                    return linked
        except Exception:
            pass

        # Strategy B: FTS5 keyword overlap fallback
        try:
            results = self.search_nodes(episode_content[:200], limit=3)
            ep_words = set(episode_content.lower().split())
            for node in results:
                node_words = set((node['title'] + ' ' + node['content']).lower().split())
                overlap = len(ep_words & node_words) / max(len(node_words), 1)
                if overlap >= 0.35:  # 35% keyword overlap
                    self.add_temporal_edge(
                        episode_id, 'DERIVES_FROM', node['id'],
                        content=f'auto-linked (fts overlap={overlap:.2f})'
                    )
                    linked += 1
        except Exception:
            pass
        return linked

    def get_episode_links(self, episode_id: str) -> list:
        """Phase 4: Get L3 nodes linked to an episode via DERIVES_FROM."""
        try:
            rows = self.conn.execute("""
                SELECT n.* FROM temporal_edges te
                JOIN nodes n ON te.target_id = n.id
                WHERE te.source_id = ? AND te.relation = 'DERIVES_FROM'
            """, (episode_id,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ── L2: temporal memory ───────────────────────────────────────────

    def add_episode(self, content: str, source: str = "", ref_time=None, confidence: float = 0.5) -> str:
        eid = "ep-" + hashlib.md5(f"{content}{source}".encode()).hexdigest()[:8]
        ts  = ref_time or datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO episodes(id,content,source,ref_time,confidence) VALUES(?,?,?,?,?)",
            (eid, content, source, ts, confidence)
        )
        self.conn.commit()
        return eid

    def recent_episodes(self, limit: int = 10) -> list:
        rows = self.conn.execute(
            "SELECT * FROM episodes ORDER BY ref_time DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def search_episodes(self, query: str, limit: int = 5) -> list:
        rows = self.conn.execute(
            "SELECT * FROM episodes WHERE content LIKE ? ORDER BY ref_time DESC LIMIT ?",
            (f"%{query}%", limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def add_temporal_edge(self, source_id: str, relation: str, target_id: str,
                          content: str = "", valid_from=None) -> int:
        ts = valid_from or datetime.now(timezone.utc).isoformat()
        # Invalidate previous edges with same source+relation (relationship changed)
        self.conn.execute("""
            UPDATE temporal_edges SET valid_until=?
            WHERE source_id=? AND relation=? AND valid_until IS NULL
        """, (ts, source_id, relation))
        cur = self.conn.execute(
            "INSERT INTO temporal_edges(source_id,relation,target_id,content,valid_from)"
            " VALUES(?,?,?,?,?)",
            (source_id, relation, target_id, content, ts)
        )
        self.conn.commit()
        return cur.lastrowid or 0

    def temporal_query(self, at_time=None, limit: int = 20) -> list:
        at   = at_time or datetime.now(timezone.utc).isoformat()
        rows = self.conn.execute("""
            SELECT * FROM temporal_edges
            WHERE valid_from<=? AND (valid_until IS NULL OR valid_until>?)
            ORDER BY valid_from DESC LIMIT ?
        """, (at, at, limit)).fetchall()
        return [dict(r) for r in rows]

    # -- L1a: session store --

    def session_set(self, key: str, value: str,
                    session_id: str = "default", category: str = "general") -> None:
        self.conn.execute("""
            INSERT INTO sessions(session_id,key,value,category) VALUES(?,?,?,?)
            ON CONFLICT(session_id,key) DO UPDATE SET value=excluded.value
        """, (session_id, key, value, category))
        self.conn.commit()

    def session_get(self, key: str, session_id: str = "default"):
        r = self.conn.execute(
            "SELECT value FROM sessions WHERE session_id=? AND key=?", (session_id, key)
        ).fetchone()
        return r[0] if r else None

    def session_list(self, session_id: str = "default") -> list:
        rows = self.conn.execute(
            "SELECT key,value,category,created_at FROM sessions"
            " WHERE session_id=? ORDER BY created_at DESC", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def session_clear(self, session_id: str = "default") -> int:
        cur = self.conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        self.conn.commit()
        return cur.rowcount

    # -- events --

    def emit(self, event_type: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT INTO events(event_type,payload) VALUES(?,?)",
            (event_type, json.dumps(payload, ensure_ascii=False))
        )
        self.conn.commit()

    def recent_events(self, event_type=None, limit: int = 20) -> list:
        if event_type:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE event_type=? ORDER BY created_at DESC LIMIT ?",
                (event_type, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # -- legacy migration --

    def migrate_from_legacy(self, brain_dir: Path) -> dict:
        """Import from old 6-file layout. Idempotent."""
        imported = {"nodes": 0, "sessions": 0, "events": 0}
        kg = brain_dir / "knowledge_graph.db"
        if kg.exists():
            try:
                old = sqlite3.connect(str(kg)); old.row_factory = sqlite3.Row
                for row in old.execute("SELECT * FROM nodes").fetchall():
                    d = dict(row)
                    try:
                        meta = {}
                        try: meta = json.loads(d.get("meta") or "{}")
                        except Exception: pass
                        self.add_node(d["id"], d["type"], d["title"],
                                      content=d.get("content",""),
                                      confidence=d.get("confidence", 0.8),
                                      importance=d.get("importance", 0.5),
                                      emotional_weight=d.get("emotional_weight", 0.5),
                                      meta=meta)
                        imported["nodes"] += 1
                    except Exception: pass
                old.close()
            except Exception as e:
                logger.warning("Legacy node migration: %s", e)
        ss = brain_dir / "session_store.db"
        if ss.exists():
            try:
                old = sqlite3.connect(str(ss)); old.row_factory = sqlite3.Row
                for tbl in ("sessions", "memories"):
                    try:
                        for row in old.execute(f"SELECT * FROM {tbl}").fetchall():
                            d = dict(row)
                            self.session_set(str(d.get("key","?")),
                                             str(d.get("value","")),
                                             session_id=str(d.get("session_id","legacy")))
                            imported["sessions"] += 1
                    except Exception: pass
                old.close()
            except Exception as e:
                logger.warning("Legacy session migration: %s", e)
        ev = brain_dir / "events.db"
        if ev.exists():
            try:
                old = sqlite3.connect(str(ev)); old.row_factory = sqlite3.Row
                for row in old.execute("SELECT * FROM events").fetchall():
                    d = dict(row)
                    try:
                        self.emit(d.get("event_type","legacy"),
                                  json.loads(d.get("payload") or "{}"))
                        imported["events"] += 1
                    except Exception: pass
                old.close()
            except Exception as e:
                logger.warning("Legacy event migration: %s", e)
        return imported
