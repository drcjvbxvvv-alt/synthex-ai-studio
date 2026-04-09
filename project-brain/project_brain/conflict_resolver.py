"""
project_brain/conflict_resolver.py — backward-compat shim

ARCHITECTURE_REVIEW.md §6.2 重構：實際模組已移至
``project_brain/engines/conflict_resolver.py``。
"""
from __future__ import annotations

import sys as _sys

from project_brain.engines import conflict_resolver as _real  # noqa: F401

_sys.modules[__name__] = _real
