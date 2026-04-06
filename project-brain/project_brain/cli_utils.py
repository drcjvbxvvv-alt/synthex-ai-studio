"""
project_brain/cli_utils.py — Shared CLI utilities (CLI-01 extracted from cli.py)

Contains ANSI colors, helper functions (_workdir, _ok, _err, _info),
_Spinner class, _banner, and all shared internal helpers.
Imported by all cli_*.py sub-modules.
"""
import sys
import os
import logging
from pathlib import Path
from project_brain.constants import DEFAULT_SEARCH_LIMIT

logger = logging.getLogger(__name__)

# ── ANSI 顏色 ────────────────────────────────────────────────
R="\033[0m"; B="\033[1m"; D="\033[2m"
G="\033[92m"; Y="\033[93m"; RE="\033[91m"
C="\033[96m"; P="\033[95m"; GR="\033[90m"; W="\033[97m"


class _Spinner:
    """
    單行 spinner：覆寫同一行，不產生新輸出。

    用法：
        with _Spinner("掃描中") as sp:
            for item in items:
                sp.update(f"{item['name']}")
                process(item)
        # 結束後自動清行並印出完成訊息
    """
    _FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

    def __init__(self, label: str = "", total: int = 0):
        self.label   = label
        self.total   = total
        self._i      = 0
        self._done   = 0
        self._msg    = ""
        self._active = False

    def __enter__(self):
        self._active = True
        return self

    def __exit__(self, *_):
        self._active = False
        # 清除 spinner 行
        print(f"\r\033[2K", end="", flush=True)

    def update(self, msg: str = "", advance: int = 1):
        """更新 spinner 訊息（覆寫同一行）"""
        self._done += advance
        self._msg   = msg
        frame = self._FRAMES[self._i % len(self._FRAMES)]
        self._i += 1
        # 進度：X/N 或只顯示計數
        if self.total:
            pct  = self._done / self.total
            bar  = "█" * int(pct * 10) + "░" * (10 - int(pct * 10))
            prog = f"{GR}[{G}{bar}{GR}] {W}{self._done}/{self.total}{R}"
        else:
            prog = f"{GR}{self._done} 筆{R}"
        # 截短訊息，保持單行
        short = (msg[:45] + "…") if len(msg) > 45 else msg.ljust(46)
        print(f"\r  {C}{frame}{R}  {self.label}  {prog}  {GR}{short}{R}",
              end="", flush=True)


def _banner() -> str:
    """大型 ASCII Art 標題"""
    from project_brain import __version__
    _B = "\033[1m"; _R = "\033[0m"
    _c = lambda n: f"\033[38;5;{n}m"
    ramp = [75,81,93,99,111,123,129,141,153,165,171,183,195,207,213]
    art = [
        "  ██████╗ ██████╗  █████╗ ██╗███╗   ██╗",
        "  ██╔══██╗██╔══██╗██╔══██╗██║████╗  ██║",
        "  ██████╔╝██████╔╝███████║██║██╔██╗ ██║",
        "  ██╔══██╗██╔══██╗██╔══██║██║██║╚██╗██║",
        "  ██████╔╝██║  ██║██║  ██║██║██║ ╚████║",
        "  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝",
    ]
    out = ""
    for i, ln in enumerate(art):
        out += _B + _c(ramp[min(i*2, len(ramp)-1)]) + ln + _R + "\n"
    sub = f"  AI  M E M O R Y  S Y S T E M  ·  v{__version__}"
    colored_sub = "".join(_c(ramp[min(j%len(ramp), len(ramp)-1)]) + ch for j, ch in enumerate(sub))
    out += _B + colored_sub + _R
    return out


def _workdir(args) -> str:
    """
    Resolve working directory — same pattern as git:
    1. --workdir flag (explicit override)
    2. Auto-detect: walk up from cwd until .brain/ is found  ← primary mechanism
    3. BRAIN_WORKDIR env var (fallback for MCP server / headless environments only)
    4. Fallback: current directory (brain setup will create .brain here)
    """
    explicit = getattr(args, 'workdir', None)
    if explicit:
        return str(Path(explicit).resolve())

    # Auto-detect: walk up directory tree looking for .brain/
    cwd = Path(os.getcwd()).resolve()
    candidate = cwd
    for _ in range(10):  # max 10 levels up
        if (candidate / '.brain').exists():
            return str(candidate)
        parent = candidate.parent
        if parent == candidate:  # reached filesystem root
            break
        candidate = parent

    # Fall back to BRAIN_WORKDIR env var (set by MCP server or user)
    env_wd = os.environ.get('BRAIN_WORKDIR')
    if env_wd:
        return str(Path(env_wd).resolve())

    # Fallback: current directory (brain init will create .brain here)
    return str(cwd)


def _brain(workdir: str):
    from project_brain.engine import ProjectBrain
    return ProjectBrain(workdir)


def _infer_scope(workdir: str, current_file: str = "") -> str:
    """ARCH-07: delegate to BrainDB.infer_scope() — single source of truth."""
    from project_brain.brain_db import BrainDB
    return BrainDB.infer_scope(workdir, current_file)


def _env_source(key: str) -> str:
    """說明環境變數的來源（.env 或 export 或預設）"""
    val = os.environ.get(key, "")
    if not val:
        return "(未設定)"
    return "(已設定)"


def _check_l2_health(wd: str) -> dict:
    """
    快速檢查 L2 FalkorDB/Graphiti 是否可達（不阻塞，timeout=2s）。
    Returns: {"available": bool, "url": str, "error": str}
    """
    import os as _os2
    from pathlib import Path as _P
    if _os2.environ.get('GRAPHITI_DISABLED','0') == '1':
        return {'available': False, 'url': 'disabled', 'error': ''}
    if (_P(wd) / '.brain' / 'brain.db').exists():
        return {'available': False, 'url': 'n/a', 'error': 'using brain.db'}
    url = os.environ.get("GRAPHITI_URL", "redis://localhost:6379")
    host = url.split("//")[-1].split(":")[0]
    port = int(url.split(":")[-1]) if ":" in url.split("//")[-1] else 6379
    try:
        import socket
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        return {"available": True, "url": url, "error": ""}
    except Exception as e:
        return {"available": False, "url": url, "error": str(e)[:60]}


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def setup_logging(verbosity: int = 0) -> None:
    """OPT-09: Configure root logger.

    If BRAIN_LOG_JSON=1 is set, emit structured JSON lines instead of plain text.
    verbosity controls level: 0→WARNING, 1→INFO, 2→DEBUG.
    """
    import json as _json
    import time as _time

    level = {0: logging.WARNING, 1: logging.INFO}.get(verbosity, logging.DEBUG)

    if os.environ.get("BRAIN_LOG_JSON", "0") == "1":
        class _JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
                payload = {
                    "ts":      _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(record.created)),
                    "level":   record.levelname,
                    "logger":  record.name,
                    "msg":     record.getMessage(),
                }
                if record.exc_info:
                    payload["exc"] = self.formatException(record.exc_info)
                return _json.dumps(payload, ensure_ascii=False)

        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(handler)
    else:
        # replace first handler (avoid duplicate output on re-run)
        root.handlers[0] = handler


def _load_dotenv():
    """
    從 .env 檔案載入環境變數。
    搜尋順序：當前目錄的 .env → $BRAIN_WORKDIR/.env → ~/.brain/.env
    已有環境變數的不覆蓋（export 的值優先）。
    """
    from pathlib import Path

    candidates = [
        Path.cwd() / ".env",
        Path(os.environ.get("BRAIN_WORKDIR", "")) / ".env" if os.environ.get("BRAIN_WORKDIR") else None,
        Path.home() / ".brain" / ".env",
    ]

    for env_path in candidates:
        if env_path and env_path.exists():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip(chr(34)).strip(chr(39))
                    if key and key not in os.environ:
                        os.environ[key] = val
            except Exception as _e:
                logger.debug("env file load failed", exc_info=True)
            break


def _settings_block() -> str:
    """目前設定區塊（LLM + 工作目錄），顯示在 help 頂部"""
    try:
        from project_brain.brain_config import load_config, _find_brain_dir
        brain_dir = _find_brain_dir()
        cfg      = load_config(brain_dir)
        provider = cfg.pipeline.llm.provider
        model    = cfg.pipeline.llm.model
        base_url = cfg.pipeline.llm.base_url
    except Exception:
        provider = os.environ.get("BRAIN_LLM_PROVIDER", "anthropic").lower()
        model    = os.environ.get("BRAIN_LLM_MODEL", "claude-haiku-4-5-20251001")
        base_url = os.environ.get("BRAIN_LLM_BASE_URL", "http://localhost:11434/v1")

    if provider in ("ollama", "openai"):
        if "11434" in base_url:
            vendor = "Ollama"
        elif "1234" in base_url:
            vendor = "LM Studio"
        else:
            vendor = "Local"
        llm_tag = f"{G}{vendor} - {model}（免費）{R}"
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            llm_tag = f"{Y}Anthropic - {model}{R}"
        else:
            llm_tag = f"{RE}未設定{R}  {GR}→ 設定 ANTHROPIC_API_KEY 或使用 Ollama{R}"

    workdir = os.environ.get("BRAIN_WORKDIR", "（當前目錄）")
    w = 54
    lines = [
        _banner(),
        f'',
        f'{B}目前設定{R}',
        f"{GR}{'═' * w}{R}",
        f'  LLM：{llm_tag}',
        f'  工作目錄：{GR}{workdir}{R}',
        f"{GR}{'─' * w}{R}",
        f'  {D}brain <command> --help   命令詳細說明{R}',
        f'  {D}brain --guide            快速入門 + 環境變數 + LLM 整合{R}',
    ]
    return chr(10).join(lines)


def _show_guide():
    """--guide：完整使用指南"""
    w = 54
    hr = f"{GR}{chr(9472) * w}{R}"
    HR = f"{GR}{chr(9552) * w}{R}"
    print(f"""
{P}{B}  Project Brain  使用指南{R}
{HR}

{B}{C}開始（第一次使用）{R}
{hr}
  {D}① 一鍵設定（建立記憶庫 + 安裝 git hook + MCP）{R}
  {GR}  brain setup{R}

  {D}② 手動加入知識{R}
  {GR}  brain add "JWT 必須使用 RS256"  {R}
  {GR}  brain add "Stripe Webhook 需要冪等性"{R}

  {D}③ 查詢知識（AI Agent 使用這個）{R}
  {GR}  brain ask "JWT 怎麼設定"{R}
  {GR}  brain ask "支付退款有什麼問題"{R}

  {D}④ 確認結果{R}
  {GR}  brain status   # 查看記憶狀態{R}
  {GR}  brain webui    # 瀏覽器視覺化{R}

{B}{C}自動化（一旦設定好就不用管）{R}
{hr}
  每次 git commit → hook 自動呼叫 brain sync → Brain 自動學習

  {D}MCP 整合（Claude Code / Cursor 自動查詢）{R}
  {GR}  brain setup   # 自動偵測並安裝{R}

{B}{C}API 整合（讓外部 LLM 工具查詢）{R}
{hr}
  {GR}  brain serve --port 7891{R}
  GET  http://localhost:7891/v1/context?q=JWT
  POST http://localhost:7891/v1/messages  （OpenAI 相容格式）

{B}{C}環境變數{R}
{hr}
  BRAIN_WORKDIR         預設工作目錄
  ANTHROPIC_API_KEY     AI 分析（scan/learn）所需
  BRAIN_LLM_PROVIDER    anthropic / openai（Ollama）
  BRAIN_LLM_BASE_URL    本地 LLM 端點
  BRAIN_LLM_MODEL       本地模型名稱
""")


def _scan_banner(mode: str, provider: str = "", model: str = "", scope: str = "") -> str:
    """印出模式 banner，回傳模式字串"""
    _W = "\033[1;37m"; _G = "\033[92m"; _Y = "\033[93m"; _R = "\033[0m"; _D = "\033[2m"
    width = 55
    border = "─" * width
    if mode == "local":
        title  = f"{_G}模式：本機 Python{_R}"
        detail = f"{_D}零費用，無任何 API 呼叫  ·  {scope}{_R}"
        icon   = "✓"
        color  = _G
    else:
        title  = f"{_Y}模式：LLM API{_R}"
        detail = f"{_D}{provider} / {model}  ·  {scope}{_R}"
        icon   = "⚡"
        color  = _Y
    print(f"\n{color}┌{border}┐{_R}")
    print(f"{color}│{_R}  {icon}  {title:<40}      {color}│{_R}")
    print(f"{color}│{_R}  {detail:<60}  {color}│{_R}")
    print(f"{color}└{border}┘{_R}\n")
    return mode


def _verify_sqlite_vec():
    """
    sqlite-vec 三層端對端驗證：
      Layer 1 — import sqlite_vec
      Layer 2 — sqlite_vec.load(conn)
      Layer 3 — vec_distance_cosine(...)
    """
    import sqlite3, struct

    try:
        import sqlite_vec as sv
        ver = getattr(sv, "__version__", "unknown")
        print(f"  {G}✓{R}  Layer 1  套件已安裝  {D}(sqlite-vec {ver}){R}")
    except ImportError:
        print(f"  {RE}✗{R}  Layer 1  套件未安裝")
        print(f"     {D}pip install sqlite-vec{R}")
        print(f"  {GR}  → 向量搜尋不可用，使用純 FTS5 關鍵字搜尋{R}")
        return

    conn = sqlite3.connect(":memory:")
    try:
        conn.enable_load_extension(True)
        sv.load(conn)
        conn.enable_load_extension(False)
        print(f"  {G}✓{R}  Layer 2  SQLite C 擴充載入成功")
    except Exception as e:
        print(f"  {RE}✗{R}  Layer 2  C 擴充載入失敗：{e}")
        err_str = str(e).lower()
        if "enable_load_extension" in err_str or "no attribute" in err_str:
            print(f"     {D}原因：Python 編譯時未開啟 SQLite 擴充支援{R}")
            print(f"     {D}pyenv 修復：PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions' \\{R}")
            print(f"     {D}            pyenv install --force $(pyenv version-name){R}")
            print(f"     {D}Homebrew：brew install python@3.12（已內建擴充支援）{R}")
        else:
            print(f"     {D}錯誤詳情：{e}{R}")
        print(f"  {GR}  → 目前使用純 Python cosine fallback（功能完整，速度較慢）{R}")
        conn.close()
        return

    try:
        dim   = 4
        vec_a = struct.pack(f'{dim}f', 1.0, 0.0, 0.0, 0.0)
        vec_b = struct.pack(f'{dim}f', 1.0, 0.0, 0.0, 0.0)
        dist  = conn.execute(
            "SELECT vec_distance_cosine(?, ?)", (vec_a, vec_b)
        ).fetchone()[0]
        if abs(dist) < 0.001:
            print(f"  {G}✓{R}  Layer 3  vec_distance_cosine 運算正確  {D}(dist={dist:.4f}){R}")
        else:
            print(f"  {Y}⚠{R}  Layer 3  vec_distance_cosine 結果異常  {D}(dist={dist:.4f}，預期 ≈ 0){R}")
    except Exception as e:
        print(f"  {RE}✗{R}  Layer 3  SQL 函數執行失敗：{e}")
        conn.close()
        return

    conn.close()

    print(f"  {G}✓{R}  搜尋路徑  {B}C 擴充加速{R}  {D}（FTS5 × 0.4 + 向量 × 0.6）{R}")

    try:
        from project_brain.embedder import get_embedder
        emb = get_embedder()
        if emb is None:
            print(f"  {Y}⚠{R}  Embedding  已停用  {D}(BRAIN_EMBED_PROVIDER=none，純 FTS5){R}")
        else:
            model = getattr(emb, 'MODEL', type(emb).__name__)
            dim_  = getattr(emb, 'dim', '?')
            if "tfidf" in model.lower():
                print(f"  {Y}⚠{R}  Embedding  {Y}LocalTFIDF{R}  {D}({dim_} dim，零依賴但品質有限){R}")
                print(f"     {D}更高品質：ollama pull nomic-embed-text{R}")
            elif "ollama" in type(emb).__name__.lower():
                print(f"  {G}✓{R}  Embedding  {G}Ollama{R}  {D}({model}，{dim_} dim，本地免費){R}")
            else:
                print(f"  {G}✓{R}  Embedding  {G}{type(emb).__name__}{R}  {D}({model}，{dim_} dim){R}")
    except Exception as e:
        print(f"  {Y}⚠{R}  Embedding 後端偵測失敗：{e}")


def _ok(msg):  print(f"{G}✓{R} {msg}")
def _err(msg): print(f"{RE}✗{R} {msg}")
def _info(msg):print(f"{C}ℹ{R} {msg}")


def _build_parser():
    """Build and return the argparse.ArgumentParser for the brain CLI."""
    import argparse
    from project_brain import __version__ as _ver

    parser = argparse.ArgumentParser(
        prog='brain',
        description='Project Brain — AI 記憶系統（獨立版，可搭配任何 LLM）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""── Primary 命令 ──────────────────────────────────────────────
  brain setup                          一鍵設定（第一次使用）
  brain init                           初始化 .brain/ 目錄
  brain add "JWT 筆記"                 加入知識（快速模式）
  brain ask "JWT 怎麼設定"             查詢知識
  brain search <關鍵詞>                純語意搜尋
  brain status                         查看三層記憶狀態
  brain doctor                         系統健康檢查 + 自動修復
  brain doctor --mcp-port 3000         同時檢查 MCP server
  brain serve --port 7891              啟動 REST API / MCP server
  brain webui --port 7890              D3.js 視覺化
  brain sync --quiet                   從 git commit 學習（hook 呼叫）
  brain scan                           舊專案考古掃描
  brain export / brain import          匯出 / 匯入知識庫
  brain config                         顯示設定來源

── Advanced 命令（維護 / 進階）────────────────────────────
  brain history <id>                   版本歷史（--diff 顯示差異）
  brain rollback <id> --to <N>         版本還原（--version <N> 亦可）
  brain deprecated list/mark/purge/info  棄用節點管理
  brain report [--analytics]           ROI + 健康度 + 使用率報告
  brain backfill-git                   從 git 歷史批次回填
  brain optimize                       資料庫維護
  brain migrate / brain fed            跨專案遷移 / 聯邦同步
  brain session / brain index          工作記憶 / 向量索引
  brain link-issue                     連結 GitHub/Linear issue

環境變數：
  BRAIN_WORKDIR         預設工作目錄（省略 --workdir）
  ANTHROPIC_API_KEY     AI 分析功能所需（scan/sync）
  BRAIN_LLM_PROVIDER    anthropic（預設）或 openai（本地 Ollama/LM Studio）
  BRAIN_LLM_BASE_URL    本地 LLM 端點（預設 http://localhost:11434/v1）
  BRAIN_LLM_MODEL       本地模型名稱（預設 llama3.1:8b）
  BRAIN_SYNTHESIZE      1 = 啟用記憶融合模式（opt-in）
""",
    )
    parser.add_argument('--guide', action='store_true',
                        help='完整使用指南（新專案/舊專案/環境變數/LLM 整合）')
    parser.add_argument('--version', '-v', action='version',
                        version=f'brain {_ver}',
                        help='顯示版本號碼')

    sub = parser.add_subparsers(dest='cmd', metavar='<command>')

    def mkp(name, help_text, advanced=False):
        _help = argparse.SUPPRESS if advanced else help_text
        p = sub.add_parser(name, help=_help)
        p.add_argument('--workdir', '-w', default=None,
                       help='專案目錄（預設：自動從當前目錄往上找 .brain/，無需設定）')
        return p

    p = mkp('init', '初始化 Project Brain')
    p.add_argument('--local-only', action='store_true',
                   help='本地模式：不呼叫任何 API，完全離線')
    p.add_argument('--name', default='', help='專案名稱')
    mkp('status', '查看三層記憶狀態（L1/L2/L3）')
    mkp('setup', 'One-command setup (first-time use)')

    p = mkp('ask', 'Ask Brain a question (alias for context)')
    p.add_argument('query', nargs='+', help='Question')
    p.add_argument('--json', action='store_true', help='PH2-07: 輸出結構化 JSON')

    p = mkp('sync', 'Learn from latest git commit (used by hook)')
    p.add_argument('--quiet', action='store_true', help='Suppress output')

    p = mkp('add', '手動加入一筆知識')
    p.add_argument('text', nargs='*', default=[],
                   help='快速模式：brain add "筆記內容"')
    p.add_argument('--title',   nargs='+')
    p.add_argument('--content', default='')
    p.add_argument('--confidence', type=float, default=None,
                   help='信心分數 0.0~1.0（預設 0.8）')
    p.add_argument('--quiet', action='store_true',
                   help='靜默模式（不輸出確認）')
    p.add_argument('--scope', default=None,
                   help='作用域（預設：從 git remote 自動推斷；global = 所有專案共享）')
    p.add_argument('--global', dest='global_scope', action='store_true',
                   help='[已棄用] 請改用 --scope global（FLY-02/STB-04：寫入 global scope）')
    p.add_argument('--kind',    default='Note',
                   choices=['Decision','Pitfall','Rule','ADR','Component','Note'],
                   help='類型（預設：Pitfall）')
    p.add_argument('--tags',    nargs='+', default=[])
    p.add_argument('--emotional-weight', dest='emotional_weight', type=float,
                   default=0.5, help='情感重量 0.0~1.0（踩坑越痛=越高，影響衰減速度）')

    p = mkp('context', '查詢任務相關知識（Context 注入）')
    p.add_argument('task', nargs='*', help='任務描述')
    p.add_argument('--interactive', '-i', action='store_true',
                   help='DEEP-04: 顯示 Brain 想確認的低信心問題')
    p.add_argument('--dry-run', dest='dry_run', action='store_true',
                   help='只預覽，不執行（與不加 --execute 等效，提供慣用語法）')

    p = mkp('review', '審查 KRB Staging 中待核准的知識')
    p.add_argument('review_sub', nargs='?', default='list',
                   choices=['list','approve','reject','pre-screen'],
                   help='子命令（預設：list）')
    p.add_argument('id', nargs='?', default=None,
                   help='Staged node ID（approve / reject 時必填）')
    p.add_argument('--reviewer',      default='human', help='審查者名稱')
    p.add_argument('--note',          default='',      help='核准備注')
    p.add_argument('--reason',        default='',      help='拒絕原因')
    p.add_argument('--limit',         type=int, default=20,  help='列出/預篩筆數上限')
    p.add_argument('--pending',       dest='pending',    action='store_true',
                   help='顯示待人工審查的 pending 隊列（預設：顯示審計記錄）')
    p.add_argument('--pending-ai',    dest='pending_ai', action='store_true',
                   help='只列出 AI 標記為 review 的待人工審查項目（需搭配 --pending）')
    p.add_argument('--auto-approve',  dest='auto_approve', type=float, default=None,
                   help='AI 信心 ≥ 此值時自動核准（預設關閉）')
    p.add_argument('--auto-reject',   dest='auto_reject',  type=float, default=None,
                   help='AI 信心 ≥ 此值且建議拒絕時自動執行（預設關閉）')
    p.add_argument('--max-api-calls', dest='max_api_calls', type=int, default=20,
                   help='pre-screen 最大 API 呼叫次數（預設 20）')

    p = mkp('doctor', '系統健康檢查與自動修復（含 MCP server 狀態）')
    p.add_argument('--fix', action='store_true', help='嘗試自動修復發現的問題')
    p.add_argument('--mcp-port', dest='mcp_port', type=int, default=None,
                   help='同時檢查 MCP server 連線（整合自 health）')

    # REFACTOR-01: health 已整合至 doctor --mcp-port，保留 parser 供向後相容
    p = mkp('health', argparse.SUPPRESS, advanced=True)
    p.add_argument('--mcp-port', dest='mcp_port', type=int, default=None)

    p = mkp('config', '顯示並驗證所有設定來源')
    p.add_argument('config_subcmd', nargs='?', default=None,
                   metavar='[init]',
                   help='init：重新生成 brain.toml')

    p = mkp('optimize', '資料庫維護 — VACUUM + FTS5 rebuild', advanced=True)
    p.add_argument('--prune-episodes', action='store_true',
                   help='清理舊 Episode（L2 git commit 記錄），搭配 --older-than 使用')
    p.add_argument('--older-than', dest='older_than', type=int, default=365,
                   help='清理幾天前的 episode（預設 365）')

    p = mkp('clear', 'U-5: 安全清除工作記憶（session 條目）')
    p.add_argument('--all', dest='target', action='store_const', const='all',
                   default='session', help='清除所有 L3 知識節點（危險）')
    p.add_argument('--yes', '-y', action='store_true', help='跳過確認（--all 時有效）')

    p = mkp('scan', '舊專案考古掃描，重建 L3 知識')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--local', action='store_true',
                      help='本機模式：零費用，無 API 呼叫（推薦入門）')
    mode.add_argument('--llm', action='store_true',
                      help='LLM 模式：高品質，需要 API key')
    mode.add_argument('--heuristic', action='store_true',
                      help='同 --local（向下相容）')
    p.add_argument('--yes', '-y', action='store_true',
                   help='LLM 模式跳過確認提示')
    p.add_argument('--all', dest='scan_all', action='store_true',
                   help='掃描全部 commit（預設只掃最近 100 個）')
    p.add_argument('--quiet', action='store_true', help='靜默模式')

    # REFACTOR-01: health-report 已整合至 report，保留 parser 供向後相容
    p = mkp('health-report', argparse.SUPPRESS, advanced=True)
    p.add_argument('--format', choices=['text','json'], default='text')

    p = mkp('report', 'ROI + 健康度 + 使用率綜合報告（--analytics 顯示詳細分析）',
            advanced=True)
    p.add_argument('--days', type=int, default=7, help='回溯天數（預設：7）')
    p.add_argument('--format', choices=['text','json'], default='text')
    p.add_argument('--output', '-o', default=None, help='儲存報告至檔案')
    p.add_argument('--analytics', action='store_true',
                   help='同時顯示使用率分析（整合自 analytics 命令）')

    p = mkp('search', 'PH2-02：純語意搜尋（不組裝 Context，速度更快）')
    p.add_argument('query', nargs='+', help='搜尋關鍵詞')
    p.add_argument('--limit', type=int, default=10, help='最多顯示幾筆（預設 10）')
    p.add_argument('--kind', default=None,
                   choices=['Decision','Pitfall','Rule','ADR','Component','Note'],
                   help='只搜尋特定類型')
    p.add_argument('--scope', default=None, help='只搜尋特定 scope')
    p.add_argument('--format', choices=['text','json'], default='text')

    p = mkp('link-issue', '連結 Brain 節點與 GitHub/Linear issue（ROI 歸因）', advanced=True)
    p.add_argument('--node-id', dest='node_id', default=None, help='Brain 節點 ID（可用前綴）')
    p.add_argument('--url', default=None, help='GitHub / Linear issue URL')
    p.add_argument('--list', action='store_true', help='列出所有已連結的 issue')

    # REFACTOR-01: analytics 已整合至 report --analytics，保留 parser 供向後相容
    p = mkp('analytics', argparse.SUPPRESS, advanced=True)
    p.add_argument('--format', choices=['text','json'], default='text')
    p.add_argument('--export', choices=['csv'], default=None)
    p.add_argument('--output', '-o', default=None)

    p = mkp('export', '匯出知識庫（JSON / Markdown）')
    p.add_argument('--format', choices=['json','markdown','neo4j','graphml'], default='json',
                   help='匯出格式（json/markdown/neo4j/graphml，預設 json）')
    p.add_argument('--kind',   default=None, help='只匯出某類型節點')
    p.add_argument('--scope',  default=None, help='只匯出某 scope 節點')
    p.add_argument('--output', '-o', default=None, help='輸出路徑（預設：brain_export.json）')

    p = mkp('import', '匯入知識庫（JSON）')
    p.add_argument('file', help='匯入檔案路徑（brain export 產生的 JSON）')
    p.add_argument('--overwrite', action='store_true', help='覆蓋已存在的節點')
    p.add_argument('--merge-strategy', choices=['skip','overwrite','confidence_wins','interactive'],
                   default='skip', dest='merge_strategy',
                   help='衝突解決策略（預設: skip）')

    p = mkp('index', '向量索引重建（語意搜尋）', advanced=True)
    p.add_argument('--quiet', action='store_true')

    # REFACTOR-01: timeline 已整合至 history（支援 --diff），保留 parser 供向後相容
    p = mkp('timeline', argparse.SUPPRESS, advanced=True)
    p.add_argument('node_ref', nargs='+')

    p = mkp('rollback', '版本還原（--to N 或 --version N）', advanced=True)
    p.add_argument('node_id', help='節點 ID')
    p.add_argument('--to', type=int, default=None, help='目標版本號')
    p.add_argument('--version', type=int, dest='to', default=None,
                   help='目標版本號（--to 的別名，整合自 restore）')

    p = mkp('history', '版本歷史（--diff 顯示差異 / --at <date> 時間快照）', advanced=True)
    p.add_argument('node_id', nargs='?', default='', help='節點 ID 或標題（與 --at 二擇一）')
    p.add_argument('--at', default='', metavar='DATE_OR_REF',
                   help='查看該時間點的知識快照（ISO 日期或 git ref）')
    p.add_argument('--diff', action='store_true',
                   help='顯示相鄰版本的 unified diff（FEAT-04）')

    # REFACTOR-01: restore 已整合至 rollback --version，保留 parser 供向後相容
    p = mkp('restore', argparse.SUPPRESS, advanced=True)
    p.add_argument('node_id')
    p.add_argument('--version', type=int, required=True)

    p = mkp('deprecated', '棄用節點管理（list / mark / purge / info）', advanced=True)
    p.add_argument('deprecated_sub', nargs='?', default='list',
                   choices=['list', 'purge', 'mark', 'info'],
                   help='子命令（預設：list）')
    p.add_argument('node_id', nargs='?', default=None,
                   help='節點 ID（mark / info 時必填）')
    p.add_argument('--limit', type=int, default=50, help='列出筆數上限（預設 50）')
    p.add_argument('--older-than', dest='older_than', type=int, default=90,
                   help='purge：刪除棄用超過幾天的節點（預設 90）')
    p.add_argument('--replaced-by', default='', dest='replaced_by',
                   help='mark：取代節點 ID')
    p.add_argument('--reason', default='', help='mark：棄用原因')

    # REFACTOR-01: deprecate 已整合至 deprecated mark，保留 parser 供向後相容
    p = mkp('deprecate', argparse.SUPPRESS, advanced=True)
    p.add_argument('node_id')
    p.add_argument('--replaced-by', default='', dest='replaced_by')
    p.add_argument('--reason', default='')

    # REFACTOR-01: lifecycle 已整合至 deprecated info，保留 parser 供向後相容
    p = mkp('lifecycle', argparse.SUPPRESS, advanced=True)
    p.add_argument('node_id')

    p = mkp('migrate', '跨專案知識遷移', advanced=True)
    p.add_argument('--from', dest='from_path', required=True,
                   help='來源 brain.db 路徑（或含 .brain/ 的目錄）')
    p.add_argument('--to', dest='to_path', default=None,
                   help='目標目錄（預設：當前工作目錄）')
    p.add_argument('--scope', default='global', help='遷移指定 scope（預設 global）')
    p.add_argument('--min-confidence', dest='min_confidence', type=float, default=0.0,
                   help='只遷移信心值 >= 此值的節點（預設 0.0）')
    p.add_argument('--dry-run', action='store_true', help='預覽模式（不實際寫入）')

    p = mkp('fed', '聯邦知識共享（export / import / sync / subscribe）', advanced=True)
    p.add_argument('fed_sub', nargs='?', default='list',
                   choices=['export','import','sync','imports','subscribe','unsubscribe','list'],
                   help='子命令（預設：list）')
    p.add_argument('--output',    '-o', default=None, help='匯出路徑（export 時使用）')
    p.add_argument('--scope',     default='global',   help='匯出 scope（預設 global）')
    p.add_argument('--confidence',type=float, default=0.5, help='最低信心值（預設 0.5）')
    p.add_argument('--max-nodes', dest='max_nodes', type=int, default=500)
    p.add_argument('--project',   default='',         help='專案名稱（export 時嵌入 bundle）')
    p.add_argument('bundle_path', nargs='?', default='', help='Bundle JSON 路徑（import 時使用）')
    p.add_argument('--dry-run',   dest='dry_run', action='store_true')
    p.add_argument('--domain',    default='',     help='領域（subscribe / unsubscribe 時使用）')
    p.add_argument('--add-source',    dest='add_source',    default=None,
                   help='sync：新增來源（格式：name:bundle_path）')
    p.add_argument('--remove-source', dest='remove_source', default=None,
                   help='sync：移除來源（依名稱）')

    p = mkp('backfill-git', '從 git 歷史批次回填知識節點', advanced=True)
    p.add_argument('--dry-run', action='store_true', dest='dry_run',
                   help='只顯示要處理的 commit，不實際寫入')
    p.add_argument('--limit', type=int, default=200, metavar='N',
                   help='最多掃描最近 N 筆 commit（預設 200）')
    p.add_argument('--ai-review', action='store_true', dest='ai_review',
                   help='回填後用 Ollama 自動審核新增節點的信心分數')
    p.add_argument('--ollama-url', dest='ollama_url', default=None,
                   help='Ollama API 位址（預設：BRAIN_OLLAMA_URL 或 http://localhost:11434）')
    p.add_argument('--ollama-model', dest='ollama_model', default=None,
                   help='Ollama 模型名稱（預設：BRAIN_OLLAMA_MODEL 或 llama3.2）')

    # REFACTOR-01: counterfactual 已移除，_apply_aliases 會 sys.exit(1) 並顯示提示

    p = mkp('webui', 'D3.js 視覺化（驗證知識庫）')
    p.add_argument('--port', type=int, default=7890)

    p = mkp('session', '工作記憶管理（list / archive）', advanced=True)
    p.add_argument('session_sub', nargs='?', default='list',
                   choices=['list', 'archive'], help='子命令（預設：list）')
    p.add_argument('--session', default='', help='archive：指定 session ID（預設：當前）')
    p.add_argument('--older-than', dest='older_than', type=int, default=0,
                   help='archive：同時清理超過 N 天的歸檔')

    p = mkp('serve', '啟動 OpenAI 相容 API / MCP server')
    p.add_argument('--port',           type=int,   default=7891,  help='監聽 port（預設：7891）')
    p.add_argument('--production',     action='store_true',       help='生產模式：使用 Gunicorn multi-worker')
    p.add_argument('--workers',        type=int,   default=4,     help='Gunicorn worker 數量（--production 時有效）')
    p.add_argument('--host',           default='0.0.0.0',         help='綁定 host（預設 0.0.0.0）')
    p.add_argument('--mcp',            action='store_true',        help='MCP Server 模式（Claude Code / Cursor 直接連接）')
    p.add_argument('--readonly',        action='store_true',        help='唯讀模式：禁止寫入操作，適合團隊共享查詢')
    p.add_argument('--slack-webhook',  dest='slack_webhook', default=None,
                   help='FEAT-10: Slack Incoming Webhook URL（覆蓋 BRAIN_SLACK_WEBHOOK_URL）')

    return parser


def _apply_aliases():
    """Apply command aliases and deprecated command redirects to sys.argv in-place."""
    # Detect extra 'brain' prefix (e.g. python brain.py brain serve)
    if len(sys.argv) > 2 and sys.argv[1] == 'brain':
        print(f"  {D}（提示：直接用 brain.py {sys.argv[2]}，不需要再打 'brain'）{R}")
        sys.argv.pop(1)

    _aliases = {
        'server':       'serve',
        'start':        'serve',
        'run':          'serve',
        'ui':           'webui',
        'web':          'webui',
        'web-ui':       'webui',
        'stat':         'status',
        'info':         'status',
        'query':        'context',
        'embed':        'index',
        'check':        'validate',
        'verify':       'validate',
        'export_rules': 'export-rules',
        'rules':        'export-rules',
    }
    if len(sys.argv) > 1 and sys.argv[1] in _aliases:
        corrected = _aliases[sys.argv[1]]
        print(f"  [90m（已修正：{sys.argv[1]} → {corrected}）[0m")
        sys.argv[1] = corrected

    _deprecated_cmds = {
        'daemon':          ('status',     'brain status 查看系統狀態（daemon 已整合）'),
        'watch-ack':       ('watch',      'brain watch --ack <id>（watch-ack 已整合）'),
        'mcp-install':     ('serve',      'brain serve --mcp --install（mcp-install 已整合）'),
        'causal-chain':    ('add-causal', 'brain add-causal --list（causal-chain 已整合）'),
        # REFACTOR-01: CLI 精簡 — 已移除命令的向後相容導向
        'context':         ('ask',        'brain ask <query>（context 已整合為 ask 的別名）'),
        'health':          ('doctor',     'brain doctor（health 已整合，可用 --mcp-port 檢查 MCP）'),
        'health-report':   ('report',     'brain report（health-report 已整合為 report）'),
        'timeline':        ('history',    'brain history <id>（timeline 已整合，支援 --diff）'),
        'restore':         ('rollback',   'brain rollback <id> --to <N> 或 --version <N>'),
        'analytics':       ('report',     'brain report --analytics（analytics 已整合為 report 子功能）'),
        'deprecate':       ('deprecated', 'brain deprecated mark <id> --reason "..."'),
        'lifecycle':       ('deprecated', 'brain deprecated info <id>'),
        'counterfactual':  (None,         'counterfactual 已移除 CLI 介面，AI 請直接使用 MCP reasoning_chain 工具'),
        'meta':            (None,         'meta 已移除 CLI 介面，請使用 brain add --kind Rule 替代'),
    }
    if len(sys.argv) > 1 and sys.argv[1] in _deprecated_cmds:
        new_cmd, hint = _deprecated_cmds[sys.argv[1]]
        if new_cmd is None:
            print(f"  {RE}✗ '{sys.argv[1]}' 已從 CLI 移除{R}")
            print(f"  {D}  {hint}{R}")
            sys.exit(1)
        print(f"  {D}⚠ '{sys.argv[1]}' 已廢棄，自動導向：{C}{new_cmd}{R}")
        print(f"  {D}建議改用：{hint}{R}")
        sys.argv[1] = new_cmd


__all__ = [
    "R", "B", "D", "G", "Y", "RE", "C", "P", "GR", "W",
    "_Spinner", "_banner", "_workdir", "_ok", "_err", "_info",
    "_brain", "_infer_scope", "_env_source", "_check_l2_health",
    "_now", "_load_dotenv", "_settings_block", "_show_guide",
    "_scan_banner", "_verify_sqlite_vec",
    "DEFAULT_SEARCH_LIMIT",
    "_build_parser", "_apply_aliases",
]
