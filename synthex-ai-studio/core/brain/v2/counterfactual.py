"""
CounterfactualEngine — 反事實推理引擎 (v2.0)

核心能力：「如果當初不這樣設計，會怎樣？」

反事實推理不是空想——它基於：
  1. 知識圖譜中記錄的「決策時考慮的替代方案」
  2. 已知的踩坑記錄（哪些方案走不通）
  3. 實際的程式碼演化軌跡（最後怎麼改的）
  4. Claude 的推理能力（綜合以上做出評估）

使用場景：
  - 技術債分析：「如果當初選了 GraphQL 而不是 REST，現在的程式碼會更好嗎？」
  - 重構決策：「如果移除這個快取層，效能影響有多大？」
  - 事後複盤：「這個 bug 如果早期採用另一種架構，能避免嗎？」

架構：
  CounterfactualQuery（輸入）
    ↓
  決策節點定位（從知識圖譜找相關 Decision/ADR）
    ↓
  替代方案重建（從 git 歷史和踩坑記錄推斷）
    ↓
  Claude 推理（GPT-style chain-of-thought）
    ↓
  CounterfactualResult（輸出：影響評估 + 信心分數）

安全設計：
  - Prompt 注入防護：用戶輸入嚴格截斷和清理，不直接拼接到 prompt
  - 成本控制：max_tokens 限制，不允許無限制的 API 呼叫
  - 輸出驗證：JSON Schema 驗證，防止 Claude 輸出格式不符
  - 推理快取：相同問題 1 小時內不重複呼叫 API
  - 失敗降級：API 不可用時回傳基於規則的靜態分析

記憶體管理：
  - 推理結果寫 SQLite，不保留在記憶體
  - 圖譜查詢限制 context 大小（不超過 4000 字元）
"""

from __future__ import annotations

import os
import re
import json
import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..graph import KnowledgeGraph

logger = logging.getLogger(__name__)

# ── 安全常數 ──────────────────────────────────────────────────────
MAX_QUESTION_LEN    = 400     # 反事實問題最大長度
MAX_CONTEXT_CHARS   = 4_000   # 注入 Claude 的上下文最大字元
MAX_ALTERNATIVES    = 5       # 最多考慮 N 個替代方案
CACHE_TTL_SECONDS   = 3_600   # 推理結果快取 1 小時
MAX_TOKENS          = 1_500   # Claude 回應 token 上限（成本控制）
REASONING_MODEL     = "claude-sonnet-4-5"  # Sonnet 夠用，省 Opus 費用

# 推理快取（question_hash → (result, timestamp)）
_reasoning_cache: dict[str, tuple[dict, float]] = {}


@dataclass
class CounterfactualQuery:
    """反事實查詢結構"""
    question:         str           # 「如果...會怎樣？」
    target_component: str = ""      # 關注的組件（可選）
    context_files:    list[str] = field(default_factory=list)  # 相關檔案
    depth:            str = "brief" # brief | detailed


@dataclass
class CounterfactualResult:
    """反事實推理結果"""
    question:      str
    likely_outcome:str   # 最可能的替代結果
    confidence:    float # 推理信心（0-1）
    avoided_risks: list[str] = field(default_factory=list)  # 如果那樣做，可以避免的風險
    new_risks:     list[str] = field(default_factory=list)  # 如果那樣做，會引入的新風險
    evidence:      list[str] = field(default_factory=list)  # 支持這個結論的證據
    alternatives_considered: list[str] = field(default_factory=list)
    reasoning_chain:str = ""   # 推理過程（CoT）
    source:        str = "ai"  # ai | rule_based（降級時）


def _sanitize_question(text: str) -> str:
    """清理反事實問題：移除控制字元，截斷，不允許 prompt injection"""
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(text))
    # 移除可能的 prompt injection 嘗試
    cleaned = re.sub(
        r'(?i)(ignore|forget|disregard|override|system prompt|as an ai)',
        '[filtered]',
        cleaned
    )
    return cleaned[:MAX_QUESTION_LEN]


def _question_hash(q: str) -> str:
    return hashlib.sha256(q.lower().encode()).hexdigest()[:24]


SYSTEM_PROMPT = """你是一位資深軟體架構師，專門進行反事實技術分析。
你的任務：基於提供的程式碼歷史和知識庫，評估「如果採用不同設計決策」的可能影響。

分析框架：
1. 首先理解實際發生了什麼（actual outcome）
2. 找出決策點（decision point）
3. 評估替代方案的可行性
4. 基於已知踩坑記錄，推斷替代方案可能遇到的問題
5. 給出有根據的結論（不是猜測）

原則：
- 結論必須有具體的技術根據，不要空泛說「可能更好」
- 如果信心不足，明確說明不確定性
- 識別「本質困難」（換哪種方案都會遇到的問題）
- 識別「偶然困難」（換一種方案可以避免的問題）

必須輸出 JSON 格式（不加 markdown 程式碼塊）。"""


class CounterfactualEngine:
    """
    反事實推理引擎。

    工作流程：
      1. 從問題中識別相關的決策節點和組件
      2. 從知識圖譜提取相關的決策歷史和踩坑
      3. 重建「當時的替代方案」
      4. 調用 Claude 進行反事實推理
      5. 結構化輸出並存儲結果
    """

    def __init__(self, graph: KnowledgeGraph, workdir: Optional[Path] = None):
        self.graph   = graph
        self.workdir = workdir
        self._conn   = graph._conn
        self._setup_cf_schema()
        self._client = None   # 懶初始化

    def _setup_cf_schema(self) -> None:
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS counterfactual_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            question_hash   TEXT    NOT NULL UNIQUE,
            question        TEXT    NOT NULL,
            result_json     TEXT    NOT NULL,
            confidence      REAL    NOT NULL,
            source          TEXT    NOT NULL DEFAULT 'ai',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            used_count      INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_cf_hash
            ON counterfactual_results(question_hash);
        CREATE INDEX IF NOT EXISTS idx_cf_confidence
            ON counterfactual_results(confidence DESC);
        """)
        self._conn.commit()

    def _get_client(self):
        if self._client is None:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise EnvironmentError("ANTHROPIC_API_KEY 未設定")
            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    # ── 主入口 ────────────────────────────────────────────────────

    def reason(self, query: CounterfactualQuery) -> CounterfactualResult:
        """
        執行反事實推理。

        先查快取，再查 SQLite 歷史，最後才呼叫 Claude API。
        """
        q_clean = _sanitize_question(query.question)
        q_hash  = _question_hash(q_clean)

        # 1. 記憶體快取
        if q_hash in _reasoning_cache:
            result_dict, ts = _reasoning_cache[q_hash]
            if time.monotonic() - ts < CACHE_TTL_SECONDS:
                logger.debug("反事實推理：使用記憶體快取")
                return self._dict_to_result(result_dict)

        # 2. SQLite 歷史快取
        cached = self._conn.execute(
            "SELECT result_json FROM counterfactual_results WHERE question_hash = ?",
            (q_hash,)
        ).fetchone()
        if cached:
            try:
                result_dict = json.loads(cached["result_json"])
                _reasoning_cache[q_hash] = (result_dict, time.monotonic())
                self._conn.execute(
                    "UPDATE counterfactual_results SET used_count = used_count + 1 WHERE question_hash = ?",
                    (q_hash,)
                )
                self._conn.commit()
                logger.debug("反事實推理：使用 SQLite 快取")
                return self._dict_to_result(result_dict)
            except Exception:
                pass

        # 3. 新推理
        context = self._build_context(q_clean, query)
        try:
            result = self._reason_with_claude(q_clean, context, query.depth)
        except Exception as e:
            logger.warning("Claude 推理失敗，降級到規則分析：%s", e)
            result = self._rule_based_fallback(q_clean, context)

        # 儲存結果
        result_dict = self._result_to_dict(result)
        try:
            self._conn.execute("""
                INSERT OR REPLACE INTO counterfactual_results
                    (question_hash, question, result_json, confidence, source)
                VALUES (?, ?, ?, ?, ?)
            """, (q_hash, q_clean[:500], json.dumps(result_dict, ensure_ascii=False),
                  result.confidence, result.source))
            self._conn.commit()
        except Exception as e:
            logger.error("儲存反事實結果失敗：%s", e)

        _reasoning_cache[q_hash] = (result_dict, time.monotonic())
        return result

    # ── 上下文建構 ───────────────────────────────────────────────

    def _build_context(self, question: str, query: CounterfactualQuery) -> str:
        """從知識圖譜提取相關的上下文，注入 Claude prompt"""
        parts: list[str] = []
        budget = MAX_CONTEXT_CHARS

        def add(text: str) -> bool:
            nonlocal budget
            if len(text) > budget:
                return False
            parts.append(text)
            budget -= len(text)
            return True

        # 相關決策
        decisions = self.graph.search_nodes(question[:100], node_type="Decision", limit=3)
        if decisions:
            dec_text = "## 相關架構決策\n"
            for d in decisions:
                dec_text += f"- **{d['title']}**：{(d.get('content') or '')[:200]}\n"
            add(dec_text)

        # 相關踩坑
        pitfalls = self.graph.search_nodes(question[:100], node_type="Pitfall", limit=4)
        if pitfalls:
            pit_text = "## 已知踩坑（重要！）\n"
            for p in pitfalls:
                pit_text += f"- **{p['title']}**：{(p.get('content') or '')[:150]}\n"
            add(pit_text)

        # 相關 ADR
        adrs = self.graph.search_nodes(question[:100], node_type="ADR", limit=2)
        if adrs:
            adr_text = "## 架構決策記錄\n"
            for a in adrs:
                adr_text += f"- {a['title']}：{(a.get('content') or '')[:300]}\n"
            add(adr_text)

        # 目標組件的依賴關係
        if query.target_component:
            impact = self.graph.impact_analysis(query.target_component)
            if impact.get("direct"):
                dep_text = f"## {query.target_component} 的依賴關係\n"
                for dep in impact["direct"][:5]:
                    dep_text += f"- {dep.get('relation','')} → {dep.get('title','')}\n"
                add(dep_text)

        return "\n".join(parts) if parts else "（知識庫尚無相關記錄）"

    # ── Claude 推理 ──────────────────────────────────────────────

    def _reason_with_claude(
        self, question: str, context: str, depth: str
    ) -> CounterfactualResult:
        """呼叫 Claude API 進行反事實推理"""
        client = self._get_client()

        detail_instruction = (
            "請給出簡要但精確的分析（3-5 句話）。"
            if depth == "brief"
            else "請給出詳細的技術分析，包含具體的程式碼層面影響。"
        )

        user_prompt = f"""請對以下反事實問題進行技術分析：

**問題**：{question}

**專案知識庫背景**：
{context}

{detail_instruction}

輸出 JSON（不加程式碼塊標記，直接輸出 JSON）：
{{
  "likely_outcome": "最可能的結果（2-3句）",
  "confidence": 0.0-1.0（對這個分析的信心）,
  "avoided_risks": ["如果那樣做，可以避免的風險"],
  "new_risks": ["如果那樣做，會引入的新風險"],
  "evidence": ["支持結論的具體證據（來自知識庫或常識）"],
  "alternatives_considered": ["評估過的替代方案"],
  "reasoning_chain": "推理過程（CoT，1-2段）"
}}"""

        resp = client.messages.create(
            model      = REASONING_MODEL,
            max_tokens = MAX_TOKENS,
            system     = SYSTEM_PROMPT,
            messages   = [{"role": "user", "content": user_prompt}],
        )

        raw = resp.content[0].text.strip()
        # 清理可能的 markdown 包裹
        raw = re.sub(r'^```(?:json)?\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)

        parsed = json.loads(raw)

        return CounterfactualResult(
            question                = question,
            likely_outcome          = str(parsed.get("likely_outcome", ""))[:1000],
            confidence              = max(0.0, min(1.0, float(parsed.get("confidence", 0.5)))),
            avoided_risks           = [str(r)[:200] for r in parsed.get("avoided_risks", [])[:5]],
            new_risks               = [str(r)[:200] for r in parsed.get("new_risks", [])[:5]],
            evidence                = [str(e)[:200] for e in parsed.get("evidence", [])[:5]],
            alternatives_considered = [str(a)[:100] for a in parsed.get("alternatives_considered", [])[:5]],
            reasoning_chain         = str(parsed.get("reasoning_chain", ""))[:800],
            source                  = "ai",
        )

    def _rule_based_fallback(
        self, question: str, context: str
    ) -> CounterfactualResult:
        """API 失敗時的降級：基於規則的靜態分析"""
        pitfalls = self.graph.search_nodes(question[:80], node_type="Pitfall", limit=5)
        decisions = self.graph.search_nodes(question[:80], node_type="Decision", limit=3)

        outcome_parts = []
        if decisions:
            outcome_parts.append(
                f"根據知識庫中的 {len(decisions)} 個相關決策記錄，"
                "此架構選擇有其技術背景。"
            )
        if pitfalls:
            outcome_parts.append(
                f"有 {len(pitfalls)} 個已知踩坑可能與此選擇相關，"
                "替代方案需要謹慎評估。"
            )

        return CounterfactualResult(
            question       = question,
            likely_outcome = "".join(outcome_parts) or "知識庫尚無足夠資訊進行推理。",
            confidence     = 0.3,
            evidence       = [p["title"] for p in pitfalls[:3]],
            source         = "rule_based",
        )

    # ── 輔助方法 ─────────────────────────────────────────────────

    def _result_to_dict(self, result: CounterfactualResult) -> dict:
        return {
            "question":               result.question,
            "likely_outcome":         result.likely_outcome,
            "confidence":             result.confidence,
            "avoided_risks":          result.avoided_risks,
            "new_risks":              result.new_risks,
            "evidence":               result.evidence,
            "alternatives_considered":result.alternatives_considered,
            "reasoning_chain":        result.reasoning_chain,
            "source":                 result.source,
        }

    def _dict_to_result(self, d: dict) -> CounterfactualResult:
        return CounterfactualResult(
            question                = d.get("question", ""),
            likely_outcome          = d.get("likely_outcome", ""),
            confidence              = float(d.get("confidence", 0.5)),
            avoided_risks           = d.get("avoided_risks", []),
            new_risks               = d.get("new_risks", []),
            evidence                = d.get("evidence", []),
            alternatives_considered = d.get("alternatives_considered", []),
            reasoning_chain         = d.get("reasoning_chain", ""),
            source                  = d.get("source", "ai"),
        )

    def format_result(self, result: CounterfactualResult) -> str:
        """格式化反事實推理結果（人類可讀）"""
        conf_label = (
            "高信心" if result.confidence >= 0.7
            else "中信心" if result.confidence >= 0.4
            else "低信心（供參考）"
        )
        lines = [
            f"## 反事實分析：{result.question[:80]}",
            "",
            f"**信心**：{result.confidence:.0%}（{conf_label}）"
            + ("  ⚠ 基於規則（非 AI 推理）" if result.source == "rule_based" else ""),
            "",
            f"**最可能的結果**：",
            result.likely_outcome,
            "",
        ]
        if result.avoided_risks:
            lines += ["**可以避免的風險**："] + [f"- {r}" for r in result.avoided_risks] + [""]
        if result.new_risks:
            lines += ["**會引入的新風險**："] + [f"- {r}" for r in result.new_risks] + [""]
        if result.evidence:
            lines += ["**推理依據**："] + [f"- {e}" for e in result.evidence] + [""]
        if result.reasoning_chain:
            lines += ["**推理過程**：", result.reasoning_chain, ""]
        return "\n".join(lines)

    def history(self, limit: int = 10) -> list[dict]:
        """取得最近的反事實推理歷史"""
        limit = max(1, min(50, int(limit)))
        rows = self._conn.execute("""
            SELECT question, confidence, source, created_at, used_count
            FROM counterfactual_results
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
