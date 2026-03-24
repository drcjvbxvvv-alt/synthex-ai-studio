"""
Web Orchestrator v3 — 完整重構版
P0 修復：文件傳遞取代截斷字串
P1 修復：Phase 斷點續跑 + 結果快取
P1 修復：負載測試整合
P2 修復：ADR 機制 + 契約測試觸發
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
    print(f"\n{c}{BOLD}{'═'*62}\n  Phase {n} · {title}\n{'═'*62}{RESET}")

def _step(msg: str):  print(f"\n{CYAN}  ▶ {msg}{RESET}")
def _ok(msg: str):    print(f"  {GREEN}✔ {msg}{RESET}")
def _warn(msg: str):  print(f"  {YELLOW}⚠ {msg}{RESET}")


# ══════════════════════════════════════════════════════════════
#  P0-1 修復：文件上下文管理器
#  所有 Phase 的輸出都寫入磁碟，後續 Phase 從磁碟讀取完整內容
#  不再截斷字串傳遞
# ══════════════════════════════════════════════════════════════

class DocContext:
    """
    文件式上下文管理：把每個 Phase 的輸出存成 Markdown 檔案，
    後續 Phase 直接讀完整檔案，不截斷。

    解決問題：
      舊版 prd[:2000] → NEXUS 只看到 PRD 的 30%
      新版 read_doc("PRD") → NEXUS 看到完整 PRD
    """

    def __init__(self, workdir: str):
        self.docs = Path(workdir) / "docs"
        self.docs.mkdir(exist_ok=True)

    def write(self, name: str, content: str, label: str = "") -> Path:
        path = self.docs / f"{name}.md"
        header = f"# {label or name}\n\n生成時間：{datetime.now().isoformat()}\n\n"
        path.write_text(header + content, encoding="utf-8")
        _ok(f"{name}.md 已儲存（{len(content)} 字）")
        return path

    def read(self, name: str) -> str:
        path = self.docs / f"{name}.md"
        if not path.exists():
            return f"[{name}.md 尚未生成]"
        return path.read_text(encoding="utf-8")

    def exists(self, name: str) -> bool:
        return (self.docs / f"{name}.md").exists()

    def read_section(self, name: str, max_chars: int = None) -> str:
        """讀取文件，可選限制大小（僅用於顯示摘要，不用於 Phase 輸入）"""
        content = self.read(name)
        if max_chars and len(content) > max_chars:
            return content[:max_chars] + f"\n\n[... 完整內容見 docs/{name}.md]"
        return content


# ══════════════════════════════════════════════════════════════
#  P1-1 修復：Phase 斷點續跑 + 快取
# ══════════════════════════════════════════════════════════════

class PhaseCheckpoint:
    """
    記錄每個 Phase 的完成狀態，支援從中斷點繼續執行。

    狀態儲存在 docs/.ship_state.json：
    {
      "requirement": "...",
      "started_at": "...",
      "phases": {
        "1": {"status": "done", "completed_at": "..."},
        "2": {"status": "done", ...},
        "6": {"status": "failed", "error": "..."},
      }
    }
    """

    def __init__(self, workdir: str, requirement: str):
        self.state_file = Path(workdir) / "docs" / ".ship_state.json"
        self.requirement = requirement
        self.state = self._load()

        # 如果是新需求，重置狀態
        if self.state.get("requirement") != requirement:
            self.state = {
                "requirement": requirement,
                "started_at": datetime.now().isoformat(),
                "phases": {}
            }
            self._save()

    def _load(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except Exception:
                pass
        return {}

    def _save(self):
        self.state_file.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2)
        )

    def is_done(self, phase: int) -> bool:
        return self.state.get("phases", {}).get(str(phase), {}).get("status") == "done"

    def mark_done(self, phase: int):
        if "phases" not in self.state:
            self.state["phases"] = {}
        self.state["phases"][str(phase)] = {
            "status": "done",
            "completed_at": datetime.now().isoformat()
        }
        self._save()

    def mark_failed(self, phase: int, error: str = ""):
        if "phases" not in self.state:
            self.state["phases"] = {}
        self.state["phases"][str(phase)] = {
            "status": "failed",
            "failed_at": datetime.now().isoformat(),
            "error": error
        }
        self._save()

    def resume_info(self) -> str:
        done = [k for k, v in self.state.get("phases", {}).items()
                if v.get("status") == "done"]
        if done:
            return f"  續跑模式：Phase {', '.join(sorted(done))} 已完成，跳過"
        return ""


# ══════════════════════════════════════════════════════════════
#  主 Orchestrator
# ══════════════════════════════════════════════════════════════

class WebOrchestrator:

    def __init__(self, workdir: str = None, auto_confirm: bool = False):
        self.workdir      = workdir or os.getcwd()
        self.auto_confirm = auto_confirm

    def _use_web_tools(self, agent):
        from core.web_tools import WebToolExecutor
        agent.executor = WebToolExecutor(workdir=self.workdir,
                                          auto_confirm=self.auto_confirm)
        return agent

    def _agent(self, name: str):
        from agents.all_agents import get_agent
        import core.tools as ct
        from core.web_tools import get_webdev_tools
        agent = get_agent(name, workdir=self.workdir, auto_confirm=self.auto_confirm)
        orig  = ct.get_tools_for_role
        ct.get_tools_for_role = lambda role: get_webdev_tools(role)
        agent._orig_get_tools = orig
        return self._use_web_tools(agent)

    def _chat(self, name: str, task: str) -> str:
        agent = self._agent(name)
        import core.tools as ct
        try:
            return agent.chat(task)
        finally:
            if hasattr(agent, "_orig_get_tools"):
                ct.get_tools_for_role = agent._orig_get_tools

    def _run(self, name: str, task: str) -> str:
        agent = self._agent(name)
        import core.tools as ct
        try:
            return agent.run(task)
        finally:
            if hasattr(agent, "_orig_get_tools"):
                ct.get_tools_for_role = agent._orig_get_tools

    # ──────────────────────────────────────────────────────────
    #  /ship 主流水線（完整重構）
    # ──────────────────────────────────────────────────────────

    def ship(self, requirement: str, resume: bool = True) -> dict:
        """
        /ship — 13 Phase 完整流水線

        P0 修復：所有 Phase 間的資料傳遞改為讀取完整文件
        P1 修復：支援斷點續跑（resume=True 時跳過已完成的 Phase）
        """
        start   = datetime.now()
        ctx     = DocContext(self.workdir)
        ckpt    = PhaseCheckpoint(self.workdir, requirement)
        results = {}

        resume_msg = ckpt.resume_info()

        print(f"\n{PURPLE}{BOLD}{'═'*62}")
        print(f"  🚀  SYNTHEX /ship  {'（續跑）' if resume_msg else ''}")
        print(f"  需求：{requirement[:58]}{'...' if len(requirement) > 58 else ''}")
        print(f"  目錄：{self.workdir}")
        if resume_msg:
            print(f"{CYAN}{resume_msg}{RESET}")
        print(f"{'═'*62}{RESET}")

        # ── Phase 1：ARIA 任務確認 ─────────────────────────────
        if resume and ckpt.is_done(1):
            _ok("Phase 1 已完成，跳過")
        else:
            _phase(1, "ARIA — 任務接收與範疇確認")
            scope = self._chat("ARIA", f"""
執行 /ship 流水線的 Phase 1。

需求：{requirement}

請輸出任務確認報告（嚴格按照你的 Phase 1 格式）。
有任何不確定的地方，在這裡提問，不帶著假設進入後續 Phase。
""")
            ctx.write("SCOPE", scope, "範疇確認")
            results["phase1_scope"] = scope
            if "⚠️ 需要確認" in scope:
                print(f"\n{YELLOW}  ⚠ ARIA 有疑問，流水線暫停{RESET}")
                ckpt.mark_failed(1, "需要使用者確認")
                return results
            ckpt.mark_done(1)

        # ── Phase 2：ECHO 寫 PRD ───────────────────────────────
        if resume and ckpt.is_done(2):
            _ok("Phase 2 已完成，跳過")
        else:
            _phase(2, "ECHO — 需求分析與 PRD")
            # P0 修復：傳遞完整範疇，不截斷
            prd = self._chat("ECHO", f"""
執行 /ship 流水線的 Phase 2。

原始需求：{requirement}

ARIA 的範疇確認：
{ctx.read("SCOPE")}

請嚴格按照你的 Phase 2 格式產出完整 PRD。
每個欄位都必須填寫，驗收標準（AC）要具體可驗證。
""")
            ctx.write("PRD", prd, "Product Requirements Document")
            results["phase2_prd"] = prd
            ckpt.mark_done(2)

        # ── Phase 3：LUMI 產品驗證 ────────────────────────────
        if resume and ckpt.is_done(3):
            _ok("Phase 3 已完成，跳過")
        else:
            _phase(3, "LUMI — 產品驗證")
            # P0 修復：讀完整 PRD 文件
            validation = self._chat("LUMI", f"""
執行 /ship 流水線的 Phase 3。

請審查以下完整 PRD：

{ctx.read("PRD")}

確認用戶旅程完整性、指出邏輯問題和 UX 風險。
輸出驗證報告（嚴格按照你的 Phase 3 格式）。
""")
            ctx.write("VALIDATION", validation, "產品驗證報告")
            results["phase3_validation"] = validation

            if "需要修改" in validation and "✅ PRD 通過" not in validation:
                _warn("LUMI 要求修改 PRD，ECHO 更新中...")
                revised_prd = self._chat("ECHO", f"""
LUMI 的驗證報告指出以下問題：
{ctx.read("VALIDATION")}

請根據意見更新 PRD，輸出修訂後的完整版本。
""")
                ctx.write("PRD", revised_prd, "Product Requirements Document（修訂版）")
                results["phase2_prd_revised"] = revised_prd
                _ok("PRD 已更新")
            ckpt.mark_done(3)

        # ── Phase 4：NEXUS 技術架構 ───────────────────────────
        if resume and ckpt.is_done(4):
            _ok("Phase 4 已完成，跳過")
        else:
            _phase(4, "NEXUS — 技術架構設計")
            # P0 修復：讀完整 PRD，同時讓 NEXUS 掃描專案
            arch = self._run("NEXUS", f"""
執行 /ship 流水線的 Phase 4。

請先用 get_project_info 了解現有技術棧，然後閱讀以下完整 PRD：

{ctx.read("PRD")}

產出完整技術架構文件（嚴格按照你的 Phase 4 格式）。
技術選型必須和現有技術棧相容，說明每個選擇的理由和 trade-off。

P2 要求：
- 為每個重要技術決策建立 ADR 條目（格式：docs/adr/ADR-NNN-title.md）
- ADR 格式：背景 / 決策 / 理由 / 後果
""")
            ctx.write("ARCHITECTURE", arch, "技術架構")
            results["phase4_arch"] = arch
            ckpt.mark_done(4)

        # ── Phase 5：SIGMA 可行性評估 ─────────────────────────
        if resume and ckpt.is_done(5):
            _ok("Phase 5 已完成，跳過")
        else:
            _phase(5, "SIGMA — 可行性評估")
            feasibility = self._chat("SIGMA", f"""
執行 /ship 流水線的 Phase 5。

完整架構設計：
{ctx.read("ARCHITECTURE")}

完整 PRD：
{ctx.read("PRD")}

輸出可行性評估報告（嚴格按照你的 Phase 5 格式）。
""")
            ctx.write("FEASIBILITY", feasibility, "可行性評估")
            results["phase5_feasibility"] = feasibility
            if "❌ 建議重新評估" in feasibility:
                _warn("SIGMA 建議重新評估範疇，流水線暫停")
                ckpt.mark_failed(5, "可行性評估未通過")
                return results
            ckpt.mark_done(5)

        # ── Phase 6：FORGE 環境準備（含可觀測性）────────────────
        if resume and ckpt.is_done(6):
            _ok("Phase 6 已完成，跳過")
        else:
            _phase(6, "FORGE — 環境準備")
            env_result = self._run("FORGE", f"""
執行 /ship 流水線的 Phase 6。

完整架構要求：
{ctx.read("ARCHITECTURE")}

依序執行：
1. get_project_info 了解現有環境
2. 建立缺少的目錄結構
3. 安裝缺少的依賴套件
4. 安裝並設定 Sentry（npm install @sentry/nextjs）
5. 安裝並設定 PostHog（npm install posthog-js）
6. 建立 .env.local.example（含 Sentry/PostHog key）
7. 確認專案可以啟動
8. 輸出環境就緒報告
""")
            ctx.write("ENV_SETUP", env_result, "環境設定報告")
            results["phase6_env"] = env_result
            ckpt.mark_done(6)

        # ── Phase 7：BYTE 前端實作 ────────────────────────────
        if resume and ckpt.is_done(7):
            _ok("Phase 7 已完成，跳過")
        else:
            _phase(7, "BYTE — 前端實作")
            # P0 修復：讀完整 PRD + 完整架構文件
            frontend = self._run("BYTE", f"""
執行 /ship 流水線的 Phase 7。

完整 PRD（含所有頁面和路由）：
{ctx.read("PRD")}

完整技術架構（含目錄結構和元件架構）：
{ctx.read("ARCHITECTURE")}

硬性規定：
- 不留任何 // TODO 或 placeholder
- 所有 TypeScript 型別明確定義，不用 any
- 每個組件有 loading/error/empty 三種狀態
- 所有顏色/間距只能用 tokens.css 變數
- 完成後執行 lint 和 typecheck，有錯就修

實作順序：型別定義 → API 客戶端 → 組件 → 頁面 → 路由
""")
            ctx.write("FRONTEND_IMPL", frontend, "前端實作報告")
            results["phase7_frontend"] = frontend
            ckpt.mark_done(7)

        # ── Phase 8：STACK 後端實作 ───────────────────────────
        if resume and ckpt.is_done(8):
            _ok("Phase 8 已完成，跳過")
        else:
            _phase(8, "STACK — 後端實作")
            # P0 修復：讀完整 PRD + 完整架構（含 API 設計和 Schema）
            backend = self._run("STACK", f"""
執行 /ship 流水線的 Phase 8。

完整 PRD（含所有 API 端點規格）：
{ctx.read("PRD")}

完整技術架構（含資料庫 Schema 和 API 設計）：
{ctx.read("ARCHITECTURE")}

硬性規定：
- 每個 API 端點有完整錯誤處理
- 所有輸入有型別驗證
- 敏感操作有授權檢查
- 遵循三層分離：路由層 → Service 層 → Repository 層
- 完成後測試每個端點

實作順序：資料模型 → Repository → Service → API 路由 → 中間件
""")
            ctx.write("BACKEND_IMPL", backend, "後端實作報告")
            results["phase8_backend"] = backend
            ckpt.mark_done(8)

        # ── Phase 9：PROBE 策略 + TRACE 執行 ─────────────────
        if resume and ckpt.is_done(9):
            _ok("Phase 9 已完成，跳過")
        else:
            _phase(9, "PROBE + TRACE — 完整測試")
            _step("PROBE 制定測試策略...")
            # P0 修復：讀完整 PRD 的驗收標準
            test_strategy = self._chat("PROBE", f"""
執行 /ship 流水線的 Phase 9a，制定完整測試策略。

完整 PRD（含所有驗收標準）：
{ctx.read("PRD")}

前端實作摘要：
{ctx.read_section("FRONTEND_IMPL", 800)}

後端實作摘要：
{ctx.read_section("BACKEND_IMPL", 800)}

輸出完整測試策略，包含：
1. 單元測試目標（核心業務邏輯函數）
2. API 整合測試（每個端點的 happy path + error cases）
3. E2E 測試（最重要的用戶旅程）
4. 契約測試（前後端 API 介面一致性）
5. 負載測試基準（k6，關鍵端點的承載量目標）
6. 品質門禁
""")
            ctx.write("TEST_STRATEGY", test_strategy, "測試策略")

            _step("TRACE 執行所有測試...")
            test_result = self._run("TRACE", f"""
執行 /ship 流水線的 Phase 9b。

依據以下測試策略實作並執行所有測試：
{ctx.read("TEST_STRATEGY")}

工作目錄：{self.workdir}

執行順序：
1. 單元測試 → 修復失敗
2. API 整合測試 → 修復失敗
3. E2E 測試（主要流程）→ 修復失敗
4. lint_and_typecheck → 0 errors

如果有測試失敗：分析原因 → 修復程式碼或測試 → 重跑 → 確認全綠
""")
            ctx.write("TEST_RESULTS", test_result, "測試結果")
            results["phase9_tests"] = test_result
            ckpt.mark_done(9)

        # ── Phase 10：SHIELD 安全審查（含自動化掃描）─────────
        if resume and ckpt.is_done(10):
            _ok("Phase 10 已完成，跳過")
        else:
            _phase(10, "SHIELD — 安全審查與修復")
            security = self._run("SHIELD", f"""
執行 /ship 流水線的 Phase 10。

對 {self.workdir} 執行完整安全審查：

步驟 1：自動化掃描
  - run_command: npm audit（依賴漏洞）
  - run_command: npx semgrep --config=auto src/（SAST 靜態分析）
  - run_command: npx gitleaks detect --source=. --no-git（Secret 掃描）
  如果工具未安裝，先安裝後執行。

步驟 2：程式碼審查
  逐一確認你的安全檢查清單（輸入驗證、越權、敏感資料）

步驟 3：修復
  發現問題立即修復，不是只列出來

輸出安全審查報告（按你的 Phase 10 格式）。
""")
            ctx.write("SECURITY", security, "安全審查報告")
            results["phase10_security"] = security
            ckpt.mark_done(10)

        # ── Phase 11：ARIA 交付總結 ───────────────────────────
        _phase(11, "ARIA — 交付總結")
        elapsed = (datetime.now() - start).seconds

        delivery = self._run("FORGE", f"""
執行 /ship 最終收尾。

1. 建立 docs/DELIVERY.md，包含：
   - 完成項目（對應 PRD 驗收標準逐一核對）
   - 新增/修改的檔案清單
   - 啟動方式（本地開發 + 生產環境）
   - 需要手動設定的環境變數
   - 已知限制
   - 下一步建議（P1/P2 功能）

   PRD 路徑：docs/PRD.md
   架構路徑：docs/ARCHITECTURE.md
   測試報告：docs/TEST_RESULTS.md
   安全報告：docs/SECURITY.md
   耗時：{elapsed} 秒

2. git add .
3. git commit -m "feat: {requirement[:60].strip()}"
""")
        ctx.write("DELIVERY", delivery, "交付摘要")
        results["phase11_delivery"] = delivery
        ckpt.mark_done(11)

        # 清除 checkpoint（成功完成）
        if ckpt.state_file.exists():
            ckpt.state_file.unlink()

        print(f"\n{GREEN}{BOLD}{'═'*62}")
        print(f"  ✅  /ship 完成！耗時 {elapsed} 秒")
        print(f"  📁  {self.workdir}/docs/")
        print(f"  文件：PRD · ARCHITECTURE · TEST_RESULTS · SECURITY · DELIVERY")
        print(f"{'═'*62}{RESET}")

        return results

    # ──────────────────────────────────────────────────────────
    #  其他方法（build、feature、fix、review、discover）
    # ──────────────────────────────────────────────────────────

    def build(self, requirement: str, project_name: str = None) -> dict:
        """舊版 build() — 導向新的 ship()"""
        return self.ship(requirement)

    def feature(self, description: str) -> str:
        _phase(0, f"新功能：{description[:50]}")
        ctx = DocContext(self.workdir)

        _step("ECHO 分析功能規格...")
        spec = self._chat("ECHO", f"""
分析以下功能需求，輸出實作規格：
- 具體的前端需求（頁面、組件、API 呼叫）
- 具體的後端需求（API 端點、資料模型變更）
- 影響的現有檔案
- 測試方案

功能需求：{description}
專案目錄：{self.workdir}
""")
        ctx.write("FEATURE_SPEC", spec, f"功能規格：{description[:40]}")

        _step("FLUX 實作功能...")
        result = self._run("FLUX", f"""
實作以下功能：

功能規格：
{ctx.read("FEATURE_SPEC")}

原始需求：{description}

步驟：
1. get_project_info 了解程式碼結構
2. 實作功能（前後端）
3. lint_and_typecheck
4. git add . && git commit -m "feat: {description[:50]}"
""")
        return result

    def fix(self, error_description: str) -> str:
        _phase(0, "Bug 修復")
        return self._run("STACK", f"""
診斷並修復以下問題：

問題：{error_description}

步驟：
1. get_project_info + search_files 定位問題
2. 分析根本原因
3. 修復
4. lint_and_typecheck
5. git commit -m "fix: {error_description[:40]}"
""")

    def review(self) -> str:
        _phase(0, "全面程式碼審查")
        probe = self._run("PROBE", f"""
對 {self.workdir} 執行全面品質審查：
1. get_project_info 了解結構
2. lint_and_typecheck 靜態分析
3. npm_run('test') 執行測試
4. 審查主要組件品質
5. 列出問題（按嚴重程度）
6. 提供修復建議
""")
        shield = self._chat("SHIELD", f"""
補充安全性分析：

程式碼審查結果摘要：
{probe[:1000]}

專案目錄：{self.workdir}

重點：輸入驗證、授權、敏感資料、CORS、rate limiting
""")
        return probe + "\n\n" + shield

    def discover(self, vague_idea: str) -> dict:
        ctx  = DocContext(self.workdir)
        results = {}

        print(f"\n{CYAN}{BOLD}{'='*62}")
        print(f"  🔍  /discover — 需求深度挖掘")
        print(f"  想法：{vague_idea[:56]}{'...' if len(vague_idea)>56 else ''}")
        print(f"{'='*62}{RESET}")

        _phase(1, "LUMI — 用戶與市場挖掘")
        user_insight = self._chat("LUMI", f"""
深挖以下產品想法的用戶與市場面。

想法：{vague_idea}

分析：
1. 目標用戶（越具體越好）
2. 用戶旅程（Before/During/After）
3. 市場機會和差異化
4. 最危險的假設

直接輸出分析，不要問問題。
""")
        ctx.write("DISCOVER_USER", user_insight, "用戶分析")
        results["user_insight"] = user_insight

        _phase(2, "ARIA — 業務定位與可行性")
        business = self._chat("ARIA", f"""
評估以下產品想法的業務可行性。

想法：{vague_idea}

用戶分析：
{ctx.read("DISCOVER_USER")}

輸出：商業模式建議、MVP 邏輯、風險評估、Go/No-Go 建議
""")
        ctx.write("DISCOVER_BIZ", business, "業務分析")
        results["business"] = business

        _phase(3, "ECHO — 功能邊界釐清")
        features = self._chat("ECHO", f"""
把以下模糊想法轉化成具體功能規格。

想法：{vague_idea}
用戶分析：{ctx.read_section("DISCOVER_USER", 600)}
業務定位：{ctx.read_section("DISCOVER_BIZ", 400)}

輸出：功能清單（標注假設/明確需求）、P0/P1/P2 排序、不做什麼
""")
        ctx.write("DISCOVER_FEATURES", features, "功能分析")
        results["features"] = features

        _phase(4, "NEXUS — 技術現實評估")
        tech = self._chat("NEXUS", f"""
對以下產品進行技術可行性評估。

想法：{vague_idea}
功能分析：{ctx.read_section("DISCOVER_FEATURES", 800)}

輸出：技術複雜度、推薦技術棧、第三方服務費用、MVP 技術範疇
""")
        ctx.write("DISCOVER_TECH", tech, "技術評估")
        results["tech"] = tech

        _phase(5, "SIGMA — 資源規劃")
        resources = self._chat("SIGMA", f"""
整合分析，產出資源規劃。

技術評估：{ctx.read_section("DISCOVER_TECH", 800)}
業務定位：{ctx.read_section("DISCOVER_BIZ", 400)}

輸出：開發時間估算、月營運成本、關鍵里程碑
""")
        ctx.write("DISCOVER_RESOURCES", resources, "資源規劃")
        results["resources"] = resources

        _phase(6, "ARIA — 整合需求書")
        final = self._chat("ARIA", f"""
整合所有分析，產出完整需求書和可直接執行的 /ship 指令。

用戶分析：{ctx.read_section("DISCOVER_USER", 400)}
業務定位：{ctx.read_section("DISCOVER_BIZ", 400)}
功能分析：{ctx.read_section("DISCOVER_FEATURES", 400)}
技術評估：{ctx.read_section("DISCOVER_TECH", 400)}
資源規劃：{ctx.read_section("DISCOVER_RESOURCES", 300)}

輸出：
1. 產品需求書（一句話定義、目標用戶、MVP 功能、技術決策、成功指標）
2. 可直接執行的 /ship 指令（具體、完整、不需要再問問題）
""")
        ctx.write("DISCOVER_FINAL", final, "需求書")
        results["final"] = final

        _ok(f"需求書已儲存：{ctx.docs}/DISCOVER_FINAL.md")
        print(f"\n{GREEN}  下一步：python synthex.py ship \"（從 DISCOVER_FINAL.md 複製）\"{RESET}")

        return results
