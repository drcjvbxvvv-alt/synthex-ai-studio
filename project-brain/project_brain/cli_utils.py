"""
project_brain/cli_utils.py — Shared CLI utilities (CLI-01 extracted from cli.py)

Contains ANSI colors, helper functions (_workdir, _ok, _err, _info),
_Spinner class, _banner, and all shared internal helpers.
Imported by all cli_*.py sub-modules.
"""
import sys
import os
from pathlib import Path
from project_brain.constants import DEFAULT_SEARCH_LIMIT

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
    """
    FLY-02: Auto-infer scope.  Priority:
      1. git remote origin → repo name
      2. Sub-directory name under workdir
      3. workdir directory name
      4. 'global' as last resort
    """
    import re as _re
    import subprocess as _sp

    # 1. git remote origin → 取 repo 名稱
    try:
        _res = _sp.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(workdir), capture_output=True, text=True, timeout=3
        )
        if _res.returncode == 0:
            _url = _res.stdout.strip()
            _m = _re.search(r'[:/]([^/]+?)(?:\.git)?$', _url)
            if _m:
                return _re.sub(r'[^a-z0-9_]', '_', _m.group(1).lower())
    except Exception:
        pass

    # 2. Sub-directory heuristic
    _skip = {'src','test','tests','docs','scripts','build','dist','.'}
    _svc  = ['service','module','pkg','app','api','lib','handler','domain']
    base  = Path(current_file) if current_file else Path(os.getcwd())
    try:
        parts = list(base.relative_to(Path(workdir).resolve()).parts)
        for part in parts:
            pl = part.lower()
            if any(k in pl for k in _svc):
                return _re.sub(r'[^a-z0-9_]', '_', pl)
        if parts and parts[0].lower() not in _skip:
            return _re.sub(r'[^a-z0-9_]', '_', parts[0].lower())
    except ValueError:
        pass

    # 3. workdir name
    _wd_name = Path(workdir).name.lower()
    if _wd_name and _wd_name not in _skip:
        return _re.sub(r'[^a-z0-9_]', '_', _wd_name)

    return 'global'


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
            except Exception:
                pass
            break


def _settings_block() -> str:
    """目前設定區塊（LLM + 工作目錄），顯示在 help 頂部"""
    provider = os.environ.get("BRAIN_LLM_PROVIDER", "anthropic").lower()
    if provider == "openai":
        base_url = os.environ.get("BRAIN_LLM_BASE_URL", "http://localhost:11434/v1")
        model    = os.environ.get("BRAIN_LLM_MODEL", "llama3.1:8b")
        if "11434" in base_url:
            vendor = "Ollama"
        elif "1234" in base_url:
            vendor = "LM Studio"
        else:
            vendor = "Local"
        llm_tag = f"{G}{vendor} - {model}（免費）{R}"
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        model   = os.environ.get("BRAIN_LLM_MODEL", "claude-haiku-4-5-20251001")
        if api_key:
            llm_tag = f"{Y}Anthropic - {model}{R}"
        else:
            llm_tag = f"{RE}未設定{R}  {GR}→ 建立 .env 或設定 ANTHROPIC_API_KEY{R}"

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
        epilog="""命令快速參考：
  brain setup                          一鍵設定（第一次使用）
  brain add "JWT 筆記"                 加入知識（快速模式）
  brain ask "JWT 怎麼設定"              查詢知識
  brain status                         查看記憶狀態
  brain doctor                         系統健康檢查
  brain doctor --fix                   自動修復問題
  brain serve --port 7891              啟動 REST API
  brain webui --port 7890              D3.js 視覺化驗證
  brain sync --quiet                   從 git commit 學習（hook 呼叫）

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

    def mkp(name, help_text):
        p = sub.add_parser(name, help=help_text)
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

    p = mkp('doctor', '系統健康檢查與自動修復')
    p.add_argument('--fix', action='store_true', help='嘗試自動修復發現的問題')

    mkp('config', '顯示並驗證所有設定來源（5 處）')

    p = mkp('optimize', 'C-1: 資料庫維護 — VACUUM + FTS5 rebuild（節省磁碟）')
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

    p = mkp('health-report', 'FEAT-01：知識庫健康度儀表板')
    p.add_argument('--format', choices=['text','json'], default='text')

    p = mkp('report', 'PH1-06：週期性 ROI + 健康度 + 使用率綜合報告')
    p.add_argument('--days', type=int, default=7, help='回溯天數（預設：7）')
    p.add_argument('--format', choices=['text','json'], default='text')
    p.add_argument('--output', '-o', default=None, help='儲存報告至檔案')

    p = mkp('search', 'PH2-02：純語意搜尋（不組裝 Context，速度更快）')
    p.add_argument('query', nargs='+', help='搜尋關鍵詞')
    p.add_argument('--limit', type=int, default=10, help='最多顯示幾筆（預設 10）')
    p.add_argument('--kind', default=None,
                   choices=['Decision','Pitfall','Rule','ADR','Component','Note'],
                   help='只搜尋特定類型')
    p.add_argument('--scope', default=None, help='只搜尋特定 scope')
    p.add_argument('--format', choices=['text','json'], default='text')

    p = mkp('link-issue', 'PH2-06：連結 Brain 節點與 GitHub/Linear issue（ROI 歸因）')
    p.add_argument('--node-id', dest='node_id', default=None, help='Brain 節點 ID（可用前綴）')
    p.add_argument('--url', default=None, help='GitHub / Linear issue URL')
    p.add_argument('--list', action='store_true', help='列出所有已連結的 issue')

    p = mkp('analytics', 'FEAT-03：使用率分析報告')
    p.add_argument('--format', choices=['text','json'], default='text')
    p.add_argument('--export', choices=['csv'], default=None,
                   help='匯出格式（csv）')
    p.add_argument('--output', '-o', default=None, help='輸出路徑')

    p = mkp('export', 'FEAT-05：匯出知識庫（JSON / Markdown）')
    p.add_argument('--format', choices=['json','markdown','neo4j'], default='json')
    p.add_argument('--kind',   default=None, help='只匯出某類型節點')
    p.add_argument('--scope',  default=None, help='只匯出某 scope 節點')
    p.add_argument('--output', '-o', default=None, help='輸出路徑（預設：brain_export.json）')

    p = mkp('import', 'FEAT-05：匯入知識庫（JSON）')
    p.add_argument('file', help='匯入檔案路徑（brain export 產生的 JSON）')
    p.add_argument('--overwrite', action='store_true', help='覆蓋已存在的節點')
    p.add_argument('--merge-strategy', choices=['skip','overwrite','confidence_wins','interactive'],
                   default='skip', dest='merge_strategy',
                   help='衝突解決策略（預設: skip）')

    p = mkp('index', '向量索引（語意搜尋 Phase 1）')
    p.add_argument('--quiet', action='store_true')

    p = mkp('timeline', 'FEAT-06：顯示節點版本歷史')
    p.add_argument('node_ref', nargs='+', help='節點 ID 或標題')

    p = mkp('rollback', 'FEAT-06：恢復節點到指定版本')
    p.add_argument('node_id', help='節點 ID')
    p.add_argument('--to', type=int, required=True, help='目標版本號')

    p = mkp('history', 'FEAT-01：顯示節點版本歷史（含 change_type）')
    p.add_argument('node_id', help='節點 ID 或標題')

    p = mkp('restore', 'FEAT-01：還原節點到指定版本')
    p.add_argument('node_id', help='節點 ID')
    p.add_argument('--version', type=int, required=True, help='目標版本號')

    p = mkp('deprecated', 'ARCH-05：管理已棄用節點（list / purge）')
    p.add_argument('deprecated_sub', nargs='?', default='list',
                   choices=['list', 'purge'], help='子命令（預設：list）')
    p.add_argument('--limit', type=int, default=50, help='列出筆數上限（預設 50）')
    p.add_argument('--older-than', dest='older_than', type=int, default=90,
                   help='purge：刪除棄用超過幾天的節點（預設 90）')

    p = mkp('deprecate', 'FEAT-13：標記節點為棄用')
    p.add_argument('node_id', help='節點 ID')
    p.add_argument('--replaced-by', default='', dest='replaced_by', help='取代節點 ID')
    p.add_argument('--reason', default='', help='棄用原因')

    p = mkp('lifecycle', 'FEAT-13：查看節點生命週期')
    p.add_argument('node_id', help='節點 ID')

    p = mkp('migrate', 'FEAT-07：跨專案知識遷移')
    p.add_argument('--from', dest='from_path', required=True,
                   help='來源 brain.db 路徑（或含 .brain/ 的目錄）')
    p.add_argument('--to', dest='to_path', default=None,
                   help='目標目錄（預設：當前工作目錄）')
    p.add_argument('--scope', default='global', help='遷移指定 scope（預設 global）')
    p.add_argument('--min-confidence', dest='min_confidence', type=float, default=0.0,
                   help='只遷移信心值 >= 此值的節點（預設 0.0）')
    p.add_argument('--dry-run', action='store_true', help='預覽模式（不實際寫入）')

    p = mkp('fed', 'VISION-03：跨專案聯邦知識共享（export / import / sync / subscribe）')
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

    p = mkp('counterfactual', 'DEEP-03：反事實推理')
    p.add_argument('hypothesis', nargs='+', help='假設條件（如：如果我們用 NoSQL）')

    p = mkp('webui', 'D3.js 視覺化（驗證知識庫）')
    p.add_argument('--port', type=int, default=7890)

    p = mkp('session', 'FEAT-04：管理 L1a 工作記憶（list / archive）')
    p.add_argument('session_sub', nargs='?', default='list',
                   choices=['list', 'archive'], help='子命令（預設：list）')
    p.add_argument('--session', default='', help='archive：指定 session ID（預設：當前）')
    p.add_argument('--older-than', dest='older_than', type=int, default=0,
                   help='archive：同時清理超過 N 天的歸檔')

    p = mkp('serve', '啟動 OpenAI 相容 API（讓 Ollama/LM Studio/Cursor 查詢知識）')
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
        'daemon':       ('status',     'brain status 查看系統狀態（daemon 已整合）'),
        'watch-ack':    ('watch',      'brain watch --ack <id>（watch-ack 已整合）'),
        'mcp-install':  ('serve',      'brain serve --mcp --install（mcp-install 已整合）'),
        'causal-chain': ('add-causal', 'brain add-causal --list（causal-chain 已整合）'),
    }
    if len(sys.argv) > 1 and sys.argv[1] in _deprecated_cmds:
        new_cmd, hint = _deprecated_cmds[sys.argv[1]]
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
