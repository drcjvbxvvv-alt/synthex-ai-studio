"""
Admin/query tools: brain_status, impact_analysis, temporal_query.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def register(mcp: Any, srv: Any, helpers: dict) -> None:
    """Register admin/query MCP tools."""

    _safe_str = helpers["_safe_str"]
    work_path = helpers["work_path"]
    brain = helpers["brain"]

    # ── Tool: brain_status ─────────────────────────────────────────

    @mcp.tool()
    def brain_status(workdir: str = "") -> str:
        """
        查看 Project Brain 知識庫的目前狀態。

        Returns:
            統計摘要字串(節點數、邊數、最近新增的知識)。
        """
        srv.rate_check()
        b = srv.resolve_brain(workdir)
        try:
            return b.status()
        except Exception as e:
            logger.error("brain_status 內部錯誤：%s", e)
            return "狀態查詢失敗"

    # ── Tool: impact_analysis ──────────────────────────────────────

    @mcp.tool()
    def impact_analysis(component: str) -> dict:
        """
        分析修改某個組件可能影響的範圍。

        Args:
            component: 組件名稱(例如 "PaymentService")

        Returns:
            包含直接依賴、間接依賴、相關踩坑、業務規則的分析結果。
        """
        srv.rate_check()
        comp = _safe_str(component, 200, "component")

        try:
            return brain.graph.impact_analysis(comp)
        except Exception as e:
            logger.error("impact_analysis 內部錯誤：%s", e)
            return {"error": "分析失敗，請確認組件名稱"}

    # ── Tool: temporal_query ───────────────────────────────────────

    @mcp.tool()
    def temporal_query(
        at_time: str = "",
        git_branch: str = "HEAD",
        limit: int = 20,
    ) -> str:
        """
        Time-machine read — query the knowledge graph at a specific point in time.

        Use this when working on old versions or legacy branches to avoid
        getting rules that didn't exist at that time.

        Args:
            at_time:    ISO timestamp (e.g. "2024-06-01T00:00:00").
                        Empty = current time.
            git_branch: Git branch name for context (e.g. "v1-legacy").
                        Used to resolve approximate timestamp if at_time is empty.
            limit:      Max results (default 20).

        Returns:
            JSON with temporal edges valid at the requested time.
        """
        import re as _re
        import subprocess

        srv.rate_check()

        wd = os.environ.get("BRAIN_WORKDIR", str(work_path))
        db_path = Path(wd) / ".brain" / "brain.db"
        if not db_path.exists():
            return json.dumps({"error": "Brain not initialized", "edges": []})

        # BUG-A05: validate git_branch format
        if git_branch and git_branch != "HEAD":
            if not _re.match(r'^[a-zA-Z0-9._\-/]+$', git_branch):
                return json.dumps({"error": "git_branch 格式無效", "edges": []})

        try:
            db = srv.resolve_brain(wd).db

            resolved_time = at_time.strip() or None
            if not resolved_time and git_branch and git_branch != "HEAD":
                try:
                    r = subprocess.run(
                        ["git", "log", "-1", "--format=%aI", git_branch],
                        capture_output=True, text=True, cwd=wd, timeout=5
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        resolved_time = r.stdout.strip()
                except Exception as _e:
                    logger.debug("git log date resolution failed in temporal_query", exc_info=True)

            edges = db.temporal_query(at_time=resolved_time, limit=limit)
            nodes = db.nodes_at_time(
                resolved_time or datetime.now(timezone.utc).isoformat(),
                limit=limit,
            )
            return json.dumps({
                "at_time": resolved_time or "current",
                "git_branch": git_branch,
                "edge_count": len(edges),
                "node_count": len(nodes),
                "edges": edges,
                "nodes": [
                    {"id": n["id"], "type": n["type"], "title": n["title"],
                     "confidence": n["confidence"], "valid_from": n.get("valid_from")}
                    for n in nodes
                ],
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e), "edges": []})

    # ── Resource: graph mermaid ─────────────────────────────────────

    @mcp.resource("brain://graph/mermaid")
    def graph_mermaid() -> str:
        """以 Mermaid 格式回傳知識圖譜(可直接在 Claude Code 渲染)"""
        try:
            return brain.export_mermaid(limit=30)
        except Exception as e:
            logger.error("graph_mermaid 內部錯誤：%s", e)
            return "graph TD\n    Error[\"圖譜載入失敗\"]"
