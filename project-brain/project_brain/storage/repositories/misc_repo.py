"""
project_brain/storage/repositories/misc_repo.py — Miscellaneous operations

API key management, federation imports, edges, episodes, temporal edges,
events, confidence propagation, and episode pruning.

All writes go through WriteContext.execute_write() for lock + commit safety.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from project_brain.storage.write_context import WriteContext

logger = logging.getLogger(__name__)


class MiscRepo:
    """API keys, federation, edges, episodes, temporal, events, pruning."""

    def __init__(self, ctx: "WriteContext"):
        self._ctx = ctx

    # ── API Key management ───────────────────────────────────────

    def store_api_key(self, token: str, role: str = "reader",
                      name: str = "") -> int:
        """Store a hashed API key for RBAC. Returns the key row ID."""
        from project_brain.rbac import VALID_ROLES
        if role not in VALID_ROLES:
            raise ValueError(f"Invalid role {role!r}; must be one of {sorted(VALID_ROLES)}")
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        cur = self._ctx.execute_write(
            "INSERT INTO api_keys (key_hash, role, name) VALUES (?, ?, ?)",
            (key_hash, role, name),
        )
        return cur.lastrowid

    def resolve_api_key(self, token: str) -> Optional[dict]:
        """Resolve a Bearer token to its role metadata, or None."""
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        row = self._ctx.conn.execute(
            "SELECT id, role, name, expires_at, is_revoked FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
        if not row:
            return None
        row = dict(row)
        if row["is_revoked"]:
            return None
        if row["expires_at"]:
            try:
                exp = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > exp:
                    return None
            except Exception:
                pass
        return {"role": row["role"], "name": row["name"], "key_id": row["id"]}

    def revoke_api_key(self, key_id: int) -> bool:
        """Revoke an API key by ID. Returns True if the key was found."""
        cur = self._ctx.execute_write(
            "UPDATE api_keys SET is_revoked = 1 WHERE id = ? AND is_revoked = 0",
            (key_id,),
        )
        return cur.rowcount > 0

    def list_api_keys(self) -> list[dict]:
        """List all API keys (without hashes). For admin dashboard."""
        rows = self._ctx.conn.execute(
            "SELECT id, role, name, created_at, expires_at, is_revoked FROM api_keys"
            " ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Federation audit log ─────────────────────────────────────

    def record_federation_import(self, source: str, node_id: str,
                                  node_title: str, status: str = 'pending') -> int:
        """FED-01: Record a federation import event."""
        try:
            cur = self._ctx.execute_write(
                "INSERT INTO federation_imports(source, node_id, node_title, status) VALUES(?,?,?,?)",
                (source, node_id, node_title, status)
            )
            return cur.lastrowid or 0
        except Exception as e:
            logger.warning("record_federation_import failed: %s", e)
            return 0

    def get_federation_imports(self, limit: int = 50, source: str = '') -> list:
        """FED-01: List federation import records."""
        try:
            if source:
                rows = self._ctx.conn.execute(
                    "SELECT * FROM federation_imports WHERE source=? ORDER BY imported_at DESC LIMIT ?",
                    (source, limit)
                ).fetchall()
            else:
                rows = self._ctx.conn.execute(
                    "SELECT * FROM federation_imports ORDER BY imported_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("get_federation_imports failed: %s", e)
            return []

    # ── Edges ────────────────────────────────────────────────────

    def add_edge(self, source_id: str, relation: str, target_id: str,
                 note: str = "") -> int:
        cur = self._ctx.execute_write(
            "INSERT OR IGNORE INTO edges(source_id,relation,target_id,note) VALUES(?,?,?,?)",
            (source_id, relation, target_id, note)
        )
        return cur.lastrowid or 0

    # ── Confidence propagation ───────────────────────────────────

    def propagate_confidence(self, node_id: str, dampening: float = 0.5,
                             max_hops: int = 3,
                             get_node_fn=None) -> dict[str, float]:
        """DEEP-02: BFS Bayesian confidence propagation."""
        if not get_node_fn:
            return {}
        root = get_node_fn(node_id)
        if not root:
            return {}
        visited: dict[str, float] = {}
        queue: list[tuple[str, float, int]] = [
            (node_id, float(root.get("confidence", 0.8)), 0)
        ]
        while queue:
            nid, upstream_conf, depth = queue.pop(0)
            if nid in visited or depth > max_hops:
                continue
            node = get_node_fn(nid)
            if not node:
                continue
            base      = float(node.get("confidence", 0.8))
            effective = base * (1 - dampening * (1 - upstream_conf))
            effective = round(max(0.05, min(1.0, effective)), 4)
            visited[nid] = effective
            try:
                rows = self._ctx.conn.execute(
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

    # ── Episode linking ──────────────────────────────────────────

    def link_episode_to_nodes(self, episode_id: str,
                              episode_content: str,
                              threshold: float = 0.80,
                              search_nodes_fn=None,
                              search_nodes_by_vector_fn=None,
                              add_temporal_edge_fn=None) -> int:
        """Phase 4: Auto-link L2 episode to semantically similar L3 nodes."""
        linked = 0
        try:
            from project_brain.embedder import get_embedder
            _emb = get_embedder()
            if _emb:
                ep_vec = _emb.embed(episode_content[:1000])
                if ep_vec and search_nodes_by_vector_fn and add_temporal_edge_fn:
                    similar = search_nodes_by_vector_fn(
                        ep_vec, threshold=threshold, limit=3
                    )
                    for node in similar:
                        add_temporal_edge_fn(
                            episode_id, 'DERIVES_FROM', node['id'],
                            content='auto-linked (vector similarity)'
                        )
                        linked += 1
                    return linked
        except Exception as _e:
            logger.error("link_episode strategy A failed: %s", _e)

        try:
            if search_nodes_fn and add_temporal_edge_fn:
                results = search_nodes_fn(episode_content[:200], limit=3)
                ep_words = set(episode_content.lower().split())
                for node in results:
                    node_words = set((node['title'] + ' ' + node['content']).lower().split())
                    overlap = len(ep_words & node_words) / max(len(node_words), 1)
                    if overlap >= 0.35:
                        add_temporal_edge_fn(
                            episode_id, 'DERIVES_FROM', node['id'],
                            content=f'auto-linked (fts overlap={overlap:.2f})'
                        )
                        linked += 1
        except Exception as _e:
            logger.error("link_episode strategy B failed: %s", _e)
        return linked

    def get_episode_links(self, episode_id: str) -> list:
        """Phase 4: Get L3 nodes linked to an episode via DERIVES_FROM."""
        try:
            rows = self._ctx.conn.execute("""
                SELECT n.* FROM temporal_edges te
                JOIN nodes n ON te.target_id = n.id
                WHERE te.source_id = ? AND te.relation = 'DERIVES_FROM'
            """, (episode_id,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ── Episodes ─────────────────────────────────────────────────

    def add_episode(self, content: str, source: str = "",
                    ref_time=None, confidence: float = 0.5) -> str:
        seed = source if source else f"{content}{source}"
        eid  = "ep-" + hashlib.md5(seed.encode()).hexdigest()[:16]
        ts   = ref_time or datetime.now(timezone.utc).isoformat()
        with self._ctx.write_guard():
            self._ctx.conn.execute(
                "INSERT OR IGNORE INTO episodes(id,content,source,ref_time,confidence) VALUES(?,?,?,?,?)",
                (eid, content, source, ts, confidence)
            )
            self._ctx.conn.commit()
        return eid

    def recent_episodes(self, limit: int = 10) -> list:
        rows = self._ctx.conn.execute(
            "SELECT * FROM episodes ORDER BY ref_time DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def search_episodes(self, query: str, limit: int = 5) -> list:
        rows = self._ctx.conn.execute(
            "SELECT * FROM episodes WHERE content LIKE ? ORDER BY ref_time DESC LIMIT ?",
            (f"%{query}%", limit)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Temporal edges ───────────────────────────────────────────

    def add_temporal_edge(self, source_id: str, relation: str, target_id: str,
                          content: str = "", valid_from=None) -> int:
        ts = valid_from or datetime.now(timezone.utc).isoformat()
        with self._ctx.write_guard():
            try:
                self._ctx.conn.execute("""
                    UPDATE temporal_edges SET valid_until=?
                    WHERE source_id=? AND relation=? AND valid_until IS NULL
                """, (ts, source_id, relation))
                cur = self._ctx.conn.execute(
                    "INSERT INTO temporal_edges(source_id,relation,target_id,content,valid_from)"
                    " VALUES(?,?,?,?,?)",
                    (source_id, relation, target_id, content, ts)
                )
                self._ctx.conn.commit()
                return cur.lastrowid or 0
            except Exception:
                try:
                    self._ctx.conn.rollback()
                except Exception as _rb_err:
                    logger.error("add_temporal_edge: rollback failed: %s", _rb_err)
                raise

    def temporal_query(self, at_time=None, limit: int = 20) -> list:
        at   = at_time or datetime.now(timezone.utc).isoformat()
        rows = self._ctx.conn.execute("""
            SELECT * FROM temporal_edges
            WHERE valid_from<=? AND (valid_until IS NULL OR valid_until>?)
            ORDER BY valid_from DESC LIMIT ?
        """, (at, at, limit)).fetchall()
        return [dict(r) for r in rows]

    def nodes_at_time(self, at_time: str, limit: int = 50,
                      node_type: str = "") -> list[dict]:
        """FEAT-03: Return nodes that were valid at the given ISO timestamp."""
        at     = at_time or datetime.now(timezone.utc).isoformat()
        params: list = [at, at]
        type_clause = ""
        if node_type:
            type_clause = "AND type=?"
            params.append(node_type)
        params.append(limit)
        rows = self._ctx.conn.execute(f"""
            SELECT id, type, title, content, confidence,
                   valid_from, valid_until, created_at
            FROM nodes
            WHERE (valid_from IS NULL OR valid_from <= ?)
              AND (valid_until IS NULL OR valid_until > ?)
              AND is_deprecated = 0
              {type_clause}
            ORDER BY confidence DESC
            LIMIT ?
        """, params).fetchall()
        return [dict(r) for r in rows]

    # ── Events ───────────────────────────────────────────────────

    def emit(self, event_type: str, payload: dict) -> None:
        self._ctx.execute_write(
            "INSERT INTO events(event_type,payload) VALUES(?,?)",
            (event_type, json.dumps(payload, ensure_ascii=False))
        )

    def recent_events(self, event_type=None, limit: int = 20) -> list:
        if event_type:
            rows = self._ctx.conn.execute(
                "SELECT * FROM events WHERE event_type=? ORDER BY created_at DESC LIMIT ?",
                (event_type, limit)
            ).fetchall()
        else:
            rows = self._ctx.conn.execute(
                "SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Episode pruning ──────────────────────────────────────────

    def prune_episodes(self, older_than_days: int = 365) -> int:
        """Clean up episodes older than specified days."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=older_than_days)
        ).isoformat()
        result = self._ctx.execute_write(
            "DELETE FROM episodes WHERE created_at < ?", (cutoff,)
        )
        deleted = result.rowcount
        if deleted:
            logger.debug("prune_episodes: deleted %d episodes older than %d days",
                         deleted, older_than_days)
        return deleted
