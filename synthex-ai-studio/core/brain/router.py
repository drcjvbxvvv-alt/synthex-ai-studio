"""
core/brain/router.py — BrainRouter v3.0（三層認知路由器）

架構理念：
  人類認知科學的三層記憶模型：
    L1 工作記憶（Working Memory）：
      → Anthropic Memory Tool
      → 當前 session/task 相關的即時資訊
      → 生命週期：session，自動清理
      → 容量：有限（~50 個文件）

    L2 情節記憶（Episodic Memory）：
      → Graphiti 時序知識圖譜
      → 「什麼時候發生了什麼」，事件因果鏈
      → 生命週期：專案，時序演化
      → 容量：無限，自動 invalidate

    L3 語義記憶（Semantic Memory）：
      → Project Brain v2.0 SQLite + Chroma
      → 深度語義知識、模式、反事實
      → 生命週期：永久，知識衰減
      → 容量：無限，衰減管理

路由邏輯：
  寫入：
    - 即時工作資訊（踩坑/進展）→ L1
    - 決策/ADR/commit → L2 + L3
    - 規則/組件關係/反事實 → L3

  讀取：
    - L1 精確匹配 → L2 時序搜尋 → L3 語義搜尋
    - 三層結果聚合，去重，Token Budget 管理

效能目標：
  - L1 查詢：<10ms（SQLite）
  - L2 查詢：<100ms（Graphiti 混合搜尋）
  - L3 查詢：<200ms（SQLite FTS5 + Chroma）
  - 端對端（三層聚合）：<500ms
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

from core.brain.memory_tool import BrainMemoryBackend, MEMORY_DIRS
from core.brain.graphiti_adapter import (
    GraphitiAdapter, KnowledgeEpisode, TemporalSearchResult,
    episode_from_phase, episode_from_commit, episode_from_adr,
)

logger = logging.getLogger(__name__)

# ── Context Budget ────────────────────────────────────────────
MAX_CONTEXT_TOKENS   = 3_000   # L1+L2+L3 聚合後最大 token 數
MAX_PER_LAYER_TOKENS = 1_200   # 每層最多 token 數
CHARS_PER_TOKEN      = 4       # 估算用


@dataclass
class BrainQueryResult:
    """三層聚合後的查詢結果"""
    l1_working:  list[dict]               = field(default_factory=list)
    l2_temporal: list[TemporalSearchResult] = field(default_factory=list)
    l3_semantic: list[dict]               = field(default_factory=list)
    query:       str                      = ""
    elapsed_ms:  int                      = 0

    @property
    def total_results(self) -> int:
        return len(self.l1_working) + len(self.l2_temporal) + len(self.l3_semantic)

    def to_context_string(self, max_tokens: int = MAX_CONTEXT_TOKENS) -> str:
        """
        格式化為可注入 Agent prompt 的 context 字串。
        按優先順序：L1 踩坑 > L2 時序決策 > L3 語義知識。
        Token Budget 動態分配。
        """
        if self.total_results == 0:
            return ""

        budget_chars = max_tokens * CHARS_PER_TOKEN
        sections     = []

        # L1：工作記憶（最高優先）
        if self.l1_working:
            l1_lines = []
            for mem in self.l1_working[:5]:
                line = f"  [{mem.get('path','').split('/')[-1]}] {mem.get('content','')[:200]}"
                l1_lines.append(line)
            section = "## ⚡ 工作記憶（L1·本次任務）\n" + "\n".join(l1_lines)
            if len(section) <= budget_chars // 3:
                sections.append(section)
                budget_chars -= len(section)

        # L2：時序情節（次優先）
        if self.l2_temporal:
            l2_lines = []
            for r in self.l2_temporal[:4]:
                l2_lines.append("  " + r.to_context_line())
            section = "## 🕰 時序決策（L2·Graphiti）\n" + "\n".join(l2_lines)
            if len(section) <= budget_chars // 2:
                sections.append(section)
                budget_chars -= len(section)

        # L3：語義知識（補充）
        if self.l3_semantic:
            l3_lines = []
            for r in self.l3_semantic[:4]:
                node_type = r.get("type", "知識")
                content   = r.get("content", r.get("description", ""))[:200]
                l3_lines.append(f"  [{node_type}] {content}")
            section = "## 📚 語義知識（L3·Project Brain）\n" + "\n".join(l3_lines)
            if len(section) <= budget_chars and l3_lines:
                sections.append(section)

        if not sections:
            return ""

        header = (
            "---\n"
            "## 📖 Project Brain v3.0 — 三層記憶系統\n"
            f"（查詢：\"{self.query[:50]}\"·{self.elapsed_ms}ms）\n\n"
        )
        return header + "\n\n".join(sections) + "\n---\n"


class BrainRouter:
    """
    三層認知記憶路由器（L1 + L2 + L3）。

    職責：
      1. 智能寫入路由（根據知識類型決定寫哪層）
      2. 多層並行查詢（聚合 + 去重 + Token 管理）
      3. 降級策略（任一層失敗不影響其他層）
      4. 性能監控（記錄每層延遲）

    使用方式（整合到 ProjectBrain.get_context()）：
      router = BrainRouter(brain_dir, l3_brain=project_brain)
      result = router.query(task_description)
      context_str = result.to_context_string()
    """

    def __init__(
        self,
        brain_dir:   Path,
        l3_brain:    Any  = None,    # ProjectBrain 實例
        graphiti_url: str = "redis://localhost:6379",
        agent_name:  str  = "synthex",
    ):
        self.brain_dir  = Path(brain_dir)
        self.agent_name = agent_name

        # L1：工作記憶（官方 Memory Tool）
        self.l1 = BrainMemoryBackend(
            brain_dir  = self.brain_dir,
            agent_name = agent_name,
        )

        # L2：情節記憶（Graphiti，帶降級到 TemporalGraph）
        l2_fallback = getattr(l3_brain, "_temporal", None) if l3_brain else None
        self.l2 = GraphitiAdapter(
            brain_dir  = self.brain_dir,
            db_url     = graphiti_url,
            fallback   = l2_fallback,
            agent_name = agent_name,
        )

        # L3：語義記憶（Project Brain v2.0）
        self.l3 = l3_brain

    # ── 寫入路由 ──────────────────────────────────────────────

    def write_working_memory(self, category: str, content: str,
                             name: str = "") -> bool:
        """
        寫入 L1 工作記憶（即時任務資訊）。

        Args:
            category: pitfalls / decisions / progress / context / notes
            content:  記憶內容
            name:     文件名（自動生成時間戳後綴）
        """
        dir_path = MEMORY_DIRS.get(category, MEMORY_DIRS["notes"])
        import uuid as _uuid
        unique_suffix = str(_uuid.uuid4())[:8]
        path = f"{dir_path}/{name or unique_suffix}.md"
        try:
            self.l1.handle_create({"path": path, "content": content})
            logger.debug("l1_write", category=category, chars=len(content))
            return True
        except Exception as e:
            logger.error("l1_write_failed: %s", str(e)[:100])
            return False

    def write_episode(self, episode: KnowledgeEpisode,
                       persist_to_l3: bool = True) -> bool:
        """
        寫入 L2 情節記憶（+ 可選同步到 L3）。

        Args:
            episode:       知識事件
            persist_to_l3: 是否同時寫入 L3 持久記憶
        """
        # L2 寫入
        l2_ok = self.l2.add_episode_sync(episode)

        # L3 同步（可選）
        if persist_to_l3 and self.l3:
            try:
                self.l3.add_knowledge(
                    content  = episode.content,
                    k_type   = "Decision",
                    source   = episode.source,
                )
            except Exception as e:
                logger.warning("l3_sync_failed", error=str(e)[:100])

        return l2_ok

    def learn_from_phase(self, phase: int, agent: str,
                          content: str, decision: str = "") -> None:
        """ship() 流水線每個 Phase 完成後自動學習"""
        ep = episode_from_phase(phase, agent, content, decision)
        self.write_episode(ep, persist_to_l3=True)

        # 提取踩坑到 L1（如果有）
        pitfall_keywords = ["錯誤", "失敗", "問題", "坑", "bug", "error", "crash", "failed"]
        if any(kw in content.lower() for kw in pitfall_keywords):
            self.write_working_memory(
                "pitfalls",
                f"Phase {phase}（{agent}）：{content[:300]}",
                name=f"phase_{phase}_pitfall"
            )

    def learn_from_commit(self, commit_hash: str, message: str,
                           author: str, files: list[str]) -> None:
        """Git commit 後自動學習"""
        ep = episode_from_commit(commit_hash, message, author, files)
        self.write_episode(ep, persist_to_l3=True)

    # ── 查詢（三層並行）────────────────────────────────────────

    def query(self, task: str, top_k_per_layer: int = 5) -> BrainQueryResult:
        """
        三層並行查詢，聚合結果。

        執行順序：L1（SQLite）→ L2（Graphiti）→ L3（SQLite+Chroma）
        每層獨立 try/except，失敗不影響其他層。
        """
        t0     = time.monotonic()
        result = BrainQueryResult(query=task)

        # L1：工作記憶搜尋
        try:
            l1_hits = self.l1.search(task, limit=top_k_per_layer)
            result.l1_working = l1_hits
        except Exception as e:
            logger.warning("l1_query_failed", error=str(e)[:100])

        # L2：時序情節搜尋
        try:
            result.l2_temporal = self.l2.search_sync(task, top_k=top_k_per_layer)
        except Exception as e:
            logger.warning("l2_query_failed: %s", str(e)[:100])

        # L3：語義知識搜尋
        if self.l3:
            try:
                l3_context = self.l3.get_context(task)
                if l3_context:
                    result.l3_semantic = [{"content": l3_context, "type": "semantic"}]
            except Exception as e:
                logger.warning("l3_query_failed: %s", str(e)[:100])

        result.elapsed_ms = int((time.monotonic() - t0) * 1_000)
        logger.debug("brain_query_done",
                     task=task[:50], elapsed_ms=result.elapsed_ms,
                     l1=len(result.l1_working),
                     l2=len(result.l2_temporal),
                     l3=len(result.l3_semantic))
        return result

    def status(self) -> dict:
        """三層狀態報告"""
        return {
            "l1_working_memory": {
                "backend":  "SQLite",
                "available": True,
                **self.l1.session_summary(),
            },
            "l2_episodic_memory": self.l2.status(),
            "l3_semantic_memory": {
                "available": self.l3 is not None,
                "backend":   "SQLite + Chroma (v2.0)",
            },
        }

    def clear_working_memory(self) -> int:
        """清空 L1 工作記憶（任務完成後可選調用）"""
        try:
            mems = self.l1.get_all()
            for m in mems:
                self.l1.handle_delete({"path": m["path"]})
            logger.info("l1_cleared", count=len(mems))
            return len(mems)
        except Exception as e:
            logger.error("l1_clear_failed: %s", str(e)[:100])
            return 0
