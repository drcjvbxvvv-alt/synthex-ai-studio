"""
project_brain/cli.py — backward-compat shim

ARCHITECTURE_REVIEW.md §6.2 重構：實際模組已移至
``project_brain/interfaces/cli.py``。pyproject.toml 的
``[project.scripts] brain = "project_brain.cli:main"`` 透過
sys.modules 別名繼續解析到本模組的 `main` function。
"""
from __future__ import annotations

import sys as _sys

from project_brain.interfaces import cli as _real  # noqa: F401

_sys.modules[__name__] = _real
