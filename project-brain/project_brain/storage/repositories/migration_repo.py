"""
project_brain/storage/repositories/migration_repo.py — Schema migrations & data migration

Versioned schema migrations (_run_migrations), legacy knowledge_graph.db import,
and cross-project migration.

All writes go through WriteContext for lock + commit safety.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from project_brain.storage.write_context import WriteContext

logger = logging.getLogger(__name__)


class MigrationRepo:
    """Schema migrations and data migration operations."""

    def __init__(self, ctx: "WriteContext"):
        self._ctx = ctx

    @staticmethod
    def _ngram(text: str) -> str:
        from project_brain.utils import ngram_cjk
        return ngram_cjk(text)

    def _run_migrations(self) -> None:
        """DEF-04: Versioned schema migrations — idempotent, incremental."""
        from project_brain.core.brain_db import SCHEMA_VERSION

        row = self._ctx.conn.execute(
            "SELECT value FROM brain_meta WHERE key='schema_version'"
        ).fetchone()
        current = int(row[0]) if row else 0

        if current >= SCHEMA_VERSION:
            return

        _migrations = [
            ("scope column on nodes",
             "ALTER TABLE nodes ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'"),
            ("episode confidence column",
             "ALTER TABLE episodes ADD COLUMN confidence REAL DEFAULT 0.5"),
            ("node_vectors table",
             """CREATE TABLE IF NOT EXISTS node_vectors (
                    node_id TEXT PRIMARY KEY,
                    vector  BLOB NOT NULL,
                    dim     INTEGER NOT NULL DEFAULT 768,
                    model   TEXT DEFAULT 'nomic-embed-text',
                    created_at TEXT DEFAULT (datetime('now'))
                )"""),
            ("unique index on episodes.source",
             "CREATE UNIQUE INDEX IF NOT EXISTS idx_episodes_source"
             " ON episodes(source) WHERE source != ''"),
            ("is_deprecated column on nodes",
             "ALTER TABLE nodes ADD COLUMN is_deprecated INTEGER NOT NULL DEFAULT 0"),
            ("valid_until column on nodes",
             "ALTER TABLE nodes ADD COLUMN valid_until TEXT DEFAULT NULL"),
            ("synonym_index table",
             """CREATE TABLE IF NOT EXISTS synonym_index (
                 term TEXT NOT NULL, synonym TEXT NOT NULL,
                 PRIMARY KEY(term, synonym)
             )"""),
            ("node_history table",
             """CREATE TABLE IF NOT EXISTS node_history (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 node_id TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                 title TEXT, content TEXT, confidence REAL, tags TEXT,
                 changed_by TEXT DEFAULT '', change_note TEXT DEFAULT '',
                 snapshot_at TEXT DEFAULT (datetime('now'))
             )"""),
            ("node_history index",
             "CREATE INDEX IF NOT EXISTS idx_nh_node ON node_history(node_id, version)"),
            ("FTS5 bigram atomic rebuild",
             lambda conn: (
                 conn.execute("DELETE FROM nodes_fts"),
                 [conn.execute(
                     "INSERT INTO nodes_fts(id, title, content, tags) VALUES(?, ?, ?, ?)",
                     (r[0], MigrationRepo._ngram(r[1] or ""),
                      MigrationRepo._ngram(r[2] or ""), r[3] or "[]")
                 ) for r in conn.execute(
                     "SELECT id, title, content, tags FROM nodes"
                 ).fetchall()],
                 conn.execute(
                     "INSERT OR REPLACE INTO brain_meta(key,value) "
                     "VALUES('fts_bigram_v1','done')"
                 )
             )),
            ("scope+confidence compound index",
             "CREATE INDEX IF NOT EXISTS idx_nodes_scope_conf ON nodes(scope, confidence)"),
            ("drop FTS5 auto-update/delete triggers",
             lambda conn: (
                 conn.execute("DROP TRIGGER IF EXISTS nodes_fts_au"),
                 conn.execute("DROP TRIGGER IF EXISTS nodes_fts_ad"),
             )),
            ("is_pinned+confidence composite index",
             "CREATE INDEX IF NOT EXISTS idx_nodes_pinned_conf"
             " ON nodes(is_pinned DESC, confidence DESC)"),
            ("version column on nodes",
             "ALTER TABLE nodes ADD COLUMN version INTEGER NOT NULL DEFAULT 1"),
            ("change_type column on node_history",
             "ALTER TABLE node_history ADD COLUMN change_type TEXT DEFAULT 'update'"),
            ("deprecated_at column on nodes",
             "ALTER TABLE nodes ADD COLUMN deprecated_at TEXT DEFAULT NULL"),
            ("adoption_count column on nodes",
             "ALTER TABLE nodes ADD COLUMN adoption_count INTEGER NOT NULL DEFAULT 0"),
            ("federation_imports table",
             """CREATE TABLE IF NOT EXISTS federation_imports (
                 id          INTEGER PRIMARY KEY AUTOINCREMENT,
                 source      TEXT NOT NULL DEFAULT '',
                 node_id     TEXT NOT NULL DEFAULT '',
                 node_title  TEXT NOT NULL DEFAULT '',
                 status      TEXT NOT NULL DEFAULT 'pending',
                 imported_at TEXT NOT NULL DEFAULT (datetime('now')),
                 notes       TEXT NOT NULL DEFAULT ''
             )"""),
            ("valid_from column on nodes",
             "ALTER TABLE nodes ADD COLUMN valid_from TEXT DEFAULT NULL"),
            ("result_count column on traces",
             "ALTER TABLE traces ADD COLUMN result_count INTEGER NOT NULL DEFAULT 0"),
            ("type+confidence compound index",
             "CREATE INDEX IF NOT EXISTS idx_nodes_type_conf"
             " ON nodes(type, confidence DESC)"),
            ("description column on nodes",
             "ALTER TABLE nodes ADD COLUMN description TEXT NOT NULL DEFAULT ''"),
            ("signal_queue table",
             """CREATE TABLE IF NOT EXISTS signal_queue (
                 id           TEXT PRIMARY KEY,
                 kind         TEXT NOT NULL,
                 workdir      TEXT NOT NULL,
                 timestamp    TEXT NOT NULL,
                 summary      TEXT NOT NULL,
                 raw_content  TEXT NOT NULL,
                 metadata     TEXT NOT NULL DEFAULT '{}',
                 priority     INTEGER NOT NULL DEFAULT 5,
                 status       TEXT NOT NULL DEFAULT 'pending',
                 attempts     INTEGER NOT NULL DEFAULT 0,
                 error        TEXT,
                 created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                 processed_at TEXT,
                 CHECK (status IN ('pending','processing','done','failed','skipped'))
             )"""),
            ("signal_queue priority index",
             "CREATE INDEX IF NOT EXISTS idx_signal_queue_status_priority"
             " ON signal_queue (status, priority, created_at)"),
            ("signal_queue dedup index",
             "CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_dedup"
             " ON signal_queue (kind, workdir, summary)"
             " WHERE status = 'pending'"),
            ("pipeline_metrics table",
             """CREATE TABLE IF NOT EXISTS pipeline_metrics (
                 node_id       TEXT NOT NULL,
                 signal_id     TEXT NOT NULL,
                 action        TEXT NOT NULL,
                 llm_model     TEXT NOT NULL DEFAULT '',
                 created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                 was_useful    INTEGER,
                 feedback_at   TEXT,
                 feedback_note TEXT,
                 PRIMARY KEY (node_id, signal_id)
             )"""),
            ("C-01: edges schema alignment + indexes",
             lambda conn: (
                 conn.execute("ALTER TABLE edges ADD COLUMN weight REAL DEFAULT 1.0"),
                 conn.execute("ALTER TABLE edges ADD COLUMN created_at TEXT DEFAULT ''"),
                 conn.execute("ALTER TABLE edges ADD COLUMN trigger_condition TEXT DEFAULT ''"),
                 conn.execute("ALTER TABLE edges ADD COLUMN confidence REAL DEFAULT 0.8"),
                 conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)"),
                 conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)"),
             )),
            ("C-05: feedback_log table",
             """CREATE TABLE IF NOT EXISTS feedback_log (
                 id          INTEGER PRIMARY KEY AUTOINCREMENT,
                 node_id     TEXT NOT NULL,
                 signal_kind TEXT DEFAULT '',
                 was_useful  INTEGER NOT NULL,
                 notes       TEXT DEFAULT '',
                 conf_before REAL,
                 conf_after  REAL,
                 created_at  TEXT DEFAULT (datetime('now'))
             )"""),
            ("E-02: api_keys table for RBAC",
             """CREATE TABLE IF NOT EXISTS api_keys (
                 id          INTEGER PRIMARY KEY AUTOINCREMENT,
                 key_hash    TEXT NOT NULL UNIQUE,
                 role        TEXT NOT NULL DEFAULT 'reader',
                 name        TEXT NOT NULL DEFAULT '',
                 created_at  TEXT DEFAULT (datetime('now')),
                 expires_at  TEXT DEFAULT NULL,
                 is_revoked  INTEGER NOT NULL DEFAULT 0,
                 CHECK (role IN ('reader','contributor','maintainer','admin'))
             )"""),
        ]

        for idx, (desc, sql) in enumerate(_migrations):
            ver = idx + 1
            if ver <= current:
                continue
            _genuine_failure = False
            try:
                if callable(sql):
                    sql(self._ctx.conn)
                else:
                    self._ctx.conn.execute(sql)
            except Exception as _me:
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
            if not _genuine_failure:
                self._ctx.conn.execute(
                    "INSERT OR REPLACE INTO brain_meta(key,value) VALUES('schema_version',?)",
                    (str(ver),)
                )
                self._ctx.conn.commit()
                logger.debug("DEF-04: schema migration v%d applied: %s", ver, desc)

    def _migrate_kg_to_unified(self, add_node_fn=None) -> None:
        """C-01: One-time import of nodes+edges from knowledge_graph.db into brain.db.

        Args:
            add_node_fn: Callback to add a node (BrainDB.add_node). If None,
                         inserts directly via SQL.
        """
        kg_path = self._ctx.brain_dir / "knowledge_graph.db"
        if not kg_path.exists():
            return
        try:
            row = self._ctx.conn.execute(
                "SELECT value FROM brain_meta WHERE key='c01_kg_merged'"
            ).fetchone()
            if row:
                return
        except Exception:
            pass

        logger.info("C-01: migrating knowledge_graph.db → brain.db …")
        try:
            import sqlite3 as _sql
            old = _sql.connect(str(kg_path))
            old.row_factory = _sql.Row

            node_count = 0
            for r in old.execute("SELECT * FROM nodes").fetchall():
                d = dict(r)
                try:
                    if add_node_fn:
                        add_node_fn(
                            node_id=d["id"],
                            node_type=d.get("type", ""),
                            title=d.get("title", ""),
                            content=d.get("content", ""),
                            confidence=float(d.get("confidence") or 0.8),
                        )
                    else:
                        # Direct SQL insert as fallback
                        self._ctx.conn.execute(
                            "INSERT OR IGNORE INTO nodes(id, type, title, content, confidence)"
                            " VALUES(?,?,?,?,?)",
                            (d["id"], d.get("type", ""), d.get("title", ""),
                             d.get("content", ""), float(d.get("confidence") or 0.8)),
                        )
                    node_count += 1
                except Exception:
                    pass

            edge_count = 0
            for r in old.execute("SELECT * FROM edges").fetchall():
                d = dict(r)
                try:
                    self._ctx.conn.execute(
                        """INSERT OR IGNORE INTO edges
                           (source_id, relation, target_id, weight, note,
                            causal_direction, trigger_condition, confidence, created_at)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            d["source_id"], d["relation"], d["target_id"],
                            d.get("weight", 1.0), d.get("note", ""),
                            d.get("causal_direction", "CORRELATES"),
                            d.get("trigger_condition", ""),
                            d.get("confidence", 0.8),
                            d.get("created_at", ""),
                        ),
                    )
                    edge_count += 1
                except Exception:
                    pass
            old.close()

            self._ctx.conn.execute(
                "INSERT OR REPLACE INTO brain_meta(key,value) VALUES('c01_kg_merged','done')"
            )
            self._ctx.conn.commit()

            bak = kg_path.with_suffix(".db.bak")
            try:
                kg_path.rename(bak)
                logger.info(
                    "C-01: migration complete — %d nodes, %d edges imported. "
                    "Old file → %s", node_count, edge_count, bak.name,
                )
            except OSError as _oe:
                logger.warning("C-01: rename failed (non-fatal): %s", _oe)

        except Exception as _e:
            logger.warning("C-01: KG migration failed (will retry next startup): %s", _e)

    def migrate_from(self, source_db_path: Path, scope: str = "global",
                     min_confidence: float = 0.0, dry_run: bool = False,
                     add_node_fn=None, add_edge_fn=None) -> dict:
        """FEAT-07: Copy nodes (and edges) from another brain.db."""
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
                        if add_node_fn:
                            add_node_fn(
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
                        if add_edge_fn:
                            add_edge_fn(d["source_id"], d["relation"],
                                        d["target_id"], d.get("note",""))
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

    def migrate_from_legacy(self, brain_dir: Path,
                            add_node_fn=None, emit_fn=None) -> dict:
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
                        except Exception as _e: logger.error("meta json parse failed in migration: %s", _e)
                        if add_node_fn:
                            add_node_fn(d["id"], d["type"], d["title"],
                                        content=d.get("content",""),
                                        confidence=d.get("confidence", 0.8),
                                        importance=d.get("importance", 0.5),
                                        emotional_weight=d.get("emotional_weight", 0.5),
                                        meta=meta)
                        imported["nodes"] += 1
                    except Exception as _e: logger.error("node migration row failed: %s", _e)
                old.close()
            except Exception as e:
                logger.warning("Legacy node migration: %s", e)
        ss = brain_dir / "session_store.db"
        if ss.exists():
            try:
                old = sqlite3.connect(str(ss)); old.row_factory = sqlite3.Row
                existing_tbls = {
                    r[0] for r in old.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                for tbl in ("sessions", "memories"):
                    if tbl not in existing_tbls:
                        logger.debug(
                            "session migration: table '%s' not found in legacy db, skipping", tbl
                        )
                        continue
                    try:
                        for row in old.execute(f"SELECT * FROM {tbl}").fetchall():
                            d = dict(row)
                            self._ctx.conn.execute(
                                "INSERT INTO sessions(session_id,key,value,category)"
                                " VALUES(?,?,?,?)"
                                " ON CONFLICT(session_id,key) DO UPDATE SET value=excluded.value",
                                (str(d.get("session_id","legacy")), str(d.get("key","?")),
                                 str(d.get("value","")), str(d.get("category","general")))
                            )
                            imported["sessions"] += 1
                    except Exception as _e:
                        logger.debug("session migration table failed: %s", _e)
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
                        if emit_fn:
                            emit_fn(d.get("event_type","legacy"),
                                    json.loads(d.get("payload") or "{}"))
                        imported["events"] += 1
                    except Exception as _e: logger.error("event migration row failed: %s", _e)
                old.close()
            except Exception as e:
                logger.warning("Legacy event migration: %s", e)
        return imported
