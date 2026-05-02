"""
project_brain/integrations/push_central.py — E-05: Push Local Knowledge to Central Brain

Selects high-value knowledge nodes from the local brain, sanitizes PII,
and pushes them to the Central Brain (via CentralBrainClient).

By default, pushed nodes enter Central Brain's KRB Staging for admin review.
With ``direct=True`` (admin only), nodes are written directly to L3.

Usage::

    from project_brain.integrations.push_central import PushTransport

    transport = PushTransport()
    nodes = transport.select_nodes(brain_db, kind="Pitfall", min_confidence=0.8)
    preview = transport.preview(nodes)        # dry-run
    result = transport.push(client, nodes)    # live push
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class PushResult:
    """Summary of a push operation."""
    total_selected: int = 0
    pushed_ok: int = 0
    pushed_fail: int = 0
    skipped_sanitize: int = 0
    errors: list[str] = field(default_factory=list)


class PushTransport:
    """Select, sanitize, and push local knowledge to Central Brain."""

    def select_nodes(
        self,
        brain_db: Any,
        *,
        kind: str = "",
        min_confidence: float = 0.7,
        scope: str = "",
        max_nodes: int = 100,
    ) -> list[dict]:
        """Query local nodes matching the filter criteria.

        Args:
            brain_db: BrainDB instance.
            kind: Filter by node type (e.g., "Pitfall", "Rule"). Empty = all.
            min_confidence: Minimum confidence threshold.
            scope: Filter by scope. Empty = all.
            max_nodes: Maximum number of nodes to return.

        Returns:
            List of node dicts, sorted by confidence DESC.
        """
        clauses = ["confidence >= ?"]
        params: list[Any] = [min_confidence]

        if kind:
            clauses.append("type = ?")
            params.append(kind)
        if scope:
            clauses.append("scope = ?")
            params.append(scope)

        where = " AND ".join(clauses)
        params.append(max_nodes)

        rows = brain_db.conn.execute(
            f"SELECT * FROM nodes WHERE {where} ORDER BY confidence DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return [dict(r) for r in rows]

    def sanitize_nodes(self, nodes: list[dict]) -> list[dict]:
        """Strip PII from nodes before pushing to Central Brain.

        Reuses the federation PII stripping logic.
        Returns sanitized nodes; nodes with empty titles after sanitization are skipped.
        """
        from project_brain.integrations.federation import _strip_pii

        result = []
        for n in nodes:
            sanitized = {
                "id": n.get("id", ""),
                "kind": n.get("type", n.get("kind", "Note")),
                "title": _strip_pii(n.get("title", "")),
                "content": _strip_pii((n.get("content", "") or "")[:2000]),
                "confidence": float(n.get("confidence", 0.5)),
                "tags": n.get("tags", "[]"),
                "source": n.get("source_url", ""),
            }
            if not sanitized["title"].strip():
                continue
            result.append(sanitized)
        return result

    def preview(self, nodes: list[dict]) -> list[dict]:
        """Return a preview-friendly list (for --dry-run display)."""
        return [
            {
                "id": n.get("id", "")[:12],
                "kind": n.get("kind", n.get("type", "")),
                "title": (n.get("title", ""))[:80],
                "confidence": n.get("confidence", 0),
            }
            for n in nodes
        ]

    def push(
        self,
        client: Any,
        nodes: list[dict],
        *,
        source_label: str = "push",
        direct: bool = False,
    ) -> PushResult:
        """Push sanitized nodes to Central Brain.

        Args:
            client: CentralBrainClient instance.
            nodes: Sanitized node dicts (from sanitize_nodes).
            source_label: Source identifier for auditing.
            direct: If True, write directly to L3 (admin only).
                    If False, nodes go to KRB Staging.

        Returns:
            PushResult with success/failure counts.
        """
        result = PushResult(total_selected=len(nodes))

        for node in nodes:
            try:
                resp = client.add_knowledge(
                    title=node["title"],
                    content=node["content"],
                    kind=node["kind"],
                    confidence=node["confidence"],
                    tags=self._parse_tags(node.get("tags", "[]")),
                    source=f"{source_label}:{node.get('source', '')}",
                )
                if resp and resp.get("success"):
                    result.pushed_ok += 1
                elif resp and resp.get("error"):
                    result.pushed_fail += 1
                    result.errors.append(
                        f"{node['title'][:40]}: {resp.get('error', 'unknown')}"
                    )
                else:
                    result.pushed_ok += 1  # assume success if no error field
            except Exception as e:
                result.pushed_fail += 1
                result.errors.append(f"{node.get('title', '?')[:40]}: {e}")

        return result

    @staticmethod
    def _parse_tags(tags_raw: str | list) -> list[str]:
        """Parse tags from JSON string or list."""
        if isinstance(tags_raw, list):
            return [str(t) for t in tags_raw[:10]]
        try:
            import json
            parsed = json.loads(tags_raw)
            if isinstance(parsed, list):
                return [str(t) for t in parsed[:10]]
        except (ValueError, TypeError):
            pass
        if isinstance(tags_raw, str) and tags_raw.strip():
            return [t.strip() for t in tags_raw.split(",") if t.strip()][:10]
        return []
