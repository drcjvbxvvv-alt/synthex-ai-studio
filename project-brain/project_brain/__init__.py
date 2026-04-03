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


__version__  = "0.2.0"
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
