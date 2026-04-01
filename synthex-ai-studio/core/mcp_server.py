"""
core/mcp_server.py — SYNTHEX AI STUDIO MCP Server

讓 Claude Code、Cursor、Zed 等支援 MCP 的工具直接呼叫 SYNTHEX。

架構：
  - 標準 JSON-RPC 2.0 over stdio（MCP 規範）
  - 工具：synthex_ask、synthex_agent、synthex_list_agents、synthex_ship
  - 無需額外安裝，直接 `python -m core.mcp_server`

設定（.claude/CLAUDE.md 或 claude_desktop_config.json）：
  {
    "mcpServers": {
      "synthex": {
        "command": "python",
        "args": ["-m", "core.mcp_server"],
        "cwd": "/path/to/synthex-ai-studio"
      }
    }
  }

安全：
  - 工具執行在 workdir 沙箱中
  - API key 從環境變數讀取，不傳遞到 JSON-RPC 層
  - 所有輸入通過 ToolExecutor 的安全層（path traversal 保護）
"""

from __future__ import annotations

import os
import sys
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── MCP 工具定義（JSON Schema）─────────────────────────────────────

SYNTHEX_MCP_TOOLS: list[dict] = [
    {
        "name": "synthex_ask",
        "description": (
            "向 SYNTHEX AI STUDIO 提問，由智能路由選擇最適合的 Agent 回答。"
            "適合：技術問題、架構建議、程式碼審查、商業分析。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "要詢問的問題或任務描述",
                },
                "workdir": {
                    "type": "string",
                    "description": "專案工作目錄（預設：目前目錄）",
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "synthex_agent",
        "description": (
            "直接呼叫特定 SYNTHEX Agent 執行任務。"
            "適合：需要特定專業領域的任務（如 BYTE=前端、STACK=後端、SHIELD=資安）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": (
                        "Agent 名稱（大寫）："
                        "ARIA/NEXUS/LUMI/SIGMA/BYTE/STACK/FLUX/KERN/"
                        "RIFT/SPARK/PRISM/ECHO/VISTA/NOVA/QUANT/ATLAS/"
                        "FORGE/SHIELD/RELAY/PROBE/TRACE/PULSE/BRIDGE/MEMO"
                    ),
                    "enum": [
                        "ARIA", "NEXUS", "LUMI", "SIGMA",
                        "BYTE", "STACK", "FLUX", "KERN", "RIFT",
                        "SPARK", "PRISM", "ECHO", "VISTA",
                        "NOVA", "QUANT", "ATLAS",
                        "FORGE", "SHIELD", "RELAY",
                        "PROBE", "TRACE",
                        "PULSE", "BRIDGE", "MEMO",
                    ],
                },
                "task": {
                    "type": "string",
                    "description": "要執行的任務描述",
                },
                "agentic": {
                    "type": "boolean",
                    "description": (
                        "True = agentic 模式（帶工具，可操作檔案系統）；"
                        "False = 對話模式（純文字回答，速度快）"
                    ),
                    "default": False,
                },
                "workdir": {
                    "type": "string",
                    "description": "專案工作目錄（預設：目前目錄）",
                },
            },
            "required": ["agent", "task"],
        },
    },
    {
        "name": "synthex_list_agents",
        "description": "列出所有可用的 SYNTHEX Agent 及其專業領域。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": "只列出特定部門（可選）：exec/engineering/product/ai_data/devops/qa/biz",
                    "enum": ["exec", "engineering", "product", "ai_data", "devops", "qa", "biz"],
                },
            },
        },
    },
    {
        "name": "synthex_ship",
        "description": (
            "啟動 SYNTHEX 完整產品交付流水線（12 Phase）。"
            "輸入需求描述，自動產出：PRD → 架構設計 → 安全審查 → 實作 → 測試 → 部署。"
            "⚠️  這是長時間執行的任務（通常 10-30 分鐘），請確認需求後再呼叫。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "requirement": {
                    "type": "string",
                    "description": "產品需求描述（越詳細越好）",
                },
                "workdir": {
                    "type": "string",
                    "description": "專案工作目錄（必填，會在此目錄產生程式碼）",
                },
                "budget_usd": {
                    "type": "number",
                    "description": "API 費用上限（USD，預設 10.0）",
                    "default": 10.0,
                },
                "auto_confirm": {
                    "type": "boolean",
                    "description": "跳過確認提示（CI 環境用，預設 False）",
                    "default": False,
                },
            },
            "required": ["requirement", "workdir"],
        },
    },
]


# ── MCP Protocol Handler ────────────────────────────────────────

class SynthexMCPServer:
    """
    MCP JSON-RPC 2.0 over stdio server。

    協議流程：
      Client → initialize → tools/list → tools/call → ...
    """

    def __init__(self, workdir: str | None = None):
        self.workdir = workdir or os.getcwd()
        self.server_info = {
            "name":    "synthex-ai-studio",
            "version": "0.0.0",
        }

    # ── 協議層 ─────────────────────────────────────────────────────

    def handle(self, request: dict) -> dict:
        """分派 JSON-RPC 請求"""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "tools/list":
                result = self._handle_tools_list()
            elif method == "tools/call":
                result = self._handle_tools_call(params)
            elif method == "ping":
                result = {"pong": True}
            else:
                return self._error(req_id, -32601, f"Method not found: {method}")

            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        except Exception as e:
            logger.exception("mcp_handler_error", exc_info=e)
            return self._error(req_id, -32603, f"Internal error: {e}")

    def _error(self, req_id: Any, code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id":      req_id,
            "error":   {"code": code, "message": message},
        }

    # ── 協議方法 ───────────────────────────────────────────────────

    def _handle_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": "2024-11-05",
            "capabilities":    {"tools": {}},
            "serverInfo":      self.server_info,
        }

    def _handle_tools_list(self) -> dict:
        return {"tools": SYNTHEX_MCP_TOOLS}

    def _handle_tools_call(self, params: dict) -> dict:
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        dispatch = {
            "synthex_ask":          self._tool_ask,
            "synthex_agent":        self._tool_agent,
            "synthex_list_agents":  self._tool_list_agents,
            "synthex_ship":         self._tool_ship,
        }

        if tool_name not in dispatch:
            raise ValueError(f"Unknown tool: {tool_name}")

        output = dispatch[tool_name](arguments)
        return {
            "content": [{"type": "text", "text": str(output)}],
        }

    # ── 工具實作 ───────────────────────────────────────────────────

    def _resolve_workdir(self, arguments: dict) -> str:
        wd = arguments.get("workdir") or self.workdir
        resolved = str(Path(wd).resolve())
        # 安全：確保路徑存在
        if not Path(resolved).exists():
            raise ValueError(f"workdir 不存在：{resolved}")
        return resolved

    def _tool_ask(self, arguments: dict) -> str:
        task    = arguments["task"]
        workdir = self._resolve_workdir(arguments)

        from core.orchestrator import Orchestrator
        orch = Orchestrator(workdir=workdir)
        return orch.run(task)

    def _tool_agent(self, arguments: dict) -> str:
        agent_name = arguments["agent"].upper()
        task       = arguments["task"]
        agentic    = arguments.get("agentic", False)
        workdir    = self._resolve_workdir(arguments)

        from agents.all_agents import get_agent
        agent = get_agent(agent_name, workdir=workdir)

        if agentic:
            return agent.run(task)
        return agent.chat(task)

    def _tool_list_agents(self, arguments: dict) -> str:
        from agents.all_agents import ALL_AGENTS, DEPT_AGENTS

        dept_filter = arguments.get("department")
        dept_labels = {
            "exec":        "🎯 高層管理",
            "engineering": "⚙️  工程開發",
            "product":     "💡 產品設計",
            "ai_data":     "🧠 AI 與資料",
            "devops":      "🚀 基礎架構",
            "qa":          "🔍 品質安全",
            "biz":         "📣 商務發展",
        }

        lines = ["# SYNTHEX AI STUDIO — 可用 Agent\n"]
        for dept, agents in DEPT_AGENTS.items():
            if dept_filter and dept != dept_filter:
                continue
            lines.append(f"## {dept_labels.get(dept, dept)}")
            for name in agents:
                cls = ALL_AGENTS[name]
                lines.append(f"- **{name}** ({cls.emoji} {cls.title})")
            lines.append("")

        return "\n".join(lines)

    def _tool_ship(self, arguments: dict) -> str:
        requirement  = arguments["requirement"]
        workdir      = self._resolve_workdir(arguments)
        budget_usd   = float(arguments.get("budget_usd", 10.0))
        auto_confirm = bool(arguments.get("auto_confirm", False))

        from core.web_orchestrator import WebOrchestrator
        from core.base_agent import init_session_budget
        from core.config import ModelID

        init_session_budget(budget_usd=budget_usd, model=ModelID.OPUS_46)
        orch = WebOrchestrator(workdir=workdir, auto_confirm=auto_confirm)
        return orch.ship(requirement)

    # ── stdio 主迴圈 ───────────────────────────────────────────────

    def run_stdio(self) -> None:
        """
        標準 MCP stdio 傳輸層。
        每行一個 JSON-RPC 請求，每行一個回應。
        """
        logger.info("synthex_mcp_server_started",
                    workdir=self.workdir,
                    version=self.server_info["version"])

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request  = json.loads(line)
                response = self.handle(request)
                print(json.dumps(response, ensure_ascii=False), flush=True)
            except json.JSONDecodeError as e:
                error_resp = {
                    "jsonrpc": "2.0",
                    "id":      None,
                    "error":   {"code": -32700, "message": f"Parse error: {e}"},
                }
                print(json.dumps(error_resp), flush=True)
            except Exception as e:
                logger.exception("stdio_loop_error")
                error_resp = {
                    "jsonrpc": "2.0",
                    "id":      None,
                    "error":   {"code": -32603, "message": str(e)},
                }
                print(json.dumps(error_resp), flush=True)


# ── CLI 入口 ────────────────────────────────────────────────────

def _print_config_help() -> None:
    """顯示設定說明"""
    import shutil
    python_path = shutil.which("python") or "python"
    cwd = os.getcwd()

    print("""
╔══════════════════════════════════════════════════════════════╗
║           SYNTHEX AI STUDIO · MCP Server v3.0               ║
╚══════════════════════════════════════════════════════════════╝

將以下設定加到 Claude Desktop（~/.claude/claude_desktop_config.json）：

{
  "mcpServers": {
    "synthex": {
      "command": "%s",
      "args": ["-m", "core.mcp_server"],
      "cwd": "%s",
      "env": {
        "ANTHROPIC_API_KEY": "your-key-here"
      }
    }
  }
}

或在 Claude Code 的 .claude/CLAUDE.md 中加入：

## MCP 工具
- synthex_ask：向 SYNTHEX 提問
- synthex_agent BYTE：呼叫特定 Agent
- synthex_ship：啟動完整交付流水線

可用工具：
""" % (python_path, cwd))

    for tool in SYNTHEX_MCP_TOOLS:
        print(f"  • {tool['name']}: {tool['description'][:70]}")
    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SYNTHEX MCP Server")
    parser.add_argument("--workdir", default=os.getcwd(), help="工作目錄")
    parser.add_argument("--info",    action="store_true",  help="顯示設定說明")
    args = parser.parse_args()

    if args.info:
        _print_config_help()
        sys.exit(0)

    # 確認 API key 存在
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print('{"jsonrpc":"2.0","id":null,"error":{"code":-32603,'
              '"message":"ANTHROPIC_API_KEY not set"}}', flush=True)
        sys.exit(1)

    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,  # MCP log 必須到 stderr，stdout 留給 JSON-RPC
        format="%(levelname)s %(name)s %(message)s",
    )

    server = SynthexMCPServer(workdir=args.workdir)
    server.run_stdio()
