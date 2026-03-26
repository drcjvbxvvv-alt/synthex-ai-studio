"""
Project Brain v2.0 — SYNTHEX 知識積累子系統

v1.0：SQLite 知識圖譜 + AI 提取 + Context 組裝 + 考古掃描
v1.1：向量記憶（Chroma）+ 時序圖譜 + MCP Server + VS Code 擴充
v2.0：跨 Repo 知識聯邦 + 多因子衰減引擎 + 反事實推理
"""
from .engine           import ProjectBrain
from .extractor        import KnowledgeExtractor
from .graph            import KnowledgeGraph
from .context          import ContextEngineer
from .archaeologist    import ProjectArchaeologist
from .vector_memory    import VectorMemory      # v1.1
from .temporal_graph   import TemporalGraph     # v1.1
from .shared_registry  import SharedRegistry    # v2.0
from .decay_engine     import DecayEngine       # v2.0
from .counterfactual   import CounterfactualReasoner  # v2.0

__version__ = "2.0.0"

__all__ = [
    "ProjectBrain",
    "KnowledgeExtractor",
    "KnowledgeGraph",
    "ContextEngineer",
    "ProjectArchaeologist",
    "VectorMemory",
    "TemporalGraph",
    "SharedRegistry",
    "DecayEngine",
    "CounterfactualReasoner",
]
