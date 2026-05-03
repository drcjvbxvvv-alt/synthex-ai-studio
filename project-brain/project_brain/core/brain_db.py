"""
project_brain/core/brain_db.py -- Unified BrainDB (v10.0)

Single brain.db replaces 6 scattered SQLite files.
L2 temporal memory replaces FalkorDB with pure SQLite.
"""
from __future__ import annotations
import dataclasses
import functools
import logging
import contextlib, hashlib, json, math, os, queue, sqlite3, threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

_T = TypeVar("_T")

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 29          # DEF-04: bump on every schema change (E-02: api_keys)

# REF-02: single source of truth in synonyms.py
from ..synonyms import SYNONYM_MAP as _SYNONYM_MAP   # noqa: E402
from . import constants as _constants               # REF-04: module ref so monkeypatch works

# REF-01: extracted sub-modules
from project_brain.vector_store    import VectorStore
from project_brain.feedback_tracker import FeedbackTracker


@dataclasses.dataclass
class _WriteRequest:
    """Internal message passed through the serialized write queue."""
    kind: str                          # "execute" | "executescript" | "callable"
    sql: str = ""
    params: tuple = ()
    fn: Callable | None = None         # for kind="callable"
    result_event: threading.Event = dataclasses.field(default_factory=threading.Event)
    result_value: Any = None
    error: BaseException | None = None


def _serialize_if_needed(method: Callable[..., _T]) -> Callable[..., _T]:
    """Decorator: route the entire method body through the write queue in serialized mode.

    When ``self._serialized_writes`` is True and the caller is NOT on the
    write-worker thread, the method is wrapped in a callable and enqueued.
    The calling thread blocks until the worker executes it and returns the result.

    When ``self._serialized_writes`` is False (default), the method runs directly.
    """
    @functools.wraps(method)
    def wrapper(self: "BrainDB", *args: Any, **kwargs: Any) -> _T:
        if self._serialized_writes and not self._is_write_worker():
            return self._enqueue_write_fn(lambda: method(self, *args, **kwargs))
        return method(self, *args, **kwargs)
    return wrapper


class BrainDB:
    """Single SQLite database holding all Project Brain data."""

    def __init__(self, brain_dir: Path, *, serialized_writes: bool = False):
        # H-01: shared write infrastructure
        from project_brain.storage.write_context import WriteContext
        self._ctx = WriteContext(brain_dir, serialized_writes=serialized_writes)
        # Backward-compatible attributes (delegate to ctx)
        self.brain_dir = self._ctx.brain_dir
        self.db_path = self._ctx.db_path
        self._write_lock = self._ctx._write_lock
        self._trace_counter = 0
        self._trace_sample_rate = self._ctx._trace_sample_rate
        self._serialized_writes = self._ctx._serialized_writes
        self._write_queue = self._ctx._write_queue
        self._write_worker_thread = self._ctx._write_worker_thread
        self._conn_obj = self._ctx._conn_obj
        # DEF-02 fix: register Python UDF (needs BrainDB._ngram reference)
        self._conn_obj.create_function("brain_ngram", 1, lambda t: BrainDB._ngram(t or ""))
        # H-01: repositories (BEFORE _setup, because migrations use add_node)
        from project_brain.storage.repositories.node_repo import NodeRepo
        from project_brain.storage.repositories.search_repo import SearchRepo
        from project_brain.storage.repositories.analytics_repo import AnalyticsRepo
        from project_brain.storage.repositories.migration_repo import MigrationRepo
        from project_brain.storage.repositories.misc_repo import MiscRepo
        self._node_repo = NodeRepo(self._ctx)
        self._search_repo = SearchRepo(self._ctx)
        self._analytics_repo = AnalyticsRepo(self._ctx)
        self._migration_repo = MigrationRepo(self._ctx)
        self._misc_repo = MiscRepo(self._ctx)
        # Schema setup
        self._setup()
        # E-02: start write worker AFTER schema is set up
        self._ctx.start_write_worker()
        self._write_queue = self._ctx._write_queue
        self._write_worker_thread = self._ctx._write_worker_thread
        # FEAT-06: daily backup
        self._maybe_backup()

    def _maybe_backup(self) -> None:
        """FEAT-06: 每日靜默備份 brain.db → .brain/backups/brain_YYYYMMDD.db

        規則：
          - 每天最多備份一次（比較最新備份的日期）
          - 使用 SQLite VACUUM INTO，保證備份為完整且不含 WAL 的乾淨資料庫
          - 保留份數由 BRAIN_BACKUP_KEEP 環境變數 或 config.json 控制（預設 7）
        """
        if not self.db_path.exists():
            return
        try:
            backup_dir = self.brain_dir / "backups"
            backup_dir.mkdir(exist_ok=True)
            today_tag  = datetime.now(timezone.utc).strftime("%Y%m%d")
            today_path = backup_dir / f"brain_{today_tag}.db"
            # 今天已備份就跳過
            if today_path.exists():
                return
            # VACUUM INTO 建立完整備份（自動 checkpoint WAL）
            self._conn_obj.execute(f"VACUUM INTO '{today_path}'")
            logger.debug("FEAT-06: daily backup created → %s", today_path.name)
            # ARCH-DEBT: configurable retention (env > config.json > default 7)
            keep = self._backup_keep_count()
            backups = sorted(backup_dir.glob("brain_????????.db"))
            for old in backups[:-keep]:
                try:
                    old.unlink()
                    logger.debug("FEAT-06: removed old backup %s", old.name)
                except OSError as _oe:
                    logger.debug("LOW-02: backup cleanup failed (non-critical): %s", _oe)
        except Exception as _e:
            # 備份失敗不應影響正常啟動
            logger.warning("FEAT-06: daily backup failed (non-fatal): %s", _e)

    def _backup_keep_count(self) -> int:
        """Read backup retention count from env/config (default 7)."""
        # 1. Environment variable
        env_val = os.environ.get("BRAIN_BACKUP_KEEP")
        if env_val:
            try:
                return max(1, int(env_val))
            except (ValueError, TypeError):
                pass
        # 2. config.json
        try:
            cfg_path = self.brain_dir / "config.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                val = cfg.get("backup_keep")
                if val is not None:
                    return max(1, int(val))
        except Exception:
            pass
        return 7

    def _make_connection(self) -> sqlite3.Connection:
        """ARCH-02: open the shared SQLite connection. Override in subclasses."""
        c = sqlite3.connect(str(self.db_path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        c.execute("PRAGMA foreign_keys=ON")
        c.create_function("brain_ngram", 1, lambda t: BrainDB._ngram(t or ""))
        return c

    @property
    def conn(self) -> sqlite3.Connection:
        return self._ctx.conn if hasattr(self, '_ctx') else self._conn_obj

    def close(self) -> None:
        """Close connection and write worker. Delegates to WriteContext."""
        if hasattr(self, '_ctx') and self._ctx is not None:
            self._ctx.close()
            self._conn_obj = None
            return
        # Fallback for subclasses (ReadBrainDB) that don't use _ctx
        if self._conn_obj is None:
            return
        try:
            self._conn_obj.close()
        except Exception:
            pass
        self._conn_obj = None

    # ── E-02: API Key management (delegates to MiscRepo) ────────────────

    def store_api_key(self, token: str, role: str = "reader", name: str = "") -> int:
        return self._misc_repo.store_api_key(token, role, name)

    def resolve_api_key(self, token: str) -> Optional[dict]:
        return self._misc_repo.resolve_api_key(token)

    def revoke_api_key(self, key_id: int) -> bool:
        return self._misc_repo.revoke_api_key(key_id)

    def list_api_keys(self) -> list[dict]:
        return self._misc_repo.list_api_keys()

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
        self._migration_repo._run_migrations()
        # C-01: one-time import of knowledge_graph.db into unified brain.db
        self._migration_repo._migrate_kg_to_unified(add_node_fn=self.add_node)

        # REF-01: instantiate extracted sub-modules
        self._vector_store     = VectorStore(self.conn)
        self._feedback_tracker = FeedbackTracker(self.conn)

        # BUG-A02 fix: FTS5 triggers removed — all write paths use manual sync.
        # Migration v12 drops existing triggers on upgrade.

    # _run_migrations and _migrate_kg_to_unified delegated to MigrationRepo
    # (called directly in _setup via self._migration_repo)

    # -- helpers (delegate to SearchRepo statics for backward compat) --

    @staticmethod
    def _ngram(text: str) -> str:
        from ..utils import ngram_cjk
        return ngram_cjk(text)

    @staticmethod
    def _sanitize_fts(q: str) -> str:
        from project_brain.storage.repositories.search_repo import SearchRepo
        return SearchRepo._sanitize_fts(q)

    @staticmethod
    def _effective_confidence(node: dict) -> float:
        from project_brain.storage.repositories.search_repo import SearchRepo
        return SearchRepo._effective_confidence(node)

    @contextlib.contextmanager
    def _write_guard(self):
        """REF-03: Write serialization via threading.RLock (cross-platform).

        Replaces the previous fcntl.flock() implementation which was
        macOS/Linux-only and added 1-2ms syscall overhead per write.
        SQLite WAL mode + busy_timeout=5000 handles cross-process serialization.
        RLock is reentrant so nested calls in the same thread are safe.

        E-02: In serialized_writes mode, the write-worker thread is the only
        thread that should hold the lock. If called from the worker, yield
        directly (worker is already serial). The RLock is still acquired for
        safety (reentrant), ensuring correct behavior if _write_guard is nested.
        """
        with self._write_lock:
            yield

    # ── E-02: Write Queue infrastructure ─────────────────────────────

    def _is_write_worker(self) -> bool:
        """Return True if the current thread is the write-worker thread."""
        return (self._write_worker_thread is not None
                and threading.current_thread() is self._write_worker_thread)

    def _write_worker(self) -> None:
        """E-02: Background thread that drains the write queue serially.

        Each request is executed under ``_write_guard()`` (which acquires the
        RLock).  Results and errors are communicated back to the calling thread
        via ``_WriteRequest.result_event``.

        A ``None`` sentinel (poison pill) terminates the loop.
        """
        while True:
            req = self._write_queue.get()
            if req is None:
                break
            try:
                if req.kind == "execute":
                    req.result_value = self._execute_write_direct(req.sql, req.params)
                elif req.kind == "executescript":
                    self._execute_writescript_direct(req.sql)
                elif req.kind == "callable" and req.fn is not None:
                    req.result_value = req.fn()
            except Exception as e:
                req.error = e
            finally:
                req.result_event.set()

    def _enqueue_write(self, kind: str, sql: str, params: tuple = ()) -> Any:
        """Enqueue a simple SQL write and block until the worker completes it."""
        req = _WriteRequest(kind=kind, sql=sql, params=params)
        self._write_queue.put(req)
        req.result_event.wait()
        if req.error:
            raise req.error
        return req.result_value

    def _enqueue_write_fn(self, fn: Callable[..., _T]) -> _T:
        """Enqueue an arbitrary callable to run on the write-worker thread.

        Used by ``@_serialize_if_needed`` to route entire method bodies
        (e.g. ``add_node`` with its multi-statement atomic block) through
        the serialized queue.
        """
        req = _WriteRequest(kind="callable", fn=fn)
        self._write_queue.put(req)
        req.result_event.wait()
        if req.error:
            raise req.error
        return req.result_value

    # ── MEDIUM-01: 寫入統一入口（ARCHITECTURE_REVIEW.md §3 MEDIUM-01）─────
    #
    # 所有 runtime 寫路徑應經 _execute_write() 或 _execute_writescript()，
    # 保證 lock + commit + rollback 行為一致，便於除錯與審計。
    # 唯一例外：__init__ 內的 _setup / _migrate_schema，因為在 BrainDB 建構
    # 完成前不會有任何並發呼叫者，不需序列化。

    def _execute_write_direct(
        self,
        sql:    str,
        params: tuple = (),
    ) -> sqlite3.Cursor:
        """Direct write execution (always runs on the current thread)."""
        with self._write_guard():
            try:
                cur = self.conn.execute(sql, params)
                self.conn.commit()
                return cur
            except Exception:
                try:
                    self.conn.rollback()
                except Exception as _rb_err:
                    logger.error("_execute_write: rollback failed: %s", _rb_err)
                raise

    def _execute_writescript_direct(self, script: str) -> None:
        """Direct writescript execution (always runs on the current thread)."""
        with self._write_guard():
            try:
                self.conn.executescript(script)
            except Exception:
                try:
                    self.conn.rollback()
                except Exception as _rb_err:
                    logger.error("_execute_writescript: rollback failed: %s", _rb_err)
                raise

    def _execute_write(
        self,
        sql:    str,
        params: tuple = (),
    ) -> sqlite3.Cursor:
        """
        MEDIUM-01: 單一寫入語句統一入口。

        保證：
          - 透過 ``_write_guard()`` 取得 ``_write_lock`` （RLock，reentrant）
          - 成功則 ``self.conn.commit()``
          - 失敗則 ``self.conn.rollback()`` 後 re-raise
          - 可安全巢狀呼叫（RLock）

        E-02: In serialized_writes mode, enqueues to the write worker.

        Args:
            sql:    單一 SQL 語句（INSERT / UPDATE / DELETE / etc.）
            params: SQL 參數 tuple

        Returns:
            ``sqlite3.Cursor`` — 呼叫端可讀取 ``rowcount`` / ``lastrowid``
        """
        if self._serialized_writes and not self._is_write_worker():
            return self._enqueue_write("execute", sql, params)
        return self._execute_write_direct(sql, params)

    def _execute_writescript(self, script: str) -> None:
        """
        MEDIUM-01: 多語句寫入統一入口（用於 schema DDL / batch cleanup）。

        ``executescript()`` 會自動在腳本前隱式 COMMIT 任何 pending transaction，
        因此不需要額外 commit。失敗時仍 rollback + re-raise。
        """
        if self._serialized_writes and not self._is_write_worker():
            self._enqueue_write("executescript", script)
            return
        self._execute_writescript_direct(script)

    # ── Search helpers (delegates to SearchRepo) ───────────────────

    def _load_search_config(self) -> dict:
        return self._search_repo._load_search_config()

    def _adaptive_weights(self, query: str) -> tuple:
        return self._search_repo._adaptive_weights(query)

    def _expand_terms(self, query: str) -> list:
        return self._search_repo._expand_terms(query)

    def build_synonym_index(self) -> int:
        return self._search_repo.build_synonym_index()

    def expand_query(self, query: str) -> list:
        return self._search_repo.expand_query(query)

    # -- L3: knowledge nodes --

    def add_node(self, node_id: str, node_type: str, title: str,
                 content: str = "", tags=None, scope: str = "global", **kw) -> str:
        """Delegates to NodeRepo."""
        return self._node_repo.add_node(node_id, node_type, title, content, tags, scope, **kw)

    def sync_from_graph_node(self, event: str, data: dict) -> None:
        """Delegates to NodeRepo."""
        self._node_repo.sync_from_graph_node(event, data)

    def update_node(self, node_id: str, title=None, content=None,
                    confidence=None, importance=None,
                    changed_by: str = "", change_note: str = "",
                    change_type: str = "update") -> bool:
        """Delegates to NodeRepo."""
        return self._node_repo.update_node(node_id, title, content, confidence, importance, changed_by, change_note, change_type)

    def get_node(self, node_id: str):
        """Delegates to NodeRepo."""
        return self._node_repo.get_node(node_id)

    def search_nodes(self, query: str, node_type=None, limit: int = 8, scope: str = None) -> list:
        """Delegates to SearchRepo."""
        return self._search_repo.search_nodes(query, node_type, limit, scope)

    def prune_episodes(self, older_than_days: int = 365) -> int:
        """Delegates to MiscRepo."""
        return self._misc_repo.prune_episodes(older_than_days)

    def record_access(self, node_id: str) -> None:
        """Delegates to NodeRepo."""
        self._node_repo.record_access(node_id)

    def record_feedback(self, node_id: str, helpful: bool) -> float:
        """Delegates to NodeRepo."""
        return self._node_repo.record_feedback(node_id, helpful)

    def record_outcome(self, node_id: str, was_useful: bool) -> float:
        """Delegates to NodeRepo."""
        return self._node_repo.record_outcome(node_id, was_useful)

    def pin_node(self, node_id: str, pinned: bool = True) -> bool:
        """Delegates to NodeRepo."""
        return self._node_repo.pin_node(node_id, pinned)

    def delete_node(self, node_id: str) -> bool:
        """Delegates to NodeRepo."""
        return self._node_repo.delete_node(node_id)

    # ── FEAT-06: Version History ──────────────────────────────────

    def get_node_history(self, node_id: str) -> list:
        """Delegates to NodeRepo."""
        return self._node_repo.get_node_history(node_id)

    def rollback_node(self, node_id: str, to_version: int,
                      actor: str = "system") -> bool:
        """Delegates to NodeRepo."""
        self._node_repo.rollback_node(node_id, to_version, actor)

    def deprecate_node(self, node_id: str, replaced_by: str = "",
                       reason: str = "") -> bool:
        """Delegates to NodeRepo."""
        self._node_repo.deprecate_node(node_id, replaced_by, reason)

    def get_lifecycle(self, node_id: str) -> dict:
        """Delegates to NodeRepo."""
        return self._node_repo.get_lifecycle(node_id)

    def get_deprecated_nodes(self, limit: int = 50) -> list:
        """Delegates to NodeRepo."""
        return self._node_repo.get_deprecated_nodes(limit)

    def purge_deprecated_nodes(self, older_than_days: int = 90) -> int:
        """Delegates to NodeRepo."""
        return self._node_repo.purge_deprecated_nodes(older_than_days)

    # ── FEAT-07: Cross-project Migration ─────────────────────────

    def migrate_from(self, source_db_path: "Path", scope: str = "global",
                     min_confidence: float = 0.0, dry_run: bool = False) -> dict:
        """Delegates to MigrationRepo."""
        return self._migration_repo.migrate_from(
            source_db_path, scope, min_confidence, dry_run,
            add_node_fn=self.add_node, add_edge_fn=self.add_edge,
        )

    # ── DEEP-02: Bayesian Confidence Propagation ──────────────────

    def propagate_confidence(self, node_id: str, dampening: float = 0.5,
                             max_hops: int = 3) -> dict[str, float]:
        """Delegates to MiscRepo."""
        return self._misc_repo.propagate_confidence(
            node_id, dampening, max_hops, get_node_fn=self.get_node,
        )

    def all_nodes(self, node_type=None, limit: int = 500) -> list:
        """Delegates to NodeRepo."""
        return self._node_repo.all_nodes(node_type, limit)

    # ── FED-01: Federation audit log (delegates to MiscRepo) ────────

    def record_federation_import(self, source: str, node_id: str, node_title: str, status: str = 'pending') -> int:
        return self._misc_repo.record_federation_import(source, node_id, node_title, status)

    def get_federation_imports(self, limit: int = 50, source: str = '') -> list:
        return self._misc_repo.get_federation_imports(limit, source)

    def add_edge(self, source_id: str, relation: str, target_id: str, note: str = "") -> int:
        return self._misc_repo.add_edge(source_id, relation, target_id, note)

    def stats(self) -> dict:
        return self._analytics_repo.stats()

    # -- L2: temporal memory (pure SQLite, replaces FalkorDB) --

    # ── Phase 1: Vector Storage (delegates to SearchRepo) ────────

    def add_vector(self, node_id: str, vector: list, model: str = 'nomic-embed-text') -> bool:
        return self._search_repo.add_vector(node_id, vector, model)

    @staticmethod
    def _cosine_similarity(a: list, b: list) -> float:
        from project_brain.vector_store import VectorStore
        return VectorStore._cosine_similarity(a, b)

    def search_nodes_by_vector(self, query_vector: list, threshold: float = 0.30,
                               limit: int = 8, scope: str = None) -> list:
        return self._search_repo.search_nodes_by_vector(query_vector, threshold, limit, scope)

    def hybrid_search(self, query: str, query_vector: list = None,
                      scope: str = None, limit: int = 8,
                      min_score: float = None) -> list:
        return self._search_repo.hybrid_search(query, query_vector, scope, limit, min_score)

    def get_nodes_without_vectors(self, limit: int = 100) -> list:
        return self._search_repo.get_nodes_without_vectors(limit)

    def link_episode_to_nodes(self, episode_id: str,
                              episode_content: str,
                              threshold: float = 0.80) -> int:
        return self._misc_repo.link_episode_to_nodes(
            episode_id, episode_content, threshold,
            search_nodes_fn=self.search_nodes,
            search_nodes_by_vector_fn=self.search_nodes_by_vector,
            add_temporal_edge_fn=self.add_temporal_edge,
        )

    def get_episode_links(self, episode_id: str) -> list:
        return self._misc_repo.get_episode_links(episode_id)

    # ── L2: temporal memory (delegates to MiscRepo) ────────────────────

    @_serialize_if_needed
    def add_episode(self, content: str, source: str = "", ref_time=None, confidence: float = 0.5) -> str:
        return self._misc_repo.add_episode(content, source, ref_time, confidence)

    def recent_episodes(self, limit: int = 10) -> list:
        return self._misc_repo.recent_episodes(limit)

    def search_episodes(self, query: str, limit: int = 5) -> list:
        return self._misc_repo.search_episodes(query, limit)

    @_serialize_if_needed
    def add_temporal_edge(self, source_id: str, relation: str, target_id: str,
                          content: str = "", valid_from=None) -> int:
        return self._misc_repo.add_temporal_edge(source_id, relation, target_id, content, valid_from)

    def temporal_query(self, at_time=None, limit: int = 20) -> list:
        return self._misc_repo.temporal_query(at_time, limit)

    def nodes_at_time(self, at_time: str, limit: int = 50, node_type: str = "") -> list[dict]:
        return self._misc_repo.nodes_at_time(at_time, limit, node_type)

    # -- events (delegates to MiscRepo) --

    def emit(self, event_type: str, payload: dict) -> None:
        self._misc_repo.emit(event_type, payload)

    def recent_events(self, event_type=None, limit: int = 20) -> list:
        return self._misc_repo.recent_events(event_type, limit)

    # ── FEAT-01: knowledge health dashboard (delegates to AnalyticsRepo) ──

    def optimize(self) -> dict:
        return self._analytics_repo.optimize()

    def health_report(self) -> dict:
        return self._analytics_repo.health_report()

    @staticmethod
    def _compute_health_score(total: int, avg_conf: float,
                               stale: int, fts_count: int, vec_count: int) -> float:
        from project_brain.storage.repositories.analytics_repo import AnalyticsRepo
        return AnalyticsRepo._compute_health_score(total, avg_conf, stale, fts_count, vec_count)

    def get_pipeline_stats(self, days: int = 7) -> dict:
        return self._analytics_repo.get_pipeline_stats(days)

    # ── FEAT-02: conflict detection (delegates to SearchRepo) ───────

    def _find_conflict_candidates(self, title: str, limit: int = 10) -> list:
        return self._search_repo._find_conflict_candidates(title, limit)

    def find_conflicts(self, similarity_threshold: float = 0.7,
                       candidates_per_anchor: int = 10) -> list:
        return self._search_repo.find_conflicts(similarity_threshold, candidates_per_anchor)

    def find_conflicts_for_node(self, node_id: str,
                                similarity_threshold: float = 0.6,
                                candidates_per_anchor: int = 10) -> list:
        return self._search_repo.find_conflicts_for_node(
            node_id, similarity_threshold, candidates_per_anchor)

    # ── FEAT-03: usage analytics (delegates to AnalyticsRepo) ────

    def usage_analytics(self) -> dict:
        return self._analytics_repo.usage_analytics()

    # ── FEAT-04: auto scope inference ───────────────────────────

    @staticmethod
    def infer_scope(workdir: str, current_file: str = "") -> str:
        from project_brain.storage.repositories.analytics_repo import AnalyticsRepo
        return AnalyticsRepo.infer_scope(workdir, current_file)

    # ── FEAT-05: import / export (delegates to AnalyticsRepo) ───

    def export_json(self, node_type: str = None, scope: str = None) -> dict:
        return self._analytics_repo.export_json(node_type, scope)

    def export_markdown(self, node_type: str = None, scope: str = None) -> str:
        return self._analytics_repo.export_markdown(node_type, scope)

    def export_neo4j(self, node_type: str = None, scope: str = None) -> str:
        return self._analytics_repo.export_neo4j(node_type, scope)

    def export_graphml(self, node_type: str = None, scope: str = None) -> str:
        return self._analytics_repo.export_graphml(node_type, scope)

    def import_json(self, data: dict, overwrite: bool = False,
                    merge_strategy: str = "skip") -> dict:
        return self._analytics_repo.import_json(
            data, overwrite, merge_strategy,
            add_node_fn=self.add_node, get_node_fn=self.get_node,
            add_edge_fn=self.add_edge,
        )

    # -- legacy migration --

    def migrate_from_legacy(self, brain_dir: Path) -> dict:
        """Delegates to MigrationRepo."""
        return self._migration_repo.migrate_from_legacy(
            brain_dir, add_node_fn=self.add_node, emit_fn=self.emit,
        )


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
