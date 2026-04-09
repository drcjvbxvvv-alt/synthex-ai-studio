"""
project_brain/api_server.py — backward-compat shim

ARCHITECTURE_REVIEW.md §6.2 重構：實際模組已移至
``project_brain/interfaces/api_server.py``。
"""
from __future__ import annotations

import sys as _sys

from project_brain.interfaces import api_server as _real  # noqa: F401

_sys.modules[__name__] = _real
