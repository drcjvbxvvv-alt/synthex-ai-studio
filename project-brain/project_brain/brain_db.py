"""
project_brain/brain_db.py — backward-compat shim

ARCHITECTURE_REVIEW.md §6.2 重構：實際模組已移至
``project_brain/core/brain_db.py``。本檔案使用 ``sys.modules`` 別名
確保 ``project_brain.brain_db`` 與 ``project_brain.core.brain_db`` 為
**同一個 module 物件**，讓既有 ``import project_brain.brain_db as bd``
與直接 attribute 存取（包括 logger、monkey-patch）繼續如常運作。
"""
from __future__ import annotations

import sys as _sys

from project_brain.core import brain_db as _real_brain_db  # noqa: F401

_sys.modules[__name__] = _real_brain_db
