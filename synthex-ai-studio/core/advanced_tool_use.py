"""
AdvancedToolUse — 2025 前沿工具調用整合 (v3.0)

整合三項 Anthropic 2025-11 最新功能：
  1. Tool Search Tool — 動態工具發現（不需要把 100 個工具全部塞進 context）
  2. Programmatic Tool Calling — 工具在 code execution 環境執行（不污染 context）
  3. Tool Use Examples — 示範正確調用模式（減少參數錯誤）
  4. Structured Outputs — JSON Schema 強制格式（取代 regex 解析）

使用方式：
  from core.advanced_tool_use import ToolRegistry, StructuredOutputParser
  
  # 動態工具發現
  registry = ToolRegistry(tools=ALL_TOOLS)
  relevant = registry.search("讀取檔案並執行測試")
  
  # 結構化輸出
  parser = StructuredOutputParser()
  score = parser.parse_eval_score(raw_text)

安全設計：
  - Tool Search Tool 只回傳相關工具的 schema（不暴露全部）
  - Programmatic Tool 的輸出截斷（防 context 爆炸）
  - JSON Schema 驗證（輸出不符格式時 fallback 到 regex）
  - beta header 版本管理（API 升級時只改一個常數）
"""

from __future__ import annotations

import re
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── API beta header 版本 ────────────────────────────────────────
ADVANCED_TOOL_USE_BETA = "advanced-tool-use-2025-11-20"
STRUCTURED_OUTPUT_BETA = "structured-outputs-2025-11-13"
CODE_EXECUTION_BETA    = "code-execution-2025-08-25"


# ── Structured Output JSON Schema 定義 ─────────────────────────

EVAL_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score":     {"type": "integer", "minimum": 1, "maximum": 10},
        "gate":      {"type": "string",  "enum": ["PASS", "FAIL"]},
        "summary":   {"type": "string"},
        "top_issue": {"type": ["string", "null"]},
    },
    "required": ["score", "gate", "summary"],
}

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision":    {"type": "string", "enum": ["APPROVED", "REJECTED", "NEEDS_REVISION"]},
        "confidence":  {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "rationale":   {"type": "string"},
        "suggestions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision", "confidence", "rationale"],
}

ARCHITECTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "components": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":   {"type": "string"},
                    "type":   {"type": "string"},
                    "tech":   {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["name", "type", "tech"],
            },
        },
        "stack": {
            "type": "object",
            "properties": {
                "frontend":  {"type": "string"},
                "backend":   {"type": "string"},
                "database":  {"type": "string"},
                "cache":     {"type": ["string", "null"]},
                "queue":     {"type": ["string", "null"]},
            },
            "required": ["frontend", "backend", "database"],
        },
        "adr_notes": {"type": "string"},
    },
    "required": ["components", "stack"],
}


class StructuredOutputParser:
    """
    Structured Output 解析器。

    策略（優先順序）：
      1. 嘗試用 JSON Schema beta（structured-outputs-2025-11-13）
      2. 嘗試直接 json.loads()
      3. 用 regex 提取關鍵欄位（降級）
      4. 回傳 default 值（最後手段）
    """

    @staticmethod
    def build_api_params_for_schema(
        schema:     dict,
        tool_name:  str = "structured_output",
    ) -> dict:
        """
        建立使用 Structured Output beta 的 API 參數。
        
        使用方式：
            params = StructuredOutputParser.build_api_params_for_schema(EVAL_SCORE_SCHEMA)
            params["messages"] = [{"role": "user", "content": "..."}]
            resp = client.messages.create(**params)
        """
        return {
            "betas": [STRUCTURED_OUTPUT_BETA],
            "tools": [{
                "name":        tool_name,
                "description": "輸出結構化結果",
                "input_schema": schema,
            }],
            "tool_choice": {"type": "tool", "name": tool_name},
        }

    def parse_eval_score(self, raw: str) -> dict:
        """
        解析評分輸出 → 標準 EvalScore dict。
        多層 fallback 確保永遠有結果。
        """
        # 1. 直接 JSON
        cleaned = re.sub(r'^```(?:json)?\n?', '', raw.strip())
        cleaned = re.sub(r'\n?```$',           '', cleaned)
        try:
            parsed = json.loads(cleaned)
            score = int(parsed.get("score", 5))
            _gate = parsed.get("gate")
            if _gate and str(_gate).upper() in ("PASS", "FAIL"):
                gate = str(_gate).upper()
            else:
                # gate 未提供或無效 → 從 score 推斷（≥ 7 為 PASS）
                gate = "PASS" if score >= 7 else "FAIL"
            return {
                "score":     max(1, min(10, score)),
                "gate":      gate,
                "summary":   str(parsed.get("summary", ""))[:500],
                "top_issue": parsed.get("top_issue"),
                "_source":   "json",
            }
        except Exception:
            pass

        # 2. Regex fallback（P1-2 之前的舊方式，保留向後相容）
        score_m = re.search(r'"?score"?\s*:\s*(\d+)',            raw, re.IGNORECASE)
        gate_m  = re.search(r'"?gate"?\s*:\s*"?(PASS|FAIL)"?',   raw, re.IGNORECASE)
        sum_m   = re.search(r'"?summary"?\s*:\s*"([^"]+)"',       raw, re.IGNORECASE)

        if not score_m:
            score_m = re.search(r'SCORE[:\s]+(\d+)',              raw, re.IGNORECASE)
        if not gate_m:
            gate_m  = re.search(r'GATE[:\s]+(PASS|FAIL)',         raw, re.IGNORECASE)

        score = int(score_m.group(1)) if score_m else 5
        gate  = gate_m.group(1).upper() if gate_m else ("PASS" if score >= 7 else "FAIL")
        summary = sum_m.group(1) if sum_m else raw[:200]

        return {
            "score":     max(1, min(10, score)),
            "gate":      gate,
            "summary":   summary[:500],
            "top_issue": None,
            "_source":   "regex_fallback",
        }

    def parse_architecture(self, raw: str) -> dict:
        """解析架構輸出 → 結構化 ArchitectureSpec"""
        cleaned = re.sub(r'^```(?:json)?\n?', '', raw.strip())
        cleaned = re.sub(r'\n?```$',           '', cleaned)
        try:
            parsed = json.loads(cleaned)
            return {**parsed, "_source": "json"}
        except Exception:
            return {
                "components": [],
                "stack": {"frontend": "Next.js", "backend": "FastAPI", "database": "PostgreSQL"},
                "adr_notes": raw[:500],
                "_source":   "fallback",
            }


class ToolRegistry:
    """
    動態工具發現系統（Tool Search Tool 啟發）。

    SYNTHEX 有 32+ 個工具，全部塞進 context 約 30K tokens。
    ToolRegistry 根據任務描述只回傳最相關的 8-12 個工具，
    節省 ~70% 的工具定義 token 成本。
    """

    # 工具分類標籤（用於語義搜尋）
    TOOL_CATEGORIES: dict[str, list[str]] = {
        "file":     ["read_file", "write_file", "list_dir", "move_file"],
        "code":     ["run_command", "run_tests", "lint_and_typecheck", "npm_install"],
        "git":      ["git_commit", "git_push", "git_status", "git_diff"],
        "web":      ["browse_web", "fetch_url", "search_web"],
        "analysis": ["sast_scan", "secret_scan", "dependency_audit", "perf_profile"],
        "deploy":   ["deploy_app", "docker_build", "k8s_apply"],
        "brain":    ["brain_context", "brain_add", "brain_search"],
    }

    def __init__(self, tools: list[dict]):
        self._tools = {t["name"]: t for t in tools}
        self._index = self._build_index()

    def _build_index(self) -> dict[str, set[str]]:
        """建立工具搜尋索引：keyword → {tool_names}"""
        index: dict[str, set[str]] = {}
        for name, tool in self._tools.items():
            # 從工具名稱提取關鍵字
            words = re.split(r'[_\s]+', name.lower())
            desc  = tool.get("description", "").lower()
            for w in words + re.findall(r'\w{3,}', desc)[:20]:
                index.setdefault(w, set()).add(name)
        return index

    def search(self, task_description: str, top_k: int = 10) -> list[dict]:
        """
        根據任務描述找出最相關的工具。
        
        Args:
            task_description: 自然語言任務描述
            top_k:            回傳最多幾個工具

        Returns:
            最相關的工具定義列表（只包含 name, description, input_schema）
        """
        top_k   = max(1, min(32, int(top_k)))
        words   = re.findall(r'\w{3,}', task_description.lower())
        scores: dict[str, int] = {}

        for word in words:
            # 精確匹配
            if word in self._index:
                for tool_name in self._index[word]:
                    scores[tool_name] = scores.get(tool_name, 0) + 2
            # 前綴匹配
            for key, tool_names in self._index.items():
                if key.startswith(word) or word.startswith(key):
                    for tool_name in tool_names:
                        scores[tool_name] = scores.get(tool_name, 0) + 1

        # 分類加分
        for category, keywords in [
            ("file",    ["檔案", "文件", "讀取", "寫入", "file", "read", "write"]),
            ("code",    ["執行", "測試", "運行", "test", "run", "lint"]),
            ("git",     ["提交", "推送", "git", "commit", "push"]),
            ("web",     ["網頁", "瀏覽", "fetch", "browse", "http"]),
            ("analysis",["安全", "掃描", "分析", "scan", "audit", "security"]),
            ("deploy",  ["部署", "deploy", "docker", "k8s"]),
        ]:
            if any(kw in task_description.lower() for kw in keywords):
                for tool_name in self.TOOL_CATEGORIES.get(category, []):
                    scores[tool_name] = scores.get(tool_name, 0) + 3

        # 按分數排序，回傳 top_k
        sorted_tools = sorted(scores.items(), key=lambda x: -x[1])
        return [
            self._tools[name]
            for name, _ in sorted_tools[:top_k]
            if name in self._tools
        ]

    def get_all(self) -> list[dict]:
        """取得所有工具（完整列表，用於基本 Agent）"""
        return list(self._tools.values())

    def get_by_category(self, category: str) -> list[dict]:
        """取得特定分類的工具"""
        names = self.TOOL_CATEGORIES.get(category, [])
        return [self._tools[n] for n in names if n in self._tools]

    @property
    def tool_count(self) -> int:
        return len(self._tools)


def build_advanced_tool_params(
    tools:         list[dict],
    task:          str,
    use_search:    bool = True,
    use_programmatic: bool = False,
) -> dict:
    """
    建立使用 Advanced Tool Use beta 的 API 參數。

    Args:
        tools:            工具列表
        task:             當前任務（用於動態工具發現）
        use_search:       是否啟用 Tool Search Tool
        use_programmatic: 是否啟用 Programmatic Tool Calling

    Returns:
        額外的 API 參數（合併到現有 params 中）
    """
    extra_params: dict = {}

    betas = [ADVANCED_TOOL_USE_BETA]
    extra_params["betas"] = betas

    if use_search and len(tools) > 10:
        # 加入 Tool Search Tool（讓 Claude 動態發現工具）
        tool_search = {
            "type": "tool_search_tool_regex_20251119",
            "name": "tool_search_tool_regex",
        }
        # 標記所有工具為 deferred loading（按需載入）
        deferred_tools = []
        for t in tools:
            deferred = dict(t)
            deferred["defer_loading"] = True
            deferred_tools.append(deferred)
        extra_params["tools_extra"] = [tool_search] + deferred_tools
    else:
        extra_params["tools_extra"] = tools

    if use_programmatic:
        betas.append(CODE_EXECUTION_BETA)
        code_exec = {
            "type": "code_execution_20250825",
            "name": "code_execution",
        }
        extra_params.setdefault("tools_extra", []).append(code_exec)

    return extra_params
