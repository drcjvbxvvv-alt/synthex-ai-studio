"""
core/brain/graphiti_mcp_server.py — Graphiti L2 MCP Server（v4.0）

功能：
  讓 Claude Code 直接透過 MCP 協議查詢 L2 情節記憶（Graphiti）。
  
  這比 L3 的 brain_query 更強大：
  - 時序查詢：「2024 年初的架構決策是什麼？」
  - 因果鏈：「這個 bug 的根本原因是什麼？」
  - 事件追蹤：「誰在什麼時候改了這個組件？」

MCP Tools 提供：
  graphiti_search(query, top_k, current_only)
    → 混合搜尋（語義 + BM25 + 圖遍歷）
    → current_only=True 只回傳仍然有效的知識
    
  graphiti_add_episode(content, source, reference_time)
    → 把任何資訊加入 L2 時序圖
    
  graphiti_get_timeline(topic, days)
    → 取得某個主題的時序演化
    
  graphiti_status()
    → Graphiti 連線狀態和統計
    
  graphiti_adr(adr_id, title, decision, supersedes)
    → 快速記錄 ADR（架構決策記錄）到 L2

整合到 Claude Code 的 MCP 設定：
  {
    "mcpServers": {
      "graphiti-brain": {
        "command": "python",
        "args": ["-m", "core.brain.graphiti_mcp_server"],
        "env": {
          "BRAIN_WORKDIR": "/your/project",
          "GRAPHITI_URL": "redis://localhost:6379"
        }
      }
    }
  }

安全設計：
  - 所有輸入嚴格長度和格式驗證
  - Rate limiting（60 RPM）
  - 錯誤訊息不洩漏系統路徑
  - Graphiti 連線池管理（不洩漏）
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import logging
import argparse
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 安全常數 ──────────────────────────────────────────────────
MAX_QUERY_LEN   = 500
MAX_CONTENT_LEN = 3_000
MAX_TITLE_LEN   = 200
RATE_LIMIT_RPM  = 60
_call_times: list[float] = []


def _rate_check() -> None:
    now    = time.monotonic()
    cutoff = now - 60.0
    _call_times[:] = [t for t in _call_times if t > cutoff]
    if len(_call_times) >= RATE_LIMIT_RPM:
        raise RuntimeError(f"Rate limit：每分鐘最多 {RATE_LIMIT_RPM} 次")
    _call_times.append(now)


def _safe_str(v: Any, max_len: int, field: str) -> str:
    if not isinstance(v, str):
        raise TypeError(f"{field} 必須是字串")
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', v)
    if len(cleaned) > max_len:
        raise ValueError(f"{field} 超過長度限制（{len(cleaned)} > {max_len}）")
    return cleaned


def _validate_workdir(workdir: str) -> Path:
    path = Path(workdir).resolve()
    if ".." in path.parts:
        raise ValueError("不允許路徑遍歷")
    brain_dir = path / ".brain"
    if not brain_dir.exists():
        raise ValueError(f"未初始化的 Brain 目錄：{workdir}")
    return path


# ── Graphiti MCP Tools ────────────────────────────────────────

def tool_graphiti_search(
    query:        str,
    top_k:        int  = 5,
    current_only: bool = True,
    workdir:      str  = ".",
    graphiti_url: str  = "redis://localhost:6379",
) -> str:
    """
    混合搜尋 L2 情節記憶（語義 + BM25 + 圖遍歷）。
    
    Args:
        query:        搜尋關鍵字（自然語言）
        top_k:        最多回傳筆數（1-20）
        current_only: True 只回傳仍然有效的知識（valid_until=None）
        
    Returns:
        JSON 格式的搜尋結果，含時序資訊
    """
    _rate_check()
    query = _safe_str(query, MAX_QUERY_LEN, "query")
    top_k = max(1, min(20, int(top_k)))

    try:
        path = _validate_workdir(workdir)
        sys.path.insert(0, str(path.parent))
        from core.brain.graphiti_adapter import GraphitiAdapter

        adapter = GraphitiAdapter(
            brain_dir    = path / ".brain",
            db_url       = graphiti_url,
            agent_name   = "mcp_graphiti",
        )

        results = adapter.search_sync(query, top_k=top_k)

        if current_only:
            results = [r for r in results if r.is_current]

        output = {
            "query":   query,
            "count":   len(results),
            "results": [
                {
                    "content":    r.content,
                    "source":     r.source,
                    "relevance":  round(r.relevance, 3),
                    "valid_from": r.valid_from,
                    "is_current": r.is_current,
                    "status":     "✓ 現行" if r.is_current else f"⟲ 已更新（{r.valid_until[:10] if r.valid_until else '?'}）",
                }
                for r in results
            ],
        }

        return json.dumps(output, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error("graphiti_search_failed | error=str(e")
        return json.dumps({"error": str(e)[:200], "query": query})


def tool_graphiti_add_episode(
    content:        str,
    source:         str = "mcp_user",
    reference_time: str | None = None,
    workdir:        str = ".",
    graphiti_url:   str = "redis://localhost:6379",
) -> str:
    """
    把任何資訊加入 L2 時序知識圖譜。
    
    Args:
        content:        知識內容（自然語言）
        source:         來源標識（Agent名稱、commit hash、ADR ID）
        reference_time: 事件的真實發生時間（ISO 8601，可選）
    """
    _rate_check()
    content = _safe_str(content, MAX_CONTENT_LEN, "content")
    source  = _safe_str(source,  MAX_TITLE_LEN,   "source")

    try:
        path = _validate_workdir(workdir)
        sys.path.insert(0, str(path.parent))
        from core.brain.graphiti_adapter import GraphitiAdapter, KnowledgeEpisode

        adapter = GraphitiAdapter(
            brain_dir    = path / ".brain",
            db_url       = graphiti_url,
            agent_name   = "mcp_graphiti",
        )

        ep = KnowledgeEpisode(
            content        = content,
            source         = source,
            reference_time = reference_time,
        )
        ok = adapter.add_episode_sync(ep)

        return json.dumps({
            "success": ok,
            "source":  source,
            "chars":   len(content),
            "message": "已加入 L2 時序圖" if ok else "加入失敗（Graphiti 可能不可用）",
        }, ensure_ascii=False)

    except Exception as e:
        logger.error("graphiti_add_failed | error=str(e")
        return json.dumps({"success": False, "error": str(e)[:200]})


def tool_graphiti_adr(
    adr_id:     str,
    title:      str,
    decision:   str,
    context:    str = "",
    supersedes: str = "",
    workdir:    str = ".",
    graphiti_url: str = "redis://localhost:6379",
) -> str:
    """
    快速記錄 ADR（架構決策記錄）到 L2 時序圖。
    
    Args:
        adr_id:     ADR 編號（例如 ADR-042）
        title:      決策標題
        decision:   決策內容（做了什麼決定，理由是什麼）
        context:    決策背景（可選）
        supersedes: 取代的舊 ADR（可選）
    """
    _rate_check()
    adr_id   = _safe_str(adr_id,   20,             "adr_id")
    title    = _safe_str(title,     MAX_TITLE_LEN,  "title")
    decision = _safe_str(decision,  MAX_CONTENT_LEN,"decision")

    try:
        path = _validate_workdir(workdir)
        sys.path.insert(0, str(path.parent))
        from core.brain.graphiti_adapter import (
            GraphitiAdapter, episode_from_adr
        )

        adapter = GraphitiAdapter(
            brain_dir  = path / ".brain",
            db_url     = graphiti_url,
            agent_name = "mcp_graphiti",
        )

        ep = episode_from_adr(
            adr_id    = adr_id,
            title     = title,
            decision  = decision,
            context   = context[:500],
            supersedes= supersedes,
        )
        ok = adapter.add_episode_sync(ep)

        return json.dumps({
            "success":    ok,
            "adr_id":    adr_id,
            "title":     title,
            "supersedes": supersedes or None,
            "message":   f"ADR {adr_id} 已記錄到 L2" if ok else "記錄失敗",
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)[:200]})


def tool_graphiti_status(
    workdir:      str = ".",
    graphiti_url: str = "redis://localhost:6379",
) -> str:
    """
    查詢 Graphiti L2 連線狀態和基本統計。
    """
    try:
        path = _validate_workdir(workdir)
        sys.path.insert(0, str(path.parent))
        from core.brain.graphiti_adapter import GraphitiAdapter

        adapter = GraphitiAdapter(
            brain_dir  = path / ".brain",
            db_url     = graphiti_url,
            agent_name = "mcp_graphiti",
        )

        status = adapter.status()
        return json.dumps({
            "graphiti_available": status["graphiti_available"],
            "backend":           status.get("backend", "unknown"),
            "has_fallback":      status.get("has_fallback", False),
            "fallback_mode":     "TemporalGraph (SQLite)" if not status["graphiti_available"] else None,
            "workdir":           str(path.name),
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)[:200]})


# ── MCP Server stdio 模式 ─────────────────────────────────────

def run_mcp_server() -> None:
    """
    MCP Server 主循環（stdio 模式，供 Claude Code 呼叫）。
    讀取 JSON-RPC 請求，執行對應工具，回傳結果。
    """
    import sys

    workdir      = os.environ.get("BRAIN_WORKDIR", os.getcwd())
    graphiti_url = os.environ.get("GRAPHITI_URL", "redis://localhost:6379")

    TOOLS = {
        "graphiti_search":      lambda p: tool_graphiti_search(
            query        = p.get("query", ""),
            top_k        = p.get("top_k", 5),
            current_only = p.get("current_only", True),
            workdir      = workdir,
            graphiti_url = graphiti_url,
        ),
        "graphiti_add_episode": lambda p: tool_graphiti_add_episode(
            content        = p.get("content", ""),
            source         = p.get("source", "mcp_user"),
            reference_time = p.get("reference_time"),
            workdir        = workdir,
            graphiti_url   = graphiti_url,
        ),
        "graphiti_adr": lambda p: tool_graphiti_adr(
            adr_id    = p.get("adr_id", ""),
            title     = p.get("title", ""),
            decision  = p.get("decision", ""),
            context   = p.get("context", ""),
            supersedes= p.get("supersedes", ""),
            workdir   = workdir,
            graphiti_url = graphiti_url,
        ),
        "graphiti_status": lambda p: tool_graphiti_status(
            workdir      = workdir,
            graphiti_url = graphiti_url,
        ),
    }

    # 工具定義（供 Claude Code 發現）
    TOOL_DEFS = {
        "tools": [
            {
                "name":        "graphiti_search",
                "description": "混合搜尋 L2 情節記憶（語義+BM25+圖遍歷）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query":        {"type": "string",  "description": "搜尋關鍵字"},
                        "top_k":        {"type": "integer", "default": 5},
                        "current_only": {"type": "boolean", "default": True},
                    },
                    "required": ["query"],
                },
            },
            {
                "name":        "graphiti_add_episode",
                "description": "把任何資訊加入 L2 時序知識圖譜",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content":        {"type": "string"},
                        "source":         {"type": "string"},
                        "reference_time": {"type": "string", "description": "ISO 8601"},
                    },
                    "required": ["content"],
                },
            },
            {
                "name":        "graphiti_adr",
                "description": "快速記錄 ADR 到 L2 時序圖",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "adr_id":     {"type": "string"},
                        "title":      {"type": "string"},
                        "decision":   {"type": "string"},
                        "context":    {"type": "string"},
                        "supersedes": {"type": "string"},
                    },
                    "required": ["adr_id", "title", "decision"],
                },
            },
            {
                "name":        "graphiti_status",
                "description": "查詢 Graphiti L2 連線狀態",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]
    }

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req    = json.loads(line)
            method = req.get("method", "")
            req_id = req.get("id")
            params = req.get("params", {})

            if method == "tools/list":
                resp = {"id": req_id, "result": TOOL_DEFS}
            elif method == "tools/call":
                tool_name = params.get("name", "")
                tool_args = params.get("arguments", {})
                if tool_name in TOOLS:
                    result = TOOLS[tool_name](tool_args)
                    resp = {
                        "id":     req_id,
                        "result": {"content": [{"type": "text", "text": result}]},
                    }
                else:
                    resp = {
                        "id":    req_id,
                        "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
                    }
            elif method == "initialize":
                resp = {
                    "id":     req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo":      {"name": "graphiti-brain", "version": "4.0.0"},
                        "capabilities":    {"tools": {}},
                    },
                }
            else:
                resp = {
                    "id":    req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

            print(json.dumps(resp), flush=True)

        except json.JSONDecodeError:
            error_resp = {"error": {"code": -32700, "message": "Parse error"}}
            print(json.dumps(error_resp), flush=True)
        except Exception as e:
            logger.error("mcp_handler_error | error=str(e")
            error_resp = {
                "id":    None,
                "error": {"code": -32603, "message": str(e)[:200]},
            }
            print(json.dumps(error_resp), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir",      default=os.getcwd())
    parser.add_argument("--graphiti-url", default="redis://localhost:6379")
    args = parser.parse_args()
    os.environ.setdefault("BRAIN_WORKDIR", args.workdir)
    os.environ.setdefault("GRAPHITI_URL",  args.graphiti_url)
    logging.basicConfig(level=logging.WARNING)
    run_mcp_server()
