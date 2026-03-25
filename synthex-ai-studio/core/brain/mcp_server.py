"""
Project Brain MCP Server (v1.1)

讓 Claude Code 直接呼叫 Project Brain 的能力，不需要透過命令列。

安全設計：
  - 所有輸入做嚴格型別和長度驗證
  - workdir 必須是已初始化的專案目錄（有 .brain/）
  - 不允許目錄遍歷（../）攻擊
  - Rate limiting：避免 AI 無限制呼叫消耗資源
  - 錯誤訊息不洩漏系統路徑和 stack trace

使用方式：
  # 在 Claude Code 的 MCP 設定中加入：
  # {
  #   "mcpServers": {
  #     "project-brain": {
  #       "command": "python",
  #       "args": ["-m", "core.brain.mcp_server"],
  #       "env": { "BRAIN_WORKDIR": "/your/project" }
  #     }
  #   }
  # }

  # 或直接執行：
  # python -m core.brain.mcp_server --workdir /your/project
"""

from __future__ import annotations

import os
import re
import sys
import time
import logging
import argparse
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 安全常數 ────────────────────────────────────────────────────
MAX_QUERY_LEN    = 500
MAX_CONTENT_LEN  = 2_000
MAX_TITLE_LEN    = 200
MAX_TAGS_COUNT   = 10
RATE_LIMIT_RPM   = 60          # 每分鐘最多 60 次呼叫
_call_times: list[float] = []  # Rate limiter 狀態


def _rate_check() -> None:
    """簡單的滑動視窗 Rate Limiting"""
    now = time.monotonic()
    cutoff = now - 60.0
    _call_times[:] = [t for t in _call_times if t > cutoff]
    if len(_call_times) >= RATE_LIMIT_RPM:
        raise RuntimeError(f"Rate limit：每分鐘最多 {RATE_LIMIT_RPM} 次呼叫")
    _call_times.append(now)


def _safe_str(value: Any, max_len: int, field: str) -> str:
    """安全字串清理：型別檢查 + 長度限制 + 控制字元移除"""
    if not isinstance(value, str):
        raise TypeError(f"{field} 必須是字串，得到 {type(value).__name__}")
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', value)
    if len(cleaned) > max_len:
        raise ValueError(f"{field} 超過長度限制（{len(cleaned)} > {max_len}）")
    return cleaned


def _validate_workdir(workdir: str) -> Path:
    """驗證工作目錄：存在、無路徑遍歷、已初始化"""
    if not workdir:
        raise ValueError("BRAIN_WORKDIR 未設定")

    path = Path(workdir).resolve()

    # 防止路徑遍歷
    if ".." in path.parts:
        raise ValueError("工作目錄路徑不允許包含 ..")

    if not path.exists():
        raise FileNotFoundError(f"工作目錄不存在：{path}")

    if not path.is_dir():
        raise NotADirectoryError(f"工作目錄不是目錄：{path}")

    # 確認已初始化
    brain_dir = path / ".brain"
    if not brain_dir.exists():
        raise FileNotFoundError(
            f".brain/ 不存在，請先執行：python synthex.py brain init"
        )

    return path


# ── MCP Server 主體 ─────────────────────────────────────────────

def create_server(workdir: str) -> Any:
    """建立並設定 MCP Server"""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise ImportError("請安裝 mcp 套件：pip install mcp")

    work_path = _validate_workdir(workdir)

    # 初始化 Project Brain（只在 Server 啟動時做一次）
    sys.path.insert(0, str(work_path.parent))
    from core.brain.engine import ProjectBrain
    brain = ProjectBrain(str(work_path))

    mcp = FastMCP(
        name        = "project-brain",
        version     = "1.1.0",
        description = "Project Brain — 專案知識記憶系統",
    )

    # ── Tool 1：取得 Context 注入 ────────────────────────────────
    @mcp.tool()
    def get_context(
        task: str,
        current_file: str = "",
    ) -> str:
        """
        根據當前任務動態組裝最相關的專案知識，注入 AI 的 Context。

        Args:
            task:         當前任務描述（自然語言）
            current_file: 當前操作的檔案路徑（選填，提升相關性）

        Returns:
            格式化的知識注入字串，可直接加在 prompt 前面。
            若知識庫為空，回傳空字串。
        """
        _rate_check()
        task_clean = _safe_str(task, MAX_QUERY_LEN, "task")
        file_clean = _safe_str(current_file, 500, "current_file") if current_file else ""

        # 防止目錄遍歷
        if ".." in file_clean:
            file_clean = ""

        try:
            return brain.get_context(task_clean, file_clean) or ""
        except Exception as e:
            logger.error("get_context 內部錯誤：%s", e)
            return ""  # 降級：不回傳錯誤細節

    # ── Tool 2：語義搜尋知識庫 ──────────────────────────────────
    @mcp.tool()
    def search_knowledge(
        query:     str,
        kind:      str = "",
        top_k:     int = 5,
    ) -> list[dict]:
        """
        語義搜尋專案知識庫。

        Args:
            query:  搜尋詞（自然語言）
            kind:   節點類型過濾（Decision / Pitfall / Rule / ADR，空字串=全部）
            top_k:  回傳筆數（1-10）

        Returns:
            知識片段列表，每筆包含 title / content / type / similarity。
        """
        _rate_check()
        q_clean = _safe_str(query, MAX_QUERY_LEN, "query")

        valid_kinds = {"", "Decision", "Pitfall", "Rule", "ADR",
                       "Component", "Commit", "Person"}
        if kind not in valid_kinds:
            raise ValueError(f"kind 必須是 {valid_kinds} 之一")

        top_k = max(1, min(10, int(top_k)))

        try:
            # 優先用向量搜尋，fallback 到 FTS5
            from core.brain.vector_memory import VectorMemory
            vm = VectorMemory(Path(str(work_path)) / ".brain")
            if vm.available:
                results = vm.search(q_clean, top_k=top_k,
                                    node_type=kind or None)
                if results:
                    return [
                        {
                            "title":      r["title"],
                            "content":    r["content"][:500],
                            "type":       r["type"],
                            "similarity": r["similarity"],
                            "tags":       r["tags"],
                        }
                        for r in results
                    ]

            # Fallback：SQLite FTS5
            raw = brain.graph.search_nodes(
                q_clean, node_type=kind or None, limit=top_k
            )
            return [
                {
                    "title":      r.get("title", ""),
                    "content":    (r.get("content", "") or "")[:500],
                    "type":       r.get("type", ""),
                    "similarity": None,
                    "tags":       r.get("tags", []),
                }
                for r in raw
            ]
        except Exception as e:
            logger.error("search_knowledge 內部錯誤：%s", e)
            return []

    # ── Tool 3：衝擊分析 ────────────────────────────────────────
    @mcp.tool()
    def impact_analysis(component: str) -> dict:
        """
        分析修改某個組件可能影響的範圍。

        Args:
            component: 組件名稱（例如 "PaymentService"）

        Returns:
            包含直接依賴、間接依賴、相關踩坑、業務規則的分析結果。
        """
        _rate_check()
        comp = _safe_str(component, 200, "component")

        try:
            return brain.graph.impact_analysis(comp)
        except Exception as e:
            logger.error("impact_analysis 內部錯誤：%s", e)
            return {"error": "分析失敗，請確認組件名稱"}

    # ── Tool 4：手動加入知識 ────────────────────────────────────
    @mcp.tool()
    def add_knowledge(
        title:   str,
        content: str,
        kind:    str = "Decision",
        tags:    list[str] | None = None,
    ) -> dict:
        """
        手動加入一筆知識片段到知識庫。

        Args:
            title:   標題（簡短，< 200 字）
            content: 詳細說明（< 2000 字）
            kind:    類型（Decision / Pitfall / Rule / ADR）
            tags:    標籤列表（最多 10 個）

        Returns:
            {"node_id": "...", "success": true}
        """
        _rate_check()

        title_c   = _safe_str(title,   MAX_TITLE_LEN, "title")
        content_c = _safe_str(content, MAX_CONTENT_LEN, "content")

        valid_kinds = {"Decision", "Pitfall", "Rule", "ADR"}
        if kind not in valid_kinds:
            raise ValueError(f"kind 必須是 {valid_kinds} 之一")

        safe_tags = []
        for tag in (tags or [])[:MAX_TAGS_COUNT]:
            t = _safe_str(str(tag), 50, "tag")
            if t:
                safe_tags.append(t)

        try:
            node_id = brain.add_knowledge(
                title   = title_c,
                content = content_c,
                kind    = kind,
                tags    = safe_tags,
            )
            return {"node_id": node_id, "success": True}
        except Exception as e:
            logger.error("add_knowledge 內部錯誤：%s", e)
            return {"node_id": "", "success": False, "error": "加入失敗"}

    # ── Tool 5：知識庫狀態 ──────────────────────────────────────
    @mcp.tool()
    def brain_status() -> str:
        """
        查看 Project Brain 知識庫的目前狀態。

        Returns:
            統計摘要字串（節點數、邊數、最近新增的知識）。
        """
        _rate_check()
        try:
            return brain.status()
        except Exception as e:
            logger.error("brain_status 內部錯誤：%s", e)
            return "狀態查詢失敗"

    # ── Resource：知識圖譜視覺化 ─────────────────────────────────
    @mcp.resource("brain://graph/mermaid")
    def graph_mermaid() -> str:
        """以 Mermaid 格式回傳知識圖譜（可直接在 Claude Code 渲染）"""
        try:
            return brain.export_mermaid(limit=30)
        except Exception as e:
            logger.error("graph_mermaid 內部錯誤：%s", e)
            return "graph TD\n    Error[\"圖譜載入失敗\"]"

    return mcp


def main() -> None:
    """MCP Server 主入口"""
    logging.basicConfig(
        level  = logging.WARNING,   # 生產環境不輸出 DEBUG
        format = "%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Project Brain MCP Server")
    parser.add_argument(
        "--workdir", "-w",
        default = os.environ.get("BRAIN_WORKDIR", os.getcwd()),
        help    = "專案工作目錄（需要有 .brain/），預設使用 BRAIN_WORKDIR 環境變數",
    )
    parser.add_argument(
        "--transport",
        default = "stdio",
        choices = ["stdio", "sse"],
        help    = "傳輸方式（stdio 供 Claude Code 使用，sse 供網頁使用）",
    )
    args = parser.parse_args()

    try:
        mcp = create_server(args.workdir)
        logger.warning("Project Brain MCP Server 啟動（workdir: %s）", args.workdir)
        mcp.run(transport=args.transport)
    except FileNotFoundError as e:
        print(f"[錯誤] {e}", file=sys.stderr)
        sys.exit(1)
    except ImportError as e:
        print(f"[錯誤] 缺少依賴：{e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        logger.warning("MCP Server 已停止")


if __name__ == "__main__":
    main()
