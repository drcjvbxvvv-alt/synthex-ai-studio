"""
MCP Tools — Domain-separated tool modules for Project Brain MCP Server.

Each module exports a ``register(mcp, srv, helpers)`` function that registers
its tools onto the given FastMCP server instance.

Architecture:
  - mcp_server.py creates the FastMCP instance and BrainServer
  - Each tool module receives (mcp, srv, helpers) and registers @mcp.tool() handlers
  - helpers dict provides shared utilities (_safe_str, _check_permission, etc.)
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# All tool modules in registration order
TOOL_MODULES = [
    "project_brain.interfaces.mcp_tools.knowledge_tools",
    "project_brain.interfaces.mcp_tools.feedback_tools",
    "project_brain.interfaces.mcp_tools.admin_tools",
    "project_brain.interfaces.mcp_tools.pipeline_tools",
    "project_brain.interfaces.mcp_tools.federation_tools",
    "project_brain.interfaces.mcp_tools.reasoning_tools",
]


def register_all_tools(mcp: Any, srv: Any, helpers: dict) -> None:
    """Import and register all tool modules onto the MCP server.

    Args:
        mcp:     FastMCP server instance
        srv:     BrainServer instance (provides rate_check, resolve_brain, etc.)
        helpers: Dict of shared utilities (see mcp_server.py create_mcp_server)
    """
    for module_path in TOOL_MODULES:
        try:
            mod = importlib.import_module(module_path)
            mod.register(mcp, srv, helpers)
        except Exception as e:
            logger.error("Failed to register tool module %s: %s", module_path, e)
            raise
