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

# (entry point moved to end of file)


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
    from core.base_agent import init_session_budget
    requirement = " ".join(args.requirement)
    workdir     = get_workdir(getattr(args, "workdir", None))
    auto        = getattr(args, "yes", False)
    budget      = getattr(args, "budget", 5.0)
    no_resume   = getattr(args, "no_resume", False)
    init_session_budget(budget_usd=budget)
    print(f"{DIM}  💰 預算上限：${budget:.1f} USD{RESET}")

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


def cmd_retro(args):
    """
    /retro — 回顧統計
    分析 git log，輸出這段時間的程式碼產出、提交分布、測試比例
    """
    from agents.all_agents import get_agent
    workdir = get_workdir(getattr(args, "workdir", None))
    since   = getattr(args, "since", None) or "7 days ago"

    print(f"\n{CYAN}{BOLD}  📊 /retro — 回顧統計{RESET}")
    print(f"{DIM}  時間範圍：{since} · 目錄：{workdir}{RESET}\n")

    import subprocess
    from pathlib import Path

    # 收集 git 統計
    def git(cmd):
        r = subprocess.run(cmd, shell=True, cwd=workdir,
                           capture_output=True, text=True, timeout=15)
        return r.stdout.strip()

    commits     = git(f'git log --since="{since}" --oneline')
    commit_list = [l for l in commits.splitlines() if l]
    stat        = git(f'git log --since="{since}" --numstat --pretty=format:""')

    added = deleted = test_added = 0
    for line in stat.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            try:
                a, d = int(parts[0]), int(parts[1])
                added   += a
                deleted += d
                fname = parts[2]
                if any(x in fname for x in ["test", "spec", "__test__", ".test.", ".spec."]):
                    test_added += a
            except ValueError:
                pass

    net_loc       = added - deleted
    test_pct      = round(test_added / added * 100) if added > 0 else 0
    commit_count  = len(commit_list)

    # 統計數據
    stats_str = f"""
Git 統計（過去 {since}）：
  提交數：     {commit_count}
  新增行數：   {added:,}
  刪除行數：   {deleted:,}
  淨增行數：   {net_loc:,}
  測試程式碼：   {test_added:,} 行（佔 {test_pct}%）
  每天平均：   約 {added // 7:,} 行新增（以 7 天計算）

最近提交：
{chr(10).join(commit_list[:10])}
"""
    print(stats_str)

    # 讓 ARIA 做質化回顧
    agent = get_agent("ARIA", workdir=workdir)
    agent.chat(f"""
請根據以下 Git 統計做一個簡短的回顧分析：

{stats_str}

請評估：
1. 產出量是否健康（程式碼量、提交頻率）
2. 測試比例（{test_pct}%）是否足夠
3. 根據提交訊息，這段時間的工作重心是什麼
4. 建議下一週應該聚焦什麼

保持簡短，不超過 10 行。
""")


def cmd_qa_browser(args):
    """
    qa-browser — 真實瀏覽器 QA
    開啟 Chromium，截圖每個頁面，檢查 console 錯誤和 network 失敗
    比 TRACE 的程式碼分析更真實：看到的就是用戶看到的
    """
    from core.browser_qa import BrowserToolExecutor, BrowserQA, SCREENSHOT_DIR
    from agents.all_agents import get_agent

    workdir  = get_workdir(getattr(args, "workdir", None))
    base_url = " ".join(args.url) if hasattr(args, "url") and args.url else "http://localhost:3000"
    headless = not getattr(args, "headed", False)

    routes_arg = getattr(args, "routes", None)
    if routes_arg:
        routes = [r.strip() for r in " ".join(routes_arg).split(",")]
    else:
        routes = ["/", "/login", "/dashboard", "/about"]

    print(f"\n{CYAN}{BOLD}  🌐 Browser QA — 真實瀏覽器驗收{RESET}")
    print(f"{DIM}  URL：{base_url}")
    print(f"  路由：{', '.join(routes)}")
    print(f"  截圖儲存：{SCREENSHOT_DIR}")
    print(f"  模式：{'有頭（可見）' if not headless else '無頭（背景）'}{RESET}\n")

    executor = BrowserToolExecutor(headless=headless)
    result   = executor.execute("browser_audit", {"base_url": base_url, "routes": routes})

    import json
    report = json.loads(result)
    summary = report.get("summary", {})

    print(f"\n{BOLD}審計摘要{RESET}")
    print(f"  檢查路由：{summary.get('routes_checked', 0)}")
    print(f"  {GREEN}無錯誤：{summary.get('routes_clean', 0)}{RESET}")
    total_err = summary.get("total_errors", 0)
    if total_err:
        print(f"  {RED}有錯誤：{total_err} 個{RESET}")
        for e in summary.get("all_errors", [])[:10]:
            print(f"    {DIM}• {e}{RESET}")

    # 讓 PROBE 分析結果
    if total_err > 0:
        print(f"\n{CYAN}▶ PROBE 分析錯誤...{RESET}")
        agent = get_agent("PROBE", workdir=workdir)
        agent.chat(f"""
瀏覽器 QA 發現以下錯誤：

{json.dumps(summary.get('all_errors', []), ensure_ascii=False, indent=2)}

完整路由報告：
{json.dumps({k: {
    'console_errors': v.get('console_errors', []),
    'network_errors': v.get('network_errors', [])
} for k, v in report.get('routes', {}).items()}, ensure_ascii=False, indent=2)}

請分析這些錯誤，判斷嚴重程度，並給出具體的修復建議。
""")


def cmd_investigate(args):
    """
    investigate — 在真實運行的 app 上互動式調查問題
    描述問題，PROBE 會用真實瀏覽器重現它，截圖，然後給出診斷
    """
    from core.browser_qa import BrowserToolExecutor
    from agents.all_agents import get_agent

    workdir     = get_workdir(getattr(args, "workdir", None))
    description = " ".join(args.description)
    base_url    = getattr(args, "url", None) or "http://localhost:3000"
    headless    = not getattr(args, "headed", False)

    print(f"\n{RED}{BOLD}  🔎 /investigate — 問題調查{RESET}")
    print(f"{DIM}  問題：{description[:60]}")
    print(f"  URL：{base_url}{RESET}\n")

    # 先讓 PROBE 設計重現步驟
    probe = get_agent("PROBE", workdir=workdir)
    steps_plan = probe.chat(f"""
用戶回報以下問題：{description}

app URL：{base_url}

請設計一個在瀏覽器中重現這個問題的步驟計畫。
輸出格式：用 JSON 描述步驟，例如：
[
  {{"action": "screenshot", "label": "初始狀態"}},
  {{"action": "click", "selector": "#login-btn", "label": "點擊登入"}},
  {{"action": "fill", "selector": "#email", "value": "test@example.com", "label": "填入 email"}},
  {{"action": "assert_text", "value": "錯誤訊息", "label": "確認錯誤出現"}}
]

只輸出 JSON 陣列，不要其他文字。
""")

    # 嘗試解析步驟
    import json, re
    try:
        match = re.search(r'\[.*\]', steps_plan, re.DOTALL)
        steps = json.loads(match.group()) if match else []
    except Exception:
        steps = [{"action": "screenshot", "label": "問題重現截圖"}]

    if steps:
        print(f"\n{CYAN}▶ 用瀏覽器重現問題（{len(steps)} 個步驟）...{RESET}")
        executor = BrowserToolExecutor(headless=headless)
        result   = executor.execute("browser_flow", {"url": base_url, "steps": steps})
        flow_result = json.loads(result)

        # PROBE 分析瀏覽器結果給出診斷
        probe.chat(f"""
瀏覽器重現結果：
{json.dumps(flow_result, ensure_ascii=False, indent=2)}

原始問題描述：{description}

請根據以上結果：
1. 確認問題是否重現
2. 分析根本原因
3. 給出具體的修復方案
""")


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

    # 網頁開發命令
    p=mkp("discover"); p.add_argument("idea", nargs="+")
    p=mkp("ship");     p.add_argument("requirement", nargs="+")
    p.add_argument("--budget",    type=float, default=5.0,
                   help="API 費用預算上限 USD（預設 $5.0）")
    p.add_argument("--no-resume", action="store_true",
                   help="不使用斷點續跑，從頭開始")
    p=mkp("webdev");   p.add_argument("requirement", nargs="+"); p.add_argument("--name", default=None)
    p=mkp("feature");  p.add_argument("description", nargs="+")
    p=mkp("fixbug");   p.add_argument("description", nargs="+")
    mkp("codereview")

    # 新增弱項補強命令
    p=mkp("retro");       p.add_argument("--since", default="7 days ago")
    p=mkp("qa-browser");  p.add_argument("url", nargs="?", default=None)
    p.add_argument("--routes", nargs="+")
    p.add_argument("--headed", action="store_true",
                                           help="顯示瀏覽器視窗（非無頭模式）")
    p=mkp("investigate"); p.add_argument("description", nargs="+")
    p.add_argument("--url", default="http://localhost:3000")
    p.add_argument("--headed", action="store_true")

    # ── Project Brain 命令 ──────────────────────────────────
    p = mkp("brain")
    p.add_argument("subcommand", nargs="?", default="status",
                   choices=["init","scan","status","context","learn",
                            "add","export","share","query-shared",
                            "decay","counterfactual","validate",
                            "distill","webui"],
                   help="Brain 子命令")
    # init
    p.add_argument("--name",       default="",  help="專案名稱（init 用）")
    # context
    p.add_argument("--task",       nargs="+",   help="任務描述（context 用）")
    p.add_argument("--file",       default="",  help="相關檔案（context 用）")
    # learn
    p.add_argument("--commit",     default="HEAD", help="commit hash（learn 用）")
    # add
    p.add_argument("--title",      nargs="+",   help="知識標題（add/share 用）")
    p.add_argument("--content",    default="",  help="知識內容（add 用）")
    p.add_argument("--kind",       default="Decision",
                   choices=["Decision","Pitfall","Rule","ADR","Component"],
                   help="知識類型（add/share 用）")
    p.add_argument("--tags",       nargs="+",   default=[])
    # share
    p.add_argument("--visibility", default="team",
                   choices=["team","org","public"])
    # query-shared
    p.add_argument("--query",      nargs="+",   help="查詢關鍵字（query-shared 用）")
    # decay
    p.add_argument("--action",     default="report",
                   choices=["report","update","invalidate"])
    p.add_argument("--node-id",    default="",  help="節點 ID（decay invalidate 用）")
    p.add_argument("--reason",     default="",  help="失效原因（decay invalidate 用）")
    # counterfactual
    p.add_argument("--question",   nargs="+",   help="反事實問題")
    p.add_argument("--component",  default="",  help="目標組件")
    p.add_argument("--depth",      default="brief",
                   choices=["brief","detailed"])
    # validate
    p.add_argument("--max-api-calls", type=int, default=20)
    p.add_argument("--dry-run",    action="store_true")
    # distill
    p.add_argument("--layers",     nargs="+",
                   default=["context","prompts","lora"])
    # webui
    p.add_argument("--port",       type=int, default=7890)

    args = parser.parse_args()
    if args.command is None or args.command == "help":
        cmd_help()
        print(f"""{CYAN}── 弱項補強（新增）─────────────────────────────────────{RESET}

{GREEN}retro{RESET}                    回顧統計：git 產出、提交分布、測試比例
  --since "14 days ago"  統計時間範圍（預設 7 天）

{GREEN}qa-browser{RESET} [URL]         真實瀏覽器 QA：截圖、console 錯誤、network 失敗
  --routes /,/login      指定要檢查的路由（逗號分隔）
  --headed               顯示瀏覽器視窗（debug 用）

{GREEN}investigate{RESET} <問題描述>   用真實瀏覽器重現問題，PROBE 診斷並給修復方案
  --url http://...       目標 URL（預設 localhost:3000）
  --headed               顯示瀏覽器視窗

{CYAN}── 網頁開發 ──────────────────────────────────────────────{RESET}

{GREEN}discover{RESET} <想法>           需求模糊時深挖，產出 /ship 指令
{GREEN}ship{RESET}     <需求>           完整 13 Phase 流水線
{GREEN}feature{RESET}  <描述>           新增功能
{GREEN}fixbug{RESET}   <描述>           修復 bug
{GREEN}codereview{RESET}                PROBE + SHIELD 全面審查

{BOLD}Browser QA 需要安裝：{RESET}
  {DIM}pip install playwright && playwright install chromium{RESET}
""")
        return

    check_api_key()

    cmds = {
        "ask":cmd_ask,"agent":cmd_agent,"chat":cmd_chat,
        "do":cmd_do,"run":cmd_run,"build":cmd_build,"shell":cmd_shell,
        "dept":cmd_dept,"project":cmd_project,"review":cmd_review,
        "list":cmd_list,"clear":cmd_clear,"workdir":cmd_workdir,
        "discover":cmd_discover,"ship":cmd_ship,"webdev":cmd_webdev,
        "feature":cmd_feature,"fixbug":cmd_fix,"codereview":cmd_review_project,
        # 弱項補強
        "retro":cmd_retro,"qa-browser":cmd_qa_browser,"investigate":cmd_investigate,
        # Project Brain
        "brain":cmd_brain,
    }
    fn = cmds.get(args.command)
    if fn:
        try: fn(args)
        except KeyboardInterrupt: print(f"\n{DIM}  已中止{RESET}\n")
    else:
        print(f"{RED}✖ 未知命令: {args.command}{RESET}")

# (entry point moved to end of file)



# ── 弱項補強：新命令 ──────────────────────────────────────────


# ══════════════════════════════════════════════════════════
#  Project Brain 命令群
# ══════════════════════════════════════════════════════════

def cmd_brain(args):
    """Project Brain — 知識積累主命令（分派子命令）"""
    subcmd = getattr(args, "subcommand", None) or "status"
    if   subcmd == "init":          cmd_brain_init(args)
    elif subcmd == "scan":          cmd_brain_scan(args)
    elif subcmd == "context":       cmd_brain_context(args)
    elif subcmd == "learn":         cmd_brain_learn(args)
    elif subcmd == "status":        cmd_brain_status(args)
    elif subcmd == "export":        cmd_brain_export(args)
    elif subcmd == "add":           cmd_brain_add(args)
    elif subcmd == "share":         cmd_brain_share(args)
    elif subcmd == "query-shared":  cmd_brain_query_shared(args)
    elif subcmd == "decay":         cmd_brain_decay(args)
    elif subcmd == "counterfactual":cmd_brain_counterfactual(args)
    elif subcmd == "validate":      cmd_brain_validate(args)
    elif subcmd == "distill":       cmd_brain_distill(args)
    elif subcmd == "webui":         cmd_brain_webui(args)
    else:
        print("用法：synthex brain <init|scan|status|context|learn|add|export|"
              "share|query-shared|decay|counterfactual|validate|distill|webui>")


def cmd_brain_init(args):
    """初始化 Project Brain（新專案）"""
    from core.brain import ProjectBrain
    workdir = get_workdir(getattr(args, "workdir", None))
    brain   = ProjectBrain(workdir)
    name    = getattr(args, "name", None) or ""
    result  = brain.init(project_name=name)
    print(result)


def cmd_brain_scan(args):
    """考古掃描（舊專案重建知識圖譜）"""
    from core.brain import ProjectBrain
    workdir = get_workdir(getattr(args, "workdir", None))
    print(f"\n🔍 開始考古掃描：{workdir}")
    print("  這可能需要幾分鐘，取決於 git 歷史大小...")
    brain  = ProjectBrain(workdir)
    report = brain.scan(verbose=True)
    # 儲存報告
    report_path = f"{workdir}/.brain/SCAN_REPORT.md"
    print(f"\n📄 考古報告已儲存：{report_path}")
    print(report[:1000])


def cmd_brain_context(args):
    """為指定任務生成 Context 注入"""
    from core.brain import ProjectBrain
    workdir = get_workdir(getattr(args, "workdir", None))
    task    = " ".join(args.task)
    file    = getattr(args, "file", None) or ""
    brain   = ProjectBrain(workdir)
    ctx     = brain.get_context(task, file)
    if ctx:
        print(ctx)
    else:
        print("（知識庫為空，請先執行 synthex brain init 或 scan）")


def cmd_brain_learn(args):
    """手動觸發從最近 commit 學習"""
    from core.brain import ProjectBrain
    workdir     = get_workdir(getattr(args, "workdir", None))
    commit_hash = getattr(args, "commit", "HEAD")
    brain       = ProjectBrain(workdir)
    n           = brain.learn_from_commit(commit_hash)
    print(f"✓ 從 {commit_hash} 學習了 {n} 個知識片段")


def cmd_brain_status(args):
    """查看知識庫狀態"""
    from core.brain import ProjectBrain
    workdir = get_workdir(getattr(args, "workdir", None))
    brain   = ProjectBrain(workdir)
    print(brain.status())


def cmd_brain_export(args):
    """匯出知識圖譜（Mermaid 格式）"""
    from core.brain import ProjectBrain
    workdir = get_workdir(getattr(args, "workdir", None))
    brain   = ProjectBrain(workdir)
    mermaid = brain.export_mermaid()
    out = f"{workdir}/.brain/graph.md"
    open(out, "w").write(f"```mermaid\n{mermaid}\n```")
    print(f"✓ 知識圖譜已匯出：{out}")
    print(mermaid[:500])



# ══════════════════════════════════════════════════════════════
#  Project Brain v2.0 命令
# ══════════════════════════════════════════════════════════════

def cmd_brain_share(args):
    """發布知識到跨專案共享庫"""
    from core.brain import ProjectBrain
    workdir = get_workdir(getattr(args, "workdir", None))
    brain   = ProjectBrain(workdir)
    title   = " ".join(args.title)
    content_text = getattr(args, "content", "") or ""
    kind    = getattr(args, "kind", "Pitfall") or "Pitfall"
    vis     = getattr(args, "visibility", "team") or "team"

    reg = brain.shared_registry
    new_id = reg.publish(title, content_text, kind,
                         confidence=0.85, visibility=vis)
    if new_id:
        print(f"✓ 已發布到共享庫（ID: {new_id}，可見性: {vis}）")
    else:
        print("ℹ 相同知識已存在（冪等），已更新信心分數")


def cmd_brain_query_shared(args):
    """查詢跨專案知識庫"""
    from core.brain import ProjectBrain
    workdir = get_workdir(getattr(args, "workdir", None))
    brain   = ProjectBrain(workdir)
    q       = " ".join(args.query)

    results = brain.shared_registry.query(q, limit=10)
    if not results:
        print("（共享庫中無相關知識）")
        return
    print(f"找到 {len(results)} 筆跨專案知識：")
    for r in results:
        print(f"\n  [{r['type']}] {r['title']}")
        print(f"  來源：{r['namespace']}  信心：{r['confidence']:.0%}")
        print(f"  {(r.get('content') or '')[:120]}...")


def cmd_brain_decay(args):
    """查看知識衰減報告"""
    from core.brain import ProjectBrain
    workdir = get_workdir(getattr(args, "workdir", None))
    brain   = ProjectBrain(workdir)
    de      = brain.decay_engine
    action  = getattr(args, "action", "report")
    if action == "report":
        summary = de.decay_summary()
        print("## 知識衰減報告")
        for k, v in summary.items():
            print(f"  {k}: {v}")
        deprecated = de.deprecated_knowledge(limit=10)
        if deprecated:
            print("\n低信心知識前" + str(len(deprecated)) + "筆：")


            for node in deprecated:
                conf  = node.get("confidence", 0)
                kind  = node.get("kind", "?")
                title = node.get("title", "")
                print(f"  [{kind}] {title} (conf={conf:.2f})")
    elif action == "update":
        result = de.run()
        print(f"✓ 衰減掃描完成，更新 {len(result)} 筆知識")
    elif action == "invalidate":
        node_id = getattr(args, "node_id", "") or ""
        ok = de.restore(node_id, confidence=0.05)
        status = "✓ 已標記節點失效" if ok else "✗ 節點不存在"
        print(f"{status}：{node_id}")


def cmd_brain_counterfactual(args):
    """反事實推理：如果當初不這樣設計，會怎樣？"""
    from core.brain import ProjectBrain
    from core.brain.v2.counterfactual import CounterfactualQuery
    workdir   = get_workdir(getattr(args, "workdir", None))
    brain     = ProjectBrain(workdir)
    question  = " ".join(args.question)
    component = getattr(args, "component", "") or ""
    depth     = getattr(args, "depth", "brief") or "brief"

    print(f"\n🔮 反事實分析中（{depth} 模式）...")
    q      = CounterfactualQuery(question=question,
                                  target_component=component, depth=depth)
    result = brain.counterfactual.reason(q)
    print(brain.counterfactual.format_result(result))

def cmd_brain_add(args):
    """手動加入知識片段"""
    from core.brain import ProjectBrain
    workdir = get_workdir(getattr(args, "workdir", None))
    brain   = ProjectBrain(workdir)
    title   = " ".join(args.title)
    content = getattr(args, "content", "") or ""
    kind    = getattr(args, "kind", "Decision") or "Decision"
    tags    = getattr(args, "tags", []) or []
    node_id = brain.add_knowledge(title, content, kind, tags)
    print(f"✓ 知識已加入：{node_id}")

def cmd_init(args):
    """
    init — 智能專案初始化
    新專案：scaffold 完整起點
    現有專案：深度掃描，分析健康度，提出行動建議
    """
    from core.project_scanner import ProjectScanner
    from agents.all_agents import get_agent

    workdir = get_workdir(getattr(args, "workdir", None))
    scanner = ProjectScanner(workdir)
    scan    = scanner.scan()

    print(scanner.format_report(scan))

    if scan["is_new"]:
        print(f"\n{CYAN}{BOLD}  🆕 新專案 — 開始 scaffold{RESET}")
        print(f"{DIM}  FORGE 將建立完整的專案起點（含可觀測性）{RESET}")
        agent = get_agent("FORGE", workdir=workdir, auto_confirm=True)
        agent.run(f"""
這是一個新的 Next.js 16 + TypeScript 專案。
請依照你的 SKILL.md 完整設定環境，特別注意：

1. 建立標準目錄結構（src/app、src/components、src/services、
   src/repositories、src/lib、src/types）
2. 安裝並設定 Sentry（錯誤追蹤）
3. 安裝並設定 PostHog（使用分析）
4. 建立 .env.local.example（包含 Sentry 和 PostHog 的 key）
5. 建立 .github/workflows/ci.yml
6. 建立 .gitignore、tsconfig.json、next.config.ts
7. 建立 src/lib/errors.ts（統一錯誤類別）
8. 建立 src/lib/api-response.ts（統一 API 回應格式）
9. 執行 git init && git add . && git commit -m "chore: initial setup"

工作目錄：{workdir}
""")
    else:
        issues = scan.get("issues", [])
        print(f"\n{CYAN}{BOLD}  📁 現有專案 — 分析完成{RESET}")

        if issues:
            print(f"\n{YELLOW}  發現 {len(issues)} 個問題，交由對應角色處理...{RESET}")
            # 高優先問題先處理
            high = [i for i in issues if i["severity"] == "high"]
            if high:
                agent = get_agent("FORGE", workdir=workdir, auto_confirm=getattr(args, "yes", False))
                issues_text = "\n".join(f"- {i['issue']}：{i['fix']}" for i in high)
                agent.run(f"""
掃描發現以下高優先問題，請逐一修復：

{issues_text}

工作目錄：{workdir}
技術棧：{scan.get('project_type', 'unknown')}
""")
        else:
            print(f"  {GREEN}✔ 專案健康度良好，無高優先問題{RESET}")

        # 輸出快速行動清單
        if not scan["health"].get("has_observability"):
            print(f"\n{YELLOW}  ⚠ 缺少可觀測性工具，執行以下命令安裝：{RESET}")
            print(f"  {DIM}python synthex.py do FORGE \"安裝並設定 Sentry 和 PostHog\"{RESET}")


def cmd_deploy(args):
    """
    deploy — 本地驗證通過後才部署
    不通過就不部署，通過才推上去
    """
    from core.deploy_pipeline import DeployPipeline

    workdir       = get_workdir(getattr(args, "workdir", None))
    target        = getattr(args, "target", None) or "vercel"
    skip_browser  = getattr(args, "skip_browser", False)
    auto          = getattr(args, "yes", False)
    prod_url      = getattr(args, "url", None)

    pipeline = DeployPipeline(workdir=workdir, target=target, auto_confirm=auto)
    pipeline.run(skip_browser_qa=skip_browser, production_url=prod_url)


def cmd_vitals(args):
    """
    vitals — 量測 Core Web Vitals（LCP、CLS、TTI）
    """
    from core.browser_qa import _check_playwright, install_playwright

    url   = " ".join(args.url) if hasattr(args, "url") and args.url else "http://localhost:3000"
    runs  = getattr(args, "runs", 3)

    if not _check_playwright():
        install_playwright()

    print(f"\n{CYAN}{BOLD}  📊 Core Web Vitals — {url}{RESET}")

    try:
        from core.browser_qa import ExtendedBrowserQA
    except ImportError:
        # ExtendedBrowserQA 在 append 的程式碼裡，直接 exec browser_qa 後取得
        import importlib.util, sys
        spec = importlib.util.spec_from_file_location(
            "browser_qa",
            str(__import__("pathlib").Path(__file__).parent / "core" / "browser_qa.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ExtendedBrowserQA = mod.ExtendedBrowserQA

    with ExtendedBrowserQA(headless=True) as qa:
        result = qa.web_vitals(url, runs=runs)

    from agents.all_agents import get_agent
    workdir = get_workdir(getattr(args, "workdir", None))
    if result.get("lcp", {}).get("rating", "").startswith("差") or \
       result.get("cls", {}).get("rating", "").startswith("差"):
        print(f"\n{YELLOW}  ⚠ 有需要改善的指標，BYTE + KERN 分析...{RESET}")
        agent = get_agent("BYTE", workdir=workdir)
        agent.chat(f"""
Core Web Vitals 量測結果：
- LCP：{result.get('lcp', {}).get('value_ms')}ms ({result.get('lcp', {}).get('rating')})
- CLS：{result.get('cls', {}).get('value')} ({result.get('cls', {}).get('rating')})
- TTI：{result.get('tti', {}).get('value_ms')}ms

Google 標準：LCP < 2500ms、CLS < 0.1

請分析可能的原因，並給出具體的優化建議（程式碼層面）。
""")


def cmd_cross_device(args):
    """
    cross-device — 在桌機、平板、手機三種視窗截圖，找出響應式問題
    """
    from core.browser_qa import _check_playwright, install_playwright
    import json

    url     = " ".join(args.url) if hasattr(args, "url") and args.url else "http://localhost:3000"
    workdir = get_workdir(getattr(args, "workdir", None))

    if not _check_playwright():
        install_playwright()

    print(f"\n{CYAN}{BOLD}  📱 跨裝置測試 — {url}{RESET}")

    try:
        from core.browser_qa import ExtendedBrowserQA
        with ExtendedBrowserQA(headless=True) as qa:
            result = qa.cross_device(url)
    except Exception as e:
        print(f"{RED}✖ {e}{RESET}")
        return

    # 讓 SPARK 分析截圖結果
    devices_with_errors = {k: v for k, v in result.get("devices", {}).items() if v.get("errors")}
    if devices_with_errors:
        agent = get_agent("SPARK", workdir=workdir)
        agent.chat(f"""
跨裝置測試發現以下問題：

{json.dumps(devices_with_errors, ensure_ascii=False, indent=2)}

截圖已儲存到 ~/.synthex/screenshots/

請分析各裝置的問題，給出 UI/UX 修復建議。
""")


# re-wire final main()
def main():
    import sys, os, argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="synthex", add_help=False)
    sub    = parser.add_subparsers(dest="command")

    def mkp(name, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("--workdir", default=None)
        p.add_argument("--yes", action="store_true")
        return p

    # 核心對話
    mkp("ask").add_argument("task", nargs="+")
    p=mkp("agent");  p.add_argument("name"); p.add_argument("task", nargs="+")
    for c in ("do","run"):
        p=mkp(c);    p.add_argument("name"); p.add_argument("task", nargs="+")
    mkp("build").add_argument("task", nargs="+")
    mkp("chat").add_argument("name")
    mkp("shell").add_argument("name")
    mkp("project").add_argument("brief", nargs="+")
    p=mkp("dept");   p.add_argument("dept"); p.add_argument("task", nargs="+")
    mkp("review").add_argument("name")
    sub.add_parser("list"); sub.add_parser("help")
    p=sub.add_parser("clear");   p.add_argument("name")
    p=sub.add_parser("workdir"); p.add_argument("path")

    # 規劃流水線
    p=mkp("discover"); p.add_argument("idea", nargs="+")
    p=mkp("ship");     p.add_argument("requirement", nargs="+")
    p.add_argument("--budget",    type=float, default=5.0,
                   help="API 費用預算上限 USD（預設 $5.0）")
    p.add_argument("--no-resume", action="store_true",
                   help="不使用斷點續跑，從頭開始")
    p=mkp("webdev");   p.add_argument("requirement", nargs="+"); p.add_argument("--name", default=None)
    p=mkp("feature");  p.add_argument("description", nargs="+")
    p=mkp("fixbug");   p.add_argument("description", nargs="+")
    mkp("codereview")

    # 弱項補強第一批
    p=mkp("retro");       p.add_argument("--since", default="7 days ago")
    p=mkp("qa-browser");  p.add_argument("url", nargs="?", default=None)
    p.add_argument("--routes", nargs="+")
    p.add_argument("--headed", action="store_true")
    p=mkp("investigate"); p.add_argument("description", nargs="+")
    p.add_argument("--url", default="http://localhost:3000")
    p.add_argument("--headed", action="store_true")

    # 弱項補強第二批（本次新增）
    mkp("init")
    p=mkp("deploy");      p.add_argument("--target", default="vercel",
                                          choices=["vercel","railway","manual"])
    p.add_argument("--skip-browser", action="store_true")
    p.add_argument("--url", default=None)
    p=mkp("vitals");      p.add_argument("url", nargs="?", default="http://localhost:3000")
    p.add_argument("--runs", type=int, default=3)
    p=mkp("cross-device"); p.add_argument("url", nargs="?", default="http://localhost:3000")

    # ── Project Brain v4.0 ─────────────────────────────────
    p = mkp("brain")
    p.add_argument("subcommand", nargs="?", default="status",
                   choices=["init","scan","status","context","learn",
                            "add","export","share","query-shared",
                            "decay","counterfactual","validate",
                            "distill","webui"],
                   help="Brain 子命令")
    p.add_argument("--name",          default="",     help="專案名稱（init）")
    p.add_argument("--task",          nargs="+",      help="任務描述（context）")
    p.add_argument("--file",          default="",     help="相關檔案（context）")
    p.add_argument("--commit",        default="HEAD", help="commit hash（learn）")
    p.add_argument("--title",         nargs="+",      help="知識標題（add/share）")
    p.add_argument("--content",       default="",     help="知識內容（add）")
    p.add_argument("--kind",          default="Decision",
                   choices=["Decision","Pitfall","Rule","ADR","Component"])
    p.add_argument("--tags",          nargs="+",      default=[])
    p.add_argument("--visibility",    default="team",
                   choices=["team","org","public"])
    p.add_argument("--query",         nargs="+",      help="查詢關鍵字（query-shared）")
    p.add_argument("--action",        default="report",
                   choices=["report","update","invalidate"])
    p.add_argument("--node-id",       default="")
    p.add_argument("--reason",        default="")
    p.add_argument("--question",      nargs="+",      help="反事實問題")
    p.add_argument("--component",     default="")
    p.add_argument("--depth",         default="brief",
                   choices=["brief","detailed"])
    p.add_argument("--max-api-calls", type=int, default=20)
    p.add_argument("--dry-run",       action="store_true")
    p.add_argument("--layers",        nargs="+",
                   default=["context","prompts","lora"])
    p.add_argument("--port",          type=int, default=7890)

    args = parser.parse_args()

    if args.command is None or args.command == "help":
        cmd_help()
        print(f"""
{CYAN}── 完整命令表（最新版）──────────────────────────────────────{RESET}

{BOLD}弱項一：智能專案初始化{RESET}
  {GREEN}init{RESET}                     偵測新/現有專案，自動 scaffold 或掃描健康度

{BOLD}弱項二：部署路徑{RESET}
  {GREEN}deploy{RESET}                   本地驗證通過才部署（Vercel/Railway/Manual）
    --target vercel|railway|manual
    --skip-browser           跳過瀏覽器 QA
    --url https://...        指定線上驗證 URL

{BOLD}弱項三：可觀測性（在 FORGE SKILL.md 中定義，init 自動安裝）{RESET}

{BOLD}弱項四：架構約束（在 NEXUS SKILL.md 中定義，ship 時強制遵守）{RESET}

{BOLD}弱項五：完整瀏覽器 QA{RESET}
  {GREEN}qa-browser{RESET} [URL]         截圖 + console 錯誤 + network 失敗
  {GREEN}vitals{RESET} [URL]             Core Web Vitals（LCP、CLS、TTI）
    --runs N                 量測次數取平均（預設 3）
  {GREEN}cross-device{RESET} [URL]        桌機 + 平板 + 手機三種視窗截圖
  {GREEN}investigate{RESET} <問題描述>    用瀏覽器重現問題，PROBE 診斷

{BOLD}回顧{RESET}
  {GREEN}retro{RESET}                    Git 統計 + ARIA 質化回顧
    --since "14 days ago"
""")
        return

    # brain 的部分子命令不需要 API Key（純本地操作）
    _BRAIN_NO_API_KEY = {
        "init", "status", "add", "export", "decay",
        "distill", "webui", "query-shared", "validate",
    }
    _skip_api_check = (
        args.command == "brain"
        and getattr(args, "subcommand", "status") in _BRAIN_NO_API_KEY
    ) or args.command in ("list", "clear", "workdir")

    if not _skip_api_check:
        check_api_key()

    cmds = {
        "ask":cmd_ask, "agent":cmd_agent, "chat":cmd_chat,
        "do":cmd_do, "run":cmd_run, "build":cmd_build, "shell":cmd_shell,
        "dept":cmd_dept, "project":cmd_project, "review":cmd_review,
        "list":cmd_list, "clear":cmd_clear, "workdir":cmd_workdir,
        "discover":cmd_discover, "ship":cmd_ship, "webdev":cmd_webdev,
        "feature":cmd_feature, "fixbug":cmd_fix, "codereview":cmd_review_project,
        "retro":cmd_retro, "qa-browser":cmd_qa_browser, "investigate":cmd_investigate,
        # 弱項補強第二批
        "init":cmd_init, "deploy":cmd_deploy,
        "vitals":cmd_vitals, "cross-device":cmd_cross_device,
        # Project Brain v4.0
        "brain":cmd_brain,
    }
    fn = cmds.get(args.command)
    if fn:
        try: fn(args)
        except KeyboardInterrupt: print(f"\n{DIM}  已中止{RESET}\n")
    else:
        print(f"{RED}✖ 未知命令：{args.command}{RESET}")


# ══════════════════════════════════════════════════════════════
#  Project Brain v4.0 命令
# ══════════════════════════════════════════════════════════════

def cmd_brain_validate(args):
    """知識自主驗證（v4.0）"""
    from core.brain import ProjectBrain
    workdir      = get_workdir(getattr(args, "workdir", None))
    max_api      = getattr(args, "max_api_calls", 20)
    dry_run      = getattr(args, "dry_run", False)
    brain        = ProjectBrain(workdir)
    print(f"\n🔍 知識驗證（max_api_calls={max_api}, dry_run={dry_run}）")
    try:
        validator = brain.validator
        report    = validator.run(max_api_calls=max_api, dry_run=dry_run)
        print(f"\n{report.summary()}")
    except Exception as e:
        print(f"{RED}✖ 驗證失敗：{e}{RESET}")


def cmd_brain_distill(args):
    """知識蒸餾（v4.0）"""
    from core.brain import ProjectBrain
    workdir = get_workdir(getattr(args, "workdir", None))
    layers  = getattr(args, "layers", ["context", "prompts", "lora"]) or ["context", "prompts", "lora"]
    brain   = ProjectBrain(workdir)
    print(f"\n⚗ 知識蒸餾（layers={layers}）")
    try:
        distiller = brain.distiller
        result    = distiller.distill_all(layers=layers)
        print(f"\n{result.summary()}")
    except Exception as e:
        print(f"{RED}✖ 蒸餾失敗：{e}{RESET}")


def cmd_brain_webui(args):
    """啟動知識圖譜 Web UI（v4.0，預設 port 7890）"""
    from core.brain import ProjectBrain
    from core.brain.web_ui.server import run_server
    workdir = get_workdir(getattr(args, "workdir", None))
    port    = getattr(args, "port", 7890)
    from pathlib import Path
    brain_dir = Path(workdir) / ".brain"
    if not brain_dir.exists():
        print(f"{RED}✖ 找不到 .brain 目錄，請先執行：{RESET}")
        print(f"  python synthex.py brain init --workdir {workdir}")
        return
    try:
        run_server(Path(workdir), port=port)
    except Exception as e:
        print(f"{RED}✖ Web UI 啟動失敗：{e}{RESET}")
        print("  請確認已安裝：pip install flask flask-cors")

if __name__ == "__main__":
    main()
