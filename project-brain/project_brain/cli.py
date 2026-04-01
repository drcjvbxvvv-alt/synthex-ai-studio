#!/usr/bin/env python3
"""
project_brain.cli — Project Brain CLI 入口

安裝後直接使用：
    pip install project-brain
    brain init   --workdir .
    brain scan
    brain context "JWT 認證問題"

開發者 Python API：
    from project_brain import Brain
    b = Brain(".")
    ctx = b.get_context("JWT 認證問題")
"""
import sys, os
from pathlib import Path

# project_brain 套件安裝後不需要手動設定 sys.path
# 保留兼容本地開發（python brain.py）
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── ANSI 顏色 ─────────────────────────────────────────────────
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
    B = "\033[1m"; R = "\033[0m"
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
        out += B + _c(ramp[min(i*2, len(ramp)-1)]) + ln + R + "\n"
    sub = f"  AI  M E M O R Y  S Y S T E M  ·  v{__version__}"
    colored_sub = "".join(_c(ramp[min(j%len(ramp), len(ramp)-1)]) + ch for j, ch in enumerate(sub))
    out += B + colored_sub + R
    return out
def _workdir(args) -> str:
    """
    Resolve working directory — same pattern as git:
    1. --workdir flag
    2. BRAIN_WORKDIR env var
    3. Auto-detect: walk up from cwd until .brain/ is found
    4. Fallback: current directory

    This means `brain status` works from any subdirectory of the project,
    exactly like `git status`.
    """
    explicit = getattr(args, 'workdir', None) or os.environ.get('BRAIN_WORKDIR')
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

    # Fallback: current directory (brain init will create .brain here)
    return str(cwd)

def _brain(workdir: str):
    from project_brain.engine import ProjectBrain
    return ProjectBrain(workdir)

def _infer_scope(workdir: str, current_file: str = "") -> str:
    """Phase 5: Auto-infer scope from directory.
    /project/payment_service/stripe.py → 'payment_service'"""
    import re as _re
    _skip = {'src','test','tests','docs','scripts','build','dist','.'}
    _svc  = ['service','module','pkg','app','api','lib','handler','domain']
    base  = Path(current_file) if current_file else Path(os.getcwd())
    try:
        parts = list(base.relative_to(Path(workdir).resolve()).parts)
    except ValueError:
        return 'global'
    for part in parts:
        pl = part.lower()
        if any(k in pl for k in _svc):
            return _re.sub(r'[^a-z0-9_]', '_', pl)
    if parts and parts[0].lower() not in _skip:
        return _re.sub(r'[^a-z0-9_]', '_', parts[0].lower())
    return 'global'


def _env_source(key: str) -> str:
    """說明環境變數的來源（.env 或 export 或預設）"""
    import os
    val = os.environ.get(key, "")
    if not val:
        return "(未設定)"
    # 嘗試判斷是否來自 .env（簡單啟發式：.env 在 _load_dotenv 之前 key 不存在）
    # 無法確定時不顯示 "export"，避免誤導
    return "(已設定)"

def _ok(msg):  print(f"{G}✓{R} {msg}")
def _err(msg): print(f"{RE}✗{R} {msg}")
def _info(msg):print(f"{C}ℹ{R} {msg}")

# ══════════════════════════════════════════════════════════════
#  命令實作
# ══════════════════════════════════════════════════════════════

def cmd_init(args):
    """初始化 Project Brain（建立 .brain/ 目錄 + 知識圖譜）"""
    wd         = _workdir(args)
    name       = getattr(args, 'name', '') or Path(wd).name
    local_only = getattr(args, 'local_only', False)

    if local_only:
        # 寫入 .brain/.env 設定本地模式
        import os
        bd = Path(wd) / ".brain"
        bd.mkdir(exist_ok=True)
        env_path = bd / ".env"
        local_env = (
            "# Project Brain 本地模式（brain init --local-only）\n"
            "# 所有資料不離開本機\n"
            "BRAIN_LLM_PROVIDER=openai\n"
            "BRAIN_LLM_BASE_URL=http://localhost:11434/v1\n"
            "BRAIN_LLM_MODEL=llama3.1:8b\n"
            "BRAIN_LOCAL_ONLY=1\n"
            "# L2 時序記憶使用本地 SQLite（不需要 FalkorDB）\n"
            "GRAPHITI_DISABLED=1\n"
        )
        env_path.write_text(local_env)
        _ok(f"本地模式啟用：設定已寫入 {env_path}")
        _info("LLM：Ollama（需要先執行 ollama serve && ollama pull llama3.1:8b）")
        _info("L2：使用 SQLite 替代 FalkorDB（無需 Docker）")
        _info("所有資料完全離線，不呼叫任何外部 API")
        print()
        # 設定環境變數（當前進程）
        os.environ.setdefault("BRAIN_LLM_PROVIDER", "openai")
        os.environ.setdefault("BRAIN_LLM_BASE_URL", "http://localhost:11434/v1")
        os.environ.setdefault("GRAPHITI_DISABLED", "1")

    b = _brain(wd)
    print(b.init(project_name=name))


    # A-10: also initialise unified brain.db
    try:
        from project_brain.brain_db import BrainDB
        _bd = Path(wd) / '.brain'
        _db = BrainDB(_bd)
        _db.conn.execute(
            "INSERT OR REPLACE INTO brain_meta(key,value) VALUES('project_name',?)",
            (name,)
        )
        _db.conn.commit()
    except Exception:
        pass  # brain.db creation must not block legacy init
def _check_l2_health(wd: str) -> dict:
    """
    快速檢查 L2 FalkorDB/Graphiti 是否可達（不阻塞，timeout=2s）。
    Returns: {"available": bool, "url": str, "error": str}
    """
    import os
    # A-15: skip 2-second TCP probe when brain.db exists or L2 disabled
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

def cmd_status(args):
    """查看知識庫狀態（L1/L2/L3 三層，彩色輸出）"""
    wd = _workdir(args)
    b  = _brain(wd)
    print(b.status())

def cmd_add(args):
    """手動加入一筆知識"""
    # 快速模式：brain add "筆記"
    if getattr(args, 'text', None) and not getattr(args, 'title', None):
        txt = ' '.join(args.text)
        args.title   = [txt[:60].strip()]
        if not args.content: args.content = txt
    elif not getattr(args, 'title', None):
        _err('請提供內容，例如：brain add "JWT 必須使用 RS256"'); return
    wd      = _workdir(args)
    title   = ' '.join(args.title) if args.title else ''
    content = args.content or ''
    kind    = args.kind or 'Pitfall'
    tags    = args.tags or []
    if not title:
        _err("請提供 --title"); return
    ew = getattr(args, 'emotional_weight', 0.5)
    b = _brain(wd)
    _scope  = getattr(args, 'scope', 'global') or 'global'
    if _scope == 'global':  # auto-infer if not set
        _scope = _infer_scope(wd)
    _conf   = getattr(args, 'confidence', 0.8) or 0.8
    node_id = b.add_knowledge(title, content, kind, tags,
                             scope=_scope, confidence=_conf)
    # 寫入 emotional_weight
    if ew != 0.5:
        try:
            b.graph._conn.execute(
                "UPDATE nodes SET emotional_weight=? WHERE id=?", (ew, node_id))
            b.graph._conn.commit()
        except Exception:
            pass
    _ok(f"知識已加入：{C}{B}{node_id}{R}")
    _info(f"類型：{kind}  標題：{title}")
    # P3: surface near-duplicate warning if detected
    if not getattr(args, 'quiet', False):
        try:
            evts = b.db.recent_events(event_type="near_duplicate", limit=1)
            if evts and evts[0].get("payload"):
                import json as _j
                p = _j.loads(evts[0]["payload"]) if isinstance(evts[0]["payload"], str) else evts[0]["payload"]
                if p.get("new_id") == node_id:
                    print(f"  {Y}⚠ 相似知識已存在（相似度 {p['similarity']:.0%}）：{p['existing_id'][:16]}{R}")
                    print(f"  {D}  若確認重複請執行：brain dedup --execute{R}")
        except Exception:
            pass
        first_word = title.split()[0] if title.split() else title
        _info(f"查詢：{GR}brain ask \"{first_word}\"{R}")


def cmd_review(args):
    """審查 KRB Staging 中待核准的知識（brain review list / approve / reject）"""
    wd  = _workdir(args)
    sub = getattr(args, 'review_sub', None)
    bd  = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    from project_brain.brain_db    import BrainDB
    from project_brain.graph       import KnowledgeGraph
    from project_brain.review_board import KnowledgeReviewBoard
    graph = KnowledgeGraph(bd)
    krb   = KnowledgeReviewBoard(bd, graph)

    if sub == 'list' or sub is None:
        limit   = getattr(args, 'limit', 20)
        pending = krb.list_pending(limit=limit)
        if not pending:
            _info("KRB Staging 目前沒有待審知識")
            _info("自動捕捉的知識（brain scan / git hook LLM 提取）會出現在這裡")
            return
        print(f"\n{B}{C}  KRB Staging — 待審知識 ({len(pending)} 筆){R}")
        print(f"{D}{'─'*54}{R}")
        for node in pending:
            print(f"  {node.summary_line()}")
        print(f"\n{D}  brain review approve <id>   核准進入 L3{R}")
        print(f"{D}  brain review reject  <id>   拒絕並記錄原因{R}\n")

    elif sub == 'approve':
        sid = getattr(args, 'id', None)
        if not sid:
            _err("請提供 staged ID：brain review approve <id>"); return
        reviewer = getattr(args, 'reviewer', 'human')
        note     = getattr(args, 'note', '')
        l3_id = krb.approve(sid, reviewer=reviewer, note=note)
        if l3_id:
            _ok(f"已核准 → L3 節點：{l3_id}")
        else:
            _err(f"找不到 staging ID：{sid}")

    elif sub == 'reject':
        sid = getattr(args, 'id', None)
        if not sid:
            _err("請提供 staged ID：brain review reject <id>"); return
        reason = getattr(args, 'reason', '')
        if not reason:
            _err("請提供拒絕原因：--reason \"...\""  ); return
        ok = krb.reject(sid, reviewer=getattr(args, 'reviewer', 'human'), reason=reason)
        if ok:
            _ok(f"已拒絕 {sid}：{reason}")
        else:
            _err(f"找不到 staging ID：{sid}")

    else:
        _err(f"未知子命令：{sub}，可用：list / approve / reject")


def cmd_setup(args):
    """One-command setup (first-time use)."""
    wd = _workdir(args)
    from project_brain.setup_wizard import run_setup
    run_setup(workdir=wd)


def cmd_ask(args):
    """Ask a question (alias for brain context)."""
    wd    = _workdir(args)
    query = " ".join(args.query) if isinstance(args.query, list) else (args.query or "")
    if not query:
        _err("Usage: brain ask <question>")
        return
    class _A:
        workdir = wd
        task    = [query]
    cmd_context(_A())


def cmd_sync(args):
    """Learn from the latest git commit (called by git hook)."""
    import pathlib, subprocess
    wd    = _workdir(args)
    quiet = getattr(args, "quiet", False)
    bd    = pathlib.Path(wd) / ".brain"
    if not bd.exists():
        if not quiet:
            _err("Brain not initialised -- run: brain setup")
        return
    # Get latest commit info
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=%H|%s|%an"],
            cwd=wd, capture_output=True, text=True
        )
        if result.returncode != 0 or not result.stdout.strip():
            if not quiet:
                _info("No git history found — nothing to sync")
            return
        parts   = result.stdout.strip().split("|", 2)
        commit  = parts[0][:8]
        message = parts[1] if len(parts) > 1 else ""
        author  = parts[2] if len(parts) > 2 else ""
        # A-22: commit message quality filter
        msg_words = len(message.split())
        low_q     = (len(message) < 10 or msg_words < 3 or
                     message.lower().strip() in {
                         "wip","fix","update","changes","misc",
                         "temp","test","debug","hack","hotfix"
                     })
        episode_confidence = 0.2 if low_q else 0.5
        if low_q and not quiet:
            _info(f"Low-quality commit (confidence=0.2): {message[:40]}")

        # Write episode to BrainDB
        from project_brain.brain_db import BrainDB
        db = BrainDB(bd)
        ep = db.add_episode(
            content=f"{message} ({author})",
            source=f"git-{commit}",
            confidence=episode_confidence
        )
        # Phase 4: auto-link episode to related L3 nodes
        try:
            linked = db.link_episode_to_nodes(ep, f"{message} {commit}")
            if linked > 0 and not quiet:
                _info(f"L2→L3 連結 {linked} 個相關知識節點")
        except Exception:
            pass

        # Extract L3 knowledge from commit (heuristic or AI)
        try:
            from project_brain.engine import ProjectBrain
            brain = ProjectBrain(wd)
            learned = brain.learn_from_commit("HEAD")
            if learned > 0 and not quiet:
                _info(f"L3 新增 {learned} 筆知識")
        except Exception:
            pass

        if not quiet:
            _ok(f"Synced commit {commit}: {message[:50]}")
    except Exception as e:
        if not quiet:
            _err(f"Sync failed: {e}")


def cmd_context(args):
    """查詢：這個任務需要注入哪些知識？"""
    wd   = _workdir(args)
    task = ' '.join(args.task) if args.task else ''
    if not task:
        _err("請提供 --task 或直接寫任務描述"); return
    b   = _brain(wd)
    ctx = b.get_context(task)
    if ctx:
        print(f"\n{C}{B}🧠  相關知識注入{R}\n{GR}{'─'*50}{R}")
        print(ctx)
        print(f"{GR}{'─'*50}{R}")
    else:
        # 診斷：區分「真的空」和「只有 Component，沒有 Pitfall/Decision/Rule/ADR」
        stats = b.graph.stats()
        total = stats.get('nodes', 0)
        by_type = stats.get('by_type', {})
        knowledge_types = [t for t in ('Pitfall','Decision','Rule','ADR') if by_type.get(t,0) > 0]

        if total == 0:
            print(f"{Y}⚠{R}  知識庫剛建立，還沒有任何知識")
            print(f"   加入第一條知識：")
            print(f"   {GR}  brain add \"JWT 必須使用 RS256\"  --kind Rule{R}")
            print(f"   {GR}  brain add \"你的踩坑記錄\"        --kind Pitfall{R}")
            print(f"   {D}每次 commit 也會自動記錄（透過 git hook）{R}")
        elif not knowledge_types:
            # A-24: check BrainDB for Note type too
            from project_brain.brain_db import BrainDB as _BDB
            from pathlib import Path as _P
            _bdb  = _BDB(_P(wd) / ".brain")
            _note_count = _bdb.conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE type='Note'"
            ).fetchone()[0]
            if _note_count > 0:
                # Has Notes but brain ask doesn't show them yet
                print(f"{Y}⚠{R}  找到 {W}{_note_count}{R} 筆筆記，但關鍵字不符")
                print(f"   試試更換關鍵字，或加入更多知識")
                print(f"   {GR}  brain add \"更多知識\"  --kind Rule{R}")
            else:
                print(f"{Y}⚠{R}  知識庫剛建立，還沒有知識")
                print(f"   馬上加入第一條規則：")
                print(f"   {GR}  brain add \"你的第一條規則或踩坑\"  --kind Rule{R}")
                print(f"   {GR}  brain add \"你的第一條踩坑紀錄\"   --kind Pitfall{R}")
        else:
            print(f"{Y}⚠{R}  找不到「{task}」相關的知識")
            print(f"   知識庫現有：{', '.join(f'{t} {by_type[t]}' for t in knowledge_types)}")
            print(f"   試試更換關鍵字，或用 {D}brain add{R} 手動加入相關知識")


def cmd_meta_knowledge(args):
    """設定知識節點的適用條件與失效條件（Meta-Knowledge，v7.0）

    讓 Agent 知道「這條知識在什麼時候才適用」「什麼時候就不適用了」，
    避免無條件套用不應該套用的規則。

    範例：
        brain meta <node_id> \
          --applies-when "只在微服務架構中" \
          --invalidated-when "升級到 Node.js 20+ 後此 polyfill 不再需要"
    """
    wd      = _workdir(args)
    node_id = args.node_id
    ac      = args.applies_when    or ""
    ic      = args.invalidated_when or ""

    if not ac and not ic:
        _err("至少提供 --applies-when 或 --invalidated-when 其中一個")
        return

    b  = _brain(wd)
    ok = b.graph.set_meta_knowledge(node_id, ac, ic)
    if ok:
        _ok(f"節點 {C}{node_id}{R} Meta-Knowledge 已更新")
        if ac: print(f"  {Y}⚠ 適用條件{R}：{ac}")
        if ic: print(f"  {RE}🚫 失效條件{R}：{ic}")
    else:
        _err(f"找不到節點：{node_id}")




def cmd_serve(args):
    """啟動 Project Brain API Server（L3 知識庫 + L1a Session Store）"""
    wd   = _workdir(args)
    port = args.port or 7891

    # ── MCP Server 模式（v8.1）─────────────────────────────────────────────
    if getattr(args, 'mcp', False):
        print(f"\n{B}{C}🔌 Brain MCP Server 模式{R}")
        print(f"  {D}讓 Claude Code / Cursor / VS Code 直接連接 Project Brain{R}\n")
        print(f"  Claude Code 設定範例：")
        print(f"  {GR}{{")
        print(f'    "mcpServers": {{')
        print(f'      "project-brain": {{')
        print(f'        "command": "python",')
        print(f'        "args": ["-m", "project_brain.mcp_server"],')
        print(f'        "env": {{"BRAIN_WORKDIR": "{wd}"}}')
        print(f"      }}")
        print(f"    }}")
        print(f"  }}{R}\n")
        try:
            import sys as _sys
            _sys.argv = ['mcp_server', '--workdir', wd]
            from project_brain.mcp_server import main as _mcp_main
            _mcp_main()
        except ImportError as e:
            _err(f"MCP Server 需要安裝依賴：pip install mcp")
            _err(f"詳情：{e}")
            _info("或直接執行：python -m project_brain.mcp_server --workdir " + wd)
        return

    brain_dir = Path(wd) / '.brain'
    if not brain_dir.exists():
        _err(f"找不到 .brain 目錄，請先執行：brain init --workdir {wd}")
        return

    try:
        from flask import Flask, request, jsonify
        from flask_cors import CORS
    except ImportError:
        _err("請安裝依賴：pip install flask flask-cors")
        return

    from project_brain.engine import ProjectBrain
    from project_brain.session_store import SessionStore, CATEGORY_CONFIG

    brain = ProjectBrain(wd)
    store = SessionStore(brain_dir=brain_dir)

    # ── Flask App（routes 定義在 core/brain/api_server.py）────────────

    from project_brain.api_server import create_app

    _api_key = os.environ.get('BRAIN_API_KEY','') or os.environ.get('ANTHROPIC_API_KEY','')
    app = create_app(workdir=wd, api_key=_api_key)

    # ── 啟動模式（3b + 3c：生產/開發二選一）────────────────────────
    production = getattr(args, 'production', False)
    workers    = getattr(args, 'workers', 4)
    bind_host  = getattr(args, 'host', '0.0.0.0')

    if production:
        # 生產模式：Gunicorn multi-worker
        print(f"\n  {G}⚡ Production 模式：Gunicorn {workers} workers{R}")
        print(f"  {D}  比 Flask dev server 高 {workers}x 吞吐量{R}")
        try:
            import subprocess
            cmd = [
                "gunicorn",
                "--workers",      str(workers),
                "--worker-class", "gthread",
                "--threads",      "2",
                "--bind",         f"{bind_host}:{port}",
                "--timeout",      "30",
                "--access-logfile", "-",
                "--error-logfile",  "-",
                "brain:app",
            ]
            print(f"  {D}執行：{' '.join(cmd)}{R}\n")
            subprocess.execvp("gunicorn", cmd)
        except FileNotFoundError:
            _err("Gunicorn 未安裝：pip install gunicorn")
            _info("退回開發模式...")
            app.run(host=bind_host, port=port, debug=False, use_reloader=False, threaded=True)
    else:
        # 開發模式（預設）：Flask dev server with threaded=True
        app.run(host=bind_host, port=port, debug=False, use_reloader=False, threaded=True)


# ══════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════

def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

def _load_dotenv():
    """
    從 .env 檔案載入環境變數。

    搜尋順序：
      1. 當前目錄的 .env
      2. $BRAIN_WORKDIR/.env（若已設定）
      3. ~/.brain/.env（全域設定）

    支援的格式：
      ANTHROPIC_API_KEY=sk-ant-...
      BRAIN_LLM_PROVIDER=openai
      BRAIN_LLM_BASE_URL=http://localhost:11434/v1
      BRAIN_LLM_MODEL=llama3.1:8b
      GRAPHITI_URL=redis://localhost:6379
      BRAIN_WORKDIR=/your/project

    已有環境變數的不覆蓋（export 的值優先）。
    """
    import os
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
                    val = val.strip().strip(chr(34)).strip(chr(39))  # 移除引號
                    if key and key not in os.environ:  # 不覆蓋已有值
                        os.environ[key] = val
            except Exception:
                pass
            break  # 找到第一個就停止

def _settings_block() -> str:
    """目前設定區塊（LLM + 工作目錄），顯示在 help 頂部"""
    import os
    provider = os.environ.get("BRAIN_LLM_PROVIDER", "anthropic").lower()
    if provider == "openai":
        base_url = os.environ.get("BRAIN_LLM_BASE_URL", "http://localhost:11434/v1")
        model    = os.environ.get("BRAIN_LLM_MODEL", "llama3.1:8b")
        # 判斷供應商名稱
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
    import os
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


def cmd_scan(args):
    """舊專案考古掃描：分析 git 歷史，重建 L3 知識圖譜"""
    import os, subprocess as _sp
    wd        = _workdir(args)
    verbose   = not getattr(args, 'quiet', False)
    heuristic = getattr(args, 'heuristic', False)
    scan_all  = getattr(args, 'scan_all', False)
    limit     = 999_999 if scan_all else 100
    bd        = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請先執行：brain setup"); return

    # ── Heuristic 模式（零費用）──────────────────────────────────
    if heuristic:
        scope_msg = "全部 commit" if scan_all else f"最近 100 個 commit"
        _info(f"Heuristic 掃描：{scope_msg}（零費用，零 API）")
        try:
            log = _sp.check_output(
                ["git", "log", f"--max-count={limit}",
                 "--pretty=format:%H|%ae|%s", "--diff-filter=M"],
                cwd=wd, text=True, stderr=_sp.DEVNULL
            )
        except Exception:
            _err("無法讀取 git 歷史"); return

        lines = [l for l in log.strip().splitlines() if l.strip()]
        from project_brain.engine import ProjectBrain
        b  = ProjectBrain(wd)
        ok = 0
        with _Spinner("解析 commit", total=len(lines)) as sp:
            for line in lines:
                parts = line.split("|", 2)
                if len(parts) < 3:
                    sp.update("（格式不符，略過）")
                    continue
                commit_hash, author, msg = parts
                chunk = b._heuristic_extract(msg, commit_hash)
                if chunk:
                    sp.update(f"[{chunk['type']}] {msg}")
                    node_id = b.extractor.make_id(chunk["type"], chunk["title"] + chunk["content"])
                    b.db.add_node(node_id, chunk["type"], chunk["title"],
                                  content=chunk["content"],
                                  confidence=chunk["confidence"])
                    b.graph.add_node(node_id, chunk["type"], chunk["title"],
                                     content=chunk["content"],
                                     source_url=f"git-{commit_hash[:8]}")
                    ok += 1
                else:
                    sp.update(f"略過：{msg}")
        _ok(f"完成：{ok}/{len(lines)} 筆知識寫入 L3")
        _info("接著執行：brain embed  →  建立向量索引")
        return

    # ── LLM 模式（高品質，需要 API）─────────────────────────────
    provider = os.environ.get("BRAIN_LLM_PROVIDER", "anthropic")
    has_key  = bool(os.environ.get("ANTHROPIC_API_KEY") or
                    os.environ.get("OPENAI_API_KEY") or
                    provider == "openai")
    if not has_key:
        _err("brain scan 需要 LLM（付費 API 或本地 Ollama）")
        print(f"""
替代方案（擇一）：

  {G}1. 本地 Ollama（免費）{R}
     ollama pull qwen2.5:7b
     export BRAIN_LLM_PROVIDER=openai
     export BRAIN_LLM_BASE_URL=http://localhost:11434/v1
     export BRAIN_LLM_MODEL=qwen2.5:7b
     brain scan

  {G}2. 便宜 Claude Haiku（約 $0.08）{R}
     export ANTHROPIC_API_KEY=sk-ant-...
     export BRAIN_LLM_MODEL=claude-haiku-4-5-20251001
     brain scan

  {G}3. 純 Heuristic（零費用，無 LLM）{R}
     brain scan --heuristic          # 最近 100 個 commit
     brain scan --heuristic --all    # 全部 commit
""")
        return

    model_name = os.environ.get("BRAIN_LLM_MODEL", "預設")
    scope_msg  = "全部 commit" if scan_all else "最近 100 個 commit"
    _info(f"LLM 掃描（{provider} / {model_name}）")
    _info(f"掃描 {scope_msg}，每個 commit 呼叫一次 LLM...")

    # 先取 commit 清單（不加 --diff-filter，與 archaeologist 保持一致）
    try:
        log_lines = _sp.check_output(
            ["git", "log", f"--max-count={limit}", "--pretty=format:%H|%s"],
            cwd=wd, text=True, stderr=_sp.DEVNULL
        ).strip().splitlines()
        # 排除 skip_patterns（與 extractor.from_git_history 相同邏輯）
        import re as _re
        skip = [r"^(Merge|bump|version|release|format|lint|style|typo)", r"^\d+\.\d+"]
        total = sum(
            1 for l in log_lines
            if l.strip() and not any(
                _re.match(p, l.split("|",1)[-1].strip(), _re.IGNORECASE)
                for p in skip
            )
        )
    except Exception:
        total = limit  # fallback

    b = _brain(wd)

    # Monkey-patch extractor 加入 spinner callback
    _orig   = b.extractor.from_git_commit
    _sp_ctx = _Spinner("LLM 分析", total=total)
    _sp_ctx.__enter__()

    def _patched(commit_hash, commit_msg, diff):
        _sp_ctx.update(commit_msg)
        return _orig(commit_hash, commit_msg, diff)

    b.extractor.from_git_commit = _patched
    try:
        report = b.scan(verbose=False, limit=limit)
    finally:
        _sp_ctx.__exit__(None, None, None)
        b.extractor.from_git_commit = _orig

    print(report)


def cmd_webui(args):
    """D3.js 知識圖譜視覺化（在瀏覽器驗證 add 的結果）"""
    wd   = _workdir(args)
    port = getattr(args, 'port', 7890)
    bd   = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，執行：brain setup"); return

    from project_brain.web_ui.server import create_app as create_webui_app
    try:
        web_app = create_webui_app(workdir=wd)
        print(f"\n  {G}🌐 Brain WebUI{R}  http://127.0.0.1:{port}")
        print(f"  {D}Ctrl+C 結束{R}\n")
        web_app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)
    except Exception as e:
        _err(f"WebUI 啟動失敗：{e}")
        print(f"  {D}使用 brain serve 並訪問 http://localhost:7891/v1/knowledge{R}")



def cmd_index(args):
    """Phase 1: 批次為現有知識建立向量索引（提升語意搜尋）"""
    wd    = _workdir(args)
    quiet = getattr(args, 'quiet', False)
    bd    = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，執行：brain setup"); return

    from project_brain.brain_db import BrainDB
    from project_brain.embedder  import get_embedder

    emb = get_embedder()
    if not emb:
        _info("Embedding 已停用（BRAIN_EMBED_PROVIDER=none）")
        return

    db      = BrainDB(bd)
    pending = db.get_nodes_without_vectors()
    if not pending:
        _info(f"所有節點已有向量索引（共 {db.stats()['total']} 個）")
        return

    model_name = getattr(emb, 'MODEL', type(emb).__name__)
    if not quiet:
        _info(f"向量索引：{len(pending)} 個節點  模型：{model_name}")
        if "tfidf" in model_name.lower():
            _info("使用本地 TF-IDF（零依賴）。更高品質：ollama pull nomic-embed-text")

    ok = 0
    for node in pending:
        text = f"{node['title']} {node['content']}"[:2000]
        vec  = emb.embed(text)
        if vec:
            db.add_vector(node['id'], vec, model=model_name)
            ok += 1
            if not quiet and ok % 10 == 0:
                print(f"  {ok}/{len(pending)}...", end='\r')

    if not quiet:
        print()
        _ok(f"完成：{ok}/{len(pending)} 個節點已建立向量索引")
        _info("brain ask 現在使用混合搜尋（FTS5 × 0.4 + 向量 × 0.6）")


def _verify_sqlite_vec():
    """
    sqlite-vec 三層端對端驗證：
      Layer 1 — import sqlite_vec          套件是否安裝
      Layer 2 — sqlite_vec.load(conn)      能否載入 SQLite C 擴充
      Layer 3 — vec_distance_cosine(...)   SQL 函數是否可執行

    同時偵測 embedding 後端（決定向量品質）。
    """
    import sqlite3, struct

    # ── Layer 1：套件安裝 ──────────────────────────────────────
    try:
        import sqlite_vec as sv
        ver = getattr(sv, "__version__", "unknown")
        print(f"  {G}✓{R}  Layer 1  套件已安裝  {D}(sqlite-vec {ver}){R}")
    except ImportError:
        print(f"  {RE}✗{R}  Layer 1  套件未安裝")
        print(f"     {D}pip install sqlite-vec{R}")
        print(f"  {GR}  → 向量搜尋不可用，使用純 FTS5 關鍵字搜尋{R}")
        return

    # ── Layer 2：載入 SQLite C 擴充 ───────────────────────────
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

    # ── Layer 3：SQL 函數執行 ─────────────────────────────────
    try:
        dim   = 4
        vec_a = struct.pack(f'{dim}f', 1.0, 0.0, 0.0, 0.0)
        vec_b = struct.pack(f'{dim}f', 1.0, 0.0, 0.0, 0.0)
        dist  = conn.execute(
            "SELECT vec_distance_cosine(?, ?)", (vec_a, vec_b)
        ).fetchone()[0]
        if abs(dist) < 0.001:   # 相同向量距離應接近 0
            print(f"  {G}✓{R}  Layer 3  vec_distance_cosine 運算正確  {D}(dist={dist:.4f}){R}")
        else:
            print(f"  {Y}⚠{R}  Layer 3  vec_distance_cosine 結果異常  {D}(dist={dist:.4f}，預期 ≈ 0){R}")
    except Exception as e:
        print(f"  {RE}✗{R}  Layer 3  SQL 函數執行失敗：{e}")
        conn.close()
        return

    conn.close()

    # ── 顯示使用中的搜尋路徑 ──────────────────────────────────
    print(f"  {G}✓{R}  搜尋路徑  {B}C 擴充加速{R}  {D}（FTS5 × 0.4 + 向量 × 0.6）{R}")

    # ── Embedding 後端 ────────────────────────────────────────
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


def cmd_doctor(args):
    """系統健康檢查與自動修復（brain doctor [--fix]）"""
    import sqlite3, shutil, stat, json
    from project_brain import __version__

    fix   = getattr(args, 'fix', False)
    wd    = _workdir(args)
    bd    = Path(wd) / ".brain"

    ok_n = warn_n = err_n = 0
    fixes_applied = []

    def _ok2(msg):
        nonlocal ok_n; ok_n += 1
        print(f"  {G}✓{R}  {msg}")

    def _warn2(msg, hint=""):
        nonlocal warn_n; warn_n += 1
        print(f"  {Y}⚠{R}  {msg}")
        if hint:
            print(f"     {D}{hint}{R}")

    def _err2(msg, hint="", fix_desc=""):
        nonlocal err_n; err_n += 1
        print(f"  {RE}✗{R}  {msg}")
        if hint:
            print(f"     {D}{hint}{R}")
        if fix_desc:
            tag = f"{G}[已修復]{R}" if fix else f"{C}[--fix 可修復]{R}"
            print(f"     {tag} {fix_desc}")

    def _section(title):
        print(f"\n  {B}{C}{title}{R}")
        print(f"  {D}{'─' * 44}{R}")

    print(f"\n  {B}{P}🔍  brain doctor  —  系統健康檢查{R}  {D}v{__version__}{R}")

    # ── 1. 環境 ────────────────────────────────────────────────
    _section("環境")

    # Python 版本
    import sys
    pv = sys.version_info
    if pv >= (3, 10):
        _ok2(f"Python {pv.major}.{pv.minor}.{pv.micro}")
    else:
        _err2(f"Python {pv.major}.{pv.minor}.{pv.micro}（需要 3.10+）",
              "請升級 Python")

    # brain 指令可執行
    brain_bin = shutil.which("brain")
    if brain_bin:
        _ok2(f"brain 指令已安裝  {D}({brain_bin}){R}")
    else:
        _warn2("brain 指令不在 PATH 中", "執行：pip install -e . 或確認 PATH 設定")

    # LLM 設定
    provider = os.environ.get("BRAIN_LLM_PROVIDER", "anthropic").lower()
    api_key  = os.environ.get("ANTHROPIC_API_KEY", "")
    if provider == "openai":
        base_url = os.environ.get("BRAIN_LLM_BASE_URL", "http://localhost:11434/v1")
        model    = os.environ.get("BRAIN_LLM_MODEL", "llama3.1:8b")
        _ok2(f"本地 LLM 模式  {D}({model} @ {base_url}){R}")
    elif api_key:
        masked = api_key[:8] + "..." + api_key[-4:]
        _ok2(f"ANTHROPIC_API_KEY 已設定  {D}({masked}){R}")
    else:
        _warn2("ANTHROPIC_API_KEY 未設定，AI 提取功能不可用",
               "設定後可使用 brain scan / brain sync 自動提取知識\n"
               "     或改用本地 LLM：export BRAIN_LLM_PROVIDER=openai")

    # BRAIN_WORKDIR
    env_wd = os.environ.get("BRAIN_WORKDIR", "")
    if env_wd:
        _ok2(f"BRAIN_WORKDIR={env_wd}")
    else:
        _warn2(f"BRAIN_WORKDIR 未設定（自動偵測：{wd}）",
               "可設定 export BRAIN_WORKDIR=/your/project 省略 --workdir")

    # ── 2. 資料庫 ───────────────────────────────────────────────
    _section("資料庫")

    if not bd.exists():
        _err2(".brain/ 目錄不存在", "執行：brain setup", "brain setup")
        if fix:
            import subprocess
            subprocess.run(["brain", "setup", "--workdir", wd], check=False)
            fixes_applied.append("執行 brain setup")
    else:
        _ok2(f".brain/ 目錄存在  {D}({bd}){R}")

        db_path = bd / "brain.db"
        if not db_path.exists():
            _err2("brain.db 不存在", "執行：brain setup")
        else:
            size_kb = db_path.stat().st_size // 1024
            try:
                conn = sqlite3.connect(str(db_path))
                conn.row_factory = sqlite3.Row

                # 檢查 WAL 模式
                wal = conn.execute("PRAGMA journal_mode").fetchone()[0]
                if wal == "wal":
                    _ok2(f"brain.db 正常  {D}({size_kb} KB, WAL 模式){R}")
                else:
                    _warn2(f"brain.db 未使用 WAL 模式（當前：{wal}）",
                           "多進程並發讀寫時建議 WAL 模式")

                # 檢查關鍵表格
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}
                required = {"nodes", "edges", "episodes", "sessions"}
                missing  = required - tables
                if missing:
                    _err2(f"資料庫缺少表格：{', '.join(missing)}",
                          "Schema 可能需要遷移，執行：brain setup")
                else:
                    nodes    = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                    edges    = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
                    episodes = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
                    _ok2(f"Schema 完整  {D}(節點 {nodes}  邊 {edges}  情節 {episodes}){R}")

                    # 過時知識
                    deprecated = conn.execute(
                        "SELECT COUNT(*) FROM nodes WHERE confidence < 0.2"
                    ).fetchone()[0]
                    if deprecated:
                        _warn2(f"{deprecated} 個節點信心值 < 0.2（可能過時）",
                               "執行：brain status 查看詳情")
                    else:
                        _ok2("無過時知識（confidence ≥ 0.2）")

                conn.close()
            except Exception as e:
                _err2(f"brain.db 讀取失敗：{e}")

        # KRB 待審
        krb_path = bd / "review_board.db"
        if krb_path.exists():
            try:
                kc = sqlite3.connect(str(krb_path))
                pending = kc.execute(
                    "SELECT COUNT(*) FROM staged_nodes WHERE status='pending'"
                ).fetchone()[0]
                kc.close()
                if pending > 0:
                    _warn2(f"KRB 有 {pending} 筆待審知識",
                           "執行：brain review list")
                else:
                    _ok2("KRB 暫存區清空")
            except Exception:
                pass

    # ── 3. Git 整合 ─────────────────────────────────────────────
    _section("Git 整合")

    git_root = Path(wd)
    if not (git_root / ".git").exists():
        for p in git_root.parents:
            if (p / ".git").exists():
                git_root = p
                break

    if not (git_root / ".git").exists():
        _warn2("未偵測到 git repo",
               "brain 的自動學習功能需要 git")
    else:
        _ok2(f"git repo  {D}({git_root}){R}")

        hook_path = git_root / ".git" / "hooks" / "post-commit"
        if not hook_path.exists():
            _err2("post-commit hook 未安裝，commit 後不會自動學習",
                  "執行：brain setup",
                  "重新安裝 git hook")
            if fix:
                from project_brain.setup_wizard import run_setup
                run_setup(wd)
                fixes_applied.append("重新安裝 git hook")
        else:
            # 可執行
            mode = hook_path.stat().st_mode
            if mode & stat.S_IXUSR:
                _ok2("post-commit hook 已安裝且可執行")
            else:
                _err2("post-commit hook 存在但不可執行",
                      "", "設定可執行權限")
                if fix:
                    hook_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP)
                    fixes_applied.append("設定 hook 可執行權限")

            # 內容驗證
            content = hook_path.read_text(errors="ignore")
            if "brain" in content or "project_brain" in content:
                _ok2("hook 內容有效（含 brain 指令）")
            else:
                _warn2("hook 存在但不含 brain 指令，可能是其他工具安裝的",
                       f"檢查：{hook_path}")

    # ── 4. MCP 整合 ─────────────────────────────────────────────
    _section("MCP 整合")

    try:
        import mcp  # noqa: F401
        _ok2("mcp 套件已安裝")
    except ImportError:
        _warn2("mcp 套件未安裝，MCP Server 不可用",
               "pip install mcp")

    claude_cfg = Path.home() / ".claude" / "settings.json"
    if claude_cfg.exists():
        try:
            data = json.loads(claude_cfg.read_text())
            servers = data.get("mcpServers", {})
            if "project-brain" in servers:
                cfg_wd = servers["project-brain"].get("env", {}).get("BRAIN_WORKDIR", "")
                if cfg_wd == wd:
                    _ok2(f"Claude Code MCP 設定正常  {D}(BRAIN_WORKDIR={cfg_wd}){R}")
                else:
                    _warn2(
                        f"Claude Code MCP 的 BRAIN_WORKDIR 指向不同目錄",
                        f"目前：{cfg_wd}\n     預期：{wd}\n"
                        "     執行：brain setup 更新設定"
                    )
            else:
                _err2("Claude Code settings.json 未設定 project-brain",
                      "", "加入 MCP 設定")
                if fix:
                    mcp_entry = {
                        "command": "python",
                        "args": ["-m", "project_brain.mcp_server"],
                        "env": {"BRAIN_WORKDIR": wd}
                    }
                    data.setdefault("mcpServers", {})
                    data["mcpServers"]["project-brain"] = mcp_entry
                    claude_cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                    fixes_applied.append("已寫入 Claude Code MCP 設定")
        except Exception as e:
            _warn2(f"Claude Code settings.json 讀取失敗：{e}")
    else:
        _warn2("未找到 Claude Code settings.json",
               "確認 Claude Code 已安裝，或手動設定 MCP")

    # ── 5. 相依套件 ─────────────────────────────────────────────
    _section("相依套件")

    def _check_pkg(pkg, import_name=None, extra="", optional=False):
        name = import_name or pkg
        try:
            mod = __import__(name)
            ver = getattr(mod, "__version__", "")
            ver_str = f"  {D}({ver}){R}" if ver else ""
            _ok2(f"{pkg}{ver_str}")
        except ImportError:
            if optional:
                _warn2(f"{pkg} 未安裝（選填）", f"pip install {pkg}{extra}")
            else:
                _err2(f"{pkg} 未安裝", f"pip install {pkg}{extra}")

    _check_pkg("flask")
    _check_pkg("flask-cors",  "flask_cors")
    _check_pkg("anthropic",   optional=True)
    _check_pkg("mcp",         optional=True)
    _check_pkg("openai",      optional=True, extra="  （Ollama / LM Studio）")

    # sqlite-vec 端對端驗證（安裝 + 載入 + SQL 函數三層）
    _section("向量搜尋引擎")
    _verify_sqlite_vec()

    # ── 6. 知識庫健康 ───────────────────────────────────────────
    _section("知識庫健康")

    db_path = bd / "brain.db"
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            if nodes == 0:
                _warn2("知識庫是空的",
                       "執行：brain add \"第一條規則\"  或  brain scan")
            elif nodes < 5:
                _warn2(f"只有 {nodes} 個知識節點，效果有限",
                       "執行：brain scan --all 掃描歷史 commit")
            else:
                _ok2(f"{nodes} 個知識節點")

            # 向量索引覆蓋率
            try:
                vec_count = conn.execute(
                    "SELECT COUNT(*) FROM node_vectors"
                ).fetchone()[0]
                if nodes > 0:
                    pct = vec_count / nodes * 100
                    if pct >= 80:
                        _ok2(f"向量索引覆蓋率 {pct:.0f}%  {D}({vec_count}/{nodes}){R}")
                    elif pct > 0:
                        _warn2(f"向量索引覆蓋率 {pct:.0f}%  {D}({vec_count}/{nodes}){R}",
                               "執行：brain index 補齊索引")
                    else:
                        _warn2("尚未建立向量索引（僅使用 FTS5 關鍵字搜尋）",
                               "執行：brain index 啟用混合語意搜尋")
            except Exception:
                _warn2("向量索引表不存在（僅使用 FTS5 搜尋）",
                       "執行：brain index")

            # scope 分布
            scopes = conn.execute(
                "SELECT scope, COUNT(*) c FROM nodes GROUP BY scope ORDER BY c DESC LIMIT 5"
            ).fetchall()
            if scopes:
                scope_str = "  ".join(
                    f"{r['scope'] or 'global'}({r['c']})" for r in scopes
                )
                _ok2(f"Scope 分布  {D}{scope_str}{R}")

            conn.close()
        except Exception as e:
            _warn2(f"知識庫健康檢查失敗：{e}")
    else:
        _warn2("brain.db 不存在，跳過知識庫健康檢查")

    # ── 總結 ────────────────────────────────────────────────────
    print(f"\n  {D}{'─' * 44}{R}")
    parts = []
    if ok_n:   parts.append(f"{G}{ok_n} 通過{R}")
    if warn_n: parts.append(f"{Y}{warn_n} 警告{R}")
    if err_n:  parts.append(f"{RE}{err_n} 錯誤{R}")
    print(f"  {'  '.join(parts)}")

    if fixes_applied:
        print(f"\n  {G}已自動修復：{R}")
        for f_ in fixes_applied:
            print(f"    {G}✓{R}  {f_}")

    if err_n and not fix:
        print(f"\n  {D}執行 brain doctor --fix 嘗試自動修復{R}")

    print()


def main():
    import argparse

    _load_dotenv()

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

    sub = parser.add_subparsers(dest='cmd', metavar='<command>')

    def mkp(name, help_text):
        p = sub.add_parser(name, help=help_text)
        p.add_argument('--workdir', '-w', default=None,
                       help='專案目錄（預設：$BRAIN_WORKDIR 或當前目錄）')
        return p

    p = mkp('init',   '初始化 Project Brain')
    p.add_argument('--local-only', action='store_true',
                   help='本地模式：不呼叫任何 API，完全離線')
    p.add_argument('--name', default='', help='專案名稱')
    mkp('status', '查看三層記憶狀態（L1/L2/L3）')
    mkp('setup', 'One-command setup (first-time use)')

    p = mkp('ask', 'Ask Brain a question (alias for context)')
    p.add_argument('query', nargs='+', help='Question')

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
    p.add_argument('--scope', default='global',
                   help='作用域（空=自動推導）')
    p.add_argument('--kind',    default='Note',
                   choices=['Decision','Pitfall','Rule','ADR','Component','Note'],
                   help='類型（預設：Pitfall）')
    p.add_argument('--tags',    nargs='+', default=[])
    p.add_argument('--emotional-weight', dest='emotional_weight', type=float,
                   default=0.5, help='情感重量 0.0~1.0（踩坑越痛=越高，影響衰減速度）')

    p = mkp('context', '查詢任務相關知識（Context 注入）')
    p.add_argument('task', nargs='*', help='任務描述')


    p.add_argument('--dry-run', dest='dry_run', action='store_true',
                   help='只預覽，不執行（與不加 --execute 等效，提供慣用語法）')






    p = mkp('review', '審查 KRB Staging 中待核准的知識')
    p.add_argument('review_sub', nargs='?', default='list',
                   choices=['list','approve','reject'],
                   help='子命令（預設：list）')
    p.add_argument('id', nargs='?', default=None,
                   help='Staged node ID（approve / reject 時必填）')
    p.add_argument('--reviewer', default='human', help='審查者名稱')
    p.add_argument('--note',     default='',      help='核准備注')
    p.add_argument('--reason',   default='',      help='拒絕原因')
    p.add_argument('--limit',    type=int, default=20, help='列出筆數上限')

    p = mkp('doctor', '系統健康檢查與自動修復')
    p.add_argument('--fix', action='store_true', help='嘗試自動修復發現的問題')

    p = mkp('scan', '舊專案考古掃描，重建 L3 知識')
    p.add_argument('--heuristic', action='store_true',
                   help='零費用模式：只用 Conventional Commits 解析，不呼叫任何 LLM')
    p.add_argument('--all', dest='scan_all', action='store_true',
                   help='掃描全部 commit（預設只掃最近 100 個）')
    p.add_argument('--quiet', action='store_true', help='靜默模式')

    p = mkp('index', '向量索引（語意搜尋 Phase 1）')
    p.add_argument('--quiet', action='store_true')

    p = mkp('webui', 'D3.js 視覺化（驗證知識庫）')
    p.add_argument('--port', type=int, default=7890)

    p = mkp('serve', '啟動 OpenAI 相容 API（讓 Ollama/LM Studio/Cursor 查詢知識）')
    p.add_argument('--port',       type=int,   default=7891,  help='監聽 port（預設：7891）')
    p.add_argument('--production', action='store_true',       help='生產模式：使用 Gunicorn multi-worker')
    p.add_argument('--workers',    type=int,   default=4,     help='Gunicorn worker 數量（--production 時有效）')
    p.add_argument('--host',       default='0.0.0.0',        help='綁定 host（預設 0.0.0.0）')
    p.add_argument('--mcp',        action='store_true',       help='MCP Server 模式（Claude Code / Cursor 直接連接）')


    # 無參數時：印出設定區塊 + 標準 argparse help
    if len(sys.argv) == 1:
        print(_settings_block())
        print()
        parser.print_help()
        return

    # ── 常見打字錯誤自動修正 ─────────────────────────────────
    _aliases = {
        'server':       'serve',
        'start':        'serve',
        'run':          'serve',
        'ui':           'webui',
        'web':          'webui',
        'web-ui':       'webui',
        'stat':         'status',
        'info':         'status',
        'search':       'context',
        'query':        'context',
        'embed':        'index',
        'check':        'validate',
        'verify':       'validate',
        'export_rules': 'export-rules',
        'rules':        'export-rules',
    }
    # 偵測多餘的 'brain' 前綴（用戶輸入：python brain.py brain serve）
    if len(sys.argv) > 2 and sys.argv[1] == 'brain':
        print(f"  {D}（提示：直接用 brain.py {sys.argv[2]}，不需要再打 'brain'）{R}")
        sys.argv.pop(1)

    if len(sys.argv) > 1 and sys.argv[1] in _aliases:
        corrected = _aliases[sys.argv[1]]
        import sys as _sys
        print(f"  [90m（已修正：{sys.argv[1]} → {corrected}）[0m")
        _sys.argv[1] = corrected

    # ── 廢棄命令提示（v9.3）────────────────────────────────────────────
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

    args = parser.parse_args()

    if getattr(args, 'guide', False):
        _show_guide()
        return

    dispatch = {
        'init':         cmd_init,
        'status':       cmd_status,
        'setup':        cmd_setup,
        'ask':          cmd_ask,
        'sync':         cmd_sync,
        'add':          cmd_add,
        'context':      cmd_context,
        'meta':         cmd_meta_knowledge,
        'doctor':       cmd_doctor,
        'review':       cmd_review,
        'scan':         cmd_scan,
        'serve':        cmd_serve,
        'index':        cmd_index,
        'webui':        cmd_webui,
    }

    fn = dispatch.get(args.cmd)
    if fn:
        try:
            fn(args)
        except KeyboardInterrupt:
            print(f"\n{GR}已中止{R}")
    else:
        print(_settings_block())
        print()
        parser.print_help()

if __name__ == '__main__':
    main()
