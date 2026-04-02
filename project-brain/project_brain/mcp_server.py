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
  #       "args": ["-m", "project_brain.mcp_server"],
  #       "env": { "BRAIN_WORKDIR": "/your/project" }
  #     }
  #   }
  # }

  # 或直接執行：
  # python -m project_brain.mcp_server --workdir /your/project
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
            f".brain/ 不存在，請先執行：brain init"
        )

    return path


def _find_brain_root(start: str) -> Path | None:
    """從 start 往上找第一個含有 .brain/ 的目錄，找不到回傳 None"""
    p = Path(start).resolve()
    if p.is_file():
        p = p.parent
    for candidate in [p, *p.parents]:
        if (candidate / ".brain").is_dir():
            return candidate
    return None


# 多工作目錄 Brain 實例快取（key = resolved path str）
_brain_cache: dict[str, Any] = {}


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
    from project_brain.engine import ProjectBrain
    brain = ProjectBrain(str(work_path))
    _brain_cache[str(work_path)] = brain

    def _resolve_brain(caller_workdir: str) -> "ProjectBrain":
        """
        根據呼叫端提供的 workdir 回傳對應的 Brain 實例。
        優先往上找 .brain/；找不到時回退到預設 brain。
        """
        if not caller_workdir:
            return brain
        root = _find_brain_root(caller_workdir)
        if root is None or root == work_path:
            return brain
        key = str(root)
        if key not in _brain_cache:
            try:
                _brain_cache[key] = ProjectBrain(key)
            except Exception:
                return brain
        return _brain_cache[key]

    # Minimal FastMCP init — different versions have different kwargs
    try:
        mcp = FastMCP(
            name        = "project-brain",
            description = "Project Brain — 專案知識記憶系統",
        )
    except TypeError:
        try:
            mcp = FastMCP(name="project-brain")
        except TypeError:
            mcp = FastMCP("project-brain")

    # ── Tool 1：取得 Context 注入 ────────────────────────────────
    @mcp.tool()
    def get_context(
        task: str,
        current_file: str = "",
        scope: str = "global",
        workdir: str = "",
    ) -> str:
        """
        根據當前任務動態組裝最相關的專案知識，注入 AI 的 Context。

        Args:
            task:         當前任務描述（自然語言）
            current_file: 當前操作的檔案路徑（選填，提升相關性）
            workdir:      Claude Code 當前工作目錄（選填，讓 Brain 自動找對應 .brain/）

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

        b = _resolve_brain(workdir or file_clean)
        try:
            ctx = b.get_context(task_clean, file_clean) or ""
            # A-19: apply Memory Synthesizer if BRAIN_SYNTHESIZE=1
            try:
                from project_brain.memory_synthesizer import MemorySynthesizer, is_enabled
                if is_enabled():
                    l1_data = []
                    try:
                        from project_brain.session_store import SessionStore
                        ss = SessionStore(brain_dir=b.brain_dir)
                        l1_data = [{"content": e.value, "category": e.category}
                                   for e in ss.list(limit=5)]
                    except Exception:
                        pass
                    l2_data = []
                    try:
                        l2_data = b.db.recent_episodes(limit=5)
                    except Exception:
                        pass
                    synth = MemorySynthesizer(str(b.workdir))
                    ctx   = synth.fuse(l1_data, l2_data, ctx, task=task_clean) or ctx
            except Exception:
                pass  # synthesis failure must never break context delivery
            # P2-A: attach nudges to every MCP response
            # Agent cannot opt out — if it queries anything, nudges come with it
            try:
                from project_brain.nudge_engine import NudgeEngine
                nudge_eng = NudgeEngine(b.graph)
                nudges    = nudge_eng.check(task_clean, top_k=3)
                if nudges:
                    nudge_block = "\n## 🧠 Brain Nudges（主動警告）\n"
                    for n in nudges:
                        level = getattr(n, 'level', 'info')
                        msg   = getattr(n, 'message', '') or getattr(n, 'content', '') or str(n)
                        icon  = '⚠' if level == 'warning' else 'ℹ'
                        nudge_block += f"  {icon} {msg}\n"
                    ctx = nudge_block + ctx if ctx else nudge_block
            except Exception:
                pass  # nudge failure must never break context delivery
            return ctx
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
            from project_brain.vector_memory import VectorMemory
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
        kind:    str = "Note",
        scope:   str = "global",
        tags:    list[str] | None = None,
        confidence: float = 0.8,
        workdir: str = "",
    ) -> dict:
        """
        手動加入一筆知識片段到知識庫。

        Args:
            title:   標題（簡短，< 200 字）
            content: 詳細說明（< 2000 字）
            kind:    類型（Note / Decision / Pitfall / Rule / ADR）
            scope:   模組作用域（"global" / "auth" / "payment_service" 等）
            confidence: 確信度 0.0~1.0（agent 發現 = 0.6, human verified = 0.9）
            tags:    標籤列表（最多 10 個）
            workdir: Claude Code 當前工作目錄（選填，讓 Brain 自動找對應 .brain/）

        Returns:
            {"node_id": "...", "success": true}
        """
        _rate_check()

        title_c   = _safe_str(title,   MAX_TITLE_LEN, "title")
        content_c = _safe_str(content, MAX_CONTENT_LEN, "content")

        valid_kinds = {"Note", "Decision", "Pitfall", "Rule", "ADR", "Component"}
        kind = kind if kind in valid_kinds else "Note"

        safe_tags = []
        for tag in (tags or [])[:MAX_TAGS_COUNT]:
            t = _safe_str(str(tag), 50, "tag")
            if t:
                safe_tags.append(t)

        b = _resolve_brain(workdir)
        try:
            node_id = b.add_knowledge(
                title      = title_c,
                content    = content_c,
                kind       = kind,
                tags       = safe_tags,
                confidence = max(0.0, min(1.0, confidence)),
            )
            # A-21: write scope to BrainDB (P1-A integration)
            if scope and scope != "global" and node_id:
                try:
                    from project_brain.brain_db import BrainDB
                    _bdir = b.brain_dir
                    _db   = BrainDB(_bdir)
                    _db.conn.execute(
                        "UPDATE nodes SET scope=? WHERE title=?",
                        (scope, title_c)
                    )
                    _db.conn.commit()
                except Exception:
                    pass  # scope write failure is non-critical
            return {"node_id": node_id, "success": True, "scope": scope, "confidence": confidence}
        except Exception as e:
            logger.error("add_knowledge 內部錯誤：%s", e)
            return {"node_id": "", "success": False, "error": "加入失敗"}

    # ── Tool 5：知識庫狀態 ──────────────────────────────────────
    @mcp.tool()
    def brain_status(workdir: str = "") -> str:
        """
        查看 Project Brain 知識庫的目前狀態。

        Returns:
            統計摘要字串（節點數、邊數、最近新增的知識）。
        """
        _rate_check()
        b = _resolve_brain(workdir)
        try:
            return b.status()
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

    # ── Tool：時間機器查詢 ──────────────────────────────────────────
    @mcp.tool()
    def temporal_query(
        at_time:    str = "",
        git_branch: str = "HEAD",
        limit:      int = 20,
    ) -> str:
        """
        Time-machine read — query the knowledge graph at a specific point in time.

        Use this when working on old versions or legacy branches to avoid
        getting rules that didn't exist at that time.

        Args:
            at_time:    ISO timestamp (e.g. "2024-06-01T00:00:00").
                        Empty = current time.
            git_branch: Git branch name for context (e.g. "v1-legacy").
                        Used to resolve approximate timestamp if at_time is empty.
            limit:      Max results (default 20).

        Returns:
            JSON with temporal edges valid at the requested time.
        """
        _rate_check()
        import json
        from project_brain.brain_db import BrainDB
        from pathlib import Path as _P

        wd = os.environ.get("BRAIN_WORKDIR", workdir)
        db_path = _P(wd) / ".brain" / "brain.db"
        if not db_path.exists():
            return json.dumps({"error": "Brain not initialized", "edges": []})

        try:
            db = BrainDB(_P(wd) / ".brain")

            resolved_time = at_time.strip() or None
            if not resolved_time and git_branch and git_branch != "HEAD":
                try:
                    import subprocess
                    r = subprocess.run(
                        ["git", "log", "-1", "--format=%aI", git_branch],
                        capture_output=True, text=True, cwd=wd, timeout=5
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        resolved_time = r.stdout.strip()
                except Exception:
                    pass

            edges = db.temporal_query(at_time=resolved_time, limit=limit)
            return json.dumps({
                "at_time":    resolved_time or "current",
                "git_branch": git_branch,
                "count":      len(edges),
                "edges":      edges,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e), "edges": []})

    # ── Tool：信心回饋 ─────────────────────────────────────────────
    @mcp.tool()
    def mark_helpful(
        node_id: str,
        helpful: bool = True,
    ) -> str:
        """
        Confidence feedback — call this after a piece of knowledge was actually useful.

        When helpful=True:  confidence += 0.03 (capped at 1.0)
        When helpful=False: confidence -= 0.05 (floored at 0.05)

        Args:
            node_id: The node ID returned by get_context or add_knowledge.
            helpful: True if the knowledge was correct/useful, False otherwise.

        Returns:
            JSON with updated confidence value.
        """
        _rate_check()
        import json
        from project_brain.brain_db import BrainDB
        from pathlib import Path as _P

        node_id = _safe_str(node_id, 100, "node_id")
        wd = os.environ.get("BRAIN_WORKDIR", workdir)
        db_path = _P(wd) / ".brain" / "brain.db"
        if not db_path.exists():
            return json.dumps({"error": "Brain not initialized"})

        try:
            db       = BrainDB(_P(wd) / ".brain")
            new_conf = db.record_feedback(node_id, helpful=bool(helpful))
            return json.dumps({
                "node_id":    node_id,
                "helpful":    helpful,
                "confidence": round(new_conf, 3),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

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

