"""
project_brain/mcp_server.py — backward-compat shim

ARCHITECTURE_REVIEW.md §6.2 重構：實際模組已移至
``project_brain/interfaces/mcp_server.py``。
"""
from __future__ import annotations

import sys as _sys

_is_main = __name__ == "__main__"

from project_brain.interfaces import mcp_server as _real  # noqa: F401

_sys.modules[__name__] = _real

if _is_main:
    _real.main()
