"""
project_brain/web_ui/__init__.py — backward-compat shim package

ARCHITECTURE_REVIEW.md §6.2 重構：實際 web_ui 套件已移至
``project_brain/interfaces/web_ui/``。

本 shim 會同時別名 package 與 server 子模組，確保：
    from project_brain.web_ui.server import run_server
等同於：
    from project_brain.interfaces.web_ui.server import run_server
（指向同一個 module 物件、同一個 function 物件）。
"""
from __future__ import annotations

import sys as _sys

from project_brain.interfaces import web_ui as _real_pkg  # noqa: F401
from project_brain.interfaces.web_ui import server as _real_server  # noqa: F401

# 先 pre-register 子模組，否則 Python 會從 aliased package 的 __path__
# 重新載入 interfaces/web_ui/server.py，建立一個獨立的 module 物件。
_sys.modules[__name__ + ".server"] = _real_server
_sys.modules[__name__] = _real_pkg
