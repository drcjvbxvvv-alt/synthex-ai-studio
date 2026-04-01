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


    # ── L2 記憶（A-15: brain.db → skip FalkorDB probe）────────────
    _bdb_path = Path(brain_dir) / "brain.db"
    if _bdb_path.exists():
        try:
            import sqlite3 as _sl2
            _c2 = _sl2.connect(str(_bdb_path))
            _ep = _c2.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            _c2.close()
        except Exception:
            _ep = 0
        lines.append(section("L2  時序記憶（SQLite）", "✅"))
        lines.append(f"    {GREEN}{_ep} 個情節記憶{RESET}  {GRAY}零依賴，無需 FalkorDB{RESET}")
    else:
        # FalkorDB probe (only when brain.db does not exist)
        try:
            import socket, re
            url  = graphiti_url or os.environ.get("GRAPHITI_URL", "redis://localhost:6379")
            m    = re.search(r'[:/]([a-zA-Z0-9._-]+)[:/](\d+)', url)
            host = m.group(1) if m else "localhost"
            port = int(m.group(2)) if m else 6379
            try:
                sock = socket.create_connection((host, port), timeout=1.5)
                sock.close(); connected = True
            except Exception:
                connected = False
            try:
                from graphiti_core import Graphiti; has_graphiti = True
            except ImportError:
                has_graphiti = False
            lines.append(section("L2  時序知識圖 (Graphiti)", ""))
            if connected and has_graphiti:
                lines.append(f"  {OK}  已連接  {GREEN}{BOLD}{url}{RESET}")
            elif connected:
                lines.append(f"  {WARN}  FalkorDB 可達但 graphiti-core 未安裝")
            else:
                lines.append(f"  {ERR}  未連接  {GRAY}{url}{RESET}")
                lines.append(f"  {GRAY}  docker run -d -p 6379:6379 falkordb/falkordb{RESET}")
        except Exception as e:
            lines.append(f"  {ERR}  L2 檢查失敗：{e}")

    # ── L1a Session Store（任意 LLM 可用）───────────────────────
    try:
        from project_brain.session_store import SessionStore, CATEGORY_CONFIG
        ss      = SessionStore(brain_dir)
        ss_stat = ss.stats()
        total   = ss_stat.get("total", 0)
        by_cat  = ss_stat.get("by_category", {})

        lines.append(section("L1a  Session Store", "任意 LLM 可用"))
        lines.append(f"  {OK}  SQLite WAL  {DIM}(session_store.db){RESET}")
        lines.append(
            f"  {INFO}  工作記憶  {WHITE}{BOLD}{total:>4}{RESET}  筆  │  "
            f"session：{DIM}{ss_stat.get('session_id','')[:16]}{RESET}"
        )
        # 分類明細
        if by_cat:
            cat_parts = []
            CAT_COLORS = {
                "pitfalls":  "\033[91m",  # red
                "decisions": "\033[92m",  # green
                "context":   "\033[96m",  # cyan
                "progress":  "\033[93m",  # yellow
                "notes":     "\033[90m",  # gray
            }
            for cat, cnt in sorted(by_cat.items()):
                cfg   = CATEGORY_CONFIG.get(cat, {})
                ttl   = f"{cfg.get('ttl_days',0)}d" if cfg.get("persistent") else "session"
                color = CAT_COLORS.get(cat, "")
                cat_parts.append(f"    {color}{cat}{RESET} {WHITE}{cnt}{RESET} ({DIM}{ttl}{RESET})")
            lines.append("\n".join(cat_parts))

        # 端點提示
        lines.append(
            f"  {DIM}  brain serve → GET  /v1/session{RESET}"
        )
        lines.append(
            f"  {DIM}              POST /v1/session  {{key,value,category}}{RESET}"
        )
    except Exception as e:
        lines.append(section("L1a  Session Store", ""))
        lines.append(f"  {WARN}  初始化失敗：{e}")

    lines.append("")

    # ── L1a 工作記憶 (SessionStore) ──────────────────────────────
    lines.append(section("L1a  工作記憶 (SessionStore)", ""))
    try:
        from project_brain.session_store import SessionStore
        _ss = SessionStore(brain_dir=brain_dir, session_id="status")
        _ss_stats = _ss.stats()
        lines.append(f"  {OK}  SQLite WAL  "
                     f"{DIM}({_ss_stats.get('total',0)} 條目){RESET}")
    except Exception as e:
        lines.append(f"  {WARN}  SessionStore 不可用：{e}")

    # ── v10 記憶功能狀態 ─────────────────────────────────────────
    lines.append(section("v10 記憶功能", ""))

    # knowledge graph stats
    try:
        node_count = len(db.conn.execute("SELECT id FROM nodes LIMIT 100").fetchall())
        edge_count = len(db.conn.execute("SELECT id FROM edges LIMIT 100").fetchall())
        lines.append(f"  {OK}  知識節點  {WHITE}{BOLD}{node_count}{RESET}  │  因果邊  {WHITE}{BOLD}{edge_count}{RESET}")
    except Exception:
        pass

    # Scope distribution
    try:
        scopes = db.conn.execute(
            "SELECT scope, COUNT(*) as c FROM nodes GROUP BY scope ORDER BY c DESC LIMIT 3"
        ).fetchall()
        if scopes and any(row['scope'] != 'global' for row in scopes):
            scope_str = "  ".join(f"{row['scope']}({row['c']})" for row in scopes)
            lines.append(f"  {INFO}  作用域分布  {GRAY}{scope_str}{RESET}")
    except Exception:
        pass

    # Memory Synthesizer
    import os as _os
    synth = _os.environ.get("BRAIN_SYNTHESIZE","0") == "1"
    lines.append(
        f"  {OK}  Memory Synthesizer  {GREEN}啟用{RESET}" if synth else
        f"  {GRAY}  Memory Synthesizer  關閉  {DIM}[如需啟用：export BRAIN_SYNTHESIZE=1]{RESET}"
    )


    # ── KRB Staging 待審提醒 ─────────────────────────────────
    try:
        _krb_path = Path(brain_dir) / "review_board.db"
        if _krb_path.exists():
            import sqlite3 as _sl3
            _kc = _sl3.connect(str(_krb_path))
            _pending = _kc.execute(
                "SELECT COUNT(*) FROM staged_nodes WHERE status='pending'"
            ).fetchone()[0]
            _kc.close()
            if _pending > 0:
                lines.append(f"\n{YELLOW}{BOLD}  ⚠  KRB Staging：{_pending} 筆待審知識{RESET}")
                lines.append(f"  {DIM}  執行 brain review list 查看並核准{RESET}")
    except Exception:
        pass

    # ── 頁尾 ──────────────────────────────────────────────────
    lines.append(f"\n{hr('═')}")
    lines.append(f"{GRAY}  Project Brain  v{version}  ·  {brain_dir}{RESET}\n")

    return "\n".join(lines)
