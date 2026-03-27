"""
core/brain/graphiti_adapter.py — Graphiti 時序知識圖譜整合 (L2)

Graphiti 是什麼：
  Zep 開源的時序知識圖譜引擎。核心特點：
  - 雙時態模型（t_valid / t_invalid）：追蹤「什麼時候是真的」
  - 知識衝突自動 invalidate（不刪除，保留歷史）
  - 混合檢索：語義 + BM25 + 圖遍歷，<100ms 查詢
  - 後端：FalkorDB（輕量）/ Neo4j / Kuzu

與 Project Brain SQLite 的差異：
  L2（Graphiti）：「三個月前 BYTE 為什麼選 Next.js？那個決策現在還有效嗎？」
                   時序關係圖、決策演化、ADR 版本鏈
  L3（SQLite）：  「我們有哪些反事實分析？知識衰減分數是多少？」
                   靜態知識圖，深度語義，跨 Repo 聯邦

降級設計（Graphiti 不可用時）：
  → 自動使用現有 TemporalGraph（SQLite 時序圖）
  → 功能降級但不崩潰
  → 日誌記錄降級原因

使用方式：
  adapter = GraphitiAdapter(brain_dir=Path(".brain"), fallback=temporal_graph)
  if adapter.available:
      await adapter.add_episode("NEXUS 決定使用 Next.js App Router")
      results = await adapter.search("Next.js 架構決策", top_k=5)
  else:
      results = adapter.fallback_search("Next.js 架構決策")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)

# ── Graphiti 依賴（graceful fallback）────────────────────────
try:
    from graphiti_core import Graphiti
    from graphiti_core.nodes import EpisodeType
    _HAS_GRAPHITI = True
except ImportError:
    _HAS_GRAPHITI = False
    logger.info("graphiti_core 未安裝，L2 降級到 TemporalGraph")


@dataclass
class KnowledgeEpisode:
    """
    一個知識事件（Episode）—— Graphiti 的基本輸入單元。

    例子：
      - "NEXUS 在 Phase 4 決定使用 PostgreSQL，原因是事務支援"
      - "BYTE 發現 Next.js 的 RSC 和 Suspense 邊界衝突"
      - "SHIELD 標記 JWT 演算法為 HS256（弱），改為 RS256"
    """
    content:      str
    source:       str = "synthex"      # 來源（agent 名稱、commit、ship）
    episode_type: str = "text"         # text | json
    reference_time: Optional[str] = None  # ISO 8601 可選
    metadata:     dict = field(default_factory=dict)


@dataclass
class TemporalSearchResult:
    """統一的時序搜尋結果格式（L2/L3 共用）"""
    content:       str
    source:        str
    relevance:     float       # 0.0 - 1.0
    valid_from:    Optional[str] = None
    valid_until:   Optional[str] = None  # None = 仍有效
    node_type:     str = "fact"
    metadata:      dict = field(default_factory=dict)

    @property
    def is_current(self) -> bool:
        """這個知識目前仍有效嗎？"""
        return self.valid_until is None

    def to_context_line(self) -> str:
        """格式化為 context 注入字串"""
        status  = "✓ 現行" if self.is_current else f"⟲ 已更新（{self.valid_until[:10]}）"
        date    = self.valid_from[:10] if self.valid_from else "?"
        return f"[{status}·{date}] {self.content} (來源:{self.source})"


class GraphitiAdapter:
    """
    Graphiti 時序知識圖譜的 SYNTHEX 適配層（L2）。

    功能：
      1. add_episode() — 把 Agent 決策、commit、ADR 寫入時序圖
      2. search() — 混合搜尋（語義 + BM25 + 圖遍歷）
      3. get_node_history() — 查詢一個實體的時序演化
      4. 降級到 TemporalGraph（Graphiti 不可用時）

    非同步設計：
      Graphiti 的 add_episode() 和 search() 是 async。
      提供同步包裝 add_episode_sync() 供非 async 環境使用。
    """

    def __init__(
        self,
        brain_dir:     Path,
        db_url:        str  = "bolt://localhost:7687",  # Neo4j/FalkorDB
        fallback:      Any  = None,    # TemporalGraph 實例
        agent_name:    str  = "synthex",
    ):
        self.brain_dir  = Path(brain_dir)
        self.db_url     = db_url
        self._fallback  = fallback    # TemporalGraph（降級用）
        self.agent_name = agent_name
        self._client:   Optional[Any] = None
        self._available: Optional[bool] = None

    @property
    def available(self) -> bool:
        """Graphiti 是否可用（懶初始化）"""
        if self._available is None:
            self._available = self._try_connect()
        return self._available

    def _try_connect(self) -> bool:
        """嘗試連接 Graphiti 後端（不拋例外）"""
        if not _HAS_GRAPHITI:
            return False
        try:
            # 嘗試建立連線（5 秒 timeout）
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                asyncio.wait_for(self._init_client(), timeout=5.0)
            )
            loop.close()
            logger.info("graphiti_connected", url=self.db_url)
            return True
        except Exception as e:
            logger.info("graphiti_unavailable", reason=str(e)[:100])
            return False

    async def _init_client(self) -> None:
        from graphiti_core import Graphiti
        import anthropic
        import os
        self._client = Graphiti(
            uri      = self.db_url,
            llm_client    = None,  # Graphiti 可用 OpenAI/Anthropic
            embedder_client = None,
        )
        await self._client.build_indices_and_constraints()

    # ── 寫入操作 ──────────────────────────────────────────────

    async def add_episode(self, episode: KnowledgeEpisode) -> bool:
        """
        將知識事件加入時序知識圖譜。
        Graphiti 自動：提取實體、建立關係、處理衝突。
        """
        if not self.available:
            return self._fallback_add(episode)

        try:
            from graphiti_core.nodes import EpisodeType as ET
            ep_type = ET.text if episode.episode_type == "text" else ET.json
            ref_time = (
                datetime.fromisoformat(episode.reference_time)
                if episode.reference_time
                else datetime.now(timezone.utc)
            )
            await self._client.add_episode(
                name         = f"{episode.source}:{int(time.time())}",
                episode_body = episode.content[:8_000],  # 安全截斷
                source       = ep_type,
                source_description = episode.source,
                reference_time     = ref_time,
            )
            logger.debug("graphiti_episode_added",
                         source=episode.source, chars=len(episode.content))
            return True
        except Exception as e:
            logger.error("graphiti_add_failed", error=str(e)[:200])
            return self._fallback_add(episode)

    def add_episode_sync(self, episode: KnowledgeEpisode) -> bool:
        """同步包裝（供非 async 環境，如 ship() 流水線）"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 已有 event loop，用 thread 執行
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(
                        lambda: asyncio.run(self.add_episode(episode))
                    )
                    return future.result(timeout=30)
            return loop.run_until_complete(self.add_episode(episode))
        except Exception as e:
            logger.error("graphiti_sync_add_failed", error=str(e)[:100])
            return self._fallback_add(episode)

    # ── 查詢操作 ──────────────────────────────────────────────

    async def search(
        self,
        query:   str,
        top_k:   int = 5,
        current_only: bool = False,
    ) -> list[TemporalSearchResult]:
        """
        混合搜尋（語義 + BM25 + 圖遍歷）。
        Graphiti 自動處理時序過濾。
        """
        if not self.available:
            return self._fallback_search(query, top_k)

        try:
            results = await self._client.search(query, num_results=top_k)
            output  = []
            for r in results:
                # Graphiti 回傳 edge 物件，包含時序資訊
                valid_until = None
                if hasattr(r, "expired_at") and r.expired_at:
                    valid_until = r.expired_at.isoformat()
                if current_only and valid_until:
                    continue  # 跳過已過期的知識
                output.append(TemporalSearchResult(
                    content    = str(r.fact if hasattr(r, "fact") else r)[:500],
                    source     = getattr(r, "source_description", "graphiti"),
                    relevance  = getattr(r, "score", 0.5),
                    valid_from = (getattr(r, "valid_at", None) or
                                  getattr(r, "created_at", None) or ""),
                    valid_until= valid_until,
                ))
            return output
        except Exception as e:
            logger.error("graphiti_search_failed", error=str(e)[:200])
            return self._fallback_search(query, top_k)

    def search_sync(self, query: str, top_k: int = 5) -> list[TemporalSearchResult]:
        """同步搜尋包裝"""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    return ex.submit(
                        lambda: asyncio.run(self.search(query, top_k))
                    ).result(timeout=10)
            return asyncio.run(self.search(query, top_k))
        except Exception as e:
            logger.warning("graphiti_search_sync_failed: %s", str(e)[:100])
            return self._fallback_search(query, top_k)

    # ── 降級實作 ──────────────────────────────────────────────

    def _fallback_add(self, episode: KnowledgeEpisode) -> bool:
        """降級到 TemporalGraph（Graphiti 不可用時）"""
        if self._fallback is None:
            logger.debug("graphiti_fallback_no_temporal_graph")
            return False
        try:
            # TemporalGraph.add_edge() 介面
            self._fallback.add_temporal_fact(
                subject   = episode.source,
                predicate = "reported",
                obj       = episode.content[:500],
                source    = episode.source,
            ) if hasattr(self._fallback, "add_temporal_fact") else None
            return True
        except Exception as e:
            logger.error("graphiti_fallback_failed", error=str(e)[:100])
            return False

    def _fallback_search(
        self, query: str, top_k: int = 5
    ) -> list[TemporalSearchResult]:
        """降級搜尋（TemporalGraph 或空結果）"""
        if self._fallback is None:
            return []
        try:
            # TemporalGraph 的現有搜尋介面
            if hasattr(self._fallback, "search_temporal"):
                raw = self._fallback.search_temporal(query, limit=top_k)
            elif hasattr(self._fallback, "graph"):
                raw = self._fallback.graph.search_nodes(query, limit=top_k)
            else:
                return []
            return [
                TemporalSearchResult(
                    content   = r.get("content", r.get("description", ""))[:500],
                    source    = r.get("source", "temporal_graph"),
                    relevance = r.get("confidence", 0.5),
                    valid_from= r.get("created_at", ""),
                )
                for r in (raw or [])
            ]
        except Exception as e:
            logger.warning("graphiti_fallback_search_failed", error=str(e)[:100])
            return []

    def status(self) -> dict:
        """回傳當前 L2 記憶層狀態"""
        return {
            "graphiti_available": self.available,
            "backend": self.db_url if self.available else "TemporalGraph (fallback)",
            "has_fallback": self._fallback is not None,
        }


# ── 便利函數：從 SYNTHEX 事件建立 Episode ────────────────────

def episode_from_phase(
    phase:   int,
    agent:   str,
    content: str,
    decision: str = "",
) -> KnowledgeEpisode:
    """從 ship() 的 Phase 輸出建立知識 Episode"""
    text = f"Phase {phase}（{agent}）"
    if decision:
        text += f"決策：{decision}\n"
    text += content[:2_000]
    return KnowledgeEpisode(
        content  = text,
        source   = f"phase_{phase}_{agent.lower()}",
        metadata = {"phase": phase, "agent": agent},
    )


def episode_from_commit(
    commit_hash: str,
    message:     str,
    author:      str = "?",
    files:       list[str] | None = None,
) -> KnowledgeEpisode:
    """從 git commit 建立知識 Episode"""
    files_str = ", ".join((files or [])[:5])
    text = f"Commit {commit_hash[:8]}（{author}）：{message}"
    if files_str:
        text += f"\n修改檔案：{files_str}"
    return KnowledgeEpisode(
        content  = text,
        source   = f"commit_{commit_hash[:8]}",
        metadata = {"commit": commit_hash, "author": author},
    )


def episode_from_adr(
    adr_id:    str,
    title:     str,
    decision:  str,
    context:   str = "",
    supersedes: str = "",
) -> KnowledgeEpisode:
    """從 ADR（架構決策記錄）建立知識 Episode"""
    text = f"ADR {adr_id}：{title}\n決策：{decision}"
    if context:
        text += f"\n背景：{context[:500]}"
    if supersedes:
        text += f"\n取代了：{supersedes}"
    return KnowledgeEpisode(
        content  = text,
        source   = f"adr_{adr_id}",
        metadata = {"adr_id": adr_id, "supersedes": supersedes},
    )
