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

from project_brain.session_store import SessionStore, CATEGORY_CONFIG

logger = logging.getLogger(__name__)

# ── Context Budget ────────────────────────────────────────────
MAX_CONTEXT_TOKENS   = 3_000   # L1+L2+L3 聚合後最大 token 數
MAX_PER_LAYER_TOKENS = 1_200   # 每層最多 token 數
CHARS_PER_TOKEN      = 4       # 估算用

@dataclass
class LayerTrace:
    """單層查詢追蹤（v6.x OpenTelemetry-style）"""
    layer:      str
    elapsed_ms: int  = 0
    hits:       int  = 0
    status:     str  = "ok"
    error:      str  = ""
    def to_dict(self) -> dict:
        return {"layer":self.layer,"elapsed_ms":self.elapsed_ms,
                "hits":self.hits,"status":self.status}

@dataclass
class BrainQueryResult:
    """三層聚合後的查詢結果（v6.x：附帶 traces）"""
    l1_working:  list[dict]               = field(default_factory=list)
    l2_temporal: list = field(default_factory=list)  # TemporalSearchResult when available
    l3_semantic: list[dict]               = field(default_factory=list)
    query:       str       = ""
    elapsed_ms:  int       = 0
    traces:      list      = field(default_factory=list)

    def trace_summary(self) -> str:
        if not self.traces:
            return f"total={self.elapsed_ms}ms"
        parts = [f"{t.layer}={t.elapsed_ms}ms/{t.hits}hits" for t in self.traces]
        return f"total={self.elapsed_ms}ms [{' | '.join(parts)}]"

    def total_hits(self) -> int:
        return len(self.l1_working) + len(self.l2_temporal) + len(self.l3_semantic)

    # Backward-compatible aliases
    @property
    def total_results(self) -> int:
        return self.total_hits()

    @property
    def total_results(self) -> int:
        """向後相容 alias"""
        return self.total_hits()

    def to_context_string(self, max_tokens: int = 3000) -> str:
        """聚合三層結果為 Context 字串（向後相容）"""
        CHARS   = 4
        budget  = max_tokens * CHARS
        parts: list[str] = []

        if self.l1_working:
            lines_l1 = [f"- {m.get(chr(99)+chr(111)+chr(110)+chr(116)+chr(101)+chr(110)+chr(116), m.get(chr(118)+chr(97)+chr(108)+chr(117)+chr(101), chr(63)))[:200]}" for m in self.l1_working[:5]]
            s = "## L1 工作記憶\n" + "\n".join(lines_l1)
            if len(s) <= budget:
                parts.append(s); budget -= len(s)

        if self.l2_temporal:
            lines_l2 = [f"- {getattr(r, chr(99)+chr(111)+chr(110)+chr(116)+chr(101)+chr(110)+chr(116), str(r))[:200]}" for r in self.l2_temporal[:4]]
            s = "## L2 Temporal\n" + "\n".join(lines_l2)
            if len(s) <= budget:
                parts.append(s); budget -= len(s)

        if self.l3_semantic:
            for r in self.l3_semantic[:2]:
                s = r.get("content", "")[:budget // 2]
                if s: parts.append(s)

        return "\n\n".join(parts)

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
        agent_name:  str  = "project-brain",
    ):
        self.brain_dir  = Path(brain_dir)
        self.agent_name = agent_name

        # L1a：Session Store（任意 LLM 可用，不依賴 Anthropic SDK）
        self.l1a = SessionStore(
            brain_dir  = self.brain_dir,
            session_id = agent_name,
        )


        # L2：情節記憶（Graphiti，帶降級到 TemporalGraph）
        l2_fallback = None  # temporal_graph 已移除
        from project_brain.graphiti_adapter import GraphitiAdapter as _GA
        self.l2 = _GA(
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
        import uuid as _uuid
        unique_suffix = str(_uuid.uuid4())[:8]
        entry_name = name or unique_suffix

        ok = False

        # 寫入 L1a Session Store（任意 LLM 可查詢）
        # v5.1 修正：key 加入 agent_name 前綴，避免多 Agent 靜默覆蓋
        # 格式：{category}/{agent_name}/{entry_name}
        safe_agent = self.agent_name.replace("/", "_")[:20]
        l1a_key    = f"{category}/{safe_agent}/{entry_name}"

        # v6.0 修正：Cross-Layer Write Transaction（L1a ↔ L3 原子性）
        # 在 L1a.set() 成功後，若 category 為持久化類型，同步到 L3
        # 失敗時回滾 L1a，確保兩層資料一致
        from project_brain.session_store import CATEGORY_CONFIG
        persistent = CATEGORY_CONFIG.get(category, {}).get("persistent", False)

        try:
            entry = self.l1a.set(l1a_key, content, category=category)
            ok    = True
        except Exception as e:
            logger.error("l1a_write_failed: %s", str(e)[:100])
            return False

        # 持久化類型同步到 L3（Pitfall/Decision/Rule → 長期知識）
        # 非持久化類型（progress/notes）不寫 L3
        if persistent and self.l3 and ok:
            kind_map = {
                "pitfalls":  "Pitfall",
                "decisions": "Decision",
                "context":   "Rule",
            }
            l3_kind = kind_map.get(category, "Rule")
            try:
                self.l3.add_knowledge(
                    content  = content,
                    k_type   = l3_kind,
                    source   = f"l1a:{l1a_key}",
                )
            except Exception as e:
                # L3 寫入失敗 → 回滾 L1a（原子性補償）
                logger.warning("l3_sync_failed, rolling back l1a: %s", str(e)[:100])
                try:
                    self.l1a.delete(l1a_key)
                except Exception:
                    pass
                return False

        # 寫入 L1b Anthropic Memory Tool（選填橋接，非原子性）
        try:
            path = f"{dir_path}/{entry_name}.md"
            self.l1a.handle_create({"path": path, "content": content})
        except Exception as e:
            logger.debug("l1b_write_failed (non-critical): %s", str(e)[:100])

        if ok:
            logger.debug("l1_write_ok: category=%s chars=%d persistent=%s", category, len(content), persistent)
        return ok

    def write_episode(self, episode: KnowledgeEpisode,
                       persist_to_l3: bool = True) -> bool:
        """
        寫入 L2 情節記憶（+ 可選同步到 L3）。

        v6.0 改進：Cross-Layer Write Transaction
        ─ 使用補償事務（Saga Pattern）取代無保護的雙寫：
          1. 嘗試 L2 寫入
          2. 嘗試 L3 寫入
          3. 若 L3 失敗，記錄到 .brain/write_queue.jsonl（稍後重試）
          4. 若 L2 失敗，直接嘗試只寫 L3

        這解決了原本 L2 成功 / L3 失敗時資料靜默丟失的問題。

        Args:
            episode:       知識事件
            persist_to_l3: 是否同時寫入 L3 持久記憶
        """
        l2_ok = False
        l3_ok = False

        # Step 1: L2 寫入
        try:
            l2_ok = self.l2.add_episode_sync(episode)
        except Exception as e:
            logger.warning("l2_write_failed: %s", str(e)[:100])

        # Step 2: L3 同步（可選）
        if persist_to_l3 and self.l3:
            try:
                self.l3.add_knowledge(
                    content = episode.content,
                    k_type  = "Decision",
                    source  = episode.source,
                )
                l3_ok = True
            except Exception as e:
                logger.warning("l3_write_failed: %s", str(e)[:100])
                # 補償：寫入待重試佇列（Write Queue）
                self._enqueue_failed_write(episode, layer="l3", error=str(e))

        return l2_ok or l3_ok

    def _enqueue_failed_write(
        self, episode: "KnowledgeEpisode", layer: str, error: str
    ) -> None:
        """
        v6.0 Write Queue：記錄跨層寫入失敗，供後續重試。

        失敗記錄存入 .brain/write_queue.jsonl，
        每行一個 JSON 物件，格式：
        {
            "ts": "ISO 8601",
            "layer": "l3",
            "episode_source": "git:abc1234",
            "episode_content": "...",
            "error": "...",
            "retried": false
        }
        執行 brain write-queue --retry 可重試失敗的寫入。
        """
        import json
        from datetime import datetime, timezone
        queue_path = self.brain_dir / "write_queue.jsonl"
        entry = {
            "ts":              datetime.now(timezone.utc).isoformat(),
            "layer":           layer,
            "episode_source":  getattr(episode, "source", ""),
            "episode_content": getattr(episode, "content", "")[:500],
            "error":           error[:200],
            "retried":         False,
        }
        try:
            with queue_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.info("write_queue_enqueued: layer=%s", layer)
        except Exception as eq:
            logger.error("write_queue_failed: %s", str(eq)[:100])

        return True

    def learn_from_phase(self, phase: int, agent: str,
                          content: str, decision: str = "") -> None:
        """ship() 流水線每個 Phase 完成後自動學習"""
        try:
            from project_brain.graphiti_adapter import episode_from_phase as _efp
            ep = _efp(phase, agent, content, decision)
        except ImportError:
            ep = None
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
        try:
            from project_brain.graphiti_adapter import episode_from_commit as _efc
            ep = _efc(commit_hash, message, author, files)
        except ImportError:
            ep = None
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

        # v5.1 修正：真正的並行查詢（ThreadPoolExecutor）
        # 原本是順序阻塞：L1a → L1b → L2 → L3，合計可能 >500ms
        # 現在是並行：四層同時查，延遲取最慢那層，而非四層加總
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _query_l1a():
            hits = self.l1a.search(task, limit=top_k_per_layer)
            return "l1a", [
                {"content": e.value, "key": e.key, "category": e.category,
                 "source": "l1a_session_store"}
                for e in hits
            ]

        def _query_l1b():
            return "l1b", self.l1a.search(task, limit=top_k_per_layer)

        def _query_l2():
            try:
                result_l2 = self.l2.search_sync(task, top_k=top_k_per_layer)
                return "l2", result_l2
            except Exception as e:
                # L2 不可用時記錄警告（FalkorDB 未啟動等）
                err_msg = str(e)[:80]
                if not hasattr(self, '_l2_warned'):
                    logger.warning("L2（Graphiti）不可用，時序記憶已降級：%s", err_msg)
                    self._l2_warned = True  # 只警告一次，不重複噪音
                raise

        def _query_l3():
            if not self.l3:
                return "l3", []
            ctx = self.l3.get_context(task)
            return "l3", [{"content": ctx, "type": "semantic"}] if ctx else []

        futures_map = {}
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="brain_query") as ex:
            import time as _time
            def _timed(fn):
                _t0 = _time.monotonic()
                try:
                    lyr, data = fn()
                    ms = int((_time.monotonic() - _t0) * 1000)
                    return lyr, data, LayerTrace(layer=lyr, elapsed_ms=ms, hits=len(data))
                except Exception as _e:
                    ms = int((_time.monotonic() - _t0) * 1000)
                    lyr = getattr(fn, "__name__", "?").replace("_query_","")
                    return lyr, [], LayerTrace(layer=lyr, elapsed_ms=ms, status="error", error=str(_e)[:60])

            futures_map[ex.submit(_timed, _query_l1a)] = "l1a"
            futures_map[ex.submit(_timed, _query_l1b)] = "l1b"
            futures_map[ex.submit(_timed, _query_l2)]  = "l2"
            futures_map[ex.submit(_timed, _query_l3)]  = "l3"

            for future in as_completed(futures_map, timeout=5.0):
                try:
                    layer, data, trace = future.result()
                    result.traces.append(trace)
                    if layer == "l1a":
                        result.l1_working = data
                    elif layer == "l1b":
                        # 合併 L1b，去除 L1a 已有的 key
                        l1a_keys = {h.get("key","") for h in result.l1_working}
                        for h in data:
                            if h.get("path","") not in l1a_keys:
                                h["source"] = "l1b_memory_tool"
                                result.l1_working.append(h)
                    elif layer == "l2":
                        result.l2_temporal = data
                    elif layer == "l3":
                        result.l3_semantic = data
                except Exception as e:
                    layer = futures_map.get(future, "?")
                    logger.warning("parallel_query_failed: layer=%s error=%s", layer, str(e)[:100])

        result.elapsed_ms = int((time.monotonic() - t0) * 1_000)
        logger.debug("brain_query_done: task=%s %s", task[:40], result.trace_summary())
        return result

    def status(self) -> dict:
        """三層狀態報告"""
        return {
            "l1_working_memory": {
                "backend":  "SQLite",
                "available": True,
                **self.l1a.stats(),
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
            mems = self.l1a.get_all()
            for m in mems:
                self.l1a.handle_delete({"path": m["path"]})
            logger.info("l1_cleared", count=len(mems))
            return len(mems)
        except Exception as e:
            logger.error("l1_clear_failed: %s", str(e)[:100])
            return 0
