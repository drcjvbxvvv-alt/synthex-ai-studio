"""
project_brain/pipeline/llm_judgment.py — Auto Knowledge Pipeline Layer 3

Layer 3 — LLM 判斷引擎。
接收 Layer 1/2 產生的 Signal，呼叫 LLM，輸出結構化 KnowledgeDecision
供 Layer 4 KnowledgeExecutor 消費。

設計原則（docs/AUTO_KNOWLEDGE_PIPELINE.md §6）：
  - 判斷與執行嚴格分離（LLM 不直接操作 DB）
  - 非同步、不阻塞主流程
  - 可降級：LLM 不可用時回傳 skip,signal_queue 可後續重試
  - 結構化輸出,可審計
  - 本地模型優先（Ollama gemma4:27b），雲端 Haiku fallback
  - Prompt Injection 防護

使用方式：
    # 推薦：從 brain.toml [pipeline.llm] 建立
    judge = LLMJudgmentEngine.from_brain_config(brain_dir)
    decision = judge.analyze(signal)

    # 也可手動注入 client（測試用）
    judge = LLMJudgmentEngine(client=mock_client, model="mock")
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from project_brain.pipeline.executor import (
    KnowledgeDecision,
    KnowledgeExecutor,
    NodeSpec,
)
from project_brain.pipeline.signal import Signal, SignalKind

logger = logging.getLogger(__name__)

# ── 常數 ──────────────────────────────────────────────────────────

DEFAULT_MODEL        = "gemma4:27b"
DEFAULT_OLLAMA_URL   = "http://localhost:11434"
DEFAULT_HAIKU_MODEL  = "claude-haiku-4-5-20251001"

# Signal raw_content 送入 prompt 的最大字元數（避免 context 爆炸）
MAX_RAW_CONTENT_CHARS = 2_000
MAX_SUMMARY_CHARS     = 500
MAX_RELATED_NODES     = 5

# 單次 LLM 呼叫最大 output tokens
MAX_OUTPUT_TOKENS = 512

# Prompt Injection 防護（與 krb_ai_assist.py / conflict_resolver.py 一致）
_INJECTION_PATTERNS = re.compile(
    r"\b(ignore|forget|override|disregard|pretend|jailbreak|"
    r"act as|new instruction|system:|<\|im_start\|>)\b",
    re.IGNORECASE,
)


def _safe(text: str, limit: int) -> str:
    """Prompt Injection 防護 + 長度截斷"""
    if not text:
        return ""
    text = _INJECTION_PATTERNS.sub("[filtered]", text)
    return text[:limit]


# ── LLMJudgmentEngine ────────────────────────────────────────────

class LLMJudgmentEngine:
    """
    Layer 3 — 將 Signal 轉換為 KnowledgeDecision 的 LLM 引擎。

    Client 介面要求（duck-typed，與 anthropic.Anthropic 相容）：
        client.messages.create(
            model=str, max_tokens=int, messages=[{"role": "user", "content": str}]
        ) -> Response
    其中 Response.content[0].text 為 LLM 原始輸出字串。

    支援的 client 類型：
        - anthropic.Anthropic (雲端 Claude)
        - krb_ai_assist.OllamaClient (本地 Ollama)

    失敗降級：LLM 任何錯誤 → KnowledgeDecision(action="skip", reason="llm_error: ...")
    """

    def __init__(
        self,
        client:    Any = None,
        model:     str = DEFAULT_MODEL,
        brain_dir: Optional[Path] = None,
        *,
        llm_client: "Any | None" = None,
    ) -> None:
        # C-02: prefer unified LLMClient, fall back to legacy duck-typed client
        self._llm_client = llm_client  # project_brain.integrations.llm_client.LLMClient
        self.client    = client        # legacy: anthropic.Anthropic / OllamaClient
        self.model     = model
        self.brain_dir = Path(brain_dir) if brain_dir else None

    # ── 工廠 ─────────────────────────────────────────────────────

    @classmethod
    def from_brain_config(
        cls,
        brain_dir: Optional[Path] = None,
    ) -> "LLMJudgmentEngine":
        """
        從 brain.toml [pipeline.llm] 建立 LLMJudgmentEngine（推薦方式）。

        C-02: 使用統一 LLMClient 介面（integrations/llm_client.py）。
        Fallback chain 由 from_brain_config() 工廠自動處理。
        """
        bd = Path(brain_dir) if brain_dir else None
        try:
            from project_brain.integrations.llm_client import from_brain_config as _factory
            llm = _factory("pipeline", brain_dir=bd)
            logger.debug(
                "LLMJudgmentEngine: using unified LLMClient %r", llm,
            )
            return cls(
                llm_client=llm,
                model=llm.model,
                brain_dir=bd,
            )
        except Exception as e:
            logger.warning(
                "LLMJudgmentEngine.from_brain_config failed: %s — "
                "falling back to legacy OllamaClient",
                e,
            )
            from project_brain.krb_ai_assist import OllamaClient
            return cls(
                client=OllamaClient(base_url=DEFAULT_OLLAMA_URL),
                model=DEFAULT_MODEL,
                brain_dir=bd,
            )

    # ── 主入口 ────────────────────────────────────────────────────

    def analyze(
        self,
        signal:        Signal,
        related_nodes: Optional[list[dict]] = None,
    ) -> KnowledgeDecision:
        """
        分析 Signal，產生 KnowledgeDecision。

        Args:
            signal:        Layer 1/2 產生的 Signal（已持久化到 signal_queue）
            related_nodes: 選填。與 signal 主題相關的既有知識節點列表
                           （由呼叫方先做關鍵字搜尋），用於讓 LLM 避免重複。
                           每個 dict 應至少有 title/content 欄位。

        Returns:
            KnowledgeDecision — action 為 "add" 或 "skip"。
            任何異常都安全降級為 skip，不會拋出。
        """
        if signal is None:
            logger.warning("LLMJudgmentEngine.analyze: signal is None")
            return KnowledgeDecision(
                action    = "skip",
                reason    = "signal is None",
                signal_id = "",
                llm_model = self.model,
            )

        prompt = self._build_prompt(signal, related_nodes or [])

        try:
            raw_text = self._call_llm(prompt)
        except Exception as e:
            logger.warning(
                "LLMJudgmentEngine.analyze: LLM call failed for signal_id=%s: %s",
                signal.id[:8], e,
            )
            return KnowledgeDecision(
                action    = "skip",
                reason    = f"llm_error: {str(e)[:150]}",
                signal_id = signal.id,
                llm_model = self.model,
            )

        # Parse JSON
        try:
            raw_dict = self._extract_json(raw_text)
        except Exception as e:
            logger.warning(
                "LLMJudgmentEngine.analyze: JSON parse failed for signal_id=%s: %s (raw=%r)",
                signal.id[:8], e, raw_text[:200],
            )
            return KnowledgeDecision(
                action    = "skip",
                reason    = f"json_parse_error: {str(e)[:100]}",
                signal_id = signal.id,
                llm_model = self.model,
            )

        # 注入 signal_id 和 llm_model（LLM 不一定會正確回填）
        raw_dict["signal_id"] = signal.id
        raw_dict["llm_model"] = self.model

        # 交給 KnowledgeExecutor.validate 做嚴格清洗
        decision = KnowledgeExecutor.validate(raw_dict)

        logger.info(
            "LLMJudgmentEngine.analyze: signal_id=%s kind=%s → action=%s conf=%.2f reason=%.60s",
            signal.id[:8],
            signal.kind.value if isinstance(signal.kind, SignalKind) else signal.kind,
            decision.action,
            decision.confidence,
            decision.reason,
        )
        return decision

    # ── Prompt 建構 ───────────────────────────────────────────────

    # C-04: signal-specific context hints for LLM prompt
    _SIGNAL_HINTS: dict[str, str] = {
        "mcp_tool_call": (
            "\nSignal-specific guidance (MCP_TOOL_CALL):\n"
            "- If this is an add_knowledge call with kind=Pitfall → high value, action=add, confidence=0.8\n"
            "- If this is a repeated get_context call with no new insights → action=skip\n"
            "- Focus on USAGE PATTERNS that reveal important project knowledge\n"
        ),
        "test_failure": (
            "\nSignal-specific guidance (TEST_FAILURE):\n"
            "- Extract the ROOT CAUSE and the fix, not just 'test failed'\n"
            "- Prefer kind=Pitfall for recurring patterns, kind=Rule for new constraints\n"
            "- If the failure is a flaky test or environment issue → action=skip\n"
        ),
        "knowledge_conflict": (
            "\nSignal-specific guidance (KNOWLEDGE_CONFLICT):\n"
            "- Two existing knowledge nodes contradict each other\n"
            "- Determine which is correct based on the content timestamps and confidence\n"
            "- If one clearly supersedes the other → action=add with kind=Decision explaining the resolution\n"
            "- If both are valid in different contexts → action=skip (they coexist)\n"
        ),
    }

    def _build_prompt(self, signal: Signal, related_nodes: list[dict]) -> str:
        """建構送給 LLM 的 prompt。輸入已做 injection 清理。"""
        kind = signal.kind.value if isinstance(signal.kind, SignalKind) else str(signal.kind)
        safe_summary = _safe(signal.summary, MAX_SUMMARY_CHARS)
        safe_content = _safe(signal.raw_content, MAX_RAW_CONTENT_CHARS)

        # 相關節點摘要（最多 N 筆）
        related_section = ""
        if related_nodes:
            items = []
            for n in related_nodes[:MAX_RELATED_NODES]:
                t = _safe(str(n.get("title", ""))[:120], 120)
                c = _safe(str(n.get("content", ""))[:200], 200)
                items.append(f"  - [{n.get('type', n.get('kind', '?'))}] {t}: {c}")
            if items:
                related_section = (
                    "\n\n既有相關知識（避免重複入庫）：\n"
                    + "\n".join(items)
                )

        # C-04: signal-specific hint
        hint = self._SIGNAL_HINTS.get(kind, "")

        return f"""You are a knowledge extraction assistant for a software engineering project.
Your task: analyze a signal from the project (git commit / task completion / etc.) and
decide whether it contains a concrete, actionable knowledge item worth persisting.

Signal:
  kind:    {kind}
  summary: {safe_summary}
  content: {safe_content}{related_section}

Reply with ONE valid JSON object ONLY (no markdown fences, no preamble):
{{
  "action":     "add" | "skip",
  "reason":     "<one sentence, ≤ 80 chars, 中文或英文皆可>",
  "confidence": <float 0.0-1.0, your confidence in this judgement>,
  "node": {{                                  // only required when action == "add"
    "title":       "<≤ 100 chars, declarative, no question marks>",
    "content":     "<≤ 400 chars, concrete and actionable>",
    "kind":        "Note" | "Decision" | "Pitfall" | "Rule" | "ADR" | "Component",
    "tags":        ["<lowercase>", "<short>"],
    "confidence":  <float 0.0-0.85, intrinsic confidence of the extracted knowledge>
  }}
}}

Decision rules:
- ADD only if the signal reveals a CONCRETE, REUSABLE insight:
  * Rule:     a constraint that must always be followed (e.g. "JWT must use RS256")
  * Pitfall:  a specific bug pattern + root cause (not vague "be careful about X")
  * Decision: a tradeoff chosen with rationale (e.g. "use Postgres because need JSONB")
  * ADR:      a documented architectural decision record
  * Note:     a concrete fact worth remembering (use sparingly)
- SKIP if the signal is:
  * A version bump, formatting change, typo fix, or trivial cleanup
  * A duplicate of the listed related knowledge above
  * Too vague or context-specific to be reusable ("fixed the bug")
  * A WIP / experiment / reverted change
- Pitfall MUST describe the root cause, not just "X didn't work"
- Never fabricate details not present in the signal content
- confidence for node.confidence should reflect how certain you are the knowledge is correct
  AND reusable in similar situations; keep ≤ 0.85 for auto-extracted knowledge{hint}"""

    # ── LLM 呼叫 ─────────────────────────────────────────────────

    def _call_llm(self, prompt: str) -> str:
        """
        呼叫 LLM 取得原始回應字串。

        C-02: 優先使用統一 LLMClient.complete()；若未提供則 fallback 到
        legacy duck-typed client.messages.create()。
        不做任何 parsing — 交給 _extract_json 處理。
        """
        if self._llm_client is not None:
            return self._llm_client.complete(
                prompt, max_tokens=MAX_OUTPUT_TOKENS,
            ).strip()
        # Legacy path: duck-typed anthropic / OllamaClient
        resp = self.client.messages.create(
            model      = self.model,
            max_tokens = MAX_OUTPUT_TOKENS,
            messages   = [{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()

    # ── JSON 解析 ─────────────────────────────────────────────────

    @staticmethod
    def _extract_json(raw: str) -> dict:
        """
        從 LLM 原始輸出中提取 JSON dict。

        處理策略：
          1. 移除 markdown 程式碼塊圍欄（```json ... ```）
          2. 尋找第一個 { ... } 片段
          3. json.loads 解析

        若完全失敗則拋出 exception（由呼叫方降級為 skip）。
        """
        if not raw:
            raise ValueError("empty LLM response")

        # 1. 移除 markdown fences
        cleaned = re.sub(r"```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        cleaned = cleaned.replace("```", "").strip()

        # 2. 如果不是以 { 開頭，嘗試找第一個 { ... 最後一個 }
        if not cleaned.startswith("{"):
            start = cleaned.find("{")
            end   = cleaned.rfind("}")
            if start == -1 or end == -1 or end < start:
                raise ValueError(f"no JSON object found in response: {raw[:150]}")
            cleaned = cleaned[start : end + 1]

        # 3. 解析
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError(f"JSON root is not a dict: {type(data).__name__}")
        return data
