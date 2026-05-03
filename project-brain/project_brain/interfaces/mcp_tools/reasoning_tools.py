"""
Reasoning tools: reasoning_chain.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def register(mcp: Any, srv: Any, helpers: dict) -> None:
    """Register reasoning-related MCP tools."""

    _safe_str = helpers["_safe_str"]
    MAX_QUERY_LEN = helpers["MAX_QUERY_LEN"]

    # ── Tool: reasoning_chain ──────────────────────────────────────

    @mcp.tool()
    def reasoning_chain(task: str, workdir: str = "") -> str:
        """DEEP-01: 從任務關鍵字出發,遍歷知識圖譜,產生推理鏈。

        Args:
            task: 當前任務描述
            workdir: 工作目錄(選填)

        Returns:
            Markdown 格式推理鏈,顯示相關節點與邊的關係。
        """
        srv.rate_check()
        t_clean = _safe_str(task, MAX_QUERY_LEN, "task")
        b = srv.resolve_brain(workdir)
        try:
            from project_brain.context import ContextEngineer
            ce = ContextEngineer(b.graph, b.brain_dir, brain_db=b.db)
            return ce.build_reasoning_chain(t_clean) or "（無相關推理鏈）"
        except Exception as e:
            logger.error("reasoning_chain error: %s", e)
            return ""
