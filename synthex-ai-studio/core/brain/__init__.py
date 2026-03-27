"""
Project Brain v4.0 — SYNTHEX 四層認知記憶架構

版本演進：
  v1.0：SQLite 知識圖譜 + AI 提取 + 考古掃描
  v1.1：Chroma 向量記憶 + 時序圖譜 + MCP Server + VS Code 擴充
  v2.0：跨 Repo 聯邦 + 三維衰減 + 反事實推理
  v3.0：三層認知架構（Memory Tool + Graphiti + v2.0）
  v4.0：
    - Agent 自主知識驗證（KnowledgeValidator）
    - 跨組織匿名知識共享（KnowledgeFederation + 差分隱私）
    - 多層知識蒸餾（KnowledgeDistiller，Layer 1/2/3）
    - Graphiti 專屬 MCP Server（graphiti_mcp_server）
    - 知識圖譜視覺化 Web UI（Flask + D3.js）
    - L1 工作記憶跨 session 持久化
"""
from .engine           import ProjectBrain
from .extractor        import KnowledgeExtractor
from .graph            import KnowledgeGraph
from .context          import ContextEngineer
from .archaeologist    import ProjectArchaeologist
from .vector_memory    import VectorMemory       # v1.1
from .temporal_graph   import TemporalGraph      # v1.1
from .shared_registry  import SharedRegistry     # v2.0
from .decay_engine     import DecayEngine        # v2.0
from .counterfactual   import CounterfactualReasoner  # v2.0
from .memory_tool      import (                  # v3.0 L1
    BrainMemoryBackend, make_memory_params,
    persist_session_memories,                    # v4.0 新增
    restore_session_memories,                    # v4.0 新增
    list_available_sessions,                     # v4.0 新增
)
from .graphiti_adapter import (                  # v3.0 L2
    GraphitiAdapter, KnowledgeEpisode, TemporalSearchResult,
    episode_from_phase, episode_from_commit, episode_from_adr,
)
from .router           import BrainRouter, BrainQueryResult  # v3.0 router
from .knowledge_validator import KnowledgeValidator, ValidationReport  # v4.0
from .federation          import KnowledgeFederation, FederatedKnowledge  # v4.0
from .knowledge_distiller import KnowledgeDistiller, DistillationResult   # v4.0

__version__ = "4.0.0"

__all__ = [
    # v1.0 + v1.1 + v2.0（完整保留）
    "ProjectBrain", "KnowledgeExtractor", "KnowledgeGraph",
    "ContextEngineer", "ProjectArchaeologist",
    "VectorMemory", "TemporalGraph",
    "SharedRegistry", "DecayEngine", "CounterfactualReasoner",
    # v3.0
    "BrainMemoryBackend", "make_memory_params",
    "GraphitiAdapter", "KnowledgeEpisode", "TemporalSearchResult",
    "episode_from_phase", "episode_from_commit", "episode_from_adr",
    "BrainRouter", "BrainQueryResult",
    # v4.0 新增
    "KnowledgeValidator", "ValidationReport",
    "KnowledgeFederation", "FederatedKnowledge",
    "KnowledgeDistiller", "DistillationResult",
    "persist_session_memories", "restore_session_memories",
    "list_available_sessions",
]
