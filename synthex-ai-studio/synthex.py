#!/usr/bin/env python3
"""
SYNTHEX AI STUDIO v2 — Agentic CLI
"""
import sys, os, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

RESET="\033[0m";BOLD="\033[1m";DIM="\033[2m"
PURPLE="\033[35m";CYAN="\033[96m";GREEN="\033[92m";YELLOW="\033[93m";RED="\033[91m"
CONFIG_FILE = Path.home() / ".synthex_config.json"

BANNER = f"""{PURPLE}{BOLD}
  ███████╗██╗   ██╗███╗   ██╗████████╗██╗  ██╗███████╗██╗  ██╗
  ██╔════╝╚██╗ ██╔╝████╗  ██║╚══██╔══╝██║  ██║██╔════╝╚██╗██╔╝
  ███████╗ ╚████╔╝ ██╔██╗ ██║   ██║   ███████║█████╗   ╚███╔╝
  ╚════██║  ╚██╔╝  ██║╚██╗██║   ██║   ██╔══██║██╔══╝   ██╔██╗
  ███████║   ██║   ██║ ╚████║   ██║   ██║  ██║███████╗██╔╝ ██╗
  ╚══════╝   ╚═╝   ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
                 AI  S T U D I O  v2  ·  Agentic{RESET}"""

def check_api_key():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"\n{RED}✖ 缺少 ANTHROPIC_API_KEY{RESET}\n  export ANTHROPIC_API_KEY='...'")
        sys.exit(1)

def load_config():
    import json
    if CONFIG_FILE.exists():
        try: return json.loads(CONFIG_FILE.read_text())
        except: pass
    return {}

def save_config(cfg):
    import json
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

def get_workdir(args_workdir=None):
    if args_workdir: return str(Path(args_workdir).resolve())
    return load_config().get("workdir", os.getcwd())

# ── Commands ──────────────────────────────────────────────────

def cmd_ask(args):
    from core.orchestrator import Orchestrator
    Orchestrator(workdir=get_workdir(getattr(args,"workdir",None))).run(" ".join(args.task))

def cmd_agent(args):
    from agents.all_agents import get_agent
    try:
        get_agent(args.name.upper(), workdir=get_workdir(getattr(args,"workdir",None))).chat(" ".join(args.task))
    except ValueError as e: print(f"{RED}✖ {e}{RESET}"); sys.exit(1)

def cmd_do(args):
    from agents.all_agents import get_agent
    workdir = get_workdir(getattr(args,"workdir",None))
    auto = getattr(args,"yes",False)
    task = " ".join(args.task)
    print(f"\n{CYAN}{BOLD}  🚀 Agentic 模式 · {args.name.upper()}{RESET}")
    print(f"{DIM}  工作目錄: {workdir}{RESET}")
    try:
        get_agent(args.name.upper(), workdir=workdir, auto_confirm=auto).run(task)
    except ValueError as e: print(f"{RED}✖ {e}{RESET}"); sys.exit(1)

cmd_run = cmd_do

def cmd_build(args):
    from core.orchestrator import Orchestrator
    task = " ".join(args.task)
    workdir = get_workdir(getattr(args,"workdir",None))
    print(f"\n{PURPLE}{BOLD}  🏗  Build 模式 — Agentic + 智能路由{RESET}")
    print(f"{DIM}  工作目錄: {workdir}{RESET}")
    Orchestrator(workdir=workdir).run(task, agentic=True, auto_confirm=getattr(args,"yes",False))

def cmd_chat(args):
    from agents.all_agents import get_agent
    workdir = get_workdir(getattr(args,"workdir",None))
    try: agent = get_agent(args.name.upper(), workdir=workdir)
    except ValueError as e: print(f"{RED}✖ {e}{RESET}"); sys.exit(1)
    print(f"\n{CYAN}{BOLD}  💬 {agent.emoji} {agent.name} · 對話模式{RESET}")
    print(f"{DIM}  exit=結束  clear=清記憶  !cd <路徑>=切換目錄{RESET}\n")
    while True:
        try:
            u = input(f"{BOLD}你 > {RESET}").strip()
            if not u: continue
            if u.lower() in ("exit","quit","結束"): break
            if u.lower() == "clear": agent.clear_memory(); continue
            if u.startswith("!cd "): agent.set_workdir(u[4:].strip()); continue
            agent.chat(u)
        except (KeyboardInterrupt, EOFError): break
    print(f"\n{DIM}  對話結束{RESET}\n")

def cmd_shell(args):
    from agents.all_agents import get_agent
    workdir = get_workdir(getattr(args,"workdir",None))
    auto = getattr(args,"yes",False)
    try: agent = get_agent(args.name.upper(), workdir=workdir, auto_confirm=auto)
    except ValueError as e: print(f"{RED}✖ {e}{RESET}"); sys.exit(1)
    print(f"\n{PURPLE}{BOLD}  🤖 Agentic Shell · {agent.emoji} {agent.name}{RESET}")
    print(f"{DIM}  工作目錄: {workdir}")
    print(f"  Agent 可讀寫檔案、執行命令")
    print(f"  exit=結束  clear=清記憶  !cd <路徑>=切換目錄  !workdir=查看目錄{RESET}\n")
    while True:
        try:
            u = input(f"{PURPLE}{BOLD}[{agent.name}] > {RESET}").strip()
            if not u: continue
            if u.lower() in ("exit","quit","結束"): break
            if u.lower() == "clear": agent.clear_memory(); continue
            if u.startswith("!cd "): agent.set_workdir(u[4:].strip()); continue
            if u == "!workdir": print(f"  {DIM}{agent.workdir}{RESET}"); continue
            agent.run(u)
        except (KeyboardInterrupt, EOFError): break
    print(f"\n{DIM}  Shell 結束{RESET}\n")

def cmd_project(args):
    from core.orchestrator import Orchestrator
    print(BANNER)
    Orchestrator(workdir=get_workdir(getattr(args,"workdir",None))).project(" ".join(args.brief))

def cmd_dept(args):
    from agents.all_agents import DEPT_AGENTS, get_agent
    workdir = get_workdir(getattr(args,"workdir",None))
    dm = {"exec":"exec","engineering":"engineering","eng":"engineering","product":"product",
          "ai":"ai_data","ai_data":"ai_data","devops":"devops","qa":"qa","biz":"biz",
          "高層":"exec","工程":"engineering","產品":"product","資料":"ai_data",
          "基礎架構":"devops","品質":"qa","商務":"biz"}
    dk = dm.get(args.dept.lower())
    if not dk: print(f"{RED}✖ 找不到部門: {args.dept}{RESET}"); sys.exit(1)
    task = " ".join(args.task)
    print(f"\n{CYAN}{BOLD}  部門協作：{dk}{RESET}")
    for name in DEPT_AGENTS[dk]:
        get_agent(name, workdir=workdir).chat(task)

def cmd_review(args):
    from agents.all_agents import get_agent
    try: agent = get_agent(args.name.upper(), workdir=get_workdir(getattr(args,"workdir",None)))
    except ValueError as e: print(f"{RED}✖ {e}{RESET}"); sys.exit(1)
    print(f"\n{CYAN}  貼入內容（最後輸入 END）：{RESET}")
    lines = []
    while True:
        try:
            l = input()
            if l.strip() == "END": break
            lines.append(l)
        except EOFError: break
    content = "\n".join(lines)
    if not content.strip(): print(f"{RED}✖ 空內容{RESET}"); return
    agent.review(content)

def cmd_list(args):
    from agents.all_agents import DEPT_AGENTS, ALL_AGENTS
    dn = {"exec":"🎯 高層管理","engineering":"⚙️  工程開發","product":"💡 產品設計",
          "ai_data":"🧠 AI 與資料","devops":"🚀 基礎架構","qa":"🔍 品質安全","biz":"📣 商務發展"}
    print(f"\n{BOLD}SYNTHEX AI STUDIO · 全體 24 位 Agent{RESET}\n")
    print(f"  {DIM}對話: python synthex.py agent <n> \"任務\"{RESET}")
    print(f"  {DIM}執行: python synthex.py do <n> \"任務\"{RESET}")
    print(f"  {DIM}Shell: python synthex.py shell <n>{RESET}\n")
    for dept, agents in DEPT_AGENTS.items():
        print(f"{CYAN}{dn.get(dept, dept)}{RESET}")
        for name in agents:
            cls = ALL_AGENTS[name]
            print(f"  {cls.emoji}  {BOLD}{name:<8}{RESET} {cls.title}")
        print()

def cmd_clear(args):
    from agents.all_agents import get_agent
    try: get_agent(args.name.upper()).clear_memory()
    except ValueError as e: print(f"{RED}✖ {e}{RESET}")

def cmd_workdir(args):
    path = str(Path(args.path).resolve())
    if not Path(path).exists(): print(f"{RED}✖ 路徑不存在: {path}{RESET}"); sys.exit(1)
    cfg = load_config(); cfg["workdir"] = path; save_config(cfg)
    print(f"\n{GREEN}✔ 預設工作目錄：{BOLD}{path}{RESET}\n")

def cmd_help(args=None):
    print(BANNER)
    print(f"""
{BOLD}對話模式{RESET} （給建議，你自己執行）
  {GREEN}ask{RESET}    <任務>            智能路由到最合適 Agent
  {GREEN}agent{RESET}  <n> <任務>     直接呼叫 Agent
  {GREEN}chat{RESET}   <n>            持續對話（保留記憶）
  {GREEN}dept{RESET}   <部門> <任務>     整個部門一起分析
  {GREEN}project{RESET} <說明>           多部門完整專案規劃
  {GREEN}review{RESET} <n>           審查貼入的內容

{BOLD}Agentic 模式{RESET} （Agent 真實操作你的檔案）
  {GREEN}do{RESET}     <n> <任務>     執行任務（讀寫檔案、執行命令）
  {GREEN}run{RESET}    <n> <任務>     同 do
  {GREEN}build{RESET}  <任務>           智能路由 + Agentic 執行
  {GREEN}shell{RESET}  <n>            互動式 Agentic Shell

{BOLD}設定{RESET}
  {GREEN}workdir{RESET} <路徑>           設定預設工作目錄（永久）
  {GREEN}list{RESET}                    列出所有 Agent
  {GREEN}clear{RESET}  <n>            清除 Agent 記憶

{BOLD}全域選項{RESET}
  --workdir <路徑>    本次工作目錄
  --yes               危險操作自動確認

{BOLD}範例{RESET}
  {DIM}python synthex.py workdir ~/my-project
  python synthex.py do FORGE "建立 .github/workflows/ci.yml"
  python synthex.py do STACK "掃描所有 Python API，補全缺少的錯誤處理"
  python synthex.py shell NOVA          # 開始 Agentic 對話
  python synthex.py build "建立 Dockerfile 和 docker-compose.yml"{RESET}
""")

# ── Main ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="synthex", add_help=False)
    sub = parser.add_subparsers(dest="command")

    def mkp(name, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("--workdir", default=None)
        p.add_argument("--yes", action="store_true")
        return p

    mkp("ask").add_argument("task", nargs="+")
    p=mkp("agent"); p.add_argument("name"); p.add_argument("task", nargs="+")
    for cmd in ("do","run"):
        p=mkp(cmd); p.add_argument("name"); p.add_argument("task", nargs="+")
    mkp("build").add_argument("task", nargs="+")
    mkp("chat").add_argument("name")
    mkp("shell").add_argument("name")
    mkp("project").add_argument("brief", nargs="+")
    p=mkp("dept"); p.add_argument("dept"); p.add_argument("task", nargs="+")
    mkp("review").add_argument("name")
    sub.add_parser("list")
    sub.add_parser("help")
    p=sub.add_parser("clear"); p.add_argument("name")
    p=sub.add_parser("workdir"); p.add_argument("path")

    args = parser.parse_args()
    if args.command is None or args.command == "help":
        cmd_help(); return
    check_api_key()

    cmds = {
        "ask":cmd_ask,"agent":cmd_agent,"chat":cmd_chat,
        "do":cmd_do,"run":cmd_run,"build":cmd_build,"shell":cmd_shell,
        "dept":cmd_dept,"project":cmd_project,"review":cmd_review,
        "list":cmd_list,"clear":cmd_clear,"workdir":cmd_workdir,
    }
    fn = cmds.get(args.command)
    if fn:
        try: fn(args)
        except KeyboardInterrupt: print(f"\n{DIM}  已中止{RESET}\n")
    else:
        print(f"{RED}✖ 未知命令: {args.command}{RESET}"); cmd_help()

if __name__ == "__main__":
    main()


# ── Web Dev Commands (appended) ───────────────────────────────

def cmd_discover(args):
    """/discover — 需求模糊時，讓多個角色幫你深挖需求，產出可直接 /ship 的需求書"""
    from core.web_orchestrator import WebOrchestrator
    idea = " ".join(args.idea)
    workdir = get_workdir(getattr(args, "workdir", None))

    print(f"\n{CYAN}{BOLD}  🔍 /discover — 需求深度挖掘{RESET}")
    print(f"{DIM}  6 個角色依序分析：LUMI → ARIA → ECHO → NEXUS → SIGMA → ARIA")
    print(f"  產出：docs/DISCOVER.md + 可直接執行的 /ship 指令{RESET}\n")

    orc = WebOrchestrator(workdir=workdir, auto_confirm=True)
    orc.discover(idea)


def cmd_ship(args):
    """/ship — 從決策到實作一氣呵成（11 Phase 完整流水線）"""
    from core.web_orchestrator import WebOrchestrator
    requirement = " ".join(args.requirement)
    workdir = get_workdir(getattr(args, "workdir", None))
    auto = getattr(args, "yes", False)

    print(f"\n{PURPLE}{BOLD}  🚀 /ship — 從決策到實作一氣呵成{RESET}")
    print(f"{DIM}  11 Phase：範疇確認 → PRD → 產品驗證 → 架構 → 可行性")
    print(f"            → 環境準備 → 前端 → 後端 → 測試 → 安全 → 交付{RESET}")
    print(f"{DIM}  工作目錄：{workdir}{RESET}")

    orc = WebOrchestrator(workdir=workdir, auto_confirm=auto)
    orc.ship(requirement)


def cmd_webdev(args):
    """
    完整建站流水線：PRD → 架構 → 實作 → 測試 → 部署設定
    """
    from core.web_orchestrator import WebOrchestrator
    requirement = " ".join(args.requirement)
    workdir = get_workdir(getattr(args, "workdir", None))
    name = getattr(args, "name", None) or "my-project"
    auto = getattr(args, "yes", False)

    print(f"\n{PURPLE}{BOLD}  🌐 SYNTHEX WEB BUILD{RESET}")
    print(f"{DIM}  需求：{requirement[:80]}{RESET}")
    print(f"{DIM}  目錄：{workdir}{RESET}\n")

    orc = WebOrchestrator(workdir=workdir, auto_confirm=auto)
    orc.build(requirement, project_name=name)


def cmd_feature(args):
    """在現有專案中實作一個新功能"""
    from core.web_orchestrator import WebOrchestrator
    description = " ".join(args.description)
    workdir = get_workdir(getattr(args, "workdir", None))
    auto = getattr(args, "yes", False)

    print(f"\n{CYAN}{BOLD}  ✨ 新功能實作{RESET}")
    orc = WebOrchestrator(workdir=workdir, auto_confirm=auto)
    orc.feature(description)


def cmd_fix(args):
    """診斷並修復錯誤"""
    from core.web_orchestrator import WebOrchestrator
    description = " ".join(args.description)
    workdir = get_workdir(getattr(args, "workdir", None))

    print(f"\n{RED}{BOLD}  🔧 Bug 修復模式{RESET}")
    orc = WebOrchestrator(workdir=workdir, auto_confirm=True)
    orc.fix(description)


def cmd_review_project(args):
    """全面程式碼審查（PROBE + SHIELD）"""
    from core.web_orchestrator import WebOrchestrator
    workdir = get_workdir(getattr(args, "workdir", None))

    print(f"\n{YELLOW}{BOLD}  🔍 全面程式碼審查{RESET}")
    orc = WebOrchestrator(workdir=workdir, auto_confirm=True)
    orc.review()


# re-wire main() to include new commands
_original_main = main

def main():
    import sys, os, argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="synthex", add_help=False)
    sub = parser.add_subparsers(dest="command")

    def mkp(name, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("--workdir", default=None)
        p.add_argument("--yes", action="store_true")
        return p

    # 原有命令
    mkp("ask").add_argument("task", nargs="+")
    p=mkp("agent");   p.add_argument("name"); p.add_argument("task", nargs="+")
    for cmd in ("do","run"):
        p=mkp(cmd);   p.add_argument("name"); p.add_argument("task", nargs="+")
    mkp("build").add_argument("task", nargs="+")
    mkp("chat").add_argument("name")
    mkp("shell").add_argument("name")
    mkp("project").add_argument("brief", nargs="+")
    p=mkp("dept");    p.add_argument("dept"); p.add_argument("task", nargs="+")
    mkp("review").add_argument("name")
    sub.add_parser("list")
    sub.add_parser("help")
    p=sub.add_parser("clear");   p.add_argument("name")
    p=sub.add_parser("workdir"); p.add_argument("path")

    # 新增的網頁開發命令
    p=mkp("discover"); p.add_argument("idea", nargs="+")
    p=mkp("ship");     p.add_argument("requirement", nargs="+")
    p=mkp("webdev");   p.add_argument("requirement", nargs="+"); p.add_argument("--name", default=None)
    p=mkp("feature");  p.add_argument("description", nargs="+")
    p=mkp("fixbug");   p.add_argument("description", nargs="+")
    mkp("codereview")

    args = parser.parse_args()
    if args.command is None or args.command == "help":
        cmd_help()
        # 額外顯示新命令
        print(f"""{CYAN}── 網頁開發專用 ──────────────────────────────────────────{RESET}

{GREEN}webdev{RESET}  <需求描述>       完整建站：PRD→架構→實作→測試→部署
{GREEN}feature{RESET} <功能描述>       在現有專案新增功能（自動實作）
{GREEN}fixbug{RESET}  <錯誤描述>       診斷並修復 bug
{GREEN}codereview{RESET}               全面程式碼審查（PROBE + SHIELD）

{BOLD}範例{RESET}
  {DIM}python synthex.py webdev "電商平台，支援商品瀏覽、購物車、Stripe 結帳" --name my-shop
  python synthex.py feature "新增用戶個人頁面，可編輯頭像和名稱"
  python synthex.py fixbug "登入後 redirect 到 /dashboard 出現 404"
  python synthex.py codereview{RESET}
""")
        return

    check_api_key()

    cmds = {
        "ask":cmd_ask,"agent":cmd_agent,"chat":cmd_chat,
        "do":cmd_do,"run":cmd_run,"build":cmd_build,"shell":cmd_shell,
        "dept":cmd_dept,"project":cmd_project,"review":cmd_review,
        "list":cmd_list,"clear":cmd_clear,"workdir":cmd_workdir,
        # new
        "discover":cmd_discover,"ship":cmd_ship,"webdev":cmd_webdev,"feature":cmd_feature,
        "fixbug":cmd_fix,"codereview":cmd_review_project,
    }
    fn = cmds.get(args.command)
    if fn:
        try: fn(args)
        except KeyboardInterrupt: print(f"\n{DIM}  已中止{RESET}\n")
    else:
        print(f"{RED}✖ 未知命令: {args.command}{RESET}")

if __name__ == "__main__":
    main()
