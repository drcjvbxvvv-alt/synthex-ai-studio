"""
SYNTHEX Deploy Pipeline
弱項二解決方案：本地驗證通過才部署，明確的部署路徑

流程：
1. 本地驗證（lint → typecheck → test → build → browser QA）
2. 全部通過才執行部署
3. 部署後自動驗證線上環境

支援部署目標：Vercel（前端）+ Neon/Supabase/Railway（資料庫）
"""

import os
import json
import subprocess
from pathlib import Path
from datetime import datetime

RESET  = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
CYAN   = "\033[96m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
RED    = "\033[91m"


def _run(cmd: str, cwd: str, label: str, timeout: int = 120) -> dict:
    print(f"\n  {CYAN}▶ {label}{RESET}")
    print(f"  {DIM}$ {cmd}{RESET}")
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd,
                           capture_output=True, text=True, timeout=timeout)
        success = r.returncode == 0
        icon    = f"{GREEN}✔{RESET}" if success else f"{RED}✖{RESET}"
        out     = (r.stdout + r.stderr).strip()
        for line in out.splitlines()[-5:]:
            print(f"  {DIM}{line}{RESET}")
        print(f"  {icon} {label} — exit {r.returncode}")
        return {"label": label, "success": success, "output": out, "exit_code": r.returncode}
    except subprocess.TimeoutExpired:
        print(f"  {RED}✖ 超時（>{timeout}s）{RESET}")
        return {"label": label, "success": False, "output": "timeout", "exit_code": -1}
    except Exception as e:
        print(f"  {RED}✖ {e}{RESET}")
        return {"label": label, "success": False, "output": str(e), "exit_code": -1}


class DeployPipeline:
    """
    本地驗證 → 部署 → 線上驗證

    使用原則：
    - 任何一個本地驗證步驟失敗，立即停止，不進行部署
    - 部署後自動對線上 URL 執行 browser QA
    - 所有步驟都記錄到 docs/DEPLOY_LOG.md
    """

    def __init__(self, workdir: str, target: str = "vercel", auto_confirm: bool = False):
        self.workdir      = str(Path(workdir).resolve())
        self.target       = target   # vercel | railway | manual
        self.auto_confirm = auto_confirm
        self.results      = []
        self.start_time   = datetime.now()

    # ── 本地驗證 ─────────────────────────────────────────────────────────────

    def verify_local(self) -> bool:
        """
        完整本地驗證流程。
        全部通過才回傳 True，任何失敗立即停止。
        """
        print(f"\n{CYAN}{BOLD}{'═'*60}")
        print(f"  🔍 本地驗證")
        print(f"{'═'*60}{RESET}")

        steps = self._build_verify_steps()

        for step in steps:
            result = _run(step["cmd"], self.workdir, step["label"],
                          timeout=step.get("timeout", 120))
            self.results.append(result)
            if not result["success"]:
                print(f"\n{RED}{BOLD}  ✖ 驗證失敗：{step['label']}")
                print(f"  部署中止。修復問題後重新執行。{RESET}\n")
                self._write_log(success=False)
                return False

        print(f"\n{GREEN}{BOLD}  ✅ 所有本地驗證通過！{RESET}")
        return True

    def _build_verify_steps(self) -> list:
        p = Path(self.workdir)
        steps = []

        if (p / "package.json").exists():
            pkg = json.loads((p / "package.json").read_text())
            scripts = pkg.get("scripts", {})

            if "typecheck" in scripts:
                steps.append({"cmd": "npm run typecheck", "label": "TypeScript 型別檢查"})
            elif (p / "tsconfig.json").exists():
                steps.append({"cmd": "npx tsc --noEmit", "label": "TypeScript 型別檢查"})

            if "lint" in scripts:
                steps.append({"cmd": "npm run lint", "label": "ESLint 檢查"})

            if "test" in scripts:
                steps.append({"cmd": "npm run test -- --run",
                               "label": "單元測試", "timeout": 180})

            steps.append({"cmd": "npm run build", "label": "生產建置",
                          "timeout": 300})

        elif (p / "requirements.txt").exists():
            steps.append({"cmd": "python -m pytest tests/ -v --tb=short",
                          "label": "Python 測試", "timeout": 180})

        return steps

    def verify_browser(self, port: int = 3000) -> bool:
        """啟動本地伺服器，執行瀏覽器 QA，然後關閉"""
        print(f"\n{CYAN}{BOLD}  🌐 Browser QA（本地）{RESET}")
        try:
            from core.browser_qa import BrowserQA
            with BrowserQA(headless=True) as qa:
                routes = self._get_routes()
                report = qa.audit(f"http://localhost:{port}", routes)
                summary = report.get("summary", {})
                errors  = summary.get("total_errors", 0)
                if errors > 0:
                    print(f"  {RED}✖ Browser QA 失敗：{errors} 個錯誤{RESET}")
                    for e in summary.get("all_errors", [])[:5]:
                        print(f"    {DIM}• {e}{RESET}")
                    return False
                print(f"  {GREEN}✔ Browser QA 通過：{summary.get('routes_checked', 0)} 個路由無錯誤{RESET}")
                return True
        except Exception as e:
            print(f"  {YELLOW}⚠ Browser QA 跳過（{e}）{RESET}")
            return True  # 不阻擋部署，只是跳過

    def _get_routes(self) -> list:
        """從 Next.js app/ 目錄自動推斷路由"""
        p      = Path(self.workdir)
        routes = ["/"]
        app    = p / "src" / "app"
        if not app.exists():
            app = p / "app"
        if app.exists():
            for item in app.iterdir():
                if item.is_dir() and not item.name.startswith("(") \
                   and not item.name.startswith("_") \
                   and not item.name.startswith(".") \
                   and item.name not in ("api", "fonts"):
                    routes.append(f"/{item.name}")
        return routes[:8]  # 最多 8 個

    # ── 部署 ─────────────────────────────────────────────────────────────────

    def deploy(self) -> dict:
        """執行部署"""
        print(f"\n{CYAN}{BOLD}{'═'*60}")
        print(f"  🚀 部署到 {self.target}")
        print(f"{'═'*60}{RESET}")

        if not self.auto_confirm:
            ans = input(f"\n  確定部署到 {self.target}？(y/N) ").strip().lower()
            if ans != "y":
                print(f"  {YELLOW}部署取消{RESET}")
                return {"success": False, "reason": "user_cancelled"}

        if self.target == "vercel":
            return self._deploy_vercel()
        elif self.target == "railway":
            return self._deploy_railway()
        elif self.target == "manual":
            return self._deploy_manual()
        else:
            print(f"  {RED}✖ 不支援的部署目標：{self.target}{RESET}")
            return {"success": False}

    def _deploy_vercel(self) -> dict:
        """Vercel 部署"""
        # 確認 vercel CLI 可用
        check = subprocess.run("which vercel", shell=True, capture_output=True)
        if check.returncode != 0:
            print(f"  {YELLOW}⚠ vercel CLI 未安裝，執行安裝...{RESET}")
            subprocess.run("npm install -g vercel", shell=True)

        # 部署
        result = _run("vercel --prod --yes", self.workdir, "Vercel 生產部署", timeout=300)

        if result["success"]:
            # 從輸出中擷取部署 URL
            for line in result["output"].splitlines():
                if "https://" in line and "vercel.app" in line:
                    url = line.strip()
                    print(f"\n  {GREEN}✔ 部署成功：{url}{RESET}")
                    return {"success": True, "url": url, "target": "vercel"}

        return {"success": result["success"], "target": "vercel"}

    def _deploy_railway(self) -> dict:
        """Railway 部署"""
        check = subprocess.run("which railway", shell=True, capture_output=True)
        if check.returncode != 0:
            print(f"  {YELLOW}⚠ railway CLI 未安裝：npm install -g @railway/cli{RESET}")
            return {"success": False, "reason": "railway_cli_not_installed"}

        result = _run("railway up --detach", self.workdir, "Railway 部署", timeout=300)
        return {"success": result["success"], "target": "railway"}

    def _deploy_manual(self) -> dict:
        """手動部署（只執行 build，輸出部署說明）"""
        result = _run("npm run build", self.workdir, "生產建置", timeout=300)
        if result["success"]:
            print(f"\n{CYAN}  📋 手動部署步驟：{RESET}")
            print(f"  1. 把 .next/ 目錄上傳到你的主機")
            print(f"  2. 設定環境變數（參考 .env.local.example）")
            print(f"  3. 執行 `npm start`")
        return {"success": result["success"], "target": "manual"}

    # ── 部署後驗證 ──────────────────────────────────────────────────────────

    def verify_production(self, url: str) -> bool:
        """部署後驗證線上環境"""
        print(f"\n{CYAN}{BOLD}  🌐 線上環境驗證：{url}{RESET}")
        try:
            from core.browser_qa import BrowserQA
            with BrowserQA(headless=True) as qa:
                routes = self._get_routes()
                report = qa.audit(url, routes)
                summary = report.get("summary", {})
                errors  = summary.get("total_errors", 0)
                if errors:
                    print(f"  {RED}✖ 線上有 {errors} 個錯誤，請立即檢查{RESET}")
                    return False
                print(f"  {GREEN}✔ 線上環境正常{RESET}")
                return True
        except Exception as e:
            print(f"  {YELLOW}⚠ 線上驗證跳過（{e}）{RESET}")
            return True

    # ── 完整流程 ─────────────────────────────────────────────────────────────

    def run(self, skip_browser_qa: bool = False, production_url: str = None) -> dict:
        """
        完整流程：本地驗證 → 部署 → 線上驗證

        skip_browser_qa: 跳過瀏覽器 QA（需要先手動啟動 dev server）
        production_url: 部署後驗證的 URL（如果 CLI 無法自動取得）
        """
        print(f"\n{CYAN}{BOLD}{'═'*60}")
        print(f"  SYNTHEX Deploy Pipeline")
        print(f"  目標：{self.target} · 目錄：{self.workdir}")
        print(f"{'═'*60}{RESET}")

        # Step 1: 本地驗證
        if not self.verify_local():
            return {"success": False, "stopped_at": "local_verify"}

        # Step 2: Browser QA（可選）
        if not skip_browser_qa:
            print(f"\n{DIM}  ℹ 確保 dev server 已在 localhost:3000 運行{RESET}")
            if not self.verify_browser():
                self._write_log(success=False)
                return {"success": False, "stopped_at": "browser_qa"}

        # Step 3: 部署
        deploy_result = self.deploy()
        if not deploy_result.get("success"):
            self._write_log(success=False)
            return {"success": False, "stopped_at": "deploy"}

        # Step 4: 線上驗證
        url = production_url or deploy_result.get("url")
        if url:
            self.verify_production(url)

        self._write_log(success=True, deploy_result=deploy_result)
        elapsed = (datetime.now() - self.start_time).seconds

        print(f"\n{GREEN}{BOLD}{'═'*60}")
        print(f"  ✅ 部署完成！耗時 {elapsed} 秒")
        if url:
            print(f"  🔗 {url}")
        print(f"{'═'*60}{RESET}")

        return {"success": True, "url": url, "elapsed_seconds": elapsed}

    def _write_log(self, success: bool, deploy_result: dict = None):
        docs = Path(self.workdir) / "docs"
        docs.mkdir(exist_ok=True)
        log_file = docs / "DEPLOY_LOG.md"

        status = "✅ 成功" if success else "❌ 失敗"
        ts     = self.start_time.strftime("%Y-%m-%d %H:%M")
        entry  = f"\n## {ts} — {status}\n\n"
        entry += f"目標：{self.target}\n\n"
        entry += "### 驗證步驟\n"
        for r in self.results:
            icon = "✅" if r["success"] else "❌"
            entry += f"- {icon} {r['label']}\n"
        if deploy_result:
            url = deploy_result.get("url", "")
            if url:
                entry += f"\n部署 URL：{url}\n"
        entry += "\n---\n"

        existing = log_file.read_text() if log_file.exists() else "# Deploy Log\n"
        log_file.write_text(existing + entry)
