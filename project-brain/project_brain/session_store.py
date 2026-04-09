"""
project_brain/session_store.py — backward-compat shim

ARCHITECTURE_REVIEW.md §6.2 重構：實際模組已移至
``project_brain/core/session_store.py``。本檔案使用 ``sys.modules``
別名確保 ``project_brain.session_store`` 與 ``project_brain.core.session_store``
為同一個 module 物件。
"""
from __future__ import annotations

import sys as _sys

from project_brain.core import session_store as _real_session_store  # noqa: F401

_sys.modules[__name__] = _real_session_store
