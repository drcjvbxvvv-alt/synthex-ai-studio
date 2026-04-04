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


__all__ = [
    "R", "B", "D", "G", "Y", "RE", "C", "P", "GR", "W",
    "_Spinner", "_banner", "_workdir", "_ok", "_err", "_info",
    "_brain", "_infer_scope", "_env_source", "_check_l2_health",
    "_now", "_load_dotenv", "_settings_block", "_show_guide",
    "_scan_banner", "_verify_sqlite_vec",
    "DEFAULT_SEARCH_LIMIT",
]
