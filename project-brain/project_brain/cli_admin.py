"""
project_brain/cli_admin.py — backward-compat shim

ARCHITECTURE_REVIEW.md §6.2 重構：實際模組已移至
``project_brain/interfaces/cli_admin.py``。
"""
from __future__ import annotations

import sys as _sys

from project_brain.interfaces import cli_admin as _real  # noqa: F401

_sys.modules[__name__] = _real
