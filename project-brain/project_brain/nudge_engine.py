"""
core/brain/nudge_engine.py — 主動提醒引擎（v8.0）

## 問題

Project Brain 的第三個結構性邊界：被動記憶。
只有人問 `brain context`，系統才回應。
知識庫裡的踩坑，不會主動在「快要踩到」的時候提醒。

## 解法

NudgeEngine 分析當前任務（L1a progress 條目）、
比對 L3 的 Pitfall 節點，找出高度相關的潛在風險，
透過 `/v1/nudges` 端點讓 Agent 在任務開始前主動詢問。

## 使用方式

    engine = NudgeEngine(graph, session_store)
    nudges = engine.check("實作 Stripe 退款 API")

    # → [Nudge(title="Webhook 必須冪等", urgency="high", ...)]

    # 或透過 brain serve
    curl "http://localhost:7891/v1/nudges?task=實作+Stripe+退款"
    # → {"count": 2, "nudges": [...]}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class Nudge:
    """單一提醒項目"""
    node_id:      str
    title:        str
    content:      str
    urgency:      Literal["high", "medium", "low"]
    confidence:   float
    applies_when: str = ""
    is_pinned:    bool = False

    def to_dict(self) -> dict:
        from project_brain.utils import confidence_label
        return {
            "node_id":          self.node_id,
            "title":            self.title,
            "content":          self.content[:300],
            "urgency":          self.urgency,
            "confidence":       round(self.confidence, 3),
            "confidence_label": confidence_label(self.confidence),  # H-1
            "applies_when":     self.applies_when,
            "is_pinned":        self.is_pinned,
        }


class NudgeEngine:
    """
    主動提醒引擎（v8.0）。

    檢索 L3 的 Pitfall 節點，按照優先度排序，
    過濾掉信心太低的條目，回傳潛在風險清單。

    優先度演算法：
    1. is_pinned=True → urgency="high"（最高優先）
    2. confidence > 0.7 → urgency="medium"
    3. confidence ≤ 0.7 → urgency="low"（仍然顯示，但排後）
    4. confidence < 0.4 → 排除（信心太低，不值得提醒）

    關鍵設計決策：
    - 不呼叫 LLM（即時性，0 費用）
    - 不依賴 L2（FalkorDB 可能不可用）
    - 只依賴 L3 SQLite（最穩定的層）
    """

    MIN_CONFIDENCE = 0.4  # 低於此值不提醒
    DEFAULT_TOP_K  = 5    # 預設最多回傳幾條

    def __init__(self, graph, session_store=None, brain_db=None):
        """
        Args:
            graph:         KnowledgeGraph 實例
            session_store: SessionStore 實例（選填，用於讀取當前進度 context）
            brain_db:      BrainDB 實例（選填）。補接後 brain.db 的 Pitfall 也能觸發 nudge。
                           若為 None，只查 KnowledgeGraph（向後相容）。
        """
        self.graph         = graph
        self.session_store = session_store
        self._brain_db     = brain_db  # NudgeEngine-BrainDB bridge (v0.6.0)

    def check(
        self,
        task:  str,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[Nudge]:
        """
        分析任務字串，回傳相關的潛在風險提醒。

        Args:
            task:  當前任務描述（關鍵字）
            top_k: 最多回傳幾條提醒

        Returns:
            list[Nudge]：按優先度排序（high > medium > low，同優先度按 confidence 排序）
        """
        nudges = self._from_l3_pitfalls(task, top_k * 2)   # 多搜一些再過濾

        # 補充 L1a 的 progress 上下文（如果有 session_store）
        if self.session_store:
            task_context = self._build_task_context()
            if task_context:
                extra = self._from_l3_pitfalls(task_context, top_k)
                seen  = {n.node_id for n in nudges}
                nudges.extend(n for n in extra if n.node_id not in seen)

        # 過濾低信心 + 排序 + 截取
        nudges = [n for n in nudges if n.confidence >= self.MIN_CONFIDENCE]
        nudges.sort(
            key=lambda n: (
                {"high": 0, "medium": 1, "low": 2}[n.urgency],
                -n.confidence,
                -int(n.is_pinned),
            )
        )
        result = nudges[:top_k]
        # FLY-04: emit nudge_triggered event for hit-rate measurement
        if result and self._brain_db:
            try:
                self._brain_db.emit("nudge_triggered", {
                    "task":     task[:100],
                    "count":    len(result),
                    "node_ids": [n.node_id for n in result],
                })
            except Exception:
                pass
        return result

    def check_on_commit(self, commit_hash: str, files_changed: list[str]) -> list[Nudge]:
        """
        git commit 後的主動風險檢查。

        分析本次 commit 涉及的檔案，找出可能相關的踩坑。
        由 BrainEventBus 的 git.commit handler 呼叫。

        Args:
            commit_hash:   commit hash
            files_changed: 本次 commit 修改的檔案列表

        Returns:
            list[Nudge]：高優先度的潛在風險（urgency="high" 才回傳）
        """
        # 從檔名提取關鍵字
        keywords = set()
        for f in files_changed:
            parts = f.replace("/", " ").replace("_", " ").replace("-", " ").split()
            keywords.update(p for p in parts if len(p) > 3)

        if not keywords:
            return []

        query = " ".join(list(keywords)[:5])
        nudges = self.check(query, top_k=10)
        return [n for n in nudges if n.urgency == "high"]

    # ── 內部實作 ──────────────────────────────────────────────────────

    def _from_l3_pitfalls(self, query: str, top_k: int) -> list[Nudge]:
        """從 L3 搜尋相關 Pitfall 節點（KnowledgeGraph + BrainDB 合併）。

        v0.6.0: 同時查詢 BrainDB，讓 `brain add` 手動加入的 Pitfall 也能觸發 nudge。
        結果以 node id 去重，BrainDB 結果優先（含 effective_confidence）。
        """
        # 1. KnowledgeGraph
        try:
            results = self.graph.search_nodes(
                query, node_type="Pitfall", limit=top_k
            )
        except Exception as e:
            logger.warning("NudgeEngine KnowledgeGraph search failed: %s", e)
            results = []

        # 2. BrainDB (補接)
        if self._brain_db is not None:
            try:
                db_results = self._brain_db.search_nodes(
                    query, node_type="Pitfall", limit=top_k
                )
                # Merge: BrainDB takes precedence (may carry effective_confidence)
                seen_ids = {r["id"] for r in results if "id" in r}
                for r in db_results:
                    if r.get("id") not in seen_ids:
                        results.append(r)
                        seen_ids.add(r.get("id"))
            except Exception as e:
                logger.debug("NudgeEngine BrainDB search failed: %s", e)

        nudges = []
        now    = datetime.now(timezone.utc)
        for r in results:
            # BUG-02 fix ①: skip deprecated nodes
            if r.get("is_deprecated"):
                continue
            # BUG-02 fix ②: skip nodes whose valid_until has passed
            valid_until = r.get("valid_until")
            if valid_until:
                try:
                    vu = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
                    if vu.tzinfo is None:
                        vu = vu.replace(tzinfo=timezone.utc)
                    if vu < now:
                        continue
                except Exception:
                    pass  # malformed date — include the nudge to be safe
            # BUG-02 fix ③: use explicit None-check instead of `or` so that
            # confidence=0.0 is not silently promoted to 0.7.
            raw_conf  = r.get("confidence")
            conf      = float(raw_conf) if raw_conf is not None else 0.7
            is_pinned = bool(r.get("is_pinned") or 0)
            urgency   = (
                "high"   if is_pinned or conf > 0.85 else
                "medium" if conf > 0.65 else
                "low"
            )
            nudges.append(Nudge(
                node_id      = r["id"],
                title        = r.get("title", ""),
                content      = (r.get("content") or ""),
                urgency      = urgency,
                confidence   = conf,
                applies_when = r.get("applicability_condition", ""),
                is_pinned    = is_pinned,
            ))
        return nudges

    def _build_task_context(self) -> str:
        """從 L1a 工作記憶提取當前任務上下文"""
        if not self.session_store:
            return ""
        try:
            progress = self.session_store.list_all(category="progress")
            recent   = sorted(progress, key=lambda e: e.created_at, reverse=True)[:3]
            return " ".join(e.value[:100] for e in recent)
        except Exception:
            return ""

    # ── DEEP-04: AI Auto-Confirmation Loop ──────────────────────────────

    def generate_questions(self, task: str, threshold: float = 0.5) -> list:
        """DEEP-04: For explicit AI confirmation — surfaces low-confidence nodes
        as structured questions that an AI agent can then auto-resolve via
        auto_resolve_batch() or answer_question().

        Prefer auto_resolve_batch() for fully autonomous operation.

        Returns: [{"node_id": ..., "question": "...", "current_confidence": 0.38}]
        """
        try:
            results = self.graph.search_nodes(task, limit=10)
        except Exception:
            return []

        questions = []
        for r in results:
            conf = float(r.get("confidence", 0.8) or 0.8)
            if conf >= threshold:
                continue
            title = r.get("title","")
            ntype = r.get("type","Note")
            if ntype == "Pitfall":
                q = f"以下踩坑描述是否仍然適用（conf={conf:.2f}）？「{title[:80]}」"
            elif ntype == "Rule":
                q = f"此規則目前是否仍然有效（conf={conf:.2f}）？「{title[:80]}」"
            elif ntype == "Decision":
                q = f"此架構決策是否需要重新評估（conf={conf:.2f}）？「{title[:80]}」"
            else:
                q = f"以下知識是否仍然正確（conf={conf:.2f}）？「{title[:80]}」"
            questions.append({
                "node_id":           r["id"],
                "question":          q,
                "current_confidence": round(conf, 3),
                "node_type":         ntype,
            })
        questions.sort(key=lambda x: x["current_confidence"])
        return questions[:5]

    def auto_resolve_batch(
        self,
        task:      str,
        threshold: float = 0.5,
        use_llm:   bool  = True,
        limit:     int   = 10,
    ) -> dict:
        """DEEP-04: AI 自動判斷低信心節點，無需人工介入。

        兩層判斷策略：
        1. Rule-based（零費用）：根據 adoption_count / access_count 信號直接裁決
        2. LLM-assisted（可選）：規則無法裁決時，呼叫 Anthropic/Ollama 取得 AI 意見

        此方法適合在 get_context() 後台靜默執行，讓知識庫持續自我優化。

        Returns:
            {
              "resolved": N,      # 已處理節點數
              "boosted":  N,      # 信心提升的節點數
              "downgraded": N,    # 信心降低的節點數
              "deprecated": N,    # 標記棄用的節點數
              "unchanged": N,     # 未變更的節點數
              "details": [...]    # 每個節點的裁決詳情
            }
        """
        if not self._brain_db:
            return {"resolved": 0, "boosted": 0, "downgraded": 0,
                    "deprecated": 0, "unchanged": 0, "details": []}

        try:
            results = self.graph.search_nodes(task, limit=limit)
        except Exception:
            results = []

        low_conf = [
            r for r in results
            if float(r.get("confidence", 0.8) or 0.8) < threshold
            and not r.get("is_deprecated")
        ]
        if not low_conf:
            return {"resolved": 0, "boosted": 0, "downgraded": 0,
                    "deprecated": 0, "unchanged": 0, "details": []}

        stats   = {"boosted": 0, "downgraded": 0, "deprecated": 0, "unchanged": 0}
        details = []

        for node in low_conf:
            node_id = node["id"]
            verdict, new_conf, reason = self._rule_verdict(node)

            # If rule says uncertain AND LLM available → ask LLM
            if verdict == "uncertain" and use_llm:
                try:
                    verdict, new_conf, reason = self._llm_verdict(node, task)
                except Exception as e:
                    logger.debug("LLM verdict failed for %s: %s", node_id, e)

            old_conf = float(node.get("confidence", 0.5) or 0.5)
            self._apply_verdict(node_id, node, old_conf, verdict, new_conf, reason, stats)
            details.append({
                "node_id":   node_id,
                "title":     node.get("title", "")[:60],
                "verdict":   verdict,
                "old_conf":  round(old_conf, 3),
                "new_conf":  round(new_conf, 3),
                "reason":    reason,
            })

        resolved = len(low_conf)
        logger.info("DEEP-04 auto_resolve: %d nodes | %s", resolved, stats)
        return {"resolved": resolved, **stats, "details": details}

    # ── DEEP-04 internals ────────────────────────────────────────────

    def _rule_verdict(self, node: dict) -> tuple[str, float, str]:
        """Rule-based verdict using usage signals. Returns (verdict, new_conf, reason)."""
        conf        = float(node.get("confidence",     0.5) or 0.5)
        adoption    = int(  node.get("adoption_count", 0)   or 0)
        access      = int(  node.get("access_count",   0)   or 0)
        emo_weight  = float(node.get("emotional_weight", 0.5) or 0.5)

        if adoption >= 5:
            new = min(0.90, conf + 0.20)
            return "valid", new, f"high adoption ({adoption}x confirmed helpful)"
        if adoption >= 2:
            new = min(0.80, conf + 0.15)
            return "valid", new, f"repeated adoption ({adoption}x helpful)"
        if adoption >= 1:
            new = min(0.70, conf + 0.10)
            return "likely_valid", new, f"adopted once ({adoption}x)"
        if access > 15 and adoption == 0:
            new = max(0.15, conf - 0.08)
            return "suspect", new, f"accessed {access}x but never confirmed helpful"
        if emo_weight >= 0.8 and adoption == 0 and access == 0:
            # High emotional weight but zero usage → might be outdated trauma
            return "uncertain", conf, "high emotional weight, no usage signal"
        return "uncertain", conf, "no usage signal"

    def _llm_verdict(self, node: dict, task: str) -> tuple[str, float, str]:
        """Call LLM to evaluate node validity. Returns (verdict, new_conf, reason)."""
        import os, json as _j
        prompt = (
            "You are evaluating a knowledge node in a software project's AI memory system.\n\n"
            f"Node type: {node.get('type','Note')}\n"
            f"Title: {node.get('title','')}\n"
            f"Content: {(node.get('content') or '')[:400]}\n"
            f"Current confidence: {float(node.get('confidence', 0.5)):.2f}\n"
            f"Used helpfully: {node.get('adoption_count', 0)} times\n"
            f"Accessed: {node.get('access_count', 0)} times\n\n"
            f"Current task context: \"{task[:200]}\"\n\n"
            "Evaluate if this knowledge is still accurate and applicable for a modern enterprise software project.\n"
            'Reply ONLY with JSON (no markdown): {"verdict": "valid"|"outdated"|"uncertain", '
            '"confidence": 0.0-1.0, "reason": "one sentence"}'
        )
        raw = self._call_llm(prompt)
        # Parse JSON — strip any markdown fences
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data = _j.loads(raw)
        verdict = data.get("verdict", "uncertain")
        new_conf = float(max(0.05, min(1.0, data.get("confidence", node.get("confidence", 0.5)))))
        reason   = str(data.get("reason", "LLM verdict"))[:120]
        return verdict, new_conf, reason

    def _call_llm(self, prompt: str) -> str:
        """Call LLM. Tries Anthropic first (BRAIN_LLM_PROVIDER), then Ollama."""
        import os, urllib.request, json as _j
        provider = os.environ.get("BRAIN_LLM_PROVIDER", "anthropic").lower()
        if provider in ("openai", "ollama") or os.environ.get("BRAIN_LLM_BASE_URL"):
            base_url = os.environ.get("BRAIN_LLM_BASE_URL", "http://localhost:11434/v1")
            model    = os.environ.get("BRAIN_LLM_MODEL", "llama3.2:3b")
            from openai import OpenAI
            client   = OpenAI(base_url=base_url, api_key="ollama")
            resp     = client.chat.completions.create(
                model=model, max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
            return resp.choices[0].message.content.strip()
        else:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")
            model  = os.environ.get("BRAIN_LLM_MODEL", "claude-haiku-4-5-20251001")
            client = anthropic.Anthropic(api_key=api_key)
            msg    = client.messages.create(
                model=model, max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
            return msg.content[0].text.strip()

    def _apply_verdict(
        self,
        node_id:  str,
        node:     dict,
        old_conf: float,
        verdict:  str,
        new_conf: float,
        reason:   str,
        stats:    dict,
    ) -> None:
        """Write verdict result to brain_db."""
        db = self._brain_db
        if not db:
            return
        try:
            if verdict == "outdated":
                db.deprecate_node(node_id, reason=f"AI auto-resolve: {reason}")
                stats["deprecated"] += 1
            elif verdict in ("valid", "likely_valid") and new_conf > old_conf:
                db.update_node(
                    node_id, confidence=new_conf,
                    changed_by="auto_resolve",
                    change_note=f"AI auto-confirm: {reason}",
                )
                stats["boosted"] += 1
            elif verdict == "suspect" and new_conf < old_conf:
                db.update_node(
                    node_id, confidence=new_conf,
                    changed_by="auto_resolve",
                    change_note=f"AI auto-downgrade: {reason}",
                )
                stats["downgraded"] += 1
            else:
                stats["unchanged"] += 1
        except Exception as e:
            logger.debug("_apply_verdict failed for %s: %s", node_id, e)
            stats["unchanged"] += 1
