"""
project_brain/conflict_resolver.py — VISION-02 知識衝突自動解決

當 DecayEngine 偵測到兩個矛盾的知識節點時，透過 LLM 仲裁
決定哪一個更可信，而非對雙方均等懲罰。

設計原則：
  - 啟用條件：環境變數 BRAIN_CONFLICT_RESOLVE=1（預設關閉）
  - Duck-typed client：支援 anthropic.Anthropic 或 OllamaClient（同 krb_ai_assist.py）
  - 仲裁結果：winner="A"|"B"|"both"
    - A 或 B 勝出：winner +0.05 confidence boost，loser 套用正常 F4 懲罰
    - both：雙方套用較輕的 0.85× 懲罰（而非預設 0.7×）
  - 仲裁失敗時靜默回退到原始 F4 均等懲罰（降級優先原則）
  - 每對節點最多仲裁一次（24 小時快取，避免重複 API 呼叫）

使用方式：
  resolver = ConflictResolver(brain_db, graph)
  result   = resolver.arbitrate(node_id_a, node_id_b)
  resolver.apply_resolution(result, node_id_a, node_id_b)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── 常數 ──────────────────────────────────────────────────────────
DEFAULT_MODEL        = "claude-haiku-4-5-20251001"
DEFAULT_OLLAMA_MODEL = "llama3.2"
DEFAULT_OLLAMA_URL   = "http://localhost:11434"
CACHE_SECONDS        = 86400   # 24 小時快取
MAX_CONTENT_CHARS    = 400     # prompt 中每節點最大字元數
WINNER_BOOST         = 0.05    # 勝者 confidence 加成
BOTH_PENALTY         = 0.85    # "both" 時的輕量懲罰因子（非勝負情況）

# Prompt Injection 防護
_INJECTION_PATTERNS = re.compile(
    r"\b(ignore|forget|override|disregard|pretend|jailbreak|"
    r"act as|new instruction|system:|<\|im_start\|>)\b",
    re.IGNORECASE,
)


@dataclass
class ArbitrationResult:
    """LLM 仲裁結果"""
    node_id_a:       str
    node_id_b:       str
    winner:          str          # "A" | "B" | "both" | "error"
    reasoning:       str
    resolution_note: str


# ══════════════════════════════════════════════════════════════════
#  OllamaClient（同 krb_ai_assist.py duck-type 介面）
# ══════════════════════════════════════════════════════════════════

class _OllamaContent:
    __slots__ = ("text",)
    def __init__(self, text: str) -> None:
        self.text = text


class _OllamaResponse:
    __slots__ = ("content",)
    def __init__(self, text: str) -> None:
        self.content = [_OllamaContent(text)]


class _OllamaMessages:
    def __init__(self, base_url: str, timeout: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout  = timeout

    def create(self, model: str, max_tokens: int, messages: list[dict], **_kw):
        payload = json.dumps({
            "model":    model,
            "messages": messages,
            "stream":   False,
            "options":  {"num_predict": max_tokens},
            "format":   "json",
        }).encode()
        req = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            body = json.loads(resp.read())
        return _OllamaResponse(body["message"]["content"])


class OllamaClient:
    """本地 Ollama 後端，介面與 anthropic.Anthropic() 相容（duck-typed）"""

    def __init__(self, base_url: str = DEFAULT_OLLAMA_URL, timeout: int = 30) -> None:
        self.messages = _OllamaMessages(base_url, timeout)


# ══════════════════════════════════════════════════════════════════
#  ConflictResolver
# ══════════════════════════════════════════════════════════════════

class ConflictResolver:
    """
    LLM 輔助的知識衝突仲裁器。

    Args:
        brain_db: BrainDB 實例（用於讀取節點和更新 confidence）
        graph:    TemporalGraph 實例（用於讀取節點內容）
        client:   LLM client（Anthropic 或 OllamaClient），None = 自動選擇
        model:    模型名稱，None = 自動選擇
    """

    def __init__(self, brain_db, graph, client=None, model: str | None = None):
        self._db    = brain_db
        self._graph = graph
        self._client, self._model = self._resolve_client(client, model)
        self._cache: dict[str, tuple[float, ArbitrationResult]] = {}

    # ── 建立 client ──────────────────────────────────────────────

    @staticmethod
    def _resolve_client(client, model):
        if client is not None:
            return client, model or DEFAULT_MODEL

        # 優先 Anthropic（若有 API key）
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if key:
            try:
                import anthropic
                return anthropic.Anthropic(api_key=key), DEFAULT_MODEL
            except ImportError:
                pass

        # 回退 Ollama
        ollama_url = os.environ.get("BRAIN_OLLAMA_URL", DEFAULT_OLLAMA_URL)
        ollama_model = os.environ.get("BRAIN_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        try:
            urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=2)
            return OllamaClient(ollama_url), ollama_model
        except Exception:
            pass

        return None, None

    # ── 公開 API ─────────────────────────────────────────────────

    def arbitrate(self, node_id_a: str, node_id_b: str) -> ArbitrationResult:
        """
        仲裁兩個矛盾節點，回傳 ArbitrationResult。
        若 LLM 不可用或呼叫失敗，回傳 winner="error"（呼叫方應回退到均等懲罰）。
        """
        # 快取檢查（pair 無序）
        cache_key = ":".join(sorted([node_id_a, node_id_b]))
        now = time.monotonic()
        if cache_key in self._cache:
            ts, cached = self._cache[cache_key]
            if now - ts < CACHE_SECONDS:
                return cached

        if not self._client:
            return ArbitrationResult(node_id_a, node_id_b, "error", "no LLM client", "")

        # 讀取節點內容
        node_a = self._fetch_node(node_id_a)
        node_b = self._fetch_node(node_id_b)
        if not node_a or not node_b:
            return ArbitrationResult(node_id_a, node_id_b, "error", "node not found", "")

        # 呼叫 LLM
        result = self._call_llm(node_id_a, node_id_b, node_a, node_b)

        # 寫入快取
        self._cache[cache_key] = (now, result)
        return result

    def apply_resolution(
        self,
        result:      ArbitrationResult,
        orig_conf_a: float,
        orig_conf_b: float,
        penalty:     float = 0.7,
    ) -> tuple[float, float]:
        """
        根據仲裁結果調整兩個節點的 confidence 乘數。

        Returns:
            (factor_a, factor_b) — 要乘上原始 confidence 的因子。
            呼叫方負責 clamp 到合理範圍並寫入 DB。
        """
        if result.winner == "A":
            # A 勝 → A 取得 boost，B 受正常懲罰
            factor_a = min(1.0, (orig_conf_a + WINNER_BOOST) / max(orig_conf_a, 0.01))
            factor_b = penalty
            self._safe_feedback(result.node_id_a, helpful=True)
            self._safe_feedback(result.node_id_b, helpful=False)

        elif result.winner == "B":
            # B 勝 → B 取得 boost，A 受正常懲罰
            factor_a = penalty
            factor_b = min(1.0, (orig_conf_b + WINNER_BOOST) / max(orig_conf_b, 0.01))
            self._safe_feedback(result.node_id_a, helpful=False)
            self._safe_feedback(result.node_id_b, helpful=True)

        elif result.winner == "both":
            # 雙方均有效，輕量懲罰
            factor_a = BOTH_PENALTY
            factor_b = BOTH_PENALTY

        else:
            # error / unknown → 回退到原始均等懲罰
            factor_a = penalty
            factor_b = penalty

        logger.debug(
            "ConflictResolver: %s vs %s → winner=%s fa=%.3f fb=%.3f",
            result.node_id_a[:8], result.node_id_b[:8], result.winner, factor_a, factor_b,
        )
        return factor_a, factor_b

    # ── 私有方法 ─────────────────────────────────────────────────

    def _fetch_node(self, node_id: str) -> dict | None:
        try:
            row = self._graph._conn.execute(
                "SELECT title, content, type FROM nodes WHERE id=? LIMIT 1",
                (node_id,),
            ).fetchone()
            if row:
                return {"title": row[0] or "", "content": row[1] or "", "type": row[2] or ""}
        except Exception as exc:
            logger.debug("ConflictResolver._fetch_node %s: %s", node_id, exc)
        return None

    def _safe_str(self, text: str) -> str:
        """截斷並清除 Prompt Injection"""
        text = (text or "")[:MAX_CONTENT_CHARS]
        text = _INJECTION_PATTERNS.sub("[redacted]", text)
        return text

    def _build_prompt(self, node_a: dict, node_b: dict) -> str:
        a_title   = self._safe_str(node_a["title"])
        a_content = self._safe_str(node_a["content"])
        b_title   = self._safe_str(node_b["title"])
        b_content = self._safe_str(node_b["content"])
        return (
            "You are a technical knowledge arbitrator. "
            "Two knowledge nodes in a project's knowledge base contradict each other. "
            "Decide which is more likely to be correct.\n\n"
            f"Node A ({node_a['type']}):\n"
            f"  Title: {a_title}\n"
            f"  Content: {a_content}\n\n"
            f"Node B ({node_b['type']}):\n"
            f"  Title: {b_title}\n"
            f"  Content: {b_content}\n\n"
            "Reply ONLY with valid JSON:\n"
            '{"winner": "A" or "B" or "both", '
            '"reasoning": "<one sentence>", '
            '"resolution_note": "<optional short note>"}'
        )

    def _call_llm(
        self,
        node_id_a: str,
        node_id_b: str,
        node_a: dict,
        node_b: dict,
    ) -> ArbitrationResult:
        prompt = self._build_prompt(node_a, node_b)
        try:
            resp = self._client.messages.create(
                model      = self._model,
                max_tokens = 256,
                messages   = [{"role": "user", "content": prompt}],
            )
            raw  = resp.content[0].text.strip()
            data = json.loads(raw)
            winner = str(data.get("winner", "both")).upper()
            if winner not in ("A", "B", "BOTH"):
                winner = "both"
            return ArbitrationResult(
                node_id_a       = node_id_a,
                node_id_b       = node_id_b,
                winner          = winner.lower() if winner == "BOTH" else winner,
                reasoning       = str(data.get("reasoning", ""))[:500],
                resolution_note = str(data.get("resolution_note", ""))[:200],
            )
        except json.JSONDecodeError as exc:
            logger.debug("ConflictResolver: JSON parse error: %s", exc)
        except Exception as exc:
            logger.debug("ConflictResolver: LLM call failed: %s", exc)

        return ArbitrationResult(node_id_a, node_id_b, "error", "LLM call failed", "")

    def _safe_feedback(self, node_id: str, helpful: bool) -> None:
        try:
            self._db.record_feedback(node_id, helpful=helpful)
        except Exception as exc:
            logger.debug("ConflictResolver._safe_feedback %s: %s", node_id, exc)
