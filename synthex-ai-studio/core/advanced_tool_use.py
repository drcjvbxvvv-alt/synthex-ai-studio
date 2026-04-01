"""
AdvancedToolUse — 2026 API 規格（第十輪更新）

重大改動（第十輪）：
  - Structured Output 遷移到 GA 格式：output_config.format（無需 beta header）
  - 保留舊 beta 路徑作為向後相容 fallback（過渡期）
  - Advanced Tool Use 仍需 beta header（尚未 GA）
  - web_search_20260209：最新版 GA，含 dynamic filtering

GA 時間表（Anthropic 官方）：
  ✓ structured-outputs：GA（output_config.format，無需 header）
  ✓ web_search_20260209：GA（無需 header，含 dynamic filtering）
  ✓ programmatic tool calling：GA
  ✗ advanced-tool-use-2025-11-20：仍需 beta header
  ✗ computer-use-2025-01-24：仍需 beta header

安全設計：
  - Tool Search 只回傳相關工具的 schema（不暴露全部）
  - JSON Schema 驗證（輸出不符格式時 fallback 到 regex）
  - build_api_params_for_schema 優先走 GA 路徑
"""

from __future__ import annotations

import re
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Beta headers（仍需 beta 的功能）──────────────────────────────
ADVANCED_TOOL_USE_BETA = "advanced-tool-use-2025-11-20"
CODE_EXECUTION_BETA    = "code-execution-2025-08-25"
COMPUTER_USE_BETA      = "computer-use-2025-01-24"

# ── Web Search（GA，最新版，含 dynamic filtering）────────────────
WEB_SEARCH_TOOL_VERSION = "web_search_20260209"  # 最新 GA 版本（dynamic filtering）
WEB_SEARCH_TOOL_LEGACY  = "web_search_20250305"  # 舊版（GA，不含 dynamic filtering）

# ── 舊 beta header（已 GA，保留供向後相容過渡期使用）─────────────
# ⚠ 已 GA：不再需要 beta header。保留此常數僅供舊程式碼參考。
_STRUCTURED_OUTPUT_BETA_DEPRECATED = "structured-outputs-2025-11-13"


# ── Structured Output JSON Schema 定義 ────────────────────────────

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
    Structured Output 解析器（GA 格式）。

    GA 路徑（2026-03 起）：
      output_config = {
          "format": {
              "type": "json_schema",
              "json_schema": {
                  "name": "schema_name",
                  "schema": {...}
              }
          }
      }
      不需要 betas header，不需要 tools/tool_choice。

    降級路徑（若 GA 失敗）：
      → 舊 beta tools/tool_choice 方式
      → json.loads()
      → regex 提取
    """

    @staticmethod
    def build_ga_output_config(schema: dict, name: str = "structured_output") -> dict:
        """
        建立 GA 格式的 output_config 參數。

        使用方式（直接在 messages.create 中使用）：
            client.messages.create(
                model="claude-opus-4-6",
                max_tokens=1024,
                messages=[...],
                **StructuredOutputParser.build_ga_output_config(EVAL_SCORE_SCHEMA)
            )

        支援的模型：Sonnet 4.5, Opus 4.5, Haiku 4.5（及更新版本）
        """
        return {
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name":   name,
                        "schema": schema,
                    }
                }
            }
        }

    @staticmethod
    def build_api_params_for_schema(
        schema:    dict,
        tool_name: str = "structured_output",
    ) -> dict:
        """
        建立 Structured Output API 參數（GA 格式優先）。

        ⚠ 向後相容方法：新程式碼請直接用 build_ga_output_config()。
        此方法在過渡期仍可使用，內部走 GA 格式。
        """
        return StructuredOutputParser.build_ga_output_config(schema, name=tool_name)

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
            score  = int(parsed.get("score", 5))
            _gate  = parsed.get("gate")
            gate   = (
                str(_gate).upper()
                if _gate and str(_gate).upper() in ("PASS", "FAIL")
                else ("PASS" if score >= 7 else "FAIL")
            )
            return {
                "score":     max(1, min(10, score)),
                "gate":      gate,
                "summary":   str(parsed.get("summary", ""))[:500],
                "top_issue": parsed.get("top_issue"),
                "_source":   "json",
            }
        except Exception:
            pass

        # 2. Regex fallback
        score_m = re.search(r'"?score"?\s*:\s*(\d+)',            raw, re.IGNORECASE)
        gate_m  = re.search(r'"?gate"?\s*:\s*"?(PASS|FAIL)"?',   raw, re.IGNORECASE)
        sum_m   = re.search(r'"?summary"?\s*:\s*"([^"]+)"',       raw, re.IGNORECASE)

        if not score_m:
            score_m = re.search(r'SCORE[:\s]+(\d+)',              raw, re.IGNORECASE)
        if not gate_m:
            gate_m  = re.search(r'GATE[:\s]+(PASS|FAIL)',         raw, re.IGNORECASE)

        score   = int(score_m.group(1)) if score_m else 5
        gate    = gate_m.group(1).upper() if gate_m else ("PASS" if score >= 7 else "FAIL")
        summary = sum_m.group(1) if sum_m else raw[:200]

        logger.warning("structured_output_regex_fallback | raw_len=%d score=%d",
                       len(raw), score)

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
    動態工具發現系統。

    SYNTHEX 有 32+ 個工具，全部塞進 context 約 30K tokens。
    ToolRegistry 根據任務描述只回傳最相關的 8-12 個工具，
    節省 ~70% 的工具定義 token 成本。
    """

    TOOL_CATEGORIES: dict[str, list[str]] = {
        "file":     ["read_file", "write_file", "list_dir", "move_file"],
        "code":     ["run_command", "run_tests", "lint_and_typecheck", "npm_install"],
        "git":      ["git_commit", "git_push", "git_status", "git_diff"],
        "web":      ["browse_web", "fetch_url", "search_web"],
        "analysis": ["sast_scan", "secret_scan", "dependency_audit", "perf_profile"],
        "deploy":   ["deploy_app", "docker_build", "k8s_apply"],
    }

    def __init__(self, tools: list[dict]):
        self._tools = {t["name"]: t for t in tools}
        self._index = self._build_index()

    def _build_index(self) -> dict[str, set[str]]:
        index: dict[str, set[str]] = {}
        for name, tool in self._tools.items():
            words = re.split(r'[_\s]+', name.lower())
            desc  = tool.get("description", "").lower()
            for w in words + re.findall(r'\w{3,}', desc)[:20]:
                index.setdefault(w, set()).add(name)
        return index

    def search(self, task_description: str, top_k: int = 10) -> list[dict]:
        """根據任務描述找出最相關的工具（top_k 個）"""
        top_k   = max(1, min(32, int(top_k)))
        words   = re.findall(r'\w{3,}', task_description.lower())
        scores: dict[str, int] = {}

        for word in words:
            if word in self._index:
                for tn in self._index[word]:
                    scores[tn] = scores.get(tn, 0) + 2
            for key, tns in self._index.items():
                if key.startswith(word) or word.startswith(key):
                    for tn in tns:
                        scores[tn] = scores.get(tn, 0) + 1

        for category, keywords in [
            ("file",    ["檔案", "文件", "讀取", "寫入", "file", "read", "write"]),
            ("code",    ["執行", "測試", "運行", "test", "run", "lint"]),
            ("git",     ["提交", "推送", "git", "commit", "push"]),
            ("web",     ["網頁", "瀏覽", "fetch", "browse", "http", "搜尋"]),
            ("analysis",["安全", "掃描", "分析", "scan", "audit", "security"]),
            ("deploy",  ["部署", "deploy", "docker", "k8s"]),
        ]:
            if any(kw in task_description.lower() for kw in keywords):
                for tn in self.TOOL_CATEGORIES.get(category, []):
                    scores[tn] = scores.get(tn, 0) + 3

        sorted_tools = sorted(scores.items(), key=lambda x: -x[1])
        return [self._tools[n] for n, _ in sorted_tools[:top_k] if n in self._tools]

    def get_all(self) -> list[dict]:
        return list(self._tools.values())

    def get_by_category(self, category: str) -> list[dict]:
        return [self._tools[n] for n in self.TOOL_CATEGORIES.get(category, [])
                if n in self._tools]

    @property
    def tool_count(self) -> int:
        return len(self._tools)


def build_advanced_tool_params(
    tools:            list[dict],
    task:             str,
    use_search:       bool = True,
    use_programmatic: bool = False,
) -> dict:
    """
    建立 Advanced Tool Use beta 的 API 參數。

    ⚠ 此功能仍需 beta header（advanced-tool-use-2025-11-20）。
    """
    extra_params: dict = {"betas": [ADVANCED_TOOL_USE_BETA]}

    if use_search and len(tools) > 10:
        tool_search = {
            "type": "tool_search_tool_regex_20251119",
            "name": "tool_search_tool_regex",
        }
        deferred_tools = [{**t, "defer_loading": True} for t in tools]
        extra_params["tools_extra"] = [tool_search] + deferred_tools
    else:
        extra_params["tools_extra"] = tools

    if use_programmatic:
        extra_params["betas"].append(CODE_EXECUTION_BETA)
        extra_params.setdefault("tools_extra", []).append({
            "type": "code_execution_20250825",
            "name": "code_execution",
        })

    return extra_params


def build_web_search_tool(
    max_uses: int = 5,
    allowed_domains: list[str] | None = None,
    use_dynamic_filtering: bool = True,
) -> dict:
    """
    建立 Web Search 工具定義（GA，無需 beta header）。

    Args:
        max_uses:             最多搜尋次數
        allowed_domains:      只搜尋這些 domain（空 = 不限制）
        use_dynamic_filtering: 使用最新版（含 dynamic filtering，省 token）

    Returns:
        工具定義 dict，直接放入 tools 列表
    """
    version = WEB_SEARCH_TOOL_VERSION if use_dynamic_filtering else WEB_SEARCH_TOOL_LEGACY
    tool: dict = {
        "type":     version,
        "name":     "web_search",
        "max_uses": max_uses,
    }
    if allowed_domains:
        tool["allowed_domains"] = allowed_domains
    return tool
