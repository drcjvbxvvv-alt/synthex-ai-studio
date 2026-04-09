"""
project_brain/llm_judgment.py — Auto Knowledge Pipeline Layer 3

Layer 3 — LLM 判斷引擎。
接收 Layer 1/2 產生的 Signal，呼叫 LLM，輸出結構化 KnowledgeDecision
供 Layer 4 KnowledgeExecutor 消費。

設計原則（docs/AUTO_KNOWLEDGE_PIPELINE.md §6）：
  - 判斷與執行嚴格分離（LLM 不直接操作 DB）
  - 非同步、不阻塞主流程
  - 可降級：LLM 不可用時回傳 skip，signal_queue 可後續重試
  - 結構化輸出，可審計
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

from project_brain.pipeline import (
    KnowledgeDecision,
    KnowledgeExecutor,
    NodeSpec,
    Signal,
    SignalKind,
)

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
        client:    Any,
        model:     str = DEFAULT_MODEL,
        brain_dir: Optional[Path] = None,
    ) -> None:
        self.client    = client
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

        Fallback chain:
          [pipeline.llm] Ollama (gemma4:27b, primary) →
          [pipeline.llm.fallback] Anthropic Haiku →
          OllamaClient default (本地 llama3.2, last resort)

        Ollama provider 使用 krb_ai_assist.OllamaClient（無需 openai 套件，
        介面與 anthropic.Anthropic 相容）。
        """
        try:
            from project_brain.brain_config import (
                load_config, _find_brain_dir, _is_ollama_available,
            )
            bd  = Path(brain_dir) if brain_dir else _find_brain_dir()
            cfg = load_config(bd)
            pl  = cfg.pipeline.llm

            # 1. 嘗試 [pipeline.llm] 主要設定（通常是 Ollama）
            if pl.provider in ("ollama", "openai"):
                if _is_ollama_available(pl.base_url, timeout=2):
                    from project_brain.krb_ai_assist import OllamaClient
                    client = OllamaClient(
                        base_url=pl.base_url.replace("/v1", ""),
                        timeout=pl.timeout,
                    )
                    logger.debug(
                        "LLMJudgmentEngine: using [pipeline.llm] Ollama model=%s",
                        pl.model,
                    )
                    return cls(client=client, model=pl.model, brain_dir=bd)
                logger.debug(
                    "LLMJudgmentEngine: [pipeline.llm] Ollama 不可用 (%s)，嘗試 fallback",
                    pl.base_url,
                )

            # 2. fallback → Anthropic（通常是 Haiku）
            fb = pl.fallback
            if fb.provider == "anthropic":
                import os
                if os.environ.get("ANTHROPIC_API_KEY"):
                    try:
                        import anthropic
                        client = anthropic.Anthropic()
                        logger.info(
                            "LLMJudgmentEngine: using Anthropic fallback model=%s",
                            fb.model,
                        )
                        return cls(client=client, model=fb.model, brain_dir=bd)
                    except ImportError:
                        logger.debug("anthropic 套件未安裝，跳過 Anthropic fallback")

            # 3. 最終 fallback → 本地 OllamaClient 預設位址
            from project_brain.krb_ai_assist import OllamaClient
            logger.warning(
                "LLMJudgmentEngine: 無可用 LLM，使用預設 OllamaClient (%s)",
                DEFAULT_OLLAMA_URL,
            )
            return cls(
                client=OllamaClient(base_url=DEFAULT_OLLAMA_URL),
                model=DEFAULT_MODEL,
                brain_dir=bd,
            )

        except Exception as e:
            logger.warning(
                "LLMJudgmentEngine.from_brain_config failed: %s，使用 OllamaClient 預設",
                e,
            )
            from project_brain.krb_ai_assist import OllamaClient
            return cls(
                client=OllamaClient(base_url=DEFAULT_OLLAMA_URL),
                model=DEFAULT_MODEL,
                brain_dir=Path(brain_dir) if brain_dir else None,
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
  AND reusable in similar situations; keep ≤ 0.85 for auto-extracted knowledge"""

    # ── LLM 呼叫 ─────────────────────────────────────────────────

    def _call_llm(self, prompt: str) -> str:
        """
        呼叫 LLM 取得原始回應字串。

        使用 duck-typed 介面（與 anthropic.Anthropic.messages.create 相容）。
        不做任何 parsing — 交給 _extract_json 處理。
        """
        resp = self.client.messages.create(
            model      = self.model,
            max_tokens = MAX_OUTPUT_TOKENS,
            messages   = [{"role": "user", "content": prompt}],
        )
        # 與 anthropic Response / OllamaResponse 相容
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
