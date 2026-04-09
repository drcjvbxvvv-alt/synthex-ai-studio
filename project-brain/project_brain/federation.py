"""
project_brain/federation.py — backward-compat shim

ARCHITECTURE_REVIEW.md §6.2 重構：實際模組已移至
``project_brain/integrations/federation.py``。
"""
from __future__ import annotations

import sys as _sys

from project_brain.integrations import federation as _real  # noqa: F401

_sys.modules[__name__] = _real
