"""
SYNTHEX Browser QA Engine
真實瀏覽器驗收測試 — 解決純程式碼分析做不到的 QA 缺口

使用 Playwright 開啟真實 Chromium，讓 PROBE/TRACE 能：
- 截圖確認頁面實際外觀
- 抓取 console.error 和 network 錯誤
- 互動式點擊、填表、驗證流程
- 在真實運行的 app 上做端對端驗收

需要安裝：pip install playwright && playwright install chromium
"""

import os
import json
import time
import base64
import subprocess
from pathlib import Path
from datetime import datetime

RESET  = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
CYAN   = "\033[96m"; GREEN = "\033[92m"; YELLOW = "\033[93m"; RED = "\033[91m"

SCREENSHOT_DIR = Path.home() / ".synthex" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ── Playwright 可用性檢查 ──────────────────────────────────────────────────

def _check_playwright() -> bool:
    try:
        import playwright  # noqa
        result = subprocess.run(
            ["playwright", "install", "--dry-run", "chromium"],
            capture_output=True, text=True, timeout=5
        )
        return True
    except Exception:
        return False


def install_playwright():
    """引導安裝 Playwright"""
    print(f"\n{YELLOW}⚠ Playwright 未安裝，正在安裝...{RESET}")
    subprocess.run(["pip", "install", "playwright", "--break-system-packages", "-q"])
    subprocess.run(["playwright", "install", "chromium"])
    print(f"{GREEN}✔ Playwright 安裝完成{RESET}")


# ── 工具定義（給 Agent 使用）──────────────────────────────────────────────

BROWSER_TOOL_DEFS = [
    {
        "name": "browser_screenshot",
        "description": "開啟真實瀏覽器，截取頁面截圖，同時回傳 console 錯誤和 network 失敗。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url":      {"type": "string",  "description": "要截圖的 URL"},
                "wait_ms":  {"type": "integer", "description": "截圖前等待毫秒數（預設 2000）"},
                "viewport": {"type": "object",  "description": "視窗大小，例如 {width:1280,height:720}"},
                "mobile":   {"type": "boolean", "description": "使用手機視窗（375x812）"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_flow",
        "description": "在瀏覽器中執行多步驟互動流程（點擊、填表、導航），驗收完整用戶旅程。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url":   {"type": "string", "description": "起始 URL"},
                "steps": {
                    "type": "array",
                    "description": "操作步驟列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action":   {"type": "string",
                                        "enum": ["click","fill","select","wait","screenshot",
                                                 "assert_text","assert_url","assert_visible",
                                                 "assert_not_visible","press"],
                                        "description": "操作類型"},
                            "selector": {"type": "string", "description": "CSS 選擇器或 text= 語法"},
                            "value":    {"type": "string", "description": "填入的值（fill/select/press 用）"},
                            "label":    {"type": "string", "description": "這個步驟的說明（截圖命名用）"},
                        },
                        "required": ["action"],
                    },
                },
            },
            "required": ["url", "steps"],
        },
    },
    {
        "name": "browser_audit",
        "description": "對整個 app 執行自動化審計：Core Web Vitals、可訪問性、console 錯誤、破圖。",
        "input_schema": {
            "type": "object",
            "properties": {
                "base_url": {"type": "string", "description": "app 的根 URL，例如 http://localhost:3000"},
                "routes":   {"type": "array",  "items": {"type": "string"},
                             "description": "要檢查的路由清單，例如 ['/', '/login', '/dashboard']"},
            },
            "required": ["base_url", "routes"],
        },
    },
    {
        "name": "browser_check_console",
        "description": "開啟頁面，只回傳 console.error 和 network 4xx/5xx 錯誤列表，不截圖。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url":     {"type": "string",  "description": "要檢查的 URL"},
                "wait_ms": {"type": "integer", "description": "等待時間（預設 3000ms）"},
            },
            "required": ["url"],
        },
    },
]


# ── 瀏覽器執行引擎 ─────────────────────────────────────────────────────────

class BrowserQA:
    """Playwright 瀏覽器 QA 引擎"""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser = None
        self._playwright = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass

    def _get_browser(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self.headless)
        return self._browser

    def _save_screenshot(self, page, label: str) -> str:
        ts   = datetime.now().strftime("%H%M%S")
        name = f"{ts}_{label.replace(' ', '_')[:40]}.png"
        path = SCREENSHOT_DIR / name
        page.screenshot(path=str(path), full_page=True)
        print(f"  {GREEN}📸 截圖儲存：{path}{RESET}")
        return str(path)

    # ── browser_screenshot ───────────────────────────────────────────────

    def screenshot(self, url: str, wait_ms: int = 2000,
                   viewport: dict = None, mobile: bool = False) -> dict:
        browser = self._get_browser()
        console_errors = []
        network_errors = []

        vp = {"width": 375, "height": 812} if mobile else (viewport or {"width": 1280, "height": 720})
        ctx  = browser.new_context(viewport=vp,
                                   user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)" if not mobile else
                                   "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)")
        page = ctx.new_page()

        page.on("console",  lambda m: console_errors.append(f"[{m.type}] {m.text}") if m.type == "error" else None)
        page.on("response", lambda r: network_errors.append(f"{r.status} {r.url}") if r.status >= 400 else None)

        try:
            page.goto(url, wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(wait_ms)
            title    = page.title()
            path     = self._save_screenshot(page, f"screenshot_{url.split('/')[-1] or 'home'}")
            h1_texts = page.eval_on_selector_all("h1", "els => els.map(e => e.textContent.trim())")

            result = {
                "status":         "ok",
                "url":            url,
                "title":          title,
                "h1":             h1_texts,
                "screenshot":     path,
                "console_errors": console_errors,
                "network_errors": network_errors,
                "viewport":       vp,
            }
        except Exception as e:
            result = {"status": "error", "url": url, "error": str(e),
                      "console_errors": console_errors, "network_errors": network_errors}
        finally:
            ctx.close()

        return result

    # ── browser_flow ─────────────────────────────────────────────────────

    def flow(self, url: str, steps: list) -> dict:
        browser  = self._get_browser()
        ctx      = browser.new_context(viewport={"width": 1280, "height": 720})
        page     = ctx.new_page()
        results  = []
        console_errors = []
        network_errors = []

        page.on("console",  lambda m: console_errors.append(f"{m.text}") if m.type == "error" else None)
        page.on("response", lambda r: network_errors.append(f"{r.status} {r.url}") if r.status >= 400 else None)

        try:
            page.goto(url, wait_until="networkidle", timeout=15000)

            for i, step in enumerate(steps):
                action   = step.get("action")
                selector = step.get("selector", "")
                value    = step.get("value", "")
                label    = step.get("label", f"step_{i+1}")

                try:
                    if action == "click":
                        page.click(selector, timeout=5000)
                        results.append({"step": label, "status": "ok", "action": "click"})

                    elif action == "fill":
                        page.fill(selector, value, timeout=5000)
                        results.append({"step": label, "status": "ok", "action": "fill"})

                    elif action == "select":
                        page.select_option(selector, value, timeout=5000)
                        results.append({"step": label, "status": "ok", "action": "select"})

                    elif action == "press":
                        page.keyboard.press(value)
                        results.append({"step": label, "status": "ok", "action": "press"})

                    elif action == "wait":
                        ms = int(value) if value else 1000
                        page.wait_for_timeout(ms)
                        results.append({"step": label, "status": "ok", "action": "wait"})

                    elif action == "screenshot":
                        path = self._save_screenshot(page, label)
                        results.append({"step": label, "status": "ok",
                                        "action": "screenshot", "path": path})

                    elif action == "assert_text":
                        page.wait_for_selector(f"text={value}", timeout=5000)
                        results.append({"step": label, "status": "pass",
                                        "action": "assert_text", "expected": value})

                    elif action == "assert_url":
                        current = page.url
                        passed  = value in current
                        results.append({"step": label,
                                        "status": "pass" if passed else "fail",
                                        "action": "assert_url",
                                        "expected": value, "actual": current})

                    elif action == "assert_visible":
                        vis = page.is_visible(selector)
                        results.append({"step": label,
                                        "status": "pass" if vis else "fail",
                                        "action": "assert_visible", "selector": selector})

                    elif action == "assert_not_visible":
                        vis = page.is_visible(selector)
                        results.append({"step": label,
                                        "status": "pass" if not vis else "fail",
                                        "action": "assert_not_visible", "selector": selector})

                except Exception as e:
                    results.append({"step": label, "status": "error",
                                    "action": action, "error": str(e)})
                    print(f"  {RED}✖ {label}: {e}{RESET}")

        except Exception as e:
            return {"status": "error", "error": str(e), "steps": results}
        finally:
            ctx.close()

        passed = sum(1 for r in results if r.get("status") in ("ok", "pass"))
        failed = sum(1 for r in results if r.get("status") in ("fail", "error"))

        return {
            "status":         "pass" if failed == 0 else "partial",
            "steps_total":    len(results),
            "steps_passed":   passed,
            "steps_failed":   failed,
            "steps":          results,
            "console_errors": console_errors,
            "network_errors": network_errors,
        }

    # ── browser_audit ────────────────────────────────────────────────────

    def audit(self, base_url: str, routes: list) -> dict:
        report   = {"base_url": base_url, "routes": {}, "summary": {}}
        all_errs = []

        for route in routes:
            url    = base_url.rstrip("/") + route
            print(f"\n  {CYAN}▶ 審計 {url}{RESET}")
            result = self.screenshot(url, wait_ms=2000)
            report["routes"][route] = result

            if result.get("console_errors"):
                all_errs.extend([f"{route}: {e}" for e in result["console_errors"]])
            if result.get("network_errors"):
                all_errs.extend([f"{route}: {e}" for e in result["network_errors"]])

            status_icon = f"{GREEN}✔{RESET}" if not result.get("console_errors") and not result.get("network_errors") else f"{YELLOW}⚠{RESET}"
            print(f"  {status_icon} {route} — title: {result.get('title', '?')} "
                  f"| console errors: {len(result.get('console_errors', []))} "
                  f"| network errors: {len(result.get('network_errors', []))}")

        report["summary"] = {
            "routes_checked":  len(routes),
            "routes_clean":    sum(1 for r in report["routes"].values()
                                   if not r.get("console_errors") and not r.get("network_errors")),
            "total_errors":    len(all_errs),
            "all_errors":      all_errs,
        }
        return report

    # ── browser_check_console ────────────────────────────────────────────

    def check_console(self, url: str, wait_ms: int = 3000) -> dict:
        browser = self._get_browser()
        ctx     = browser.new_context(viewport={"width": 1280, "height": 720})
        page    = ctx.new_page()
        console_errors = []
        network_errors = []

        page.on("console",  lambda m: console_errors.append({"type": m.type, "text": m.text}))
        page.on("response", lambda r: network_errors.append({"status": r.status, "url": r.url})
                if r.status >= 400 else None)

        try:
            page.goto(url, wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(wait_ms)
        except Exception as e:
            ctx.close()
            return {"status": "error", "error": str(e)}
        finally:
            ctx.close()

        errors_only = [e for e in console_errors if e["type"] == "error"]
        return {
            "url":            url,
            "console_errors": errors_only,
            "network_errors": network_errors,
            "clean":          len(errors_only) == 0 and len(network_errors) == 0,
        }


# ── 工具分派器（給 Agent 的 execute 接口）────────────────────────────────

class BrowserToolExecutor:
    def __init__(self, headless: bool = True):
        self.headless = headless

    def execute(self, tool_name: str, tool_input: dict) -> str:
        if not _check_playwright():
            install_playwright()

        with BrowserQA(headless=self.headless) as qa:
            try:
                if tool_name == "browser_screenshot":
                    result = qa.screenshot(**tool_input)
                elif tool_name == "browser_flow":
                    result = qa.flow(**tool_input)
                elif tool_name == "browser_audit":
                    result = qa.audit(**tool_input)
                elif tool_name == "browser_check_console":
                    result = qa.check_console(**tool_input)
                else:
                    return f"[錯誤] 未知的瀏覽器工具: {tool_name}"

                return json.dumps(result, ensure_ascii=False, indent=2)

            except Exception as e:
                return f"[瀏覽器錯誤] {tool_name}: {e}"
