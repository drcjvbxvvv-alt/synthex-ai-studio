"""
project_brain/rbac.py — E-02: Role-Based Access Control foundation

Defines the role hierarchy and per-MCP-tool permission matrix used by
AuthMiddleware (HTTP transport) and MCP tool handlers.

Roles (lowest → highest):
  reader       — read-only tools (get_context, search_knowledge, brain_status)
  contributor  — + write tools (add_knowledge, complete_task, report_knowledge_outcome)
  maintainer   — + staging management (approve/reject)
  admin        — full access (all tools + admin operations)

Usage:
    from project_brain.rbac import has_permission, TOOL_PERMISSIONS
    if not has_permission(user_role, TOOL_PERMISSIONS["add_knowledge"]):
        return {"error": "permission_denied", ...}
"""
from __future__ import annotations

# Role hierarchy: higher number = more privileges
ROLE_HIERARCHY: dict[str, int] = {
    "reader":      0,
    "contributor": 1,
    "maintainer":  2,
    "admin":       3,
}

# Minimum role required for each MCP tool
TOOL_PERMISSIONS: dict[str, str] = {
    # Read-only tools
    "get_context":               "reader",
    "search_knowledge":          "reader",
    "brain_status":              "reader",
    "list_knowledge":            "reader",
    "get_knowledge":             "reader",
    "search_by_scope":           "reader",
    "find_related":              "reader",
    # Write tools
    "add_knowledge":             "contributor",
    "complete_task":             "contributor",
    "report_knowledge_outcome":  "contributor",
    # Push to central
    "push_to_central":           "contributor",
    # Staging management
    "approve_staged":            "maintainer",
    "reject_staged":             "maintainer",
}

VALID_ROLES = frozenset(ROLE_HIERARCHY.keys())


def has_permission(user_role: str, required_role: str) -> bool:
    """Check if a user's role meets or exceeds the required role level.

    Returns False for unknown roles (fail-closed).
    """
    user_level = ROLE_HIERARCHY.get(user_role, -1)
    required_level = ROLE_HIERARCHY.get(required_role, 999)
    return user_level >= required_level
