"""
C-01: Database Unification Tests

Verifies that knowledge_graph.db is merged into brain.db:
- Migration v27: edges schema aligned with graph.py expectations
- KG→brain.db data import: nodes + edges migrated, old file renamed
- Unified DB: graph.add_node searchable via brain_db.search_nodes
- Connection sharing: graph and brain_db use same SQLite connection
- Backward compat: KnowledgeGraph(brain_dir) works without conn param
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from project_brain.brain_db import BrainDB
from project_brain.graph import KnowledgeGraph


def _init_brain(tmp_path: Path) -> Path:
    """Create a minimal .brain/ directory with BrainDB initialized."""
    bd = tmp_path / ".brain"
    bd.mkdir(exist_ok=True)
    db = BrainDB(bd)
    return bd


# ════════════════════════════════════════════════════════════════
# Migration v27: edges schema alignment
# ════════════════════════════════════════════════════════════════


class TestMigrationV27:
    """brain.db edges table must have columns that graph.py expects."""

    def test_edges_has_weight_column(self, tmp_path):
        bd = _init_brain(tmp_path)
        conn = sqlite3.connect(str(bd / "brain.db"))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(edges)").fetchall()}
        conn.close()
        assert "weight" in cols

    def test_edges_has_created_at_column(self, tmp_path):
        bd = _init_brain(tmp_path)
        conn = sqlite3.connect(str(bd / "brain.db"))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(edges)").fetchall()}
        conn.close()
        assert "created_at" in cols

    def test_edges_has_trigger_condition_column(self, tmp_path):
        bd = _init_brain(tmp_path)
        conn = sqlite3.connect(str(bd / "brain.db"))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(edges)").fetchall()}
        conn.close()
        assert "trigger_condition" in cols

    def test_edges_has_confidence_column(self, tmp_path):
        bd = _init_brain(tmp_path)
        conn = sqlite3.connect(str(bd / "brain.db"))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(edges)").fetchall()}
        conn.close()
        assert "confidence" in cols

    def test_edge_indexes_exist(self, tmp_path):
        bd = _init_brain(tmp_path)
        conn = sqlite3.connect(str(bd / "brain.db"))
        indexes = {r[1] for r in conn.execute("PRAGMA index_list(edges)").fetchall()}
        conn.close()
        assert "idx_edges_source" in indexes
        assert "idx_edges_target" in indexes

    def test_schema_version_is_27(self, tmp_path):
        bd = _init_brain(tmp_path)
        conn = sqlite3.connect(str(bd / "brain.db"))
        row = conn.execute(
            "SELECT value FROM brain_meta WHERE key='schema_version'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert int(row[0]) >= 27


# ════════════════════════════════════════════════════════════════
# KG data migration
# ════════════════════════════════════════════════════════════════


class TestKGMigration:
    """knowledge_graph.db data imported into brain.db + old file renamed."""

    def _create_legacy_kg(self, bd: Path) -> None:
        """Create a legacy knowledge_graph.db with some test data."""
        kg_path = bd / "knowledge_graph.db"
        conn = sqlite3.connect(str(kg_path))
        conn.execute("""CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY, type TEXT, title TEXT, content TEXT,
            tags TEXT DEFAULT '[]', source_url TEXT DEFAULT '',
            author TEXT DEFAULT '', meta TEXT DEFAULT '{}',
            confidence REAL DEFAULT 0.8, importance REAL DEFAULT 0.5,
            is_pinned INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT,
            version INTEGER DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT, relation TEXT, target_id TEXT,
            weight REAL DEFAULT 1.0, note TEXT DEFAULT '',
            causal_direction TEXT DEFAULT 'CORRELATES',
            trigger_condition TEXT DEFAULT '',
            confidence REAL DEFAULT 0.8,
            created_at TEXT DEFAULT ''
        )""")
        conn.execute(
            "INSERT INTO nodes(id, type, title, content) VALUES(?, ?, ?, ?)",
            ("kg-node-1", "Rule", "Legacy Rule", "From knowledge_graph.db"),
        )
        conn.execute(
            "INSERT INTO nodes(id, type, title, content) VALUES(?, ?, ?, ?)",
            ("kg-node-2", "Pitfall", "Legacy Pitfall", "Old pitfall data"),
        )
        conn.execute(
            "INSERT INTO edges(source_id, relation, target_id) VALUES(?, ?, ?)",
            ("kg-node-1", "DEPENDS_ON", "kg-node-2"),
        )
        conn.commit()
        conn.close()

    def test_nodes_imported(self, tmp_path):
        bd = tmp_path / ".brain"
        bd.mkdir()
        self._create_legacy_kg(bd)
        db = BrainDB(bd)  # triggers migration
        node = db.get_node("kg-node-1")
        assert node is not None
        assert node["title"] == "Legacy Rule"
        db.close()

    def test_edges_imported(self, tmp_path):
        bd = tmp_path / ".brain"
        bd.mkdir()
        self._create_legacy_kg(bd)
        db = BrainDB(bd)
        rows = db.conn.execute(
            "SELECT * FROM edges WHERE source_id='kg-node-1'"
        ).fetchall()
        assert len(rows) >= 1
        db.close()

    def test_old_file_renamed_to_bak(self, tmp_path):
        bd = tmp_path / ".brain"
        bd.mkdir()
        self._create_legacy_kg(bd)
        db = BrainDB(bd)
        db.close()
        assert not (bd / "knowledge_graph.db").exists()
        assert (bd / "knowledge_graph.db.bak").exists()

    def test_idempotent_marker(self, tmp_path):
        bd = tmp_path / ".brain"
        bd.mkdir()
        self._create_legacy_kg(bd)
        db1 = BrainDB(bd)
        db1.close()
        # Second init — bak exists, no kg file, marker set
        db2 = BrainDB(bd)
        row = db2.conn.execute(
            "SELECT value FROM brain_meta WHERE key='c01_kg_merged'"
        ).fetchone()
        assert row is not None
        assert row[0] == "done"
        db2.close()

    def test_no_kg_file_no_migration(self, tmp_path):
        """If no knowledge_graph.db exists, migration is a no-op."""
        bd = _init_brain(tmp_path)
        conn = sqlite3.connect(str(bd / "brain.db"))
        row = conn.execute(
            "SELECT value FROM brain_meta WHERE key='c01_kg_merged'"
        ).fetchone()
        conn.close()
        assert row is None  # marker not set — migration didn't run


# ════════════════════════════════════════════════════════════════
# Unified DB operations
# ════════════════════════════════════════════════════════════════


class TestUnifiedDB:
    """graph.add_node() writes to brain.db, searchable via brain_db."""

    def test_graph_add_node_visible_in_braindb(self, tmp_path):
        """Node added via graph is in brain.db nodes table."""
        bd = _init_brain(tmp_path)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        g.add_node("test-1", "Rule", "Test Rule", content="important rule")
        # Verify via direct SQL on same connection
        row = db.conn.execute(
            "SELECT title FROM nodes WHERE id='test-1'"
        ).fetchone()
        assert row is not None
        assert row[0] == "Test Rule"
        db.close()

    def test_braindb_add_node_visible_in_graph(self, tmp_path):
        """Node added via brain_db is visible to graph queries."""
        bd = _init_brain(tmp_path)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        db.add_node("bdb-1", "Decision", "BrainDB Decision", content="test")
        node = g.get_node("bdb-1")
        assert node is not None
        assert node["title"] == "BrainDB Decision"
        db.close()

    def test_no_knowledge_graph_db_created(self, tmp_path):
        """After C-01, knowledge_graph.db should NOT be created."""
        bd = _init_brain(tmp_path)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        g.add_node("n1", "Rule", "R1")
        assert not (bd / "knowledge_graph.db").exists()
        db.close()


class TestEdgesUnified:
    """Edges written by graph.py are stored in brain.db."""

    def test_graph_add_edge_in_braindb(self, tmp_path):
        bd = _init_brain(tmp_path)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        g.add_node("a1", "Rule", "Rule A")
        g.add_node("b1", "Pitfall", "Pitfall B")
        g.add_edge("a1", "DEPENDS_ON", "b1")
        rows = db.conn.execute(
            "SELECT * FROM edges WHERE source_id='a1' AND target_id='b1'"
        ).fetchall()
        assert len(rows) == 1
        db.close()


class TestFTS5Unified:
    """FTS5 search works after unification."""

    def test_graph_node_searchable_via_fts5(self, tmp_path):
        bd = _init_brain(tmp_path)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        g.add_node("fts-1", "Rule", "Authentication Best Practice",
                    content="Always validate JWT tokens")
        results = g.search_nodes("Authentication", limit=5)
        assert len(results) >= 1
        assert any(r["id"] == "fts-1" for r in results)
        db.close()

    def test_updated_node_searchable(self, tmp_path):
        bd = _init_brain(tmp_path)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        g.add_node("fts-2", "Pitfall", "Old Title", content="old content")
        g.update_node("fts-2", title="Database Migration Pitfall",
                      content="Check foreign keys")
        results = g.search_nodes("Migration", limit=5)
        assert any(r["id"] == "fts-2" for r in results)
        db.close()


# ════════════════════════════════════════════════════════════════
# Connection sharing
# ════════════════════════════════════════════════════════════════


class TestConnectionSharing:
    """graph and brain_db share the same SQLite connection."""

    def test_same_connection_object(self, tmp_path):
        bd = _init_brain(tmp_path)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        assert g._conn_obj is db.conn

    def test_shared_conn_graph_does_not_close(self, tmp_path):
        """graph.close() on shared conn should be a no-op."""
        bd = _init_brain(tmp_path)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        g.close()  # should NOT close the connection
        # Connection still usable
        row = db.conn.execute("SELECT 1").fetchone()
        assert row[0] == 1
        db.close()

    def test_owns_conn_false_when_shared(self, tmp_path):
        bd = _init_brain(tmp_path)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        assert g._owns_conn is False
        db.close()


# ════════════════════════════════════════════════════════════════
# Backward compatibility
# ════════════════════════════════════════════════════════════════


class TestBackwardCompat:
    """KnowledgeGraph(brain_dir) without conn param still works."""

    def test_standalone_graph_creates_brain_db(self, tmp_path):
        """Without conn param, KG creates its own connection to brain.db."""
        bd = _init_brain(tmp_path)
        g = KnowledgeGraph(bd)
        assert g._owns_conn is True
        g.add_node("bc-1", "Rule", "Backward Compat Test")
        node = g.get_node("bc-1")
        assert node is not None
        g.close()

    def test_standalone_graph_uses_brain_db_path(self, tmp_path):
        """db_path should point to brain.db, not knowledge_graph.db."""
        bd = _init_brain(tmp_path)
        g = KnowledgeGraph(bd)
        assert g.db_path == bd / "brain.db"
        g.close()

    def test_concurrent_add_50_nodes(self, tmp_path):
        """50 threads adding nodes concurrently to unified DB."""
        bd = _init_brain(tmp_path)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        errors = []

        def _add(i):
            try:
                g.add_node(f"conc-{i}", "Rule", f"Concurrent {i}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_add, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent errors: {errors[:5]}"
        count = db.conn.execute("SELECT COUNT(*) FROM nodes WHERE id LIKE 'conc-%'").fetchone()[0]
        assert count == 50
        db.close()


# ════════════════════════════════════════════════════════════════
# Health check
# ════════════════════════════════════════════════════════════════


class TestHealthSingleDB:
    """Health checker reports single-DB mode."""

    def test_health_reports_single_db(self, tmp_path):
        bd = _init_brain(tmp_path)
        from project_brain.health import HealthChecker
        hc = HealthChecker(bd)
        report = hc.run()
        db_check = next(
            (c for c in report["checks"] if c["label"] == "brain.db"), None
        )
        assert db_check is not None
        assert "single DB mode" in db_check["message"]

    def test_health_no_kg_error(self, tmp_path):
        """No error for missing knowledge_graph.db (expected in unified mode)."""
        bd = _init_brain(tmp_path)
        from project_brain.health import HealthChecker
        hc = HealthChecker(bd)
        report = hc.run()
        kg_error = [c for c in report["checks"]
                    if c["label"] == "knowledge_graph.db" and c["level"] == "error"]
        assert len(kg_error) == 0
