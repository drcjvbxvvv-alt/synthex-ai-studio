"""
project_brain/storage/repositories/node_repo.py — Node CRUD & lifecycle

SQL operations for knowledge nodes: add, update, delete, deprecate,
version history, lifecycle management.

All writes go through WriteContext.execute_write() for lock + commit safety.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from project_brain.storage.write_context import WriteContext

logger = logging.getLogger(__name__)


class NodeRepo:
    """Node CRUD and lifecycle operations."""

    def __init__(self, ctx: "WriteContext"):
        self._ctx = ctx

    @staticmethod
    def _ngram(text: str) -> str:
        from project_brain.utils import ngram_cjk
        return ngram_cjk(text)

    def add_node(self, node_id: str, node_type: str, title: str,
                 content: str = "", tags=None, scope: str = "global", **kw) -> str:
        tags_json  = json.dumps(tags or [], ensure_ascii=False)
        meta       = kw.get("meta", {})
        confidence = float(kw.get("confidence",
                           meta.get("confidence", 0.8) if isinstance(meta, dict) else 0.8))
        valid_from = kw.get("valid_from")
        created_at = kw.get("created_at", "") or ""
        # MEM-02: description field — auto-generate from content if not provided
        description = kw.get("description", "") or ""
        if not description and content:
            description = content[:100].replace('\n', ' ')

        with self._ctx.write_guard():  # DEF-01 fix: cross-process write lock
            # BUG-01: move valid_from SELECT inside lock so all conn access is serialized
            if not valid_from:
                # FEAT-03: git commit date; preserve existing value if not re-provided
                existing = self._ctx.conn.execute(
                    "SELECT valid_from FROM nodes WHERE id=?", (node_id,)
                ).fetchone()
                if existing:
                    valid_from = existing[0]  # carry over from previous write
            _created_at_val = created_at or None  # None means use DEFAULT
            try:  # BUG-01: nodes INSERT + FTS sync must be atomic
                self._ctx.conn.execute("""
                    INSERT INTO nodes
                        (id,type,title,content,description,tags,confidence,importance,
                         emotional_weight,source_url,author,meta,scope,valid_from,
                         created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                            COALESCE(NULLIF(?, ''), datetime('now')))
                    ON CONFLICT(id) DO UPDATE SET
                        type=excluded.type,
                        title=excluded.title,
                        content=excluded.content,
                        description=excluded.description,
                        tags=excluded.tags,
                        confidence=excluded.confidence,
                        importance=excluded.importance,
                        emotional_weight=excluded.emotional_weight,
                        source_url=excluded.source_url,
                        author=excluded.author,
                        meta=excluded.meta,
                        scope=excluded.scope,
                        valid_from=excluded.valid_from
                        -- created_at intentionally omitted: preserve original date
                """, (node_id, node_type, title, content, description, tags_json,
                      confidence,
                      float(kw.get("importance", 0.5)),
                      float(kw.get("emotional_weight", 0.5)),
                      kw.get("source_url",""), kw.get("author",""),
                      json.dumps(meta if isinstance(meta, dict) else {}, ensure_ascii=False),
                      scope, valid_from,
                      _created_at_val))
                self._ctx.conn.execute("DELETE FROM nodes_fts WHERE id=?", (node_id,))
                self._ctx.conn.execute(
                    "INSERT INTO nodes_fts(id,title,content,tags) VALUES(?,?,?,?)",
                    (node_id, self._ngram(title), self._ngram(content), tags_json)
                )
                self._ctx.conn.commit()
            except Exception as _e:
                self._ctx.conn.rollback()
                logger.error("add_node rolled back (nodes + FTS atomic failure): %s", _e)
                raise
        return node_id

    def sync_from_graph_node(self, event: str, data: dict) -> None:
        """B-02: Observer callback — sync a KnowledgeGraph node write to brain.db.

        Called by KnowledgeGraph._emit() after add_node() or update_node() commits.
        Uses upsert semantics (INSERT ... ON CONFLICT DO UPDATE), so calling this
        multiple times with the same data is idempotent.

        Only "node_upserted" events are handled; unknown events are silently ignored
        so future event types can be added to graph.py without breaking this method.
        """
        if event != "node_upserted":
            return
        self.add_node(
            node_id   = data["node_id"],
            node_type = data.get("node_type", ""),
            title     = data.get("title", ""),
            content   = data.get("content", ""),
            tags      = data.get("tags") or [],
            confidence= float(data.get("confidence") or 0.8),
            created_at= data.get("created_at", ""),
        )

    def update_node(self, node_id: str, title=None, content=None,
                    confidence=None, importance=None,
                    changed_by: str = "", change_note: str = "",
                    change_type: str = "update") -> bool:
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
        ups.append("version=COALESCE(version,1)+1")  # FEAT-01: increment version
        params.append(node_id)
        with self._ctx.write_guard():  # DEF-01 fix
            # FEAT-06/FEAT-01: snapshot BEFORE state into node_history
            try:
                last_ver = self._ctx.conn.execute(
                    "SELECT COALESCE(MAX(version),0) FROM node_history WHERE node_id=?",
                    (node_id,)
                ).fetchone()[0]
                self._ctx.conn.execute(
                    "INSERT INTO node_history(node_id,version,title,content,confidence,tags,"
                    "changed_by,change_note,change_type) VALUES(?,?,?,?,?,?,?,?,?)",
                    (node_id, last_ver + 1, ex.get("title"), ex.get("content"),
                     ex.get("confidence"), ex.get("tags","[]"),
                     changed_by, change_note, change_type)  # OBS-03: use caller-supplied change_type
                )
            except Exception as _e:
                logger.error("node_history snapshot failed: %s", _e)
            try:  # REL-01: UPDATE + FTS must succeed together or rollback
                self._ctx.conn.execute(f"UPDATE nodes SET {', '.join(ups)} WHERE id=?", params)
                if title is not None or content is not None:
                    nt = title   if title   is not None else ex["title"]
                    nc = content if content is not None else ex["content"]
                    self._ctx.conn.execute("DELETE FROM nodes_fts WHERE id=?", (node_id,))
                    self._ctx.conn.execute(
                        "INSERT INTO nodes_fts(id,title,content,tags) VALUES(?,?,?,?)",
                        (node_id, self._ngram(nt), self._ngram(nc), ex.get("tags","[]"))
                    )
                self._ctx.conn.commit()
            except Exception as _e:
                self._ctx.conn.rollback()
                logger.error("update_node rolled back (nodes + FTS atomic failure): %s", _e)
                raise
        # OPT-10 fix: evict stale embedder cache entries when content changes
        if content is not None:
            try:
                from ..embedder import _TFIDF_CACHE
                old_key = __import__('hashlib').md5(
                    (ex.get("content") or "").encode()
                ).hexdigest()
                _TFIDF_CACHE.pop(old_key, None)
            except Exception as _e:
                logger.error("embedder cache eviction failed: %s", _e)
        return True

    def get_node(self, node_id: str):
        r = self._ctx.conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return dict(r) if r else None

    def record_access(self, node_id: str) -> None:
        """REF-01: delegated to FeedbackTracker"""
        self._ctx.feedback_tracker.record_access(node_id)

    def record_feedback(self, node_id: str, helpful: bool) -> float:
        """REF-01: delegated to FeedbackTracker"""
        return self._ctx.feedback_tracker.record_feedback(node_id, helpful)

    def record_outcome(self, node_id: str, was_useful: bool) -> float:
        """REF-01: delegated to FeedbackTracker"""
        return self._ctx.feedback_tracker.record_outcome(node_id, was_useful)

    def pin_node(self, node_id: str, pinned: bool = True) -> bool:
        # MEDIUM-01: unified write entry
        r = self._ctx.execute_write(
            "UPDATE nodes SET is_pinned=? WHERE id=?", (int(pinned), node_id)
        )
        return r.rowcount > 0

    def delete_node(self, node_id: str) -> bool:
        with self._ctx.write_guard():
            # DATA-01: capture node data for audit log before deletion
            row = self._ctx.conn.execute(
                "SELECT title, content, confidence FROM nodes WHERE id=?", (node_id,)
            ).fetchone()
            # BUG-A02: manual FTS5 cleanup (trigger removed in v12 migration)
            self._ctx.conn.execute("DELETE FROM nodes_fts WHERE id=?", (node_id,))
            r = self._ctx.conn.execute("DELETE FROM nodes WHERE id=?", (node_id,))
            if r.rowcount > 0 and row:
                try:
                    self._ctx.conn.execute(
                        "INSERT INTO node_history"
                        " (node_id, version, title, content, confidence, change_note, snapshot_at)"
                        " SELECT ?, COALESCE(MAX(version),0)+1, ?, ?, ?, 'deleted', datetime('now')"
                        " FROM node_history WHERE node_id=?",
                        (node_id, row[0], row[1], row[2], node_id)
                    )
                except Exception as _e:
                    logger.debug("delete_node: audit log failed for %s: %s", node_id, _e)
            self._ctx.conn.commit()
        return r.rowcount > 0

    def get_node_history(self, node_id: str) -> list:
        """FEAT-06: 回傳節點的版本歷史（由舊到新）。"""
        try:
            rows = self._ctx.conn.execute(
                "SELECT * FROM node_history WHERE node_id=? ORDER BY version ASC",
                (node_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def rollback_node(self, node_id: str, to_version: int,
                      actor: str = "system") -> bool:
        """FEAT-06 / OBS-03: 將節點恢復到指定版本的快照狀態，並寫入 change_type='rollback' 審計記錄。

        Args:
            node_id:    目標節點 ID
            to_version: 要恢復的版本號（node_history.version）
            actor:      執行還原的操作者（呼叫方傳入，預設 "system"）
        """
        rows = self._ctx.conn.execute(
            "SELECT * FROM node_history WHERE node_id=? AND version=?",
            (node_id, to_version)
        ).fetchone()
        if not rows:
            return False
        snap = dict(rows)
        return self.update_node(
            node_id,
            title       = snap.get("title"),
            content     = snap.get("content"),
            confidence  = snap.get("confidence"),
            changed_by  = actor,
            change_note = f"Rolled back to v{to_version}",
            change_type = "rollback",   # OBS-03: distinguish from regular updates
        )

    def deprecate_node(self, node_id: str, replaced_by: str = "",
                       reason: str = "") -> bool:
        """FEAT-13: Mark a node as deprecated.

        Sets is_deprecated=1, optionally links to replacement via REPLACED_BY edge.
        """
        node = self.get_node(node_id)
        if not node:
            return False
        with self._ctx.write_guard():
            self._ctx.conn.execute(
                "UPDATE nodes SET is_deprecated=1, updated_at=datetime('now'),"
                " deprecated_at=COALESCE(deprecated_at,datetime('now'))"  # ARCH-05
                " WHERE id=?", (node_id,)
            )
            if reason:
                self._ctx.conn.execute(
                    "UPDATE nodes SET content=content||? WHERE id=?",
                    (f"\n[棄用] {reason}", node_id)
                )
            self._ctx.conn.commit()
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
            rows = self._ctx.conn.execute(
                "SELECT target_id FROM edges WHERE source_id=? AND relation='REPLACED_BY'",
                (node_id,)
            ).fetchall()
            replaced_by = [r[0] for r in rows]
        except Exception as _e:
            logger.error("REPLACED_BY edges query failed: %s", _e)
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

    def get_deprecated_nodes(self, limit: int = 50) -> list:
        """ARCH-05: 列出已棄用的節點（含棄用時間）"""
        try:
            rows = self._ctx.conn.execute(
                "SELECT id, type, title, confidence, deprecated_at, updated_at"
                " FROM nodes WHERE is_deprecated=1"
                " ORDER BY COALESCE(deprecated_at, updated_at) DESC LIMIT ?",
                (max(1, min(200, limit)),)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def purge_deprecated_nodes(self, older_than_days: int = 90) -> int:
        """ARCH-05: 硬刪除超過指定天數的已棄用節點。"""
        try:
            cutoff = (
                __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
                - __import__('datetime').timedelta(days=older_than_days)
            ).isoformat()
            rows = self._ctx.conn.execute(
                "SELECT id FROM nodes WHERE is_deprecated=1"
                " AND COALESCE(deprecated_at, updated_at) < ?",
                (cutoff,)
            ).fetchall()
            count = 0
            for r in rows:
                if self.delete_node(r[0]):
                    count += 1
            return count
        except Exception:
            return 0

    def all_nodes(self, node_type=None, limit: int = 500) -> list:
        if node_type:
            rows = self._ctx.conn.execute(
                "SELECT * FROM nodes WHERE type=? ORDER BY confidence DESC LIMIT ?",
                (node_type, limit)
            ).fetchall()
        else:
            rows = self._ctx.conn.execute(
                "SELECT * FROM nodes ORDER BY confidence DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
