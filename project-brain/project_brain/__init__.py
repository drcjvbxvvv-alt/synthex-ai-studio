"""
project_brain — Project Brain Python SDK

AI Memory System for Software Development Teams.

Quick Start:
    from project_brain import Brain

    b = Brain("/your/project")
    b.init("my-project")

    # Store knowledge
    b.add_knowledge("JWT must use RS256", kind="Rule")

    # Retrieve context for LLM
    ctx = b.get_context("implementing JWT auth")

    # Python-first API
    from project_brain import Brain, search, add

    Brain.from_env()  # reads BRAIN_WORKDIR from environment
"""

from .engine import ProjectBrain

# Clean alias: Brain is the primary SDK class
Brain = ProjectBrain

from .context_result import ContextResult  # P3-A

from .graph         import KnowledgeGraph
from .session_store import SessionStore, SessionEntry
from .context       import ContextEngineer
from .extractor     import KnowledgeExtractor
from .review_board  import KnowledgeReviewBoard

# Optional imports (with graceful degradation)
try:
    from .router import BrainRouter
except ImportError:
    pass


def _read_version() -> str:
    # 1. Source checkout: read pyproject.toml next to this package.
    #    Prioritised because importlib.metadata may return a stale
    #    *installed* version that differs from the source tree.
    try:
        import re as _re
        from pathlib import Path as _Path
        _toml = _Path(__file__).resolve().parent.parent / "pyproject.toml"
        if _toml.is_file():
            _text = _toml.read_text(encoding="utf-8")
            _m = _re.search(r'^version\s*=\s*"([^"]+)"', _text, _re.MULTILINE)
            if _m:
                return _m.group(1)
    except Exception:
        pass
    # 2. pip-installed (no source tree available): read package metadata
    try:
        from importlib.metadata import version as _pkg_version
        return _pkg_version("project-brain")
    except Exception:
        pass
    return "0.0.0"  # last-resort fallback (should never reach here)

__version__ = _read_version()

__author__   = "Project Brain Team"
__license__  = "MIT"

__all__ = [
    "Brain",
    "ProjectBrain",
    "KnowledgeGraph",
    "SessionStore",
    "ContextEngineer",
    "KnowledgeExtractor",
    "KnowledgeReviewBoard",
    "__version__",
    "ContextResult",
]
