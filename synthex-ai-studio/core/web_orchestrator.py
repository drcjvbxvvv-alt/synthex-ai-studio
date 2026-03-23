"""
Web Development Orchestrator
單一入口，完成：PRD 生成 → 架構規劃 → 程式實作 → 測試 → 修復 → Git commit
這是讓 Synthex 真正「做出產品」的核心流程
"""

import os
import json
from pathlib import Path
from datetime import datetime
import anthropic

RESET  = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
PURPLE = "\033[35m"; CYAN = "\033[96m"; GREEN = "\033[92m"
YELLOW = "\033[93m"; RED = "\033[91m"; BLUE = "\033[34m"

PHASE_COLORS = [PURPLE, BLUE, CYAN, GREEN, YELLOW]


def _phase(n: int, title: str):
    c = PHASE_COLORS[n % len(PHASE_COLORS)]
    print(f"\n{c}{BOLD}{'═'*60}")
    print(f"  Phase {n} · {title}")
    print(f"{'═'*60}{RESET}")


def _step(msg: str):
    print(f"\n{CYAN}  ▶ {msg}{RESET}")


def _ok(msg: str):
    print(f"  {GREEN}✔ {msg}{RESET}")


def _warn(msg: str):
    print(f"  {YELLOW}⚠ {msg}{RESET}")


class WebOrchestrator:
    """
    完整的網頁開發流水線。

    執行順序：
    1. ECHO  — 分析需求，產出 PRD
    2. NEXUS — 架構設計，選定技術棧
    3. FORGE — 建立專案骨架、設定 CI/CD
    4. BYTE+STACK — 實作前後端功能
    5. PROBE+TRACE — 測試與修復
    6. FORGE — Git commit，產出部署說明
    """

    def __init__(self, workdir: str = None, auto_confirm: bool = False):
        from agents.all_agents import get_agent
        self.workdir      = workdir or os.getcwd()
        self.auto_confirm = auto_confirm
        self._get_agent   = lambda name: get_agent(
            name, workdir=self.workdir, auto_confirm=self.auto_confirm
        )
        self._use_web_tools()

    def _use_web_tools(self):
        """把所有 agent 換成帶 WebToolExecutor 的版本"""
        from core.web_tools import WebToolExecutor, get_webdev_tools
        # monkey-patch: 在 agent 初始化後替換 executor 和工具
        self._webdev_tools = get_webdev_tools("engineering")
        self._executor_factory = lambda: WebToolExecutor(
            workdir=self.workdir, auto_confirm=self.auto_confirm
        )

    def _agent(self, name: str):
        """取得帶 WebToolExecutor 的 agent"""
        from agents.all_agents import get_agent
        from core.web_tools import WebToolExecutor, get_webdev_tools
        agent = get_agent(name, workdir=self.workdir, auto_confirm=self.auto_confirm)
        agent.executor = WebToolExecutor(workdir=self.workdir, auto_confirm=self.auto_confirm)
        return agent

    def _run(self, agent_name: str, task: str, tools=None) -> str:
        """用 web tools 執行 agent 任務"""
        from core.web_tools import get_webdev_tools
        agent = self._agent(agent_name)
        # 覆蓋 get_tools_for_role 讓 agent.run() 使用 web tools
        import core.base_agent as ba
        orig_get_tools = None
        try:
            import core.tools as ct
            orig = ct.get_tools_for_role

            def patched_get_tools(role: str):
                return get_webdev_tools(role)

            ct.get_tools_for_role = patched_get_tools
            result = agent.run(task)
        finally:
            ct.get_tools_for_role = orig

        return result

    def _chat(self, agent_name: str, task: str) -> str:
        return self._agent(agent_name).chat(task)

    # ══════════════════════════════════════════════════════════
    #  主流水線
    # ══════════════════════════════════════════════════════════

    def build(self, requirement: str, project_name: str = None) -> dict:
        """
        完整建站流水線。
        requirement: 用自然語言描述你想建立的網站
        """
        start = datetime.now()
        results = {}

        print(f"\n{PURPLE}{BOLD}{'═'*60}")
        print(f"  🏗  SYNTHEX WEB BUILD PIPELINE")
        print(f"  需求：{requirement[:60]}{'...' if len(requirement)>60 else ''}")
        print(f"  工作目錄：{self.workdir}")
        print(f"{'═'*60}{RESET}")

        # ── Phase 1: 需求分析 & PRD ──────────────────────────
        _phase(1, "需求分析 & PRD")
        _step("ECHO 分析需求，產出完整 PRD...")

        prd = self._chat("ECHO", f"""
請分析以下網站需求，產出一份完整的 PRD（Product Requirements Document）。

需求：{requirement}

PRD 必須包含：
1. 產品概述（目標用戶、核心價值）
2. 功能列表（按優先級 P0/P1/P2 分類）
3. 頁面清單與路由設計
4. 資料模型（主要實體和關係）
5. API 端點設計（如有後端）
6. 非功能需求（效能、安全、SEO）
7. 技術建議（框架、資料庫、第三方服務）
8. MVP 範疇（第一版只做什麼）

請直接輸出 PRD 內容，格式清晰。
""")
        results["prd"] = prd

        # 儲存 PRD 到磁碟
        prd_path = Path(self.workdir) / "PRD.md"
        prd_path.write_text(f"# PRD — {requirement[:50]}\n\n生成時間：{datetime.now().isoformat()}\n\n{prd}")
        _ok(f"PRD 已儲存至 {prd_path}")

        # ── Phase 2: 技術架構 ────────────────────────────────
        _phase(2, "技術架構設計")
        _step("NEXUS 設計系統架構...")

        arch = self._chat("NEXUS", f"""
基於以下 PRD，設計完整的技術架構：

{prd[:2000]}

請輸出：
1. 技術棧決策（前端框架、後端框架、資料庫、部署平台）及選擇理由
2. 目錄結構設計（完整的資料夾和檔案規劃）
3. 核心資料流（用 ASCII 圖表示）
4. 環境變數清單（需要哪些 API key、設定值）
5. 開發順序建議（哪個模組先做，依賴關係）
6. 立即可以開始實作的第一個任務

工作目錄：{self.workdir}
""")
        results["architecture"] = arch

        arch_path = Path(self.workdir) / "ARCHITECTURE.md"
        arch_path.write_text(f"# 技術架構\n\n{arch}")
        _ok(f"架構文件已儲存至 {arch_path}")

        # ── Phase 3: 專案初始化 ──────────────────────────────
        _phase(3, "專案初始化 & 骨架建立")
        _step("FORGE 建立專案骨架...")

        scaffold = self._run("FORGE", f"""
請根據以下架構設計，建立完整的專案骨架：

{arch[:2000]}

執行步驟：
1. 先用 detect_framework 或 get_project_info 確認目前目錄狀態
2. 建立所有必要的目錄結構（用 write_file 建立 .gitkeep 佔位）
3. 建立 package.json（如果是 JS 專案）或 requirements.txt（如果是 Python）
4. 建立基本設定檔：tsconfig.json、.eslintrc、.gitignore、.env.local（只放範本 key）
5. 建立 README.md，說明如何啟動專案
6. 執行 git init 和 git add .

工作目錄：{self.workdir}
需求摘要：{requirement[:200]}
""")
        results["scaffold"] = scaffold

        # ── Phase 4: 前端實作 ────────────────────────────────
        _phase(4, "前端實作")
        _step("BYTE 實作前端組件和頁面...")

        frontend = self._run("BYTE", f"""
請根據 PRD 和架構設計，實作前端部分：

PRD 摘要：
{prd[:1500]}

架構設計：
{arch[:1000]}

你的任務：
1. 先用 get_project_info 了解目前的專案結構
2. 實作所有主要頁面組件（根據 PRD 的頁面清單）
3. 建立可重用的 UI 組件（按鈕、表單、卡片等）
4. 設定路由（React Router 或 Next.js App Router）
5. 實作響應式樣式（Tailwind CSS 或 CSS Modules）
6. 確保每個頁面都有基本的 loading state 和 error handling
7. 完成後執行 lint_and_typecheck 確認沒有 type error

工作目錄：{self.workdir}
""")
        results["frontend"] = frontend

        # ── Phase 5: 後端實作（如需要）──────────────────────
        _phase(5, "後端 API 實作")
        _step("STACK 實作後端 API...")

        backend = self._run("STACK", f"""
請根據 PRD 的 API 設計，實作後端部分：

PRD 摘要（API 部分）：
{prd[:1500]}

你的任務：
1. 先讀取現有的專案結構（get_project_info）
2. 實作所有 API 端點（包含完整的 request validation 和 error handling）
3. 建立資料模型/Schema
4. 實作中間件（認證、CORS、rate limiting）
5. 建立資料庫連線設定（讀取 .env）
6. 每個 API 端點都要有適當的 HTTP 狀態碼和錯誤訊息
7. 建立 API 文件（或確保 Swagger/OpenAPI 可用）

工作目錄：{self.workdir}
""")
        results["backend"] = backend

        # ── Phase 6: 測試 ────────────────────────────────────
        _phase(6, "測試 & 品質驗證")
        _step("PROBE + TRACE 建立測試...")

        tests = self._run("TRACE", f"""
請為這個專案建立完整的測試套件：

1. 先用 get_project_info 了解專案結構
2. 建立單元測試（主要功能函數）
3. 建立 API 整合測試（所有端點的 happy path 和 error path）
4. 建立基本的 E2E 測試（主要用戶流程）
5. 執行 npm_run('test') 確認所有測試通過
6. 如果有測試失敗，分析原因並修復程式碼或測試
7. 輸出測試覆蓋率摘要

工作目錄：{self.workdir}
""")
        results["tests"] = tests

        # ── Phase 7: 最終收尾 ────────────────────────────────
        _phase(7, "最終整理 & 部署準備")
        _step("FORGE 建立 CI/CD 和部署設定...")

        deploy = self._run("FORGE", f"""
請完成以下最終整理工作：

1. 建立 Dockerfile（multi-stage build，生產環境優化）
2. 建立 docker-compose.yml（包含所有服務：app、db、redis 等）
3. 建立 .github/workflows/ci.yml（lint → test → build → 可選 deploy）
4. 更新 README.md，包含：
   - 專案說明
   - 如何啟動（development / production）
   - 環境變數說明
   - API 文件連結
5. 執行 git_run('add .') 和 git_run('commit -m "feat: initial implementation"')
6. 最後執行 detect_framework 確認一切正常

工作目錄：{self.workdir}
""")
        results["deploy"] = deploy

        # ── 完成 ─────────────────────────────────────────────
        elapsed = (datetime.now() - start).seconds
        print(f"\n{GREEN}{BOLD}{'═'*60}")
        print(f"  ✅ BUILD 完成！耗時 {elapsed} 秒")
        print(f"  📁 專案位置：{self.workdir}")
        print(f"  📄 PRD：{Path(self.workdir) / 'PRD.md'}")
        print(f"  📐 架構：{Path(self.workdir) / 'ARCHITECTURE.md'}")
        print(f"{'═'*60}{RESET}")

        return results

    # ══════════════════════════════════════════════════════════
    #  單一功能任務
    # ══════════════════════════════════════════════════════════

    def feature(self, description: str) -> str:
        """
        在現有專案中實作一個新功能。
        自動判斷需要哪些 Agent 協作。
        """
        _phase(0, f"新功能：{description[:50]}")

        # ECHO 分析功能需求
        _step("ECHO 分析功能需求...")
        spec = self._chat("ECHO", f"""
分析以下功能需求，輸出：
1. 具體的實作規格（前端需要什麼，後端需要什麼）
2. 影響到哪些現有檔案
3. 需要新增哪些檔案
4. 測試方案

功能需求：{description}
專案目錄：{self.workdir}
""")

        # BYTE 或 STACK 實作（讓 NEXUS 決定）
        _step("實作功能...")
        result = self._run("FLUX", f"""
請實作以下功能：

功能規格：
{spec}

原始需求：{description}

步驟：
1. get_project_info 了解當前程式碼結構
2. 實作功能（前後端）
3. lint_and_typecheck 確認無 type error
4. 執行相關測試
5. git_run('add .') 和 git_run('commit -m "feat: {description[:50]}"')
""")
        return result

    def fix(self, error_description: str) -> str:
        """診斷並修復錯誤"""
        _phase(0, "Bug 修復")
        return self._run("STACK", f"""
請診斷並修復以下問題：

問題描述：{error_description}

步驟：
1. get_project_info 了解專案
2. search_files 搜尋相關程式碼
3. 分析根本原因
4. 修復問題
5. lint_and_typecheck 確認修復後無新問題
6. git_run('add .') 和 git_run('commit -m "fix: {error_description[:40]}"')
""")

    # ══════════════════════════════════════════════════════════
    #  /ship 完整 11 Phase 流水線
    # ══════════════════════════════════════════════════════════

    def ship(self, requirement: str) -> dict:
        """
        /ship — 從決策到實作一氣呵成
        11 個 Phase，每個 Phase 完成才進下一個

        Phase 1  ARIA  — 任務接收與範疇確認
        Phase 2  ECHO  — 需求分析與 PRD
        Phase 3  LUMI  — 產品驗證
        Phase 4  NEXUS — 技術架構設計
        Phase 5  SIGMA — 可行性評估
        Phase 6  FORGE — 環境準備
        Phase 7  BYTE  — 前端實作
        Phase 8  STACK — 後端實作
        Phase 9  PROBE+TRACE — 測試
        Phase 10 SHIELD — 安全審查
        Phase 11 ARIA  — 交付總結
        """
        from pathlib import Path
        import json

        start   = datetime.now()
        docs    = Path(self.workdir) / "docs"
        docs.mkdir(exist_ok=True)
        results = {}

        print(f"\n{PURPLE}{BOLD}{'═'*62}")
        print(f"  🚀  SYNTHEX /ship PIPELINE")
        print(f"  需求：{requirement[:58]}{'...' if len(requirement)>58 else ''}")
        print(f"  目錄：{self.workdir}")
        print(f"{'═'*62}{RESET}")

        # ── Phase 1：ARIA 任務確認 ─────────────────────────────
        _phase(1, "ARIA — 任務接收與範疇確認")
        scope = self._chat("ARIA", f"""
執行 /ship 流水線的 Phase 1。

需求：{requirement}

請輸出任務確認報告（嚴格按照你的 Phase 1 格式），
確認你完全理解需求、明確 MVP 範疇、列出依賴前提和風險預警。
如有任何模糊之處，在這裡提問（不帶著假設進入後續 Phase）。
""")
        results["phase1_scope"] = scope
        if "⚠️ 需要確認" in scope:
            print(f"\n{YELLOW}  ⚠ ARIA 有疑問，請確認後重新執行{RESET}")
            return results

        # ── Phase 2：ECHO 寫 PRD ──────────────────────────────
        _phase(2, "ECHO — 需求分析與 PRD")
        prd = self._chat("ECHO", f"""
執行 /ship 流水線的 Phase 2。

原始需求：{requirement}

ARIA 的範疇確認：
{scope}

請嚴格按照你的 Phase 2 格式產出完整 PRD。
每個欄位都必須填寫，不能省略。驗收標準（AC）要具體可驗證。
""")
        results["phase2_prd"] = prd
        prd_file = docs / "PRD.md"
        prd_file.write_text(f"# PRD\n\n{prd}", encoding="utf-8")
        _ok(f"PRD 已儲存：{prd_file}")

        # ── Phase 3：LUMI 產品驗證 ────────────────────────────
        _phase(3, "LUMI — 產品驗證")
        validation = self._chat("LUMI", f"""
執行 /ship 流水線的 Phase 3。

請審查以下 PRD，輸出產品驗證報告（嚴格按照你的 Phase 3 格式）：

{prd}

確認用戶旅程完整性、指出邏輯問題和 UX 風險。
""")
        results["phase3_validation"] = validation
        if "需要修改" in validation and "✅ PRD 通過" not in validation:
            _warn("LUMI 要求修改 PRD，ECHO 更新中...")
            prd = self._chat("ECHO", f"""
LUMI 的驗證報告：
{validation}

請根據以上意見更新 PRD，輸出修訂後的完整版本。
""")
            prd_file.write_text(f"# PRD（修訂版）\n\n{prd}", encoding="utf-8")
            results["phase2_prd_revised"] = prd
            _ok("PRD 已更新")

        # ── Phase 4：NEXUS 技術架構 ───────────────────────────
        _phase(4, "NEXUS — 技術架構設計")
        arch = self._chat("NEXUS", f"""
執行 /ship 流水線的 Phase 4。

PRD：
{prd[:2000]}

工作目錄現況（請先理解現有技術棧）：
{self._run("FORGE", "get_project_info") if False else f"工作目錄：{self.workdir}"}

請產出完整的技術架構文件（嚴格按照你的 Phase 4 格式）。
技術選型必須和現有技術棧相容，說明每個選擇的理由和 trade-off。
""")
        results["phase4_arch"] = arch
        arch_file = docs / "ARCHITECTURE.md"
        arch_file.write_text(f"# 技術架構\n\n{arch}", encoding="utf-8")
        _ok(f"架構文件已儲存：{arch_file}")

        # ── Phase 5：SIGMA 可行性評估 ─────────────────────────
        _phase(5, "SIGMA — 可行性評估")
        feasibility = self._chat("SIGMA", f"""
執行 /ship 流水線的 Phase 5。

架構設計摘要：
{arch[:1500]}

PRD 範疇：
{prd[:800]}

請輸出可行性評估報告（嚴格按照你的 Phase 5 格式），
包含第三方成本、技術複雜度風險、MVP 精簡建議。
""")
        results["phase5_feasibility"] = feasibility
        if "❌ 建議重新評估" in feasibility:
            _warn("SIGMA 建議重新評估範疇，流水線暫停")
            return results

        # ── Phase 6：FORGE 環境準備 ───────────────────────────
        _phase(6, "FORGE — 環境準備")
        env_result = self._run("FORGE", f"""
執行 /ship 流水線的 Phase 6。

架構要求：
{arch[:1500]}

依序執行：
1. get_project_info 了解現有環境
2. 建立 Architecture 要求的目錄結構
3. install_package 安裝缺少的依賴
4. 建立 .env.local.example（只放 key 名稱，不放真實值）
5. 確認專案可以啟動
6. 輸出環境就緒報告（按你的 Phase 6 格式）
""")
        results["phase6_env"] = env_result

        # ── Phase 7：BYTE 前端實作 ────────────────────────────
        _phase(7, "BYTE — 前端實作")
        frontend = self._run("BYTE", f"""
執行 /ship 流水線的 Phase 7。

PRD（前端相關部分）：
{prd[:2000]}

架構設計（前端部分）：
{arch[:1000]}

嚴格遵守你的 Phase 7 硬性規定：
- 不留任何 // TODO 或 placeholder
- 所有 TypeScript 型別明確定義
- 每個組件有 loading/error state
- 完成後執行 lint 和 typecheck，有錯就修

按實作順序執行：型別 → API客戶端 → 組件 → 頁面 → 路由
""")
        results["phase7_frontend"] = frontend

        # ── Phase 8：STACK 後端實作 ───────────────────────────
        _phase(8, "STACK — 後端實作")
        backend = self._run("STACK", f"""
執行 /ship 流水線的 Phase 8。

PRD（API 端點部分）：
{prd[:2000]}

架構設計（後端部分）：
{arch[:1000]}

嚴格遵守你的 Phase 8 硬性規定：
- 每個 API 端點有完整錯誤處理
- 所有輸入有驗證
- 敏感操作有授權檢查
- 完成後測試每個端點

按實作順序：資料模型 → Service層 → API路由 → 中間件
""")
        results["phase8_backend"] = backend

        # ── Phase 9：PROBE 策略 + TRACE 執行 ─────────────────
        _phase(9, "PROBE + TRACE — 測試")
        _step("PROBE 制定測試策略...")
        test_strategy = self._chat("PROBE", f"""
執行 /ship 流水線的 Phase 9a，制定測試策略。

PRD 驗收標準：
{prd[:1500]}

已實作的功能摘要：
前端：{str(frontend)[:400]}
後端：{str(backend)[:400]}

請輸出完整測試策略（按你的 Phase 9 格式）：
單元測試目標、API 整合測試目標、E2E 測試目標、品質門禁。
""")
        results["phase9a_strategy"] = test_strategy

        _step("TRACE 執行所有測試...")
        test_result = self._run("TRACE", f"""
執行 /ship 流水線的 Phase 9b，根據 PROBE 的策略實作並執行所有測試。

測試策略：
{test_strategy}

工作目錄：{self.workdir}

硬性規定：
- 測試必須實際執行，不是只寫出來
- 有失敗就分析原因，修復後重新執行
- 輸出最終測試結果（按你的 Phase 9 完成格式）
""")
        results["phase9b_tests"] = test_result

        # ── Phase 10：SHIELD 安全審查 ─────────────────────────
        _phase(10, "SHIELD — 安全審查與修復")
        security = self._run("SHIELD", f"""
執行 /ship 流水線的 Phase 10。

請對 {self.workdir} 的程式碼做完整安全審查：
- 逐一確認你的安全檢查清單
- 發現問題立即修復，不是只列出來
- 輸出安全審查報告（按你的 Phase 10 格式）
""")
        results["phase10_security"] = security

        # ── Phase 11：ARIA 交付總結 ───────────────────────────
        _phase(11, "ARIA — 交付總結")
        elapsed = (datetime.now() - start).seconds

        delivery_context = f"""
原始需求：{requirement}

執行摘要：
- PRD：docs/PRD.md
- 架構：docs/ARCHITECTURE.md
- 前端實作：{'完成' if frontend else '未執行'}
- 後端實作：{'完成' if backend else '未執行'}
- 測試：{'完成' if test_result else '未執行'}
- 安全審查：{'完成' if security else '未執行'}
- 耗時：{elapsed} 秒
"""
        delivery = self._run("FORGE", f"""
執行 /ship 最終收尾：

1. 建立 docs/DELIVERY.md，內容包含：
   - 完成項目清單（對應 PRD 驗收標準）
   - 新增/修改的檔案列表
   - 本地啟動方式
   - 需要手動設定的環境變數
   - 已知限制
   - 下一步建議

   背景資訊：
   {delivery_context}

2. 執行：git add .
3. 執行：git commit -m "feat: {requirement[:60].strip()}"
4. 輸出 DELIVERY.md 的內容
""")
        results["phase11_delivery"] = delivery

        # 最終總結
        print(f"\n{GREEN}{BOLD}{'═'*62}")
        print(f"  ✅  /ship 完成！耗時 {elapsed} 秒")
        print(f"  📁  {self.workdir}")
        print(f"  📄  docs/PRD.md")
        print(f"  📐  docs/ARCHITECTURE.md")
        print(f"  📦  docs/DELIVERY.md")
        print(f"{'═'*62}{RESET}")

        return results

    def review(self) -> str:
        """全面程式碼審查"""
        _phase(0, "全面程式碼審查")
        probe_result = self._run("PROBE", f"""
請對這個專案進行全面的品質審查：

1. get_project_info 了解專案結構
2. lint_and_typecheck 執行靜態分析
3. npm_run('test') 執行所有測試
4. 審查主要組件的程式碼品質
5. 列出所有發現的問題（按嚴重程度分類）
6. 提供具體的改進建議和修復方案
""")
        shield_result = self._chat("SHIELD", f"""
基於以下程式碼審查結果，補充安全性觀點：

{probe_result[:1000]}

專案目錄：{self.workdir}

請重點審查：
1. 認證和授權漏洞
2. 輸入驗證
3. 敏感資料處理
4. CORS 設定
5. 依賴套件安全性
""")
        return probe_result + "\n\n" + shield_result

    def discover(self, vague_idea: str) -> dict:
        """
        /discover — 需求模糊時使用。
        透過多個角色從不同角度深挖需求，
        最終產出一份你能直接用來跑 /ship 的完整需求書。
        """
        docs = Path(self.workdir) / "docs"
        docs.mkdir(exist_ok=True)
        results = {}

        print(f"\n{CYAN}{BOLD}{'='*62}")
        print(f"  SYNTHEX /discover -- 需求深度挖掘")
        print(f"  模糊想法：{vague_idea[:56]}{'...' if len(vague_idea)>56 else ''}")
        print(f"{'='*62}{RESET}")

        # Step 1: LUMI 用戶與市場
        _phase(1, "LUMI -- 用戶與市場挖掘")
        user_insight = self._chat("LUMI", f"""
我有一個模糊的產品想法，請幫我深挖用戶與市場面。

想法：{vague_idea}

請從以下角度深度分析，每個角度都要給出你的最佳判斷，不要只是列問題：

1. 目標用戶是誰？（越具體越好，不要說「所有人」）
   - 主要用戶群的特徵
   - 他們現在怎麼解決這個問題？
   - 他們最痛的地方是什麼？

2. 用戶旅程（Before / During / After）

3. 市場機會評估
   - 問題的普遍程度
   - 現有解決方案的主要缺陷
   - 差異化機會

4. 最危險的假設（這個想法成立最關鍵的前提）

請直接輸出分析，不要問我問題。
""")
        results["user_insight"] = user_insight

        # Step 2: ARIA 業務可行性
        _phase(2, "ARIA -- 業務定位與可行性")
        business_view = self._chat("ARIA", f"""
評估以下產品想法的業務可行性和戰略定位。

原始想法：{vague_idea}

LUMI 的用戶分析：
{user_insight[:1500]}

請給出：
1. 商業模式建議（變現方式、定價區間、獲客路徑）
2. MVP 邏輯（最小可驗證版本）
3. 風險評估（最大業務風險）
4. Go/No-Go 建議與理由
""")
        results["business_view"] = business_view

        # Step 3: ECHO 功能邊界
        _phase(3, "ECHO -- 功能邊界釐清")
        feature_analysis = self._chat("ECHO", f"""
把以下模糊的產品想法轉化成具體可開發的功能規格。

原始想法：{vague_idea}

用戶分析：{user_insight[:800]}
業務定位：{business_view[:600]}

你的任務：
1. 列出所有你「猜測」這個產品需要的功能，標注是假設還是明確需求
2. 每個功能的關鍵決策點（預設假設 → 如果假設錯了的影響）
3. 功能優先排序（P0/P1/P2），P0 沒有它產品無法運作
4. 明確說出「不做什麼」

請直接給出你的判斷，不要只是列問題讓我回答。
""")
        results["feature_analysis"] = feature_analysis

        # Step 4: NEXUS 技術現實
        _phase(4, "NEXUS -- 技術現實與複雜度評估")
        tech_reality = self._chat("NEXUS", f"""
對以下產品的技術實作進行現實評估。

原始想法：{vague_idea}
功能分析：{feature_analysis[:1200]}

評估：
1. 每個主要功能的開發難度和時間估算
2. 推薦技術棧（說明原因，不是因為流行）
3. 需要的第三方服務和費用
4. 技術風險（最可能卡住的地方）
5. 最精簡的 MVP 技術範疇

請直接輸出技術評估，不要問問題。
""")
        results["tech_reality"] = tech_reality

        # Step 5: SIGMA 資源規劃
        _phase(5, "SIGMA -- 資源規劃")
        resource_plan = self._chat("SIGMA", f"""
整合以下資訊，產出資源規劃。

技術評估：{tech_reality[:1000]}
業務定位：{business_view[:600]}

輸出：
1. 開發成本估算（時間 + 工具月費）
2. 關鍵里程碑（Week 1-2, Week 3-4, Month 2, Month 3）
3. 資源優先順序（時間應該花在哪裡）
""")
        results["resource_plan"] = resource_plan

        # Step 6: ARIA 整合需求書
        _phase(6, "ARIA -- 整合需求書 + /ship 指令")
        final_doc = self._chat("ARIA", f"""
整合所有分析，產出完整的「產品需求書」，以及一條可以直接用來執行 /ship 的指令。

原始模糊想法：{vague_idea}

用戶分析：{user_insight[:500]}
業務定位：{business_view[:500]}
功能分析：{feature_analysis[:500]}
技術評估：{tech_reality[:500]}
資源規劃：{resource_plan[:300]}

請輸出：

---

# 產品需求書：[給這個產品一個清楚的名字]

## 一句話定義
[30 字以內]

## 目標用戶

## 核心問題

## MVP 功能（P0）
- [功能]：[驗收標準]

## 之後再做（P1）

## 不做的事

## 技術決策
- 前端：
- 後端：
- 資料庫：
- 第三方服務：

## 成功指標
- Week 4：
- Month 3：

## 最危險的假設

---

## 建議的 /ship 指令

```
/ship [完整、具體的需求描述，包含：功能列表、技術棧、第三方服務、特殊規格]
```

這條指令要足夠具體，讓開發者看了不需要問任何問題就能開始做。
""")
        results["final_doc"] = final_doc

        discover_file = docs / "DISCOVER.md"
        discover_file.write_text(
            f"# /discover 需求分析報告\n\n"
            f"原始想法：{vague_idea}\n\n"
            f"生成時間：{datetime.now().isoformat()}\n\n"
            f"---\n\n{final_doc}",
            encoding="utf-8"
        )
        _ok(f"需求書已儲存：{discover_file}")

        print(f"\n{GREEN}{BOLD}{'='*62}")
        print(f"  /discover 完成")
        print(f"  docs/DISCOVER.md")
        print(f"\n  下一步：複製上方的 /ship 指令，執行：")
        print(f"  python synthex.py ship \"<複製那條需求>\"")
        print(f"{'='*62}{RESET}")

        return results
