"""
core/brain/status_renderer.py — Project Brain status 彩色輸出渲染器

職責：
  把 ProjectBrain 各層狀態組裝成帶顏色、清晰易讀的終端輸出。
  與業務邏輯分離，易於測試和修改樣式。
"""
from __future__ import annotations
import os, sqlite3
from pathlib import Path
from datetime import datetime, timezone

# ── ANSI 顏色 ─────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
PURPLE = "\033[95m"
WHITE  = "\033[97m"
GRAY   = "\033[90m"

# 狀態符號
OK   = f"{GREEN}✓{RESET}"
WARN = f"{YELLOW}⚠{RESET}"
ERR  = f"{RED}✗{RESET}"
INFO = f"{CYAN}ℹ{RESET}"

# 知識類型顏色
KIND_COLORS = {
    "Decision":  BLUE,
    "Pitfall":   RED,
    "Rule":      YELLOW,
    "ADR":       PURPLE,
    "Component": CYAN,
    "Person":    GREEN,
}


def _kind_badge(kind: str) -> str:
    c = KIND_COLORS.get(kind, WHITE)
    return f"{c}{BOLD}[{kind}]{RESET}"


def _bar(value: float, width: int = 20, fill: str = "█", empty: str = "░") -> str:
    """橫向進度條"""
    filled = round(value * width)
    return f"{GREEN}{fill * filled}{GRAY}{empty * (width - filled)}{RESET}"


def _conf_color(conf: float) -> str:
    if conf >= 0.75: return GREEN
    if conf >= 0.50: return YELLOW
    return RED


def render_status(
    graph,           # KnowledgeGraph
    brain_dir: Path,
    graphiti_url: str = "",
    version: str = "4.0.0",
) -> str:
    """
    組裝完整的 brain status 輸出（彩色版）。
    """
    lines = []
    w = 54   # 分隔線寬度

    def hr(char="─"):
        return f"{GRAY}{char * w}{RESET}"

    def section(title: str, icon: str = ""):
        icon_part = f"{icon} " if icon else ""
        return f"\n{BOLD}{CYAN}{icon_part}{title}{RESET}\n{hr()}"

    # ── 標題 ──────────────────────────────────────────────────
    lines.append(f"\n{PURPLE}{BOLD}  🧠  Project Brain  {GRAY}v{version}{RESET}")
    lines.append(hr("═"))

    # ── L3 知識圖譜 ───────────────────────────────────────────
    lines.append(section("L3  知識圖譜 (SQLite)", ""))
    try:
        stats   = graph.stats()
        nodes   = stats.get("nodes", 0)
        edges   = stats.get("edges", 0)
        by_type = stats.get("by_type", {})

        lines.append(f"  {OK}  節點  {WHITE}{BOLD}{nodes:>4}{RESET}  │  關係  {WHITE}{BOLD}{edges:>4}{RESET}")

        if by_type:
            lines.append(f"\n  {DIM}分類{RESET}")
            for kind, count in sorted(by_type.items(), key=lambda x: -x[1]):
                badge = _kind_badge(kind)
                bar   = _bar(count / max(nodes, 1), width=12)
                lines.append(f"    {badge:<30} {bar}  {WHITE}{count}{RESET}")

        # 最近新增（帶信心分數色彩）
        recent = graph._conn.execute(
            "SELECT type, title, created_at FROM nodes "
            "ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
        if recent:
            lines.append(f"\n  {DIM}最近新增{RESET}")
            for r in recent:
                badge = _kind_badge(r["type"])
                title = r["title"][:32]
                ts    = (r["created_at"] or "")[:10]
                lines.append(f"    {badge:<30} {WHITE}{title}{RESET}  {GRAY}{ts}{RESET}")
    except Exception as e:
        lines.append(f"  {ERR}  讀取失敗：{e}")

    # ── L2 Graphiti ───────────────────────────────────────────
    lines.append(section("L2  時序知識圖 (Graphiti)", ""))
    try:
        import socket
        url  = graphiti_url or os.environ.get("GRAPHITI_URL", "redis://localhost:6379")
        # 解析 host:port
        import re
        m    = re.search(r'[:/]([a-zA-Z0-9._-]+)[:/](\d+)', url)
        host = m.group(1) if m else "localhost"
        port = int(m.group(2)) if m else 6379

        try:
            sock = socket.create_connection((host, port), timeout=1.5)
            sock.close()
            connected = True
        except Exception:
            connected = False

        try:
            from graphiti_core import Graphiti
            has_graphiti = True
        except ImportError:
            has_graphiti = False

        if connected and has_graphiti:
            lines.append(f"  {OK}  已連接  {GREEN}{BOLD}{url}{RESET}")
            lines.append(f"  {INFO}  模式：FalkorDB / Redis 協議  port {port}")
        elif connected and not has_graphiti:
            lines.append(f"  {WARN}  FalkorDB 可達但 graphiti-core 未安裝")
            lines.append(f"       {GRAY}pip install graphiti-core falkordb{RESET}")
        else:
            lines.append(f"  {ERR}  未連接  {GRAY}{url}{RESET}")
            lines.append(f"  {DIM}  自動降級到 SQLite 時序圖{RESET}")
            lines.append(f"\n  啟用方式：")
            lines.append(f"    {GRAY}docker run -d -p 6379:6379 falkordb/falkordb{RESET}")
            lines.append(f"    {GRAY}pip install graphiti-core falkordb{RESET}")
            lines.append(f"    {GRAY}export GRAPHITI_URL=redis://localhost:6379{RESET}")
    except Exception as e:
        lines.append(f"  {ERR}  檢查失敗：{e}")

    # ── L1 工作記憶 ───────────────────────────────────────────
    lines.append(section("L1  工作記憶 (Memory Tool)", ""))
    try:
        from core.brain.memory_tool import (
            BrainMemoryBackend, list_available_sessions, _HAS_MEMORY_TOOL
        )

        sdk_status = (f"{GREEN}官方 SDK{RESET}" if _HAS_MEMORY_TOOL
                      else f"{YELLOW}本地實作{RESET}")
        lines.append(f"  {OK}  SQLite 工作記憶  {DIM}({sdk_status}){RESET}")

        backend     = BrainMemoryBackend(brain_dir=brain_dir, agent_name="status")
        summary     = backend.session_summary()
        total_mems  = summary.get("total_memories", 0)
        total_ops   = summary.get("total_ops", 0)
        by_dir      = summary.get("by_directory", {})
        sessions    = list_available_sessions(brain_dir)

        lines.append(f"  {INFO}  工作記憶  {WHITE}{BOLD}{total_mems:>4}{RESET}  "
                     f"筆  │  操作記錄  {WHITE}{total_ops}{RESET}  次")

        if by_dir:
            lines.append(f"\n  {DIM}記憶目錄{RESET}")
            for d, cnt in by_dir.items():
                dir_short = d.replace("/memories/", "").rstrip("/") or "root"
                lines.append(f"    {CYAN}/{dir_short:<18}{RESET}  {WHITE}{cnt}{RESET} 筆")

        if sessions:
            lines.append(f"\n  {DIM}可恢復 session（{len(sessions)} 個）{RESET}")
            for s in sessions[:3]:
                ts = (s.get("persisted_at") or "")[:16].replace("T", " ")
                n  = s.get("memory_count", 0)
                sid = s.get("session_id", "")[:8]
                lines.append(f"    {GRAY}{sid}{RESET}  {DIM}{ts}{RESET}  {WHITE}{n}{RESET} 筆")
        else:
            lines.append(f"  {DIM}  尚無已持久化的 session{RESET}")

        # 驗證 L1 讀寫是否正常（寫一筆 ping，再讀回來）
        test_path = "/memories/context/_status_ping.md"
        try:
            backend.create({"path": test_path,
                            "content": f"ping {datetime.now(timezone.utc).isoformat()}"})
            backend.view({"path": test_path})
            backend.delete({"path": test_path})
            lines.append(f"  {OK}  讀寫驗證  {GREEN}通過{RESET}  {GRAY}(create→view→delete){RESET}")
        except Exception as rw_err:
            lines.append(f"  {ERR}  讀寫驗證  {RED}失敗{RESET}  {GRAY}{str(rw_err)[:60]}{RESET}")

    except Exception as e:
        lines.append(f"  {ERR}  L1 初始化失敗：{e}")

    # ── v4.0 功能狀態 ─────────────────────────────────────────
    lines.append(section("v4.0 功能", ""))

    # 知識蒸餾
    distilled_dir = brain_dir / "distilled"
    if distilled_dir.exists():
        files = list(distilled_dir.glob("*"))
        sz_kb = sum(f.stat().st_size for f in files if f.is_file()) // 1024
        lines.append(f"  {OK}  知識蒸餾    {WHITE}{len(files)}{RESET} 個輸出  {GRAY}({sz_kb} KB){RESET}")
    else:
        lines.append(f"  {GRAY}  知識蒸餾    未執行  {DIM}(brain distill){RESET}")

    # 知識驗證
    val_db = brain_dir / "validation_log.db"
    if val_db.exists():
        try:
            conn = sqlite3.connect(str(val_db))
            row  = conn.execute(
                "SELECT run_at, total_checked, valid_count, flagged_count "
                "FROM validation_runs ORDER BY run_at DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row:
                ts = (row[0] or "")[:10]
                lines.append(f"  {OK}  知識驗證    {WHITE}{row[1]}{RESET} 筆  "
                             f"{GREEN}{row[2]} 有效{RESET}  {YELLOW}{row[3]} 標記{RESET}  "
                             f"{GRAY}({ts}){RESET}")
            else:
                lines.append(f"  {GRAY}  知識驗證    尚無記錄  {DIM}(brain validate){RESET}")
        except Exception:
            lines.append(f"  {GRAY}  知識驗證    {DIM}DB 無法讀取{RESET}")
    else:
        lines.append(f"  {GRAY}  知識驗證    未執行  {DIM}(brain validate --dry-run){RESET}")

    # 聯邦學習
    fed_db = brain_dir / "federation.db"
    if fed_db.exists():
        try:
            conn = sqlite3.connect(str(fed_db))
            shared   = conn.execute("SELECT COUNT(*) FROM outgoing_queue WHERE status='sent'").fetchone()[0]
            received = conn.execute("SELECT COUNT(*) FROM incoming_cache").fetchone()[0]
            conn.close()
            lines.append(f"  {OK}  聯邦知識    已分享 {WHITE}{shared}{RESET}  已接收 {WHITE}{received}{RESET}")
        except Exception:
            lines.append(f"  {GRAY}  聯邦知識    {DIM}DB 無法讀取{RESET}")
    else:
        lines.append(f"  {GRAY}  聯邦知識    未啟用")

    # ── 頁尾 ──────────────────────────────────────────────────
    lines.append(f"\n{hr('═')}")
    lines.append(f"{GRAY}  Project Brain  v{version}  ·  {brain_dir}{RESET}\n")

    return "\n".join(lines)
