"""
Project Brain v1.1 — SYNTHEX 知識積累子系統

v1.0：SQLite 知識圖譜 + AI 提取 + Context 組裝 + 考古掃描
v1.1：向量記憶（Chroma）+ 時序圖譜（Graphiti 啟發）+ MCP Server + VS Code 擴充
"""
from .engine       import ProjectBrain
from .extractor    import KnowledgeExtractor
from .graph        import KnowledgeGraph
from .context      import ContextEngineer
from .archaeologist import ProjectArchaeologist
from .vector_memory import VectorMemory
from .temporal_graph import TemporalGraph

__version__ = "1.1.0"

__all__ = [
    "ProjectBrain",
    "KnowledgeExtractor",
    "KnowledgeGraph",
    "ContextEngineer",
    "ProjectArchaeologist",
    "VectorMemory",
    "TemporalGraph",
]
