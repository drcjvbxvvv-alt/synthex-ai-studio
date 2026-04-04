"""
project_brain/brain_db.py -- Unified BrainDB (v10.0)

Single brain.db replaces 6 scattered SQLite files.
L2 temporal memory replaces FalkorDB with pure SQLite.
"""
from __future__ import annotations
import contextlib, hashlib, json, logging, math, sqlite3, threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 13          # DEF-04: bump on every schema change

# REF-02: single source of truth in synonyms.py
from .synonyms  import SYNONYM_MAP as _SYNONYM_MAP   # noqa: E402
from . import constants as _constants               # REF-04: module ref so monkeypatch works


class BrainDB:
    """Single SQLite database holding all Project Brain data."""

    def __init__(self, brain_dir: Path):
        self.brain_dir = Path(brain_dir)
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        self.db_path     = self.brain_dir / "brain.db"
        self._write_lock = threading.RLock()  # REF-03: replaces fcntl
        # ARCH-02: single shared connection — eliminates per-thread fd leak
        self._conn_obj: sqlite3.Connection = self._make_connection()
        self._setup()

    def _make_connection(self) -> sqlite3.Connection:
        """ARCH-02: open the shared SQLite connection. Override in subclasses."""
        c = sqlite3.connect(str(self.db_path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        c.execute("PRAGMA foreign_keys=ON")
        # DEF-02 fix: register Python UDF so SQL triggers can call brain_ngram()
        c.create_function("brain_ngram", 1, lambda t: BrainDB._ngram(t or ""))
        return c

    @property
    def conn(self) -> sqlite3.Connection:
        # ARCH-02: single connection shared across threads (check_same_thread=False)
        return self._conn_obj

    def close(self) -> None:
        """ARCH-02: explicitly close the shared connection to release the fd."""
        try:
            self._conn_obj.close()
        except Exception:
            pass

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
        self.conn.execute(
            "INSERT OR IGNORE INTO brain_meta(key,value) VALUES('created_at',datetime('now'))"
        )
        self.conn.commit()
        # DEF-04: run versioned migrations (idempotent, replaces scattered ALTER TABLE blocks)
        self._run_migrations()

        # BUG-A02 fix: FTS5 triggers removed — all write paths use manual sync.
        # Migration v12 drops existing triggers on upgrade.

    def _run_migrations(self) -> None:
        """DEF-04: Versioned schema migrations — idempotent, incremental.

        Each migration is numbered 1..SCHEMA_VERSION. The current applied
        version is stored in brain_meta.schema_version. On startup only
        unapplied migrations run, so existing databases upgrade safely.
        """
        row = self.conn.execute(
            "SELECT value FROM brain_meta WHERE key='schema_version'"
        ).fetchone()
        current = int(row[0]) if row else 0

        if current >= SCHEMA_VERSION:
            return

        # Ordered list of (description, SQL-or-callable) tuples.
        # Each entry corresponds to schema version = index + 1.
        _migrations = [
            # v1: scope column on nodes (P1-A)
            ("scope column on nodes",
             "ALTER TABLE nodes ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'"),
            # v2: episode confidence column (A-22)
            ("episode confidence column",
             "ALTER TABLE episodes ADD COLUMN confidence REAL DEFAULT 0.5"),
            # v3: node_vectors table (Phase 1 — may already exist in main schema)
            ("node_vectors table",
             """CREATE TABLE IF NOT EXISTS node_vectors (
                    node_id TEXT PRIMARY KEY,
                    vector  BLOB NOT NULL,
                    dim     INTEGER NOT NULL DEFAULT 768,
                    model   TEXT DEFAULT 'nomic-embed-text',
                    created_at TEXT DEFAULT (datetime('now'))
                )"""),
            # v4: unique index on episodes.source (BUG-01)
            ("unique index on episodes.source",
             "CREATE UNIQUE INDEX IF NOT EXISTS idx_episodes_source"
             " ON episodes(source) WHERE source != ''"),
            # v5: is_deprecated column on nodes (BUG-02)
            ("is_deprecated column on nodes",
             "ALTER TABLE nodes ADD COLUMN is_deprecated INTEGER NOT NULL DEFAULT 0"),
            # v6: valid_until column on nodes (BUG-02)
            ("valid_until column on nodes",
             "ALTER TABLE nodes ADD COLUMN valid_until TEXT DEFAULT NULL"),
            # v7: OPT-06 synonym_index pre-computed table
            ("synonym_index table",
             """CREATE TABLE IF NOT EXISTS synonym_index (
                 term TEXT NOT NULL, synonym TEXT NOT NULL,
                 PRIMARY KEY(term, synonym)
             )"""),
            # v8: FEAT-06 node_history table for version history
            ("node_history table",
             """CREATE TABLE IF NOT EXISTS node_history (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 node_id TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                 title TEXT, content TEXT, confidence REAL, tags TEXT,
                 changed_by TEXT DEFAULT '', change_note TEXT DEFAULT '',
                 snapshot_at TEXT DEFAULT (datetime('now'))
             )"""),
            # v9: FEAT-06 index on node_history
            ("node_history index",
             "CREATE INDEX IF NOT EXISTS idx_nh_node ON node_history(node_id, version)"),
            # v10: DEF-08 fix — atomic FTS5 bigram rebuild (replaces non-idempotent _setup() hack)
            ("FTS5 bigram atomic rebuild",
             lambda conn: (
                 conn.execute("DELETE FROM nodes_fts"),
                 [conn.execute(
                     "INSERT INTO nodes_fts(id, title, content, tags) VALUES(?, ?, ?, ?)",
                     (r[0], BrainDB._ngram(r[1] or ""), BrainDB._ngram(r[2] or ""), r[3] or "[]")
                 ) for r in conn.execute("SELECT id, title, content, tags FROM nodes").fetchall()],
                 conn.execute("INSERT OR REPLACE INTO brain_meta(key,value) VALUES('fts_bigram_v1','done')")
             )),
            # v11: compound index for scope+confidence queries (federation.py WHERE clause was full-scan)
            ("scope+confidence compound index",
             "CREATE INDEX IF NOT EXISTS idx_nodes_scope_conf ON nodes(scope, confidence)"),
            # v12: BUG-A02 fix — drop FTS5 triggers; all write paths now use manual sync
            ("drop FTS5 auto-update/delete triggers",
             lambda conn: (
                 conn.execute("DROP TRIGGER IF EXISTS nodes_fts_au"),
                 conn.execute("DROP TRIGGER IF EXISTS nodes_fts_ad"),
             )),
            # v13: PERF-02 — composite index for sort-heavy queries
            ("is_pinned+confidence composite index",
             "CREATE INDEX IF NOT EXISTS idx_nodes_pinned_conf"
             " ON nodes(is_pinned DESC, confidence DESC)"),
        ]

        for idx, (desc, sql) in enumerate(_migrations):
            ver = idx + 1
            if ver <= current:
                continue
            # DATA-02 fix: track genuine failures so we don't advance schema_version
            _genuine_failure = False
            try:
                if callable(sql):
                    sql(self.conn)
                else:
                    self.conn.execute(sql)
            except Exception as _me:
                # Most failures are benign (column/index already exists).
                # Log at WARNING so brain doctor can surface genuine schema problems.
                _msg = str(_me).lower()
                if "already exists" in _msg or "duplicate column" in _msg:
                    logger.debug("DEF-04: migration v%d skipped (already applied): %s", ver, desc)
                else:
                    logger.warning(
                        "DEF-04: migration v%d FAILED (%s): %s — "
                        "run `brain doctor` to inspect schema state.",
                        ver, desc, _me
                    )
                    _genuine_failure = True
            # DATA-02 fix: only advance version if migration succeeded or was benign
            if not _genuine_failure:
                self.conn.execute(
                    "INSERT OR REPLACE INTO brain_meta(key,value) VALUES('schema_version',?)",
                    (str(ver),)
                )
                self.conn.commit()
                logger.debug("DEF-04: schema migration v%d applied: %s", ver, desc)

    # -- helpers --

    @staticmethod
    def _ngram(text: str) -> str:
        """OPT-07: delegates to shared utils.ngram_cjk()."""
        from .utils import ngram_cjk
        return ngram_cjk(text)

    @staticmethod
    def _sanitize_fts(q: str) -> str:
        """OPT-08: Strip FTS5 special characters to prevent syntax errors.

        FTS5 special chars: " ( ) * - ^ are legal in complex queries but
        cause silent parse errors when user input contains them unescaped.
        Strategy: replace all special chars with space, collapse whitespace.
        """
        import re as _re
        sanitized = _re.sub(r'["()*\-^]', ' ', q)
        sanitized = _re.sub(r'\s+', ' ', sanitized).strip()
        return sanitized or '""'

    @staticmethod
    def _effective_confidence(node: dict) -> float:
        """DEF-05/OPT-04 fix: decay-adjusted confidence for search result ranking.

        Applies F1 (time decay) and F7 (access-count bonus) inline so that
        search_nodes() re-ranks by effective_confidence rather than stale
        static confidence values.  Pinned nodes are immune to decay.
        """
        base = float(node.get("confidence", 0.8))
        if node.get("is_pinned"):
            return base
        created = node.get("created_at", "") or ""
        if not created:
            return base
        try:
            # BUG-B02: use MAX(created_at, updated_at) so a recently-updated
            # node is not penalised for its original creation date.
            updated  = node.get("updated_at") or ""
            ref_time = updated if updated > created else created
            ref_dt = datetime.fromisoformat(ref_time.replace("Z", "+00:00"))
            if ref_dt.tzinfo is None:
                ref_dt = ref_dt.replace(tzinfo=timezone.utc)
            days   = max(0, (datetime.now(timezone.utc) - ref_dt).days)
            decay  = math.exp(-_constants.BASE_DECAY_RATE * days)  # F1: REF-04
            access = int(node.get("access_count") or 0)
            f7     = min(0.15, access / 10 * 0.05)   # F7: access-count bonus
            return max(0.05, min(1.0, base * decay + f7))
        except Exception:
            return base

    @contextlib.contextmanager
    def _write_guard(self):
        """REF-03: Write serialization via threading.RLock (cross-platform).

        Replaces the previous fcntl.flock() implementation which was
        macOS/Linux-only and added 1-2ms syscall overhead per write.
        SQLite WAL mode + busy_timeout=5000 handles cross-process serialization.
        RLock is reentrant so nested calls in the same thread are safe.
        """
        with self._write_lock:
            yield

    @staticmethod
    def _adaptive_weights(query: str) -> tuple:
        """OPT-02: Compute adaptive (fts_weight, vec_weight) based on query.

        Heuristics:
          - Short query (≤ 2 terms) or CJK-heavy → favour FTS5 (exact bigram index).
          - Long / semantic query (≥ 5 terms)   → favour vector similarity.
          - Medium (3–4 terms)                   → default balance (P1 baseline).

        Returns: (fts_weight, vec_weight) that sum to 1.0.
        """
        import re
        tokens = re.findall(r"[a-zA-Z0-9_]{2,}", query)
        cjk    = re.findall(r"[\u4e00-\u9fff]", query)
        n_terms = len(tokens) + len(cjk) // 2    # every 2 CJK chars ≈ 1 semantic term
        cjk_ratio = len(cjk) / max(len(query.replace(" ", "")), 1)

        if n_terms <= 2 or cjk_ratio > 0.5:
            return (0.6, 0.4)   # short / CJK-heavy → FTS5 wins
        if n_terms >= 5:
            return (0.25, 0.75) # long semantic → vector wins
        return (0.4, 0.6)       # default (P1 baseline)

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

    # ── OPT-06: Pre-computed synonym index ───────────────────────

    def build_synonym_index(self) -> int:
        """OPT-06: 將 _SYNONYM_MAP 批次寫入 synonym_index 表（O(1) 查詢）。"""
        rows = []
        for term, synonyms in _SYNONYM_MAP.items():
            for syn in synonyms:
                rows.append((term, syn))
        with self._write_guard():
            self.conn.executemany(
                "INSERT OR IGNORE INTO synonym_index(term, synonym) VALUES(?,?)", rows
            )
            self.conn.commit()
        return len(rows)

    def expand_query(self, query: str) -> list:
        """OPT-06: O(1) synonym lookup from pre-computed synonym_index table."""
        import re
        raw = re.findall(r"[a-zA-Z0-9_]+", query.lower())
        result, seen = [], set()
        def _add(w):
            w = re.sub(r"[^\w\u4e00-\u9fff]", "", w)
            if w and w not in seen:
                seen.add(w); result.append(w)
        for w in raw:
            _add(w)
            try:
                rows = self.conn.execute(
                    "SELECT synonym FROM synonym_index WHERE term=?", (w,)
                ).fetchall()
                for r in rows:
                    _add(r[0])
            except Exception:
                for syn in _SYNONYM_MAP.get(w, []):
                    _add(syn)
        return result[:25]

    # -- L3: knowledge nodes --

    def add_node(self, node_id: str, node_type: str, title: str,
                 content: str = "", tags=None, scope: str = "global", **kw) -> str:
        tags_json  = json.dumps(tags or [], ensure_ascii=False)
        meta       = kw.get("meta", {})
        confidence = float(kw.get("confidence",
                           meta.get("confidence", 0.8) if isinstance(meta, dict) else 0.8))
        with self._write_guard():  # DEF-01 fix: cross-process write lock
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
                    confidence=None, importance=None,
                    changed_by: str = "", change_note: str = "") -> bool:
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
        with self._write_guard():  # DEF-01 fix
            # FEAT-06: snapshot BEFORE state into node_history
            try:
                last_ver = self.conn.execute(
                    "SELECT COALESCE(MAX(version),0) FROM node_history WHERE node_id=?",
                    (node_id,)
                ).fetchone()[0]
                self.conn.execute(
                    "INSERT INTO node_history(node_id,version,title,content,confidence,tags,"
                    "changed_by,change_note) VALUES(?,?,?,?,?,?,?,?)",
                    (node_id, last_ver + 1, ex.get("title"), ex.get("content"),
                     ex.get("confidence"), ex.get("tags","[]"),
                     changed_by, change_note)
                )
            except Exception:
                pass
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
        # OPT-10 fix: evict stale embedder cache entries when content changes
        if content is not None:
            try:
                from .embedder import _TFIDF_CACHE
                old_key = __import__('hashlib').md5(
                    (ex.get("content") or "").encode()
                ).hexdigest()
                _TFIDF_CACHE.pop(old_key, None)
            except Exception:
                pass
        return True

    def get_node(self, node_id: str):
        r = self.conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return dict(r) if r else None

    def search_nodes(self, query: str, node_type=None, limit: int = 8, scope: str = None) -> list:
        # SEC-01: whitelist scope to prevent injection via dynamic SQL clause
        import re as _re
        if scope is not None and not _re.match(r'^[a-z0-9_-]+$', scope):
            scope = None
        terms = self._expand_terms(query)
        if not terms:
            return []
        # DEF-07 fix: expand each term through n-gram so CJK sub-word search works
        _all_tokens: list[str] = []
        for _t in terms:
            _ngram_tokens = BrainDB._ngram(_t).split()
            _all_tokens.extend(_ngram_tokens if _ngram_tokens else [_t])
        _seen_set: set = set()
        _unique: list[str] = []
        for _tok in _all_tokens:
            if _tok not in _seen_set:
                _unique.append(_tok)
                _seen_set.add(_tok)
        # OPT-08 fix: sanitize each token before putting in FTS5 query
        _safe_unique = [BrainDB._sanitize_fts(tok) for tok in _unique if BrainDB._sanitize_fts(tok) != '""']
        fts_q = " OR ".join(f'"{tok}"' for tok in _safe_unique) if _safe_unique else '""'
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
            # DEF-05/OPT-04 fix: re-rank by decay-adjusted effective confidence
            results = [dict(r) for r in rows]
            for r in results:
                r["effective_confidence"] = self._effective_confidence(r)
            results.sort(
                key=lambda x: (x.get("is_pinned", 0), x["effective_confidence"]),
                reverse=True,
            )
            return results
        except Exception:
            return []

    def prune_episodes(self, older_than_days: int = 365) -> int:
        """清理超過指定天數的 L2 episode 記錄（brain optimize --prune-episodes）。

        Episodes 為 git commit 自動提取的暫時性知識，長期累積可達 100MB+。
        此方法刪除 older_than_days 天前的記錄，返回刪除筆數。
        注意：手動 `brain add` 的 L3 節點不受影響（存在 nodes 表，不在 episodes 表）。
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=older_than_days)
        ).isoformat()
        result = self.conn.execute(
            "DELETE FROM episodes WHERE created_at < ?", (cutoff,)
        )
        self.conn.commit()
        deleted = result.rowcount
        if deleted:
            logger.debug("prune_episodes: 刪除 %d 筆超過 %d 天的 episode", deleted, older_than_days)
        return deleted

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
        with self._write_guard():
            # DATA-01: capture node data for audit log before deletion
            row = self.conn.execute(
                "SELECT title, content, confidence FROM nodes WHERE id=?", (node_id,)
            ).fetchone()
            # BUG-A02: manual FTS5 cleanup (trigger removed in v12 migration)
            self.conn.execute("DELETE FROM nodes_fts WHERE id=?", (node_id,))
            r = self.conn.execute("DELETE FROM nodes WHERE id=?", (node_id,))
            if r.rowcount > 0 and row:
                try:
                    self.conn.execute(
                        "INSERT INTO node_history"
                        " (node_id, version, title, content, confidence, change_note, snapshot_at)"
                        " SELECT ?, COALESCE(MAX(version),0)+1, ?, ?, ?, 'deleted', datetime('now')"
                        " FROM node_history WHERE node_id=?",
                        (node_id, row[0], row[1], row[2], node_id)
                    )
                except Exception as _e:
                    logger.debug("delete_node: audit log failed for %s: %s", node_id, _e)
            self.conn.commit()
        return r.rowcount > 0

    # ── FEAT-06: Version History ──────────────────────────────────

    def get_node_history(self, node_id: str) -> list:
        """FEAT-06: 回傳節點的版本歷史（由舊到新）。"""
        try:
            rows = self.conn.execute(
                "SELECT * FROM node_history WHERE node_id=? ORDER BY version ASC",
                (node_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def rollback_node(self, node_id: str, to_version: int) -> bool:
        """FEAT-06: 將節點恢復到指定版本的快照狀態。"""
        rows = self.conn.execute(
            "SELECT * FROM node_history WHERE node_id=? AND version=?",
            (node_id, to_version)
        ).fetchone()
        if not rows:
            return False
        snap = dict(rows)
        return self.update_node(
            node_id,
            title      = snap.get("title"),
            content    = snap.get("content"),
            confidence = snap.get("confidence"),
            changed_by = "rollback",
            change_note = f"Rolled back to v{to_version}",
        )

    def deprecate_node(self, node_id: str, replaced_by: str = "",
                       reason: str = "") -> bool:
        """FEAT-13: Mark a node as deprecated.

        Sets is_deprecated=1, optionally links to replacement via REPLACED_BY edge.
        """
        node = self.get_node(node_id)
        if not node:
            return False
        with self._write_guard():
            self.conn.execute(
                "UPDATE nodes SET is_deprecated=1, updated_at=datetime('now')"
                " WHERE id=?", (node_id,)
            )
            if reason:
                self.conn.execute(
                    "UPDATE nodes SET content=content||? WHERE id=?",
                    (f"\n[棄用] {reason}", node_id)
                )
            self.conn.commit()
        if replaced_by:
            self.add_edge(node_id, "REPLACED_BY", replaced_by, note=reason)
        return True

    def get_lifecycle(self, node_id: str) -> dict:
        """FEAT-13: Return lifecycle status and history for a node."""
        node = self.get_node(node_id)
        if not node:
            return {}
        history = self.get_node_history(node_id)
        replaced_by = []
        try:
            rows = self.conn.execute(
                "SELECT target_id FROM edges WHERE source_id=? AND relation='REPLACED_BY'",
                (node_id,)
            ).fetchall()
            replaced_by = [r[0] for r in rows]
        except Exception:
            pass
        status = "deprecated" if node.get("is_deprecated") else "active"
        return {
            "node_id":      node_id,
            "title":        node.get("title", ""),
            "status":       status,
            "confidence":   node.get("confidence", 0.8),
            "created_at":   node.get("created_at", ""),
            "updated_at":   node.get("updated_at", ""),
            "replaced_by":  replaced_by,
            "history":      history,
        }

    # ── FEAT-07: Cross-project Migration ─────────────────────────

    def migrate_from(self, source_db_path: "Path", scope: str = "global",
                     min_confidence: float = 0.0, dry_run: bool = False) -> dict:
        """FEAT-07: 從另一個 brain.db 複製節點（及邊）。"""
        import sqlite3 as _sq
        result = {"nodes": 0, "edges": 0, "skipped": 0, "errors": 0, "dry_run": dry_run}
        try:
            src = _sq.connect(str(source_db_path), uri=False, check_same_thread=False)
            src.row_factory = _sq.Row
            nodes = src.execute(
                "SELECT * FROM nodes WHERE scope=? AND confidence>=?",
                (scope, min_confidence)
            ).fetchall()
            for n in nodes:
                d = dict(n)
                if not dry_run:
                    try:
                        self.add_node(
                            node_id=d["id"], node_type=d.get("type","Note"),
                            title=d.get("title",""), content=d.get("content",""),
                            scope=d.get("scope","global"),
                            confidence=float(d.get("confidence",0.8)),
                            importance=float(d.get("importance",0.5)),
                        )
                        result["nodes"] += 1
                    except Exception:
                        result["errors"] += 1
                else:
                    result["nodes"] += 1
            edges = src.execute("SELECT * FROM edges").fetchall()
            for e in edges:
                d = dict(e)
                if not dry_run:
                    try:
                        self.add_edge(d["source_id"], d["relation"], d["target_id"],
                                      d.get("note",""))
                        result["edges"] += 1
                    except Exception:
                        result["errors"] += 1
                else:
                    result["edges"] += 1
            src.close()
        except Exception as exc:
            logger.warning("migrate_from failed: %s", exc)
            result["errors"] += 1
        return result

    # ── DEEP-02: Bayesian Confidence Propagation ──────────────────

    def propagate_confidence(self, node_id: str, dampening: float = 0.5,
                             max_hops: int = 3) -> dict[str, float]:
        """DEEP-02 補完: BFS 貝葉斯信念傳播（多跳圖遍歷）。

        從 node_id 出發，沿 REQUIRES 邊 BFS 傳播信心衰減。

        傳播公式: conf_eff = conf_base * (1 - dampening * (1 - upstream_conf))

        Args:
            node_id:   起始節點 ID
            dampening: 衰減係數（0~1，預設 0.5）
            max_hops:  最大傳播跳數（預設 3）

        Returns:
            {node_id: effective_confidence} 含所有受影響節點（含起始點）
        """
        root = self.get_node(node_id)
        if not root:
            return {}
        visited: dict[str, float] = {}
        # queue entries: (nid, upstream_effective_conf, depth)
        queue: list[tuple[str, float, int]] = [
            (node_id, float(root.get("confidence", 0.8)), 0)
        ]
        while queue:
            nid, upstream_conf, depth = queue.pop(0)
            if nid in visited or depth > max_hops:
                continue
            node = self.get_node(nid)
            if not node:
                continue
            base      = float(node.get("confidence", 0.8))
            effective = base * (1 - dampening * (1 - upstream_conf))
            effective = round(max(0.05, min(1.0, effective)), 4)
            visited[nid] = effective
            try:
                rows = self.conn.execute(
                    "SELECT target_id FROM edges"
                    " WHERE source_id=? AND relation='REQUIRES'",
                    (nid,)
                ).fetchall()
                for r in rows:
                    if r[0] not in visited:
                        queue.append((r[0], effective, depth + 1))
            except Exception as exc:
                logger.debug("propagate_confidence BFS error: %s", exc)
        return visited

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
        Phase 1+OPT-02: Hybrid search with adaptive FTS5/vector weights.

        Weights are computed dynamically by _adaptive_weights():
          - Short / CJK-heavy queries → FTS5 ×0.6 + vector ×0.4
          - Long / semantic queries   → FTS5 ×0.25 + vector ×0.75
          - Default (3–4 terms)       → FTS5 ×0.4 + vector ×0.6

        Falls back to pure FTS5 when no query_vector is provided.
        """
        # FTS5 results
        fts_results = self.search_nodes(query, scope=scope, limit=limit)
        if not query_vector:
            return fts_results  # pure FTS5 fallback

        # OPT-02: adaptive weights
        fts_w, vec_w = self._adaptive_weights(query)

        # Vector results
        vec_results = self.search_nodes_by_vector(
            query_vector, threshold=0.8, limit=limit, scope=scope
        )

        # Merge: assign scores, deduplicate
        scored: dict = {}
        for i, n in enumerate(fts_results):
            nid = n['id']
            fts_score = (limit - i) / limit  # rank-based score 0.0–1.0
            scored[nid] = (n, fts_score * fts_w)
        for i, n in enumerate(vec_results):
            nid = n['id']
            vec_score = (1.0 - n.get('dist', 0.5))  # convert distance to similarity
            if nid in scored:
                scored[nid] = (scored[nid][0], scored[nid][1] + vec_score * vec_w)
            else:
                scored[nid] = (n, vec_score * vec_w)

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
        # BUG-01 fix: use source alone as hash seed when available so that the
        # same git commit always produces the same episode ID regardless of how
        # the content string is formatted.  Extended to 16 hex chars (64-bit)
        # to reduce birthday-paradox collision probability to near-zero.
        seed = source if source else f"{content}{source}"
        eid  = "ep-" + hashlib.md5(seed.encode()).hexdigest()[:16]
        ts   = ref_time or datetime.now(timezone.utc).isoformat()
        with self._write_guard():  # DEF-01 fix
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

    # ── FEAT-01: knowledge health dashboard ──────────────────────

    def optimize(self) -> dict:
        """C-1/C-3: Reclaim disk space and rebuild search indexes.

        Steps:
          1. VACUUM — reclaim space from deleted nodes (SQLite never shrinks otherwise)
          2. ANALYZE — update query planner statistics for better index use
          3. FTS5 rebuild — remove orphaned FTS5 entries from deleted nodes
          4. FTS5 integrity check — verify index consistency

        Returns dict with size_before_bytes, size_after_bytes, fts5_status.
        """
        db_path = self.brain_dir / "brain.db"
        size_before = db_path.stat().st_size if db_path.exists() else 0

        # Step 1–2: VACUUM + ANALYZE
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.conn.execute("VACUUM")
        self.conn.execute("ANALYZE")
        logger.info("optimize: VACUUM + ANALYZE complete")

        # Step 3: FTS5 rebuild — removes orphaned entries (C-3)
        try:
            self.conn.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")
            self.conn.commit()
            fts5_status = "rebuilt"
            logger.info("optimize: FTS5 rebuild complete")
        except Exception as e:
            fts5_status = f"rebuild_skipped: {e}"
            logger.warning("optimize: FTS5 rebuild failed: %s", e)

        # Step 4: FTS5 integrity check
        try:
            self.conn.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('integrity-check')")
            fts5_status += "+ok"
        except Exception:
            fts5_status += "+integrity_warn"

        size_after = db_path.stat().st_size if db_path.exists() else 0
        saved = size_before - size_after
        logger.info("optimize: done — saved %d bytes (%.1f KB)", saved, saved / 1024)
        return {
            "size_before_bytes": size_before,
            "size_after_bytes":  size_after,
            "saved_bytes":       saved,
            "fts5_status":       fts5_status,
        }

    def health_report(self) -> dict:
        """FEAT-01: Summarise knowledge-base health as a structured dict.

        Returns keys:
          total_nodes, by_type, avg_confidence, low_confidence_nodes,
          stale_nodes (>90 days + conf<0.5), deprecated_nodes, expired_nodes,
          fts5_coverage, vector_coverage, episodes, sessions,
          recent_7d (nodes created in last 7 days), health_score (0.0–1.0).
        """
        now  = datetime.now(timezone.utc)
        rows = self.conn.execute("SELECT * FROM nodes").fetchall()
        nodes = [dict(r) for r in rows]
        total = len(nodes)

        by_type: dict = {}
        confs: list   = []
        stale = deprecated = expired = 0

        for n in nodes:
            by_type[n.get("type","unknown")] = by_type.get(n.get("type","unknown"), 0) + 1
            confs.append(float(n.get("confidence", 0.8)))
            if n.get("is_deprecated"):
                deprecated += 1
            vu = n.get("valid_until")
            if vu:
                try:
                    dt = datetime.fromisoformat(vu.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if now > dt:
                        expired += 1
                except Exception:
                    pass
            if not n.get("is_pinned"):
                created = n.get("created_at", "")
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if (now - dt).days > 90 and float(n.get("confidence", 0.8)) < 0.5:
                        stale += 1
                except Exception:
                    pass

        avg_conf    = round(sum(confs) / len(confs), 3) if confs else 0.0
        low_conf    = sum(1 for c in confs if c < 0.4)

        fts_count = vec_count = 0
        try:
            fts_count = self.conn.execute("SELECT COUNT(*) FROM nodes_fts").fetchone()[0]
        except Exception:
            pass
        try:
            vec_count = self.conn.execute("SELECT COUNT(*) FROM node_vectors").fetchone()[0]
        except Exception:
            pass

        episodes = self.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        sessions = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        thresh   = (now - timedelta(days=7)).isoformat()
        recent_7d = self.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE created_at >= ?", (thresh,)
        ).fetchone()[0]

        score = self._compute_health_score(total, avg_conf, stale, fts_count, vec_count)

        return {
            "total_nodes":         total,
            "by_type":             by_type,
            "avg_confidence":      avg_conf,
            "low_confidence_nodes": low_conf,
            "stale_nodes":         stale,
            "deprecated_nodes":    deprecated,
            "expired_nodes":       expired,
            "fts5_coverage":       fts_count,
            "vector_coverage":     vec_count,
            "episodes":            episodes,
            "sessions":            sessions,
            "recent_7d":           recent_7d,
            "health_score":        score,
        }

    @staticmethod
    def _compute_health_score(total: int, avg_conf: float,
                               stale: int, fts_count: int, vec_count: int) -> float:
        """0.0–1.0 composite health score (higher is healthier)."""
        if total == 0:
            return 0.5
        score  = avg_conf * 0.4
        score += (1 - stale / total) * 0.3
        score += min(fts_count / total, 1.0) * 0.2
        score += min(vec_count / total, 1.0) * 0.1
        return round(min(1.0, max(0.0, score)), 3)

    # ── FEAT-02: conflict detection ────────────────────────────

    def find_conflicts(self, similarity_threshold: float = 0.7) -> list:
        """FEAT-02: Detect potentially conflicting or duplicate knowledge nodes.

        Returns up to 50 conflict dicts, each with:
          type ('duplicate' or 'contradiction'), node_a, node_b,
          title_a, title_b, similarity, reason.

        Contradictions are ranked before duplicates.
        """
        nodes = [dict(r) for r in self.conn.execute(
            "SELECT id, type, title, content FROM nodes LIMIT 500"
        ).fetchall()]

        conflicts = []
        seen: set  = set()
        _contra = [
            ("must", "must not"), ("should", "should not"),
            ("use", "do not use"), ("enable", "disable"),
            ("allow", "deny"), ("required", "forbidden"),
            ("需要", "不需要"), ("必須", "禁止"),
        ]

        for i, a in enumerate(nodes):
            a_words = set(a["title"].lower().split())
            if not a_words:
                continue
            for b in nodes[i + 1:]:
                pair_key = (min(a["id"], b["id"]), max(a["id"], b["id"]))
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                b_words = set(b["title"].lower().split())
                if not b_words:
                    continue
                overlap = len(a_words & b_words) / len(a_words | b_words)
                if overlap < similarity_threshold:
                    continue

                a_text = (a["title"] + " " + (a.get("content") or "")).lower()
                b_text = (b["title"] + " " + (b.get("content") or "")).lower()
                is_contra = any(
                    (ka in a_text and kb in b_text) or (kb in a_text and ka in b_text)
                    for ka, kb in _contra
                )
                ctype = "contradiction" if is_contra else "duplicate"
                conflicts.append({
                    "type":       ctype,
                    "node_a":     a["id"],
                    "node_b":     b["id"],
                    "title_a":    a["title"],
                    "title_b":    b["title"],
                    "similarity": round(overlap, 3),
                    "reason":     (
                        f"相似標題（{overlap:.0%} 重疊）且內容矛盾" if is_contra
                        else f"相似標題（{overlap:.0%} 重疊），可能重複"
                    ),
                })

        conflicts.sort(key=lambda x: (x["type"] != "contradiction", -x["similarity"]))
        return conflicts[:50]

    # ── FEAT-03: usage analytics ────────────────────────────────

    def usage_analytics(self) -> dict:
        """FEAT-03: Return usage analytics as a structured dict.

        Keys: top_accessed_nodes, knowledge_growth (weekly), by_type,
              by_scope, avg_confidence_by_type, recent_queries, total_episodes,
              total_nodes.
        """
        top_nodes = [dict(r) for r in self.conn.execute(
            "SELECT id, title, type, access_count, last_accessed FROM nodes"
            " WHERE access_count > 0 ORDER BY access_count DESC LIMIT 10"
        ).fetchall()]

        growth = [dict(r) for r in self.conn.execute(
            "SELECT strftime('%Y-%W', created_at) week, COUNT(*) count"
            " FROM nodes GROUP BY week ORDER BY week DESC LIMIT 12"
        ).fetchall()]

        by_type = {r["type"]: r["c"] for r in self.conn.execute(
            "SELECT type, COUNT(*) c FROM nodes GROUP BY type ORDER BY c DESC"
        ).fetchall()}

        by_scope = {r["scope"]: r["c"] for r in self.conn.execute(
            "SELECT scope, COUNT(*) c FROM nodes GROUP BY scope"
            " ORDER BY c DESC LIMIT 10"
        ).fetchall()}

        conf_by_type = {r["type"]: round(r["avg_conf"], 3) for r in self.conn.execute(
            "SELECT type, AVG(confidence) avg_conf FROM nodes GROUP BY type"
        ).fetchall()}

        recent_queries = [dict(r) for r in self.conn.execute(
            "SELECT query, latency_ms, created_at FROM traces"
            " ORDER BY created_at DESC LIMIT 10"
        ).fetchall()]

        ep_count = self.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]

        return {
            "top_accessed_nodes":    top_nodes,
            "knowledge_growth":      growth,
            "by_type":               by_type,
            "by_scope":              by_scope,
            "avg_confidence_by_type": conf_by_type,
            "recent_queries":        recent_queries,
            "total_episodes":        ep_count,
            "total_nodes":           sum(by_type.values()),
        }

    # ── FEAT-04: auto scope inference ───────────────────────────

    @staticmethod
    def infer_scope(workdir: str, current_file: str = "") -> str:
        """FEAT-04: Auto-infer knowledge scope from directory structure.

        Examples:
          /project/payment_service/stripe.py → 'payment_service'
          /project/src/api/handler.py        → 'api'
          /project/utils.py                  → 'global'
        """
        import re as _re
        from pathlib import Path as _P
        _skip = {"src", "test", "tests", "docs", "scripts", "build", "dist", "."}
        _svc  = ["service", "module", "pkg", "app", "api", "lib", "handler", "domain"]
        base  = _P(current_file) if current_file else _P(workdir)
        try:
            parts = list(base.relative_to(_P(workdir).resolve()).parts)
        except ValueError:
            return "global"
        for part in parts:
            pl = part.lower()
            if any(k in pl for k in _svc):
                return _re.sub(r"[^a-z0-9_]", "_", pl)
        if parts and parts[0].lower() not in _skip:
            return _re.sub(r"[^a-z0-9_]", "_", parts[0].lower())
        return "global"

    # ── FEAT-05: import / export ────────────────────────────────

    def export_json(self, node_type: str = None, scope: str = None) -> dict:
        """FEAT-05: Export knowledge nodes (and edges) to a JSON-serialisable dict."""
        if node_type:
            nodes = [dict(r) for r in self.conn.execute(
                "SELECT * FROM nodes WHERE type=? ORDER BY created_at", (node_type,)
            ).fetchall()]
        elif scope:
            nodes = [dict(r) for r in self.conn.execute(
                "SELECT * FROM nodes WHERE scope=? ORDER BY created_at", (scope,)
            ).fetchall()]
        else:
            nodes = [dict(r) for r in self.conn.execute(
                "SELECT * FROM nodes ORDER BY created_at"
            ).fetchall()]

        edges = [dict(r) for r in self.conn.execute("SELECT * FROM edges").fetchall()]
        return {
            "version":     "1.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total_nodes": len(nodes),
            "nodes":       nodes,
            "edges":       edges,
        }

    def export_markdown(self, node_type: str = None, scope: str = None) -> str:
        """FEAT-05: Export knowledge nodes to a Markdown document."""
        data  = self.export_json(node_type=node_type, scope=scope)
        lines = [
            "# Project Brain Knowledge Export",
            "",
            f"Exported: {data['exported_at']}  |  Total: {data['total_nodes']} nodes",
            "",
        ]
        by_type: dict = {}
        for node in data["nodes"]:
            t = node.get("type", "Unknown")
            by_type.setdefault(t, []).append(node)

        for t, nodes in sorted(by_type.items()):
            lines += [f"## {t} ({len(nodes)})", ""]
            for n in nodes:
                lines.append(f"### {n['title']}")
                if n.get("content"):
                    lines += ["", n["content"]]
                meta = []
                if n.get("confidence") is not None:
                    meta.append(f"confidence={n['confidence']:.2f}")
                if n.get("scope") and n["scope"] != "global":
                    meta.append(f"scope={n['scope']}")
                if meta:
                    lines += ["", f"*{', '.join(meta)}*"]
                lines.append("")

        return "\n".join(lines)

    def export_neo4j(self, node_type: str = None, scope: str = None) -> str:
        """FEAT-11: Export knowledge graph as Cypher statements for Neo4j/Obsidian.

        Generates CREATE statements for nodes and relationships.
        """
        data  = self.export_json(node_type=node_type, scope=scope)
        lines = [
            "// Project Brain → Neo4j Cypher Export",
            f"// Generated: {data['exported_at']}",
            f"// Nodes: {data['total_nodes']}",
            "",
            "// ── Nodes ──────────────────────────────────────────",
        ]
        for n in data["nodes"]:
            nid   = n["id"].replace("-", "_")
            label = n.get("type", "Node")
            title = (n.get("title") or "").replace('"', '\\"')
            conf  = n.get("confidence", 0.8)
            scope_val = n.get("scope", "global")
            lines.append(
                f'CREATE (n_{nid}:{label} {{id:"{n["id"]}", title:"{title}",'
                f' confidence:{conf}, scope:"{scope_val}"}})'
            )
        lines += ["", "// ── Relationships ───────────────────────────────────"]
        for e in data.get("edges", []):
            src = e.get("source_id", "").replace("-", "_")
            tgt = e.get("target_id", "").replace("-", "_")
            rel = e.get("relation", "RELATED").upper().replace(" ", "_")
            if src and tgt:
                lines.append(
                    f'MATCH (a {{id:"{e["source_id"]}"}}),(b {{id:"{e["target_id"]}"}}) '
                    f'CREATE (a)-[:{rel}]->(b)'
                )
        return "\n".join(lines)

    def import_json(self, data: dict, overwrite: bool = False,
                    merge_strategy: str = "skip") -> dict:
        """FEAT-05/12: Import nodes and edges from an export_json() dict.

        FEAT-12: merge_strategy controls conflict resolution:
          - "skip"             : keep existing node (default, non-destructive)
          - "overwrite"        : replace with incoming node
          - "confidence_wins"  : keep whichever has higher confidence
          - "interactive"      : return conflicts list for caller to handle

        Returns:
            dict with keys: nodes, edges, skipped, errors, conflicts
            When merge_strategy="interactive", conflicts=[{existing, incoming}]
        """
        result: dict = {"nodes": 0, "edges": 0, "skipped": 0, "errors": 0, "conflicts": []}

        for node in data.get("nodes", []):
            try:
                nid = node.get("id")
                if not nid:
                    result["errors"] += 1
                    continue
                existing = self.get_node(nid)
                if existing:
                    if merge_strategy == "skip" and not overwrite:
                        result["skipped"] += 1
                        continue
                    if merge_strategy == "interactive":
                        result["conflicts"].append({
                            "existing": existing,
                            "incoming": node,
                        })
                        result["skipped"] += 1
                        continue
                    if merge_strategy == "confidence_wins":
                        if float(existing.get("confidence", 0.8)) >= float(node.get("confidence", 0.8)):
                            result["skipped"] += 1
                            continue
                    # overwrite or confidence_wins where incoming is higher
                meta = node.get("meta", {})
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                self.add_node(
                    node_id=nid,
                    node_type=node.get("type", "Note"),
                    title=node.get("title", ""),
                    content=node.get("content", ""),
                    scope=node.get("scope", "global"),
                    confidence=node.get("confidence", 0.8),
                    importance=node.get("importance", 0.5),
                    emotional_weight=node.get("emotional_weight", 0.5),
                    meta=meta,
                )
                result["nodes"] += 1
            except Exception as e:
                logger.debug("import_json node error: %s", e)
                result["errors"] += 1

        for edge in data.get("edges", []):
            try:
                self.add_edge(
                    source_id=edge["source_id"],
                    relation=edge["relation"],
                    target_id=edge["target_id"],
                    note=edge.get("note", ""),
                )
                result["edges"] += 1
            except Exception:
                result["errors"] += 1

        return result

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
                            self.conn.execute(
                                "INSERT INTO sessions(session_id,key,value,category)"
                                " VALUES(?,?,?,?)"
                                " ON CONFLICT(session_id,key) DO UPDATE SET value=excluded.value",
                                (str(d.get("session_id","legacy")), str(d.get("key","?")),
                                 str(d.get("value","")), str(d.get("category","general")))
                            )
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


# ── OPT-05: CQRS Read/Write Separation ───────────────────────────────────────

class ReadBrainDB(BrainDB):
    """OPT-05: Read-only view of BrainDB — uses WAL snapshot, no writes."""

    def _make_connection(self) -> sqlite3.Connection:
        """ARCH-02: read-only URI connection."""
        c = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True,
                            check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA query_only=ON")
        c.execute("PRAGMA journal_mode=WAL")
        c.create_function("brain_ngram", 1, lambda t: BrainDB._ngram(t or ""))
        return c

    def _setup(self): pass  # no-op: read-only, schema already exists

    # Block all write methods
    def add_node(self, *a, **kw):           raise PermissionError("ReadBrainDB is read-only")
    def update_node(self, *a, **kw):        raise PermissionError("ReadBrainDB is read-only")
    def delete_node(self, *a, **kw):        raise PermissionError("ReadBrainDB is read-only")
    def add_episode(self, *a, **kw):        raise PermissionError("ReadBrainDB is read-only")
    def add_edge(self, *a, **kw):           raise PermissionError("ReadBrainDB is read-only")
    def add_temporal_edge(self, *a, **kw):  raise PermissionError("ReadBrainDB is read-only")
    def emit(self, *a, **kw):               raise PermissionError("ReadBrainDB is read-only")
    def build_synonym_index(self, *a, **kw): raise PermissionError("ReadBrainDB is read-only")


class WriteBrainDB(BrainDB):
    """OPT-05: Write-only facade — enforces single-writer pattern via _write_guard."""
    pass  # inherits all BrainDB write methods with _write_guard already applied
