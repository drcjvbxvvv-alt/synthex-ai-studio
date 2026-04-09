"""
project_brain/graphiti_adapter.py — backward-compat shim

ARCHITECTURE_REVIEW.md §6.2 重構：實際模組已移至
``project_brain/integrations/graphiti_adapter.py``。
"""
from __future__ import annotations

import sys as _sys

from project_brain.integrations import graphiti_adapter as _real  # noqa: F401

_sys.modules[__name__] = _real
