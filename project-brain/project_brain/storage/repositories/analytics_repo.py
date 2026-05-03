"""
project_brain/storage/repositories/analytics_repo.py — Analytics, health & export

Stats, health report, optimization, pipeline stats, usage analytics,
and import/export operations (JSON, Markdown, Neo4j Cypher, GraphML).

All writes go through WriteContext.execute_write() for lock + commit safety.
"""
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from project_brain.storage.write_context import WriteContext

logger = logging.getLogger(__name__)


class AnalyticsRepo:
    """Analytics, health reporting, optimization, and import/export."""

    def __init__(self, ctx: "WriteContext"):
        self._ctx = ctx

    def stats(self) -> dict:
        rows  = self._ctx.conn.execute(
            "SELECT type,COUNT(*) c FROM nodes GROUP BY type"
        ).fetchall()
        total = self._ctx.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        eps   = self._ctx.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        sess  = self._ctx.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        return {"total": total, "by_type": {r["type"]: r["c"] for r in rows},
                "episodes": eps, "sessions": sess}

    def optimize(self) -> dict:
        """C-1/C-3: Reclaim disk space and rebuild search indexes."""
        db_path = self._ctx.brain_dir / "brain.db"
        size_before = db_path.stat().st_size if db_path.exists() else 0

        self._ctx.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._ctx.conn.execute("VACUUM")
        self._ctx.conn.execute("ANALYZE")
        logger.info("optimize: VACUUM + ANALYZE complete")

        try:
            self._ctx.execute_write(
                "INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')"
            )
            fts5_status = "rebuilt"
            logger.info("optimize: FTS5 rebuild complete")
        except Exception as e:
            fts5_status = f"rebuild_skipped: {e}"
            logger.warning("optimize: FTS5 rebuild failed: %s", e)

        try:
            self._ctx.conn.execute(
                "INSERT INTO nodes_fts(nodes_fts) VALUES('integrity-check')"
            )
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
        """FEAT-01: Summarise knowledge-base health as a structured dict."""
        now  = datetime.now(timezone.utc)
        rows = self._ctx.conn.execute("SELECT * FROM nodes").fetchall()
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
                except Exception as _e:
                    logger.error("valid_until date parse failed: %s", _e)
            if not n.get("is_pinned"):
                created = n.get("created_at", "")
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if (now - dt).days > 90 and float(n.get("confidence", 0.8)) < 0.5:
                        stale += 1
                except Exception as _e:
                    logger.error("created_at date parse failed: %s", _e)

        avg_conf    = round(sum(confs) / len(confs), 3) if confs else 0.0
        low_conf    = sum(1 for c in confs if c < 0.4)

        fts_count = vec_count = 0
        try:
            fts_count = self._ctx.conn.execute(
                "SELECT COUNT(*) FROM nodes_fts"
            ).fetchone()[0]
        except Exception as _e:
            logger.error("fts count query failed: %s", _e)
        try:
            vec_count = self._ctx.conn.execute(
                "SELECT COUNT(*) FROM node_vectors"
            ).fetchone()[0]
        except Exception as _e:
            logger.error("vector count query failed: %s", _e)

        episodes = self._ctx.conn.execute(
            "SELECT COUNT(*) FROM episodes"
        ).fetchone()[0]
        sessions = self._ctx.conn.execute(
            "SELECT COUNT(*) FROM sessions"
        ).fetchone()[0]
        thresh   = (now - timedelta(days=7)).isoformat()
        recent_7d = self._ctx.conn.execute(
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
        """0.0-1.0 composite health score (higher is healthier)."""
        if total == 0:
            return 0.5
        score  = avg_conf * 0.4
        score += (1 - stale / total) * 0.3
        score += min(fts_count / total, 1.0) * 0.2
        score += min(vec_count / total, 1.0) * 0.1
        return round(min(1.0, max(0.0, score)), 3)

    def get_pipeline_stats(self, days: int = 7) -> dict:
        """B-04: Aggregate pipeline statistics over a time window."""
        days = max(1, days)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

        result: dict = {
            "days": days,
            "signals": {"total": 0, "by_status": {}, "by_kind": {}},
            "pipeline": {
                "processed": 0,
                "by_action": {},
                "by_model": {},
                "feedback": {"useful": 0, "not_useful": 0, "no_feedback": 0},
            },
            "queue_depth": 0,
        }

        tables = set()
        try:
            tables = {
                r[0] for r in self._ctx.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        except Exception:
            return result

        if "signal_queue" in tables:
            try:
                result["signals"]["total"] = self._ctx.conn.execute(
                    "SELECT COUNT(*) FROM signal_queue WHERE created_at >= ?",
                    (cutoff,)
                ).fetchone()[0]

                for row in self._ctx.conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM signal_queue "
                    "WHERE created_at >= ? GROUP BY status",
                    (cutoff,)
                ).fetchall():
                    result["signals"]["by_status"][row[0]] = row[1]

                for row in self._ctx.conn.execute(
                    "SELECT kind, COUNT(*) as cnt FROM signal_queue "
                    "WHERE created_at >= ? GROUP BY kind",
                    (cutoff,)
                ).fetchall():
                    result["signals"]["by_kind"][row[0]] = row[1]

                result["queue_depth"] = self._ctx.conn.execute(
                    "SELECT COUNT(*) FROM signal_queue WHERE status='pending'"
                ).fetchone()[0]
            except Exception as _e:
                logger.debug("B-04: signal_queue stats query failed: %s", _e)

        if "pipeline_metrics" in tables:
            try:
                result["pipeline"]["processed"] = self._ctx.conn.execute(
                    "SELECT COUNT(*) FROM pipeline_metrics WHERE created_at >= ?",
                    (cutoff,)
                ).fetchone()[0]

                for row in self._ctx.conn.execute(
                    "SELECT action, COUNT(*) as cnt FROM pipeline_metrics "
                    "WHERE created_at >= ? GROUP BY action",
                    (cutoff,)
                ).fetchall():
                    result["pipeline"]["by_action"][row[0]] = row[1]

                for row in self._ctx.conn.execute(
                    "SELECT llm_model, COUNT(*) as cnt FROM pipeline_metrics "
                    "WHERE created_at >= ? AND llm_model != '' GROUP BY llm_model",
                    (cutoff,)
                ).fetchall():
                    result["pipeline"]["by_model"][row[0]] = row[1]

                fb = result["pipeline"]["feedback"]
                fb["useful"] = self._ctx.conn.execute(
                    "SELECT COUNT(*) FROM pipeline_metrics "
                    "WHERE created_at >= ? AND was_useful = 1",
                    (cutoff,)
                ).fetchone()[0]
                fb["not_useful"] = self._ctx.conn.execute(
                    "SELECT COUNT(*) FROM pipeline_metrics "
                    "WHERE created_at >= ? AND was_useful = 0",
                    (cutoff,)
                ).fetchone()[0]
                fb["no_feedback"] = self._ctx.conn.execute(
                    "SELECT COUNT(*) FROM pipeline_metrics "
                    "WHERE created_at >= ? AND was_useful IS NULL",
                    (cutoff,)
                ).fetchone()[0]
            except Exception as _e:
                logger.debug("B-04: pipeline_metrics stats query failed: %s", _e)

        return result

    def usage_analytics(self) -> dict:
        """FEAT-03: Return usage analytics as a structured dict."""
        top_nodes = [dict(r) for r in self._ctx.conn.execute(
            "SELECT id, title, type, access_count, last_accessed FROM nodes"
            " WHERE access_count > 0 ORDER BY access_count DESC LIMIT 10"
        ).fetchall()]

        growth = [dict(r) for r in self._ctx.conn.execute(
            "SELECT strftime('%Y-%W', created_at) week, COUNT(*) count"
            " FROM nodes GROUP BY week ORDER BY week DESC LIMIT 12"
        ).fetchall()]

        by_type = {r["type"]: r["c"] for r in self._ctx.conn.execute(
            "SELECT type, COUNT(*) c FROM nodes GROUP BY type ORDER BY c DESC"
        ).fetchall()}

        by_scope = {r["scope"]: r["c"] for r in self._ctx.conn.execute(
            "SELECT scope, COUNT(*) c FROM nodes GROUP BY scope"
            " ORDER BY c DESC LIMIT 10"
        ).fetchall()}

        conf_by_type = {r["type"]: round(r["avg_conf"], 3) for r in self._ctx.conn.execute(
            "SELECT type, AVG(confidence) avg_conf FROM nodes GROUP BY type"
        ).fetchall()}

        recent_queries = [dict(r) for r in self._ctx.conn.execute(
            "SELECT query, latency_ms, created_at FROM traces"
            " ORDER BY created_at DESC LIMIT 10"
        ).fetchall()]

        ep_count = self._ctx.conn.execute(
            "SELECT COUNT(*) FROM episodes"
        ).fetchone()[0]

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

    # ── Export ────────────────────────────────────────────────────

    def export_json(self, node_type: str = None, scope: str = None) -> dict:
        """FEAT-05: Export knowledge nodes (and edges) to a JSON-serialisable dict."""
        if node_type:
            nodes = [dict(r) for r in self._ctx.conn.execute(
                "SELECT * FROM nodes WHERE type=? ORDER BY created_at", (node_type,)
            ).fetchall()]
        elif scope:
            nodes = [dict(r) for r in self._ctx.conn.execute(
                "SELECT * FROM nodes WHERE scope=? ORDER BY created_at", (scope,)
            ).fetchall()]
        else:
            nodes = [dict(r) for r in self._ctx.conn.execute(
                "SELECT * FROM nodes ORDER BY created_at"
            ).fetchall()]

        edges = [dict(r) for r in self._ctx.conn.execute(
            "SELECT * FROM edges"
        ).fetchall()]
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
        """FEAT-11: Export knowledge graph as Cypher statements for Neo4j."""
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

    def export_graphml(self, node_type: str = None, scope: str = None) -> str:
        """FEAT-05: Export knowledge graph as GraphML XML."""
        data = self.export_json(node_type=node_type, scope=scope)

        root = ET.Element("graphml", {
            "xmlns":              "http://graphml.graphdrawing.org/graphml",
            "xmlns:xsi":          "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:schemaLocation": (
                "http://graphml.graphdrawing.org/graphml "
                "http://graphml.graphdrawing.org/graphml/1.0/graphml.xsd"
            ),
        })

        _node_attrs = [
            ("title",      "string"),
            ("type",       "string"),
            ("content",    "string"),
            ("confidence", "double"),
            ("scope",      "string"),
            ("tags",       "string"),
            ("created_at", "string"),
        ]
        for attr_id, attr_type in _node_attrs:
            ET.SubElement(root, "key", {
                "id": attr_id, "for": "node",
                "attr.name": attr_id, "attr.type": attr_type,
            })

        ET.SubElement(root, "key", {
            "id": "relation", "for": "edge",
            "attr.name": "relation", "attr.type": "string",
        })
        ET.SubElement(root, "key", {
            "id": "weight", "for": "edge",
            "attr.name": "weight", "attr.type": "double",
        })

        graph_el = ET.SubElement(root, "graph", {
            "id": "brain", "edgedefault": "directed",
        })

        for n in data["nodes"]:
            node_el = ET.SubElement(graph_el, "node", {"id": n["id"]})
            for attr_id, _ in _node_attrs:
                val = n.get(attr_id)
                if val is None:
                    continue
                d = ET.SubElement(node_el, "data", {"key": attr_id})
                d.text = str(val)

        for i, e in enumerate(data.get("edges", [])):
            src = e.get("source_id", "")
            tgt = e.get("target_id", "")
            if not src or not tgt:
                continue
            edge_el = ET.SubElement(graph_el, "edge", {
                "id": e.get("id", f"e{i}"),
                "source": src,
                "target": tgt,
            })
            rel = ET.SubElement(edge_el, "data", {"key": "relation"})
            rel.text = e.get("relation", "RELATED")
            w = ET.SubElement(edge_el, "data", {"key": "weight"})
            w.text = str(e.get("weight", 1.0))

        ET.indent(root, space="  ")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
            root, encoding="unicode"
        )

    # ── Import ───────────────────────────────────────────────────

    def import_json(self, data: dict, overwrite: bool = False,
                    merge_strategy: str = "skip",
                    add_node_fn=None, get_node_fn=None,
                    add_edge_fn=None) -> dict:
        """FEAT-05/12: Import nodes and edges from an export_json() dict.

        Callers must pass add_node_fn, get_node_fn, add_edge_fn callbacks
        because these are BrainDB-level methods (not pure SQL).
        """
        result: dict = {"nodes": 0, "edges": 0, "skipped": 0, "errors": 0, "conflicts": []}

        for node in data.get("nodes", []):
            try:
                nid = node.get("id")
                if not nid:
                    result["errors"] += 1
                    continue
                existing = get_node_fn(nid) if get_node_fn else None
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
                meta = node.get("meta", {})
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                if add_node_fn:
                    add_node_fn(
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
                if add_edge_fn:
                    add_edge_fn(
                        source_id=edge["source_id"],
                        relation=edge["relation"],
                        target_id=edge["target_id"],
                        note=edge.get("note", ""),
                    )
                result["edges"] += 1
            except Exception:
                result["errors"] += 1

        return result

    @staticmethod
    def infer_scope(workdir: str, current_file: str = "") -> str:
        """ARCH-07: Canonical scope inference — single source of truth."""
        import re as _re
        import subprocess as _sp
        from pathlib import Path as _P

        try:
            _res = _sp.run(
                ["git", "remote", "get-url", "origin"],
                cwd=str(workdir), capture_output=True, text=True, timeout=3
            )
            if _res.returncode == 0:
                _url = _res.stdout.strip()
                _m = _re.search(r'[:/]([^/]+?)(?:\.git)?$', _url)
                if _m:
                    return _re.sub(r'[^a-z0-9_]', '_', _m.group(1).lower())
        except Exception:
            pass

        _skip = {"src", "test", "tests", "docs", "scripts", "build", "dist", "."}
        _svc  = ["service", "module", "pkg", "app", "api", "lib", "handler", "domain"]
        base  = _P(current_file) if current_file else _P(workdir)
        try:
            parts = list(base.relative_to(_P(workdir).resolve()).parts)
            for part in parts:
                pl = part.lower()
                if any(k in pl for k in _svc):
                    return _re.sub(r'[^a-z0-9_]', '_', pl)
            if parts and parts[0].lower() not in _skip:
                return _re.sub(r'[^a-z0-9_]', '_', parts[0].lower())
        except ValueError:
            pass

        if not current_file:
            _wd_name = _P(workdir).name.lower()
            if _wd_name and _wd_name not in _skip:
                return _re.sub(r'[^a-z0-9_]', '_', _wd_name)

        return 'global'
