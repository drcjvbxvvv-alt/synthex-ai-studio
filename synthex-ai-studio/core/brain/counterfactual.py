"""
CounterfactualReasoner — 反事實推理引擎 (Project Brain v2.0)

核心問題：「如果當初不這樣設計，會怎樣？」

這個問題在軟體工程中極為重要，卻幾乎沒有工具能回答：
  - 「我們選了 PostgreSQL，如果選 MongoDB 會怎樣？」
  - 「我們沒用微服務，如果用了現在會是什麼情況？」
  - 「這個 bug 的根本原因是什麼決策導致的？」

設計原則（Claude 輔助 + 結構化儲存）：
  1. Counterfactual 是 Decision 節點的「反面鏡子」
  2. 每個 Decision 可以有 1-3 個 Counterfactual 替代路徑
  3. Claude 根據 Decision 的內容、時間背景、技術環境推理替代結果
  4. 結果用「影響矩陣」儲存：(技術難度, 維護成本, 擴充性, 風險)
  5. 反事實本身也是知識，存入知識圖譜

安全設計：
  - Claude API 呼叫有 token 限制，防止無限生成
  - 推理結果有信心區間，不作為確定性判斷
  - 所有 Claude 輸出經過 JSON schema 驗證
  - 防止反事實鏈無限遞迴（最大深度限制）

記憶體管理：
  - 推理結果快取在 .brain/counterfactuals/ 目錄
  - 快取 key = decision_node_id + content_hash
  - 快取過期時間：30 天（知識更新後重新計算）
"""

from __future__ import annotations

import os
import re
import json
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

from .graph import KnowledgeGraph

logger = logging.getLogger(__name__)

# ── 安全常數 ────────────────────────────────────────────────────
MAX_ALTERNATIVES       = 3      # 每個決策最多生成幾個替代路徑
MAX_CHAIN_DEPTH        = 2      # 反事實鏈最大深度（防止遞迴爆炸）
MAX_REASONING_TOKENS   = 1500   # Claude 推理的 max_tokens
CACHE_TTL_DAYS         = 30     # 快取有效期
MAX_DECISION_CONTENT   = 2000   # 輸入決策內容的最大字元

# 影響矩陣的維度（1-10 分）
IMPACT_DIMENSIONS = [
    "technical_complexity",   # 實作複雜度
    "maintenance_cost",       # 長期維護成本
    "scalability",            # 擴充性
    "team_learning_curve",    # 團隊學習曲線
    "risk_level",             # 風險等級
    "time_to_market",         # 上市時間
]

REASONING_SYSTEM_PROMPT = """你是一位資深軟體架構師，專長是分析技術決策的反事實場景。
你的任務是評估：如果採取了不同的技術決策，結果會如何。

分析原則：
1. 基於時代背景（不用現在的標準批評過去的決策）
2. 考慮具體的技術和業務脈絡
3. 給出合理的、有根據的評估，不是純粹猜測
4. 誠實標注不確定性

輸出格式：嚴格 JSON，不要 markdown，不要解釋。"""


class ImpactMatrix:
    """反事實替代路徑的影響矩陣"""
    __slots__ = ('dimensions', 'scores', 'confidence_interval', 'reasoning')

    def __init__(self):
        self.dimensions: list[str]   = IMPACT_DIMENSIONS[:]
        self.scores: dict[str, float]= {d: 5.0 for d in IMPACT_DIMENSIONS}
        self.confidence_interval: float = 0.3   # ±30% 不確定性
        self.reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "scores":    {k: round(v, 2) for k, v in self.scores.items()},
            "uncertainty": round(self.confidence_interval, 2),
            "reasoning": self.reasoning[:500],
        }


class CounterfactualPath:
    """一條反事實替代路徑"""
    __slots__ = ('path_id', 'decision_id', 'alternative_title',
                 'alternative_description', 'impact', 'cascade_effects',
                 'probability_of_success', 'created_at', 'was_viable')

    def __init__(self, path_id: str, decision_id: str):
        self.path_id              = path_id
        self.decision_id          = decision_id
        self.alternative_title    = ""
        self.alternative_description = ""
        self.impact               = ImpactMatrix()
        self.cascade_effects: list[str] = []
        self.probability_of_success: float = 0.5
        self.created_at           = datetime.now(timezone.utc).isoformat()
        self.was_viable           = True    # 這個替代方案在當時是否技術上可行

    def to_dict(self) -> dict:
        return {
            "path_id":             self.path_id,
            "decision_id":         self.decision_id,
            "alternative_title":   self.alternative_title,
            "alternative_description": self.alternative_description[:800],
            "impact":              self.impact.to_dict(),
            "cascade_effects":     self.cascade_effects[:5],
            "probability_of_success": round(self.probability_of_success, 2),
            "was_viable":          self.was_viable,
            "created_at":          self.created_at,
        }


class CounterfactualReasoner:
    """
    反事實推理引擎。

    使用方式：
        reasoner = CounterfactualReasoner(graph, workdir=brain_dir)
        paths = reasoner.analyze(decision_node_id)
        # → 回傳 2-3 個替代路徑，每個帶有影響矩陣和連鎖效應分析

        # 也可以用自然語言提問
        result = reasoner.ask("如果我們用 MongoDB 而不是 PostgreSQL 會怎樣？")
    """

    def __init__(self, graph: KnowledgeGraph, brain_dir: Path,
                 model: str = "claude-sonnet-4-5"):
        self.graph      = graph
        self.cache_dir  = brain_dir / "counterfactuals"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model      = model
        self.client     = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
        self._call_count = 0  # 追蹤 API 呼叫次數

    # ── 主入口：分析決策節點 ─────────────────────────────────────

    def analyze(
        self,
        decision_node_id: str,
        depth: int = 0,
        context: str = "",
    ) -> list[CounterfactualPath]:
        """
        分析一個決策節點的反事實替代路徑。

        Args:
            decision_node_id: 知識圖譜中的決策節點 ID
            depth:            遞迴深度（內部使用，不需手動設定）
            context:          額外的上下文資訊

        Returns:
            CounterfactualPath 列表
        """
        if depth >= MAX_CHAIN_DEPTH:
            logger.debug("反事實鏈達到最大深度 %d，停止遞迴", MAX_CHAIN_DEPTH)
            return []

        # 讀取決策節點
        node = self.graph.get_node(decision_node_id)
        if not node:
            raise ValueError(f"找不到節點：{decision_node_id}")
        if node.get("type") != "Decision":
            raise ValueError(f"節點 {decision_node_id} 不是 Decision 類型")

        # 快取查詢
        cache_key = self._cache_key(decision_node_id, node.get("content", ""))
        cached    = self._load_cache(cache_key)
        if cached:
            logger.debug("反事實推理：命中快取 %s", decision_node_id)
            return [self._dict_to_path(d) for d in cached]

        # 讀取相關上下文（依賴關係、踩坑記錄）
        related_knowledge = self._gather_context(decision_node_id, node)

        # 呼叫 Claude 推理
        paths = self._reason_with_claude(node, related_knowledge, context)

        # 儲存到知識圖譜和快取
        for path in paths:
            self._store_path(path)
        self._save_cache(cache_key, [p.to_dict() for p in paths])

        return paths

    def ask(self, question: str, context: str = "") -> dict:
        """
        自然語言反事實查詢介面。
        「如果我們用 X 而不是 Y，現在會是什麼狀況？」

        Returns:
            {"question": str, "analysis": str, "paths": list, "confidence": float}
        """
        question = question[:500]  # 長度限制

        # 從問題中嘗試找到相關的決策節點
        related_nodes = self.graph.search_nodes(question, node_type="Decision", limit=3)

        if related_nodes:
            # 找到相關決策，進行結構化分析
            node_id = related_nodes[0].get("id", "")
            if node_id:
                try:
                    paths = self.analyze(node_id, context=question)
                    return {
                        "question":  question,
                        "matched_decision": related_nodes[0].get("title", ""),
                        "paths":     [p.to_dict() for p in paths],
                        "analysis":  self._summarize_paths(paths),
                        "confidence":0.75,
                    }
                except Exception as e:
                    logger.warning("analyze 失敗，改用自由推理：%s", e)

        # 沒找到相關節點，直接用 Claude 自由推理
        analysis = self._free_reasoning(question, context)
        return {
            "question":  question,
            "matched_decision": None,
            "paths":     [],
            "analysis":  analysis,
            "confidence":0.5,   # 自由推理信心較低
        }

    # ── 核心推理 ────────────────────────────────────────────────

    def _reason_with_claude(
        self,
        node: dict,
        related: dict,
        extra_context: str,
    ) -> list[CounterfactualPath]:
        """呼叫 Claude 生成反事實替代路徑"""
        decision_content = (node.get("content") or "")[:MAX_DECISION_CONTENT]
        decision_title   = (node.get("title")   or "")[:200]
        created_at       = (node.get("created_at") or "")[:20]

        # 組裝推理 prompt
        prompt = f"""分析以下技術決策的反事實替代路徑：

## 原始決策
**標題**：{decision_title}
**時間**：{created_at}
**內容**：{decision_content}

## 相關背景
踩坑記錄：{related.get('pitfalls_summary', '無')}
依賴組件：{related.get('dependencies', '無')}
{f'額外上下文：{extra_context[:300]}' if extra_context else ''}

## 你的任務
生成 2-3 個替代技術路徑。對每個路徑，評估如果當初選了它，現在的系統會是什麼狀況。

輸出嚴格 JSON（不要任何說明文字）：
{{
  "alternatives": [
    {{
      "title": "替代方案標題（< 50字）",
      "description": "具體說明這個替代方案是什麼，以及當時選擇它的理由（100-200字）",
      "was_viable_at_the_time": true,
      "probability_of_success": 0.0-1.0,
      "impact": {{
        "technical_complexity":  1-10,
        "maintenance_cost":      1-10,
        "scalability":           1-10,
        "team_learning_curve":   1-10,
        "risk_level":            1-10,
        "time_to_market":        1-10
      }},
      "cascade_effects": [
        "連鎖效應 1（具體說明）",
        "連鎖效應 2"
      ],
      "key_insight": "如果選了這個方案，最重要的啟示是什麼"
    }}
  ],
  "reflection": "從這個反事實分析中，我們可以學到什麼"
}}"""

        try:
            self._call_count += 1
            resp = self.client.messages.create(
                model      = self.model,
                max_tokens = MAX_REASONING_TOKENS,
                system     = REASONING_SYSTEM_PROMPT,
                messages   = [{"role": "user", "content": prompt}],
            )
            raw_text = resp.content[0].text

            # 清理可能的 markdown 包裹
            raw_text = re.sub(r'```json\s*', '', raw_text)
            raw_text = re.sub(r'```\s*',     '', raw_text)
            raw_text = raw_text.strip()

            data = json.loads(raw_text)
            return self._parse_alternatives(data, node["id"])

        except json.JSONDecodeError as e:
            logger.error("Claude 輸出 JSON 解析失敗：%s", e)
            return []
        except anthropic.APIError as e:
            logger.error("Claude API 錯誤：%s", e)
            return []

    def _parse_alternatives(
        self, data: dict, decision_id: str
    ) -> list[CounterfactualPath]:
        """解析 Claude 的 JSON 輸出為 CounterfactualPath 列表"""
        paths: list[CounterfactualPath] = []
        alternatives = data.get("alternatives", [])
        if not isinstance(alternatives, list):
            return []

        for i, alt in enumerate(alternatives[:MAX_ALTERNATIVES]):
            if not isinstance(alt, dict):
                continue

            path_id = hashlib.md5(
                f"{decision_id}:{i}:{alt.get('title','')}".encode()
            ).hexdigest()[:16]

            path = CounterfactualPath(path_id, decision_id)
            path.alternative_title       = str(alt.get("title", ""))[:100]
            path.alternative_description = str(alt.get("description", ""))[:800]
            path.was_viable              = bool(alt.get("was_viable_at_the_time", True))
            path.probability_of_success  = max(0.0, min(1.0,
                float(alt.get("probability_of_success", 0.5))
            ))

            # 影響矩陣
            impact_data = alt.get("impact", {})
            if isinstance(impact_data, dict):
                for dim in IMPACT_DIMENSIONS:
                    val = impact_data.get(dim)
                    if val is not None:
                        try:
                            path.impact.scores[dim] = max(1.0, min(10.0, float(val)))
                        except (TypeError, ValueError):
                            pass

            # 連鎖效應
            cascades = alt.get("cascade_effects", [])
            if isinstance(cascades, list):
                path.cascade_effects = [
                    str(c)[:200] for c in cascades[:5]
                ]

            # key_insight 存入 reasoning
            key_insight = str(alt.get("key_insight", ""))[:300]
            path.impact.reasoning = key_insight

            paths.append(path)

        return paths

    def _free_reasoning(self, question: str, context: str) -> str:
        """自由形式的反事實推理（沒有找到相關決策節點時使用）"""
        prompt = f"""請分析以下反事實問題：

問題：{question}
{f'背景：{context[:300]}' if context else ''}

請提供：
1. 如果採取了替代方案，最可能的技術後果
2. 對工程團隊的影響
3. 對長期維護的影響
4. 這個反思帶來的學習價值

回答簡潔（300字以內），誠實標注不確定的部分。"""
        try:
            resp = self.client.messages.create(
                model      = self.model,
                max_tokens = 600,
                messages   = [{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception as e:
            logger.error("自由推理失敗：%s", e)
            return "（推理服務暫時不可用）"

    def _gather_context(self, node_id: str, node: dict) -> dict:
        """收集決策節點的相關背景知識"""
        # 取得相關的踩坑記錄
        pitfalls = self.graph.search_nodes(
            node.get("title", ""), node_type="Pitfall", limit=3
        )
        pitfalls_summary = "; ".join(
            p.get("title", "") for p in pitfalls[:3]
        ) or "無"

        # 取得依賴關係
        deps = self.graph.neighbors(node_id, "DEPENDS_ON", depth=1)
        deps_str = ", ".join(
            d.get("title", "") for d in deps[:5]
        ) or "無"

        return {
            "pitfalls_summary": pitfalls_summary[:300],
            "dependencies":     deps_str[:300],
        }

    # ── 儲存和快取 ──────────────────────────────────────────────

    def _store_path(self, path: CounterfactualPath) -> None:
        """把反事實路徑存入知識圖譜（作為特殊節點）"""
        try:
            node_id = f"cf-{path.path_id}"
            self.graph.add_node(
                node_id   = node_id,
                node_type = "Counterfactual",
                title     = f"反事實：{path.alternative_title}",
                content   = path.alternative_description,
                tags      = ["counterfactual", "what-if"],
                meta      = {
                    "decision_id":      path.decision_id,
                    "impact":           path.impact.to_dict(),
                    "cascade_effects":  path.cascade_effects,
                    "probability":      path.probability_of_success,
                    "was_viable":       path.was_viable,
                },
            )
            self.graph.add_edge(
                path.decision_id, "HAS_COUNTERFACTUAL", node_id,
                note=path.alternative_title[:100]
            )
        except Exception as e:
            logger.error("_store_path 失敗：%s", e)

    def _cache_key(self, node_id: str, content: str) -> str:
        h = hashlib.sha256(f"{node_id}:{content[:500]}".encode()).hexdigest()[:20]
        return h

    def _load_cache(self, key: str) -> list | None:
        cache_file = self.cache_dir / f"{key}.json"
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            # 檢查快取是否過期
            cached_at = data.get("cached_at", "")
            if cached_at:
                days_old = (
                    datetime.now(timezone.utc) -
                    datetime.fromisoformat(cached_at)
                ).days
                if days_old > CACHE_TTL_DAYS:
                    cache_file.unlink(missing_ok=True)
                    return None
            return data.get("paths", [])
        except Exception:
            return None

    def _save_cache(self, key: str, paths: list) -> None:
        cache_file = self.cache_dir / f"{key}.json"
        try:
            cache_file.write_text(
                json.dumps({
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                    "paths":     paths,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("快取寫入失敗：%s", e)

    def _dict_to_path(self, d: dict) -> CounterfactualPath:
        """從快取 dict 重建 CounterfactualPath 物件"""
        path = CounterfactualPath(d["path_id"], d["decision_id"])
        path.alternative_title       = d.get("alternative_title", "")
        path.alternative_description = d.get("alternative_description", "")
        path.was_viable              = d.get("was_viable", True)
        path.probability_of_success  = d.get("probability_of_success", 0.5)
        path.cascade_effects         = d.get("cascade_effects", [])
        path.created_at              = d.get("created_at", "")
        impact_data = d.get("impact", {})
        if isinstance(impact_data, dict):
            scores = impact_data.get("scores", {})
            for dim, val in scores.items():
                if dim in IMPACT_DIMENSIONS:
                    try:
                        path.impact.scores[dim] = float(val)
                    except (TypeError, ValueError):
                        pass
        return path

    def _summarize_paths(self, paths: list[CounterfactualPath]) -> str:
        """把 CounterfactualPath 列表摘要成一段可讀文字"""
        if not paths:
            return "未找到替代路徑分析。"
        lines = []
        for i, p in enumerate(paths, 1):
            viability = "（當時技術上可行）" if p.was_viable else "（當時技術尚未成熟）"
            lines.append(
                f"{i}. **{p.alternative_title}** {viability}\n"
                f"   成功機率：{p.probability_of_success:.0%}｜"
                f"複雜度：{p.impact.scores.get('technical_complexity', 5):.0f}/10｜"
                f"擴充性：{p.impact.scores.get('scalability', 5):.0f}/10\n"
                f"   {p.alternative_description[:150]}..."
            )
        return "\n\n".join(lines)

    # ── 工具方法 ────────────────────────────────────────────────

    def list_counterfactuals(self, decision_id: str) -> list[dict]:
        """列出某個決策已分析的所有反事實路徑"""
        rows = self.graph._conn.execute("""
            SELECT n.id, n.title, n.content, n.meta
            FROM edges e
            JOIN nodes n ON n.id = e.target_id
            WHERE e.source_id = ? AND e.relation = 'HAS_COUNTERFACTUAL'
        """, (decision_id,)).fetchall()
        results = []
        for r in rows:
            try:
                meta = json.loads(r["meta"] or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}
            results.append({
                "id":      r["id"],
                "title":   r["title"],
                "content": (r["content"] or "")[:300],
                **meta,
            })
        return results

    def stats(self) -> dict:
        count = self.graph._conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE type='Counterfactual'"
        ).fetchone()[0]
        cache_files = len(list(self.cache_dir.glob("*.json")))
        return {
            "counterfactual_nodes": count,
            "api_calls_this_session": self._call_count,
            "cache_entries": cache_files,
        }
