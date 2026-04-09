"""
project_brain/constants.py — backward-compat shim

ARCHITECTURE_REVIEW.md §6.2 重構：實際模組已移至
``project_brain/core/constants.py``。本檔案使用 ``sys.modules``
別名確保 ``project_brain.constants`` 與 ``project_brain.core.constants``
為**同一個 module 物件**，讓 ``monkeypatch.setattr(project_brain.constants, ...)``
仍會影響 ``project_brain.core.brain_db`` 內透過
``from . import constants as _constants`` 取得的引用（REF-04 契約）。
"""
from __future__ import annotations

import sys as _sys

from project_brain.core import constants as _real_constants  # noqa: F401

# 讓本模組完全等同於真實模組（共用同一個 namespace object）
_sys.modules[__name__] = _real_constants
