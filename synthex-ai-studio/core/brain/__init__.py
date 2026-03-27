"""
Project Brain v3.0 — SYNTHEX 三層認知記憶架構

架構演進：
  v1.0：SQLite 知識圖譜 + AI 提取 + Context 組裝 + 考古掃描
  v1.1：向量記憶（Chroma）+ 時序圖譜 + MCP Server + VS Code 擴充
  v2.0：跨 Repo 知識聯邦 + 多因子衰減引擎 + 反事實推理
  v3.0：三層認知架構
        L1 工作記憶（Anthropic Memory Tool）
        L2 情節記憶（Graphiti 時序知識圖譜）
        L3 語義記憶（Project Brain v2.0，保留）

三層設計理念：
  L1 — Working Memory：即時任務資訊，session 生命週期
       類比：「我正在修的 bug、這次踩到的坑」
       後端：Anthropic Memory Tool（memory_20250818）+ SQLite

  L2 — Episodic Memory：時序事件圖，「什麼時候誰決定了什麼」
       類比：「三個月前 NEXUS 決定用 PostgreSQL 的原因」
       後端：Graphiti（時序 KG）→ 降級到 TemporalGraph

  L3 — Semantic Memory：深度語義知識，長期規律，反事實
       類比：「我們系統的架構模式和踩坑規律」
       後端：SQLite + Chroma（v2.0 完整保留）

使用方式：
  from core.brain import ProjectBrain, BrainRouter

  # 完整三層系統
  brain  = ProjectBrain(workdir)
  router = brain.router  # BrainRouter v3.0

  # 查詢（三層聚合）
  result = router.query("修復支付 bug")
  context = result.to_context_string()

  # 學習
  router.learn_from_phase(9, "BYTE", frontend_output)
  router.learn_from_commit("abc1234", "fix: 支付超時", "ahern", ["api/payment.ts"])
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
from .memory_tool      import BrainMemoryBackend, make_memory_params  # v3.0 L1
from .graphiti_adapter import (                 # v3.0 L2
    GraphitiAdapter, KnowledgeEpisode, TemporalSearchResult,
    episode_from_phase, episode_from_commit, episode_from_adr,
)
from .router           import BrainRouter, BrainQueryResult  # v3.0 router

__version__ = "3.0.0"

__all__ = [
    # v1.0 + v1.1 + v2.0（完整保留）
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
    # v3.0 新增
    "BrainMemoryBackend",
    "make_memory_params",
    "GraphitiAdapter",
    "KnowledgeEpisode",
    "TemporalSearchResult",
    "episode_from_phase",
    "episode_from_commit",
    "episode_from_adr",
    "BrainRouter",
    "BrainQueryResult",
]
