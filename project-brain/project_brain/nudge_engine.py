"""
project_brain/nudge_engine.py — backward-compat shim

ARCHITECTURE_REVIEW.md §6.2 重構：實際模組已移至
``project_brain/engines/nudge_engine.py``。
"""
from __future__ import annotations

import sys as _sys

from project_brain.engines import nudge_engine as _real  # noqa: F401

_sys.modules[__name__] = _real
