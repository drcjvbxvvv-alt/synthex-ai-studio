"""
project_brain/vector_store.py — VectorStore (REF-01 extracted from BrainDB)

Manages node vector embeddings stored in the node_vectors table.
Extracted from brain_db.py to reduce God Object complexity.

Usage:
    from project_brain.vector_store import VectorStore
    vs = VectorStore(conn)  # conn = sqlite3.Connection
    vs.add_vector(node_id, vector)
"""
from __future__ import annotations
import logging
import math
import struct
from typing import Optional

logger = logging.getLogger(__name__)


class VectorStore:
    """Manages node vector embeddings stored in the node_vectors table."""

    def __init__(self, conn):
        self.conn = conn

    def add_vector(self, node_id: str, vector: list, model: str = 'nomic-embed-text') -> bool:
        """Store embedding vector for a node (Phase 1)."""
        try:
            blob = struct.pack(f'{len(vector)}f', *vector)
            self.conn.execute(
                "INSERT OR REPLACE INTO node_vectors(node_id,vector,dim,model) VALUES(?,?,?,?)",
                (node_id, blob, len(vector), model)
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.debug('add_vector failed: %s', e)
            return False

    @staticmethod
    def _cosine_similarity(a: list, b: list) -> float:
        """Pure-Python cosine similarity between two equal-length float lists."""
        dot   = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def search_by_vector(self, query_vector: list, threshold: float = 0.30,
                         limit: int = 10, node_type=None) -> list:
        """
        Semantic search via cosine similarity.

        Tries sqlite-vec C extension first (faster), then falls back to
        pure-Python cosine similarity (always works, zero extra deps).

        threshold: cosine *similarity* threshold (higher = more similar)
                   0.0 = orthogonal, 1.0 = identical
                   good practical values: 0.3 (loose) to 0.7 (tight)

        node_type: optional scope/type filter (maps to the 'scope' column)
        """
        if not query_vector:
            return []

        scope = node_type  # caller passes node_type; internally it's scope

        # ── Path A: sqlite-vec C extension ────────────────────────
        try:
            import sqlite_vec as sv
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
            logger.debug('vector search failed: %s', e)
            return []

    def get_nodes_without_vectors(self, limit: int = 100) -> list:
        """Return nodes that don't have embeddings yet (for batch indexing)."""
        rows = self.conn.execute("""
            SELECT n.id, n.title, n.content FROM nodes n
            LEFT JOIN node_vectors nv ON n.id = nv.node_id
            WHERE nv.node_id IS NULL
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
