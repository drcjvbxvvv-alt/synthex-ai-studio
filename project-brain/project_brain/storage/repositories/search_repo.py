"""
project_brain/storage/repositories/search_repo.py — Search & conflict detection

FTS5 search, hybrid search, vector search delegation, synonym expansion,
and conflict detection operations.

All writes go through WriteContext.execute_write() for lock + commit safety.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from project_brain.storage.write_context import WriteContext

from project_brain.synonyms import SYNONYM_MAP as _SYNONYM_MAP
from project_brain.core import constants as _constants

logger = logging.getLogger(__name__)


class SearchRepo:
    """Search, ranking, synonym expansion, and conflict detection."""

    def __init__(self, ctx: "WriteContext"):
        self._ctx = ctx

    # ── Static helpers ───────────────────────────────────────────

    @staticmethod
    def _ngram(text: str) -> str:
        """OPT-07: delegates to shared utils.ngram_cjk()."""
        from project_brain.utils import ngram_cjk
        return ngram_cjk(text)

    @staticmethod
    def _sanitize_fts(q: str) -> str:
        """OPT-08: Strip FTS5 special characters to prevent syntax errors."""
        sanitized = re.sub(r'["()*\-^]', ' ', q)
        sanitized = re.sub(r'\s+', ' ', sanitized).strip()
        return sanitized or '""'

    @staticmethod
    def _effective_confidence(node: dict) -> float:
        """DEF-05/OPT-04 fix: decay-adjusted confidence for search result ranking."""
        base = float(node.get("confidence", 0.8))
        if node.get("is_pinned"):
            return base
        try:
            meta = node.get("meta") or {}
            if isinstance(meta, str):
                meta = json.loads(meta) or {}
            if meta.get("decayed_at"):
                access = int(node.get("access_count") or 0)
                f7     = min(0.15, access / 10 * 0.05)
                return max(0.05, min(1.0, base + f7))
        except Exception:
            pass
        created = node.get("created_at", "") or ""
        if not created:
            return base
        try:
            updated  = node.get("updated_at") or ""
            ref_time = updated if updated > created else created
            ref_dt = datetime.fromisoformat(ref_time.replace("Z", "+00:00"))
            if ref_dt.tzinfo is None:
                ref_dt = ref_dt.replace(tzinfo=timezone.utc)
            days   = max(0, (datetime.now(timezone.utc) - ref_dt).days)
            decay  = math.exp(-_constants.BASE_DECAY_RATE * days)
            access = int(node.get("access_count") or 0)
            f7     = min(0.15, access / 10 * 0.05)
            return max(0.05, min(1.0, base * decay + f7))
        except Exception as _e:
            logger.error("decay score calculation failed: %s", _e)
            return base

    @staticmethod
    def _cosine_similarity(a: list, b: list) -> float:
        """REF-01: delegated to VectorStore (static)"""
        from project_brain.vector_store import VectorStore
        return VectorStore._cosine_similarity(a, b)

    # ── Config ───────────────────────────────────────────────────

    def _load_search_config(self) -> dict:
        """OPT-05: Load hybrid search weight overrides from .brain/config.json."""
        try:
            cfg_path = self._ctx.brain_dir / "config.json"
            if cfg_path.exists():
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                return data.get("search", {})
        except Exception:
            pass
        return {}

    def _adaptive_weights(self, query: str) -> tuple:
        """OPT-02+OPT-05: Compute adaptive (fts_weight, vec_weight) based on query."""
        import os as _os
        _env_fts = _os.environ.get("BRAIN_FTS_WEIGHT")
        _env_vec = _os.environ.get("BRAIN_VEC_WEIGHT")
        if _env_fts or _env_vec:
            try:
                fw = float(_env_fts) if _env_fts else None
                vw = float(_env_vec) if _env_vec else None
                if fw is not None and vw is None:
                    vw = 1.0 - fw
                elif vw is not None and fw is None:
                    fw = 1.0 - vw
                total = fw + vw
                if total > 0:
                    return (fw / total, vw / total)
            except (ValueError, TypeError):
                pass

        scfg = self._load_search_config()
        if "fts_weight" in scfg or "vec_weight" in scfg:
            try:
                fw = float(scfg.get("fts_weight", 0.4))
                vw = float(scfg.get("vec_weight", 0.6))
                total = fw + vw
                if total > 0:
                    return (fw / total, vw / total)
            except (ValueError, TypeError):
                pass

        tokens = re.findall(r"[a-zA-Z0-9_]{2,}", query)
        cjk    = re.findall(r"[\u4e00-\u9fff]", query)
        n_terms = len(tokens) + len(cjk) // 2
        cjk_ratio = len(cjk) / max(len(query.replace(" ", "")), 1)

        if n_terms <= 2 or cjk_ratio > 0.5:
            return (0.6, 0.4)
        if n_terms >= 5:
            return (0.25, 0.75)
        return (0.4, 0.6)

    # ── Term expansion ───────────────────────────────────────────

    def _expand_terms(self, query: str) -> list:
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
        """OPT-06: Batch write _SYNONYM_MAP into synonym_index table."""
        rows = []
        for term, synonyms in _SYNONYM_MAP.items():
            for syn in synonyms:
                rows.append((term, syn))
        with self._ctx.write_guard():
            self._ctx.conn.executemany(
                "INSERT OR IGNORE INTO synonym_index(term, synonym) VALUES(?,?)", rows
            )
            self._ctx.conn.commit()
        return len(rows)

    def expand_query(self, query: str) -> list:
        """OPT-06: O(1) synonym lookup from pre-computed synonym_index table."""
        raw = re.findall(r"[a-zA-Z0-9_]+", query.lower())
        result, seen = [], set()
        def _add(w):
            w = re.sub(r"[^\w\u4e00-\u9fff]", "", w)
            if w and w not in seen:
                seen.add(w); result.append(w)
        for w in raw:
            _add(w)
            try:
                rows = self._ctx.conn.execute(
                    "SELECT synonym FROM synonym_index WHERE term=?", (w,)
                ).fetchall()
                for r in rows:
                    _add(r[0])
            except Exception:
                for syn in _SYNONYM_MAP.get(w, []):
                    _add(syn)
        return result[:25]

    # ── Main search ──────────────────────────────────────────────

    def search_nodes(self, query: str, node_type=None, limit: int = 8,
                     scope: str = None) -> list:
        _t0 = time.monotonic()
        if scope is not None and not re.match(r'^[a-z0-9_-]+$', scope):
            scope = None
        terms = self._expand_terms(query)
        if not terms:
            return []
        _all_tokens: list[str] = []
        for _t in terms:
            _ngram_tokens = SearchRepo._ngram(_t).split()
            _all_tokens.extend(_ngram_tokens if _ngram_tokens else [_t])
        _seen_set: set = set()
        _unique: list[str] = []
        for _tok in _all_tokens:
            if _tok not in _seen_set:
                _unique.append(_tok)
                _seen_set.add(_tok)
        _safe_unique = [SearchRepo._sanitize_fts(tok) for tok in _unique
                        if SearchRepo._sanitize_fts(tok) != '""']
        fts_q = " OR ".join(f'"{tok}"' for tok in _safe_unique) if _safe_unique else '""'
        try:
            if scope and scope != "global":
                sf  = "AND (n.scope=? OR n.scope='global')"
                sp  = [scope]
            else:
                sf, sp = "", []
            _s = scope or "global"
            sort_clause = ("CASE WHEN n.scope=? THEN 0 ELSE 1 END, "
                           "n.is_pinned DESC, n.confidence DESC")
            if node_type:
                rows = self._ctx.conn.execute(
                    f"SELECT n.* FROM nodes_fts f JOIN nodes n ON f.id=n.id"
                    f" WHERE nodes_fts MATCH ? AND n.type=? {sf}"
                    f" ORDER BY {sort_clause} LIMIT ?",
                    (fts_q, node_type, *sp, _s, limit)).fetchall()
            else:
                rows = self._ctx.conn.execute(
                    f"SELECT n.* FROM nodes_fts f JOIN nodes n ON f.id=n.id"
                    f" WHERE nodes_fts MATCH ? {sf}"
                    f" ORDER BY {sort_clause} LIMIT ?",
                    (fts_q, *sp, _s, limit)).fetchall()
            results = [dict(r) for r in rows]

            _total_docs = self._ctx.conn.execute(
                "SELECT COUNT(*) FROM nodes"
            ).fetchone()[0] or 1
            _idf: dict[str, float] = {}
            for tok in _safe_unique:
                try:
                    df = self._ctx.conn.execute(
                        "SELECT COUNT(*) FROM nodes_fts WHERE nodes_fts MATCH ?",
                        (f'"{tok}"',),
                    ).fetchone()[0]
                    _idf[tok] = math.log((_total_docs + 1) / (df + 1)) + 1.0
                except Exception:
                    _idf[tok] = 1.0

            for r in results:
                r["effective_confidence"] = self._effective_confidence(r)
                r_title = (r.get("title") or "").lower()
                r_content = (r.get("content") or "").lower()
                r_text = r_title + " " + r_content
                idf_score = 0.0
                for tok in _safe_unique:
                    if tok.strip('"').lower() in r_text:
                        idf_score += _idf.get(tok, 1.0)
                max_idf = sum(_idf.values()) or 1.0
                idf_norm = idf_score / max_idf

                r["_search_score"] = (
                    idf_norm * 0.6
                    + float(r["effective_confidence"]) * 0.4
                )

            results.sort(
                key=lambda x: (x.get("is_pinned", 0), x.get("_search_score", 0)),
                reverse=True,
            )

            if len(results) > 1:
                reranked = [results[0]]
                for candidate in results[1:]:
                    c_words = set((candidate.get("title") or "").lower().split())
                    penalty = 1.0
                    for selected in reranked:
                        s_words = set((selected.get("title") or "").lower().split())
                        union = c_words | s_words
                        if union:
                            overlap = len(c_words & s_words) / len(union)
                            if overlap > 0.5:
                                penalty = min(penalty, 1.0 - overlap)
                    candidate["_search_score"] = candidate.get("_search_score", 0) * penalty
                    reranked.append(candidate)
                reranked.sort(
                    key=lambda x: (x.get("is_pinned", 0), x.get("_search_score", 0)),
                    reverse=True,
                )
                results = reranked

            if self._ctx.should_trace():
                try:
                    _ms = (time.monotonic() - _t0) * 1000
                    self._ctx.execute_write(
                        "INSERT INTO traces(query, result_count, latency_ms) VALUES(?,?,?)",
                        (query[:500], len(results), round(_ms, 2)),
                    )
                except Exception as _e:
                    logger.error("trace insert failed in search_nodes: %s", _e)
            return results
        except Exception as _e:
            logger.error("search_nodes failed: %s", _e)
            return []

    # ── Hybrid search ────────────────────────────────────────────

    def hybrid_search(self, query: str, query_vector: list = None,
                      scope: str = None, limit: int = 8,
                      min_score: float = None) -> list:
        """Phase 1+OPT-02: Hybrid search with adaptive FTS5/vector weights."""
        fts_results = self.search_nodes(query, scope=scope, limit=limit)
        if not query_vector:
            return fts_results

        fts_w, vec_w = self._adaptive_weights(query)

        vec_results = self.search_nodes_by_vector(
            query_vector, threshold=0.8, limit=limit, scope=scope
        )

        scored: dict = {}
        for i, n in enumerate(fts_results):
            nid = n['id']
            fts_score = (limit - i) / limit
            scored[nid] = (n, fts_score * fts_w)
        for i, n in enumerate(vec_results):
            nid = n['id']
            vec_score = (1.0 - n.get('dist', 0.5))
            if nid in scored:
                scored[nid] = (scored[nid][0], scored[nid][1] + vec_score * vec_w)
            else:
                scored[nid] = (n, vec_score * vec_w)

        merged = sorted(scored.values(), key=lambda x: x[1], reverse=True)

        if min_score is not None:
            merged = [(n, s) for n, s in merged if s >= min_score]

        return [n for n, _ in merged[:limit]]

    # ── Vector search delegation ─────────────────────────────────

    def search_nodes_by_vector(self, query_vector: list, threshold: float = 0.30,
                               limit: int = 8, scope: str = None) -> list:
        """REF-01: delegated to VectorStore"""
        from project_brain.vector_store import VectorStore
        vs = VectorStore(self._ctx.conn)
        return vs.search_by_vector(query_vector, threshold, limit, scope)

    def add_vector(self, node_id: str, vector: list,
                   model: str = 'nomic-embed-text') -> bool:
        """REF-01: delegated to VectorStore"""
        from project_brain.vector_store import VectorStore
        vs = VectorStore(self._ctx.conn)
        return vs.add_vector(node_id, vector, model)

    def get_nodes_without_vectors(self, limit: int = 100) -> list:
        """REF-01: delegated to VectorStore"""
        from project_brain.vector_store import VectorStore
        vs = VectorStore(self._ctx.conn)
        return vs.get_nodes_without_vectors(limit)

    # ── Conflict detection ───────────────────────────────────────

    def _find_conflict_candidates(self, title: str, limit: int = 10) -> list:
        """HIGH-03 helper: FTS5 n-gram match to find top-K candidate node ids."""
        if not title:
            return []
        try:
            ngram_tokens = SearchRepo._ngram(title).split()
            if not ngram_tokens:
                return []
            seen_tok: set = set()
            unique_tokens: list[str] = []
            for tok in ngram_tokens:
                if tok and tok not in seen_tok:
                    unique_tokens.append(tok)
                    seen_tok.add(tok)
            safe = [SearchRepo._sanitize_fts(t) for t in unique_tokens]
            safe = [t for t in safe if t and t != '""']
            if not safe:
                return []
            fts_q = " OR ".join(f'"{t}"' for t in safe)
            rows = self._ctx.conn.execute(
                "SELECT id FROM nodes_fts WHERE nodes_fts MATCH ? LIMIT ?",
                (fts_q, limit),
            ).fetchall()
            return [r["id"] for r in rows]
        except Exception as _e:
            logger.debug("_find_conflict_candidates failed for title=%.40s: %s",
                         title, _e)
            return []

    def find_conflicts(self, similarity_threshold: float = 0.7,
                       candidates_per_anchor: int = 10) -> list:
        """FEAT-02 + HIGH-03: Detect potentially conflicting or duplicate knowledge."""
        all_nodes = {
            r["id"]: dict(r)
            for r in self._ctx.conn.execute(
                "SELECT id, type, title, content FROM nodes"
            ).fetchall()
        }
        if not all_nodes:
            return []

        conflicts: list[dict] = []
        seen: set = set()
        _contra = [
            ("must", "must not"), ("should", "should not"),
            ("use", "do not use"), ("enable", "disable"),
            ("allow", "deny"), ("required", "forbidden"),
            ("需要", "不需要"), ("必須", "禁止"),
        ]

        for anchor_id, anchor in all_nodes.items():
            a_title = anchor.get("title") or ""
            if not a_title:
                continue
            a_words = set(a_title.lower().split())
            if not a_words:
                a_words = {a_title.lower()}

            candidate_ids = self._find_conflict_candidates(
                a_title, limit=candidates_per_anchor,
            )

            for cand_id in candidate_ids:
                if cand_id == anchor_id:
                    continue
                pair_key = (
                    anchor_id if anchor_id < cand_id else cand_id,
                    cand_id   if anchor_id < cand_id else anchor_id,
                )
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                b = all_nodes.get(cand_id)
                if not b:
                    continue
                b_title = b.get("title") or ""
                b_words = set(b_title.lower().split())
                if not b_words:
                    b_words = {b_title.lower()} if b_title else set()
                if not b_words:
                    continue

                union = a_words | b_words
                if not union:
                    continue
                overlap = len(a_words & b_words) / len(union)
                if overlap < similarity_threshold:
                    continue

                a_text = (a_title + " " + (anchor.get("content") or "")).lower()
                b_text = (b_title + " " + (b.get("content") or "")).lower()
                is_contra = any(
                    (ka in a_text and kb in b_text) or (kb in a_text and ka in b_text)
                    for ka, kb in _contra
                )
                ctype = "contradiction" if is_contra else "duplicate"
                conflicts.append({
                    "type":       ctype,
                    "node_a":     anchor_id,
                    "node_b":     cand_id,
                    "title_a":    a_title,
                    "title_b":    b_title,
                    "similarity": round(overlap, 3),
                    "reason":     (
                        f"相似標題（{overlap:.0%} 重疊）且內容矛盾" if is_contra
                        else f"相似標題（{overlap:.0%} 重疊），可能重複"
                    ),
                })

        conflicts.sort(key=lambda x: (x["type"] != "contradiction", -x["similarity"]))
        return conflicts[:50]

    def find_conflicts_for_node(self, node_id: str,
                                similarity_threshold: float = 0.6,
                                candidates_per_anchor: int = 10) -> list:
        """Detect conflicts for a single node against the rest of the knowledge base."""
        row = self._ctx.conn.execute(
            "SELECT id, type, title, content FROM nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        if not row:
            return []

        anchor = dict(row)
        a_title = anchor.get("title") or ""
        if not a_title:
            return []

        a_words = set(a_title.lower().split())
        if not a_words:
            a_words = {a_title.lower()}

        candidate_ids = self._find_conflict_candidates(
            a_title, limit=candidates_per_anchor,
        )

        _contra = [
            ("must", "must not"), ("should", "should not"),
            ("use", "do not use"), ("enable", "disable"),
            ("allow", "deny"), ("required", "forbidden"),
            ("需要", "不需要"), ("必須", "禁止"),
        ]

        conflicts: list[dict] = []
        for cand_id in candidate_ids:
            if cand_id == node_id:
                continue
            cand_row = self._ctx.conn.execute(
                "SELECT id, type, title, content FROM nodes WHERE id = ?",
                (cand_id,),
            ).fetchone()
            if not cand_row:
                continue
            cand = dict(cand_row)
            b_title = cand.get("title") or ""
            b_words = set(b_title.lower().split())
            if not b_words:
                b_words = {b_title.lower()} if b_title else set()
            if not b_words:
                continue

            union = a_words | b_words
            if not union:
                continue
            overlap = len(a_words & b_words) / len(union)
            if overlap < similarity_threshold:
                continue

            a_text = (a_title + " " + (anchor.get("content") or "")).lower()
            b_text = (b_title + " " + (cand.get("content") or "")).lower()
            is_contra = any(
                (ka in a_text and kb in b_text) or (kb in a_text and ka in b_text)
                for ka, kb in _contra
            )
            ctype = "contradiction" if is_contra else "duplicate"
            conflicts.append({
                "type":       ctype,
                "node_a":     node_id,
                "node_b":     cand_id,
                "title_a":    a_title,
                "title_b":    b_title,
                "similarity": round(overlap, 3),
                "reason":     (
                    f"相似標題（{overlap:.0%} 重疊）且內容矛盾" if is_contra
                    else f"相似標題（{overlap:.0%} 重疊），可能重複"
                ),
            })

        conflicts.sort(key=lambda x: (x["type"] != "contradiction", -x["similarity"]))
        return conflicts
