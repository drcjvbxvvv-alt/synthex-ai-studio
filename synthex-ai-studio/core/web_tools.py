"""
Web Development Tool Engine
專為網站開發設計的工具集：npm/yarn/pnpm、Git、框架偵測、開發伺服器管理
"""

import os
import re
import json
import shutil
import subprocess
import socket
from pathlib import Path
from core.tools import ToolExecutor, BLOCKED_PATTERNS, RESET, BOLD, DIM, GREEN, YELLOW, RED, CYAN, GRAY

# ══════════════════════════════════════════════════════════════
#  WEB-SPECIFIC TOOL DEFINITIONS
# ══════════════════════════════════════════════════════════════

WEB_TOOL_DEFS = [
    {
        "name": "npm_run",
        "description": "執行 npm/yarn/pnpm 指令（install、build、test、dev 等）。自動偵測套件管理器。",
        "input_schema": {
            "type": "object",
            "properties": {
                "script":  {"type": "string", "description": "要執行的腳本，例如 'install'、'build'、'test'、'lint'"},
                "cwd":     {"type": "string",  "description": "執行目錄（預設專案根目錄）"},
                "manager": {"type": "string",  "description": "套件管理器：'npm'、'yarn'、'pnpm'（預設自動偵測）"},
                "args":    {"type": "string",  "description": "額外參數，例如 '--watch'、'--coverage'"},
                "timeout": {"type": "integer", "description": "超時秒數（預設 120）"},
            },
            "required": ["script"],
        },
    },
    {
        "name": "install_package",
        "description": "安裝 npm 套件（相當於 npm install <package>）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "packages": {"type": "string",  "description": "套件名稱，空格分隔，例如 'react react-dom'"},
                "dev":      {"type": "boolean", "description": "是否安裝為 devDependency（預設 false）"},
                "cwd":      {"type": "string",  "description": "執行目錄"},
                "manager":  {"type": "string",  "description": "套件管理器（預設自動偵測）"},
            },
            "required": ["packages"],
        },
    },
    {
        "name": "git_run",
        "description": "執行 Git 指令。支援 status、add、commit、push、pull、log、diff 等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Git 指令（不含 'git' 前綴），例如 'status'、'add .'、'commit -m \"feat: add login\"'"},
                "cwd":     {"type": "string",  "description": "執行目錄"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "detect_framework",
        "description": "偵測專案使用的前端/後端框架、版本、建置工具，並提供專案健康度報告。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "專案路徑（預設當前目錄）"},
            },
            "required": [],
        },
    },
    {
        "name": "read_package_json",
        "description": "讀取並解析 package.json，回傳相依套件、腳本、版本等資訊。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "package.json 所在目錄（預設當前目錄）"},
            },
            "required": [],
        },
    },
    {
        "name": "scaffold_project",
        "description": "使用官方 CLI 建立新的前端/後端專案骨架（create-next-app、create-vite、fastapi 等）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "framework": {"type": "string", "description": "'nextjs'、'vite-react'、'vite-vue'、'nuxt'、'remix'、'astro'、'fastapi'、'express'"},
                "name":      {"type": "string", "description": "專案名稱"},
                "cwd":       {"type": "string",  "description": "建立位置（預設當前目錄）"},
                "typescript":{"type": "boolean", "description": "是否使用 TypeScript（預設 true）"},
            },
            "required": ["framework", "name"],
        },
    },
    {
        "name": "check_port",
        "description": "檢查特定 port 是否被佔用，找出是哪個程序在使用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "要檢查的 port 號"},
            },
            "required": ["port"],
        },
    },
    {
        "name": "read_env",
        "description": "讀取 .env 或 .env.local 檔案（只回傳 key 名稱，不顯示值，保護機密）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目錄路徑（預設當前目錄）"},
            },
            "required": [],
        },
    },
    {
        "name": "write_env",
        "description": "安全地在 .env 檔案中新增或更新環境變數。",
        "input_schema": {
            "type": "object",
            "properties": {
                "vars":   {"type": "object", "description": "key-value 對，例如 {\"DATABASE_URL\": \"postgres://...\"}"},
                "file":   {"type": "string",  "description": ".env 檔案名稱（預設 '.env.local'）"},
                "path":   {"type": "string",  "description": "目錄路徑（預設當前目錄）"},
            },
            "required": ["vars"],
        },
    },
    {
        "name": "lint_and_typecheck",
        "description": "執行 ESLint、TypeScript 型別檢查，回傳所有錯誤和警告。",
        "input_schema": {
            "type": "object",
            "properties": {
                "cwd":     {"type": "string",  "description": "專案目錄"},
                "fix":     {"type": "boolean", "description": "是否自動修復可修復的問題（預設 false）"},
            },
            "required": [],
        },
    },
]

ALL_WEB_TOOL_NAMES = {t["name"] for t in WEB_TOOL_DEFS}


# ══════════════════════════════════════════════════════════════
#  WEB TOOL EXECUTOR
# ══════════════════════════════════════════════════════════════

class WebToolExecutor(ToolExecutor):
    """繼承基礎 ToolExecutor，加上網頁開發專用工具"""

    def execute(self, tool_name: str, tool_input: dict) -> str:
        if tool_name in ALL_WEB_TOOL_NAMES:
            handlers = {
                "npm_run":          self._npm_run,
                "install_package":  self._install_package,
                "git_run":          self._git_run,
                "detect_framework": self._detect_framework,
                "read_package_json":self._read_package_json,
                "scaffold_project": self._scaffold_project,
                "check_port":       self._check_port,
                "read_env":         self._read_env,
                "write_env":        self._write_env,
                "lint_and_typecheck":self._lint_and_typecheck,
            }
            handler = handlers.get(tool_name)
            if handler:
                try:
                    return handler(**tool_input)
                except Exception as e:
                    return f"[工具錯誤] {tool_name}: {e}"
        return super().execute(tool_name, tool_input)

    # ── 套件管理器偵測 ─────────────────────────────────────────

    def _detect_manager(self, cwd: str) -> str:
        p = Path(cwd)
        if (p / "pnpm-lock.yaml").exists():  return "pnpm"
        if (p / "yarn.lock").exists():        return "yarn"
        return "npm"

    def _run_in(self, cmd: str, cwd: str = None, timeout: int = 120) -> str:
        work = Path(cwd).resolve() if cwd else self.workdir
        print(f"  {CYAN}$ {cmd}{RESET}  {DIM}(在 {work}){RESET}")
        try:
            r = subprocess.run(cmd, shell=True, cwd=work,
                               capture_output=True, text=True, timeout=timeout)
            out = r.stdout.strip()
            err = r.stderr.strip()
            if out:
                for line in out.splitlines()[-40:]:
                    print(f"  {DIM}{line}{RESET}")
            if err and r.returncode != 0:
                for line in err.splitlines()[-20:]:
                    print(f"  {YELLOW}{line}{RESET}")
            icon = f"{GREEN}✔{RESET}" if r.returncode == 0 else f"{YELLOW}⚠ exit {r.returncode}{RESET}"
            print(f"  {icon}")
            combined = "\n".join(filter(None, [out, err if r.returncode != 0 else ""]))
            return f"{combined}\n[exit {r.returncode}]"
        except subprocess.TimeoutExpired:
            return f"[超時] 超過 {timeout} 秒"
        except Exception as e:
            return f"[錯誤] {e}"

    # ── npm_run ────────────────────────────────────────────────

    def _npm_run(self, script: str, cwd: str = None, manager: str = None,
                 args: str = "", timeout: int = 120) -> str:
        work = str(Path(cwd).resolve() if cwd else self.workdir)
        mgr  = manager or self._detect_manager(work)
        args_str = f" {args}" if args else ""

        # npm 的 run 語法略有不同
        if script in ("install", "ci"):
            cmd = f"{mgr} {script}{args_str}"
        elif mgr == "npm":
            cmd = f"npm run {script}{args_str}"
        else:
            cmd = f"{mgr} {script}{args_str}"

        return self._run_in(cmd, cwd=work, timeout=timeout)

    # ── install_package ────────────────────────────────────────

    def _install_package(self, packages: str, dev: bool = False,
                         cwd: str = None, manager: str = None) -> str:
        work = str(Path(cwd).resolve() if cwd else self.workdir)
        mgr  = manager or self._detect_manager(work)
        flag = {"npm": "--save-dev", "yarn": "--dev", "pnpm": "--save-dev"}.get(mgr, "--save-dev") if dev else ""
        cmd_map = {"npm": f"npm install {flag} {packages}",
                   "yarn": f"yarn add {flag} {packages}",
                   "pnpm": f"pnpm add {flag} {packages}"}
        cmd = cmd_map.get(mgr, f"npm install {flag} {packages}")
        return self._run_in(cmd.strip(), cwd=work, timeout=120)

    # ── git_run ────────────────────────────────────────────────

    def _git_run(self, command: str, cwd: str = None) -> str:
        # 安全白名單
        safe_patterns = [
            r"^(status|log|diff|show|branch|tag|stash\s+list|remote\s+-v|rev-parse)",
            r"^(add|commit|push|pull|fetch|checkout|switch|merge|rebase|reset|clean)",
            r"^(init|clone|config|describe|shortlog|blame)",
        ]
        if not any(re.match(p, command.strip()) for p in safe_patterns):
            return f"[封鎖] 未知的 git 指令: {command}"
        work = str(Path(cwd).resolve() if cwd else self.workdir)
        return self._run_in(f"git {command}", cwd=work, timeout=60)

    # ── detect_framework ──────────────────────────────────────

    def _detect_framework(self, path: str = ".") -> str:
        p = self._resolve(path)
        info = [f"🔍 框架偵測：{p}\n"]

        # 讀 package.json
        pkg_path = p / "package.json"
        if pkg_path.exists():
            try:
                pkg = json.loads(pkg_path.read_text())
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

                frameworks = {
                    "next":          "Next.js",
                    "nuxt":          "Nuxt.js",
                    "remix":         "@remix-run/react",
                    "@remix-run/react": "Remix",
                    "astro":         "Astro",
                    "gatsby":        "Gatsby",
                    "react":         "React",
                    "vue":           "Vue",
                    "svelte":        "Svelte",
                    "@angular/core": "Angular",
                    "solid-js":      "Solid.js",
                }
                found_fw = []
                for dep, label in frameworks.items():
                    if dep in deps:
                        ver = deps[dep]
                        found_fw.append(f"  ✓ {label}  {ver}")

                build_tools = {
                    "vite": "Vite", "webpack": "Webpack",
                    "turbopack": "Turbopack", "esbuild": "esbuild",
                    "rollup": "Rollup", "parcel": "Parcel",
                }
                found_build = []
                for dep, label in build_tools.items():
                    if dep in deps:
                        found_build.append(f"  ✓ {label}  {deps[dep]}")

                test_tools = {
                    "jest": "Jest", "vitest": "Vitest",
                    "playwright": "Playwright", "cypress": "Cypress",
                    "@testing-library/react": "Testing Library",
                }
                found_test = []
                for dep, label in test_tools.items():
                    if dep in deps:
                        found_test.append(f"  ✓ {label}  {deps[dep]}")

                if found_fw:
                    info.append("🖼  前端框架:\n" + "\n".join(found_fw))
                if found_build:
                    info.append("\n🔨 建置工具:\n" + "\n".join(found_build))
                if found_test:
                    info.append("\n🧪 測試工具:\n" + "\n".join(found_test))

                # TypeScript
                if "typescript" in deps or (p / "tsconfig.json").exists():
                    ts_ver = deps.get("typescript", "（tsconfig.json 存在）")
                    info.append(f"\n📘 TypeScript: {ts_ver}")

                # Node 版本要求
                engines = pkg.get("engines", {})
                if engines:
                    info.append(f"\n⚙  Node 版本要求: {engines}")

                # 可用腳本
                scripts = pkg.get("scripts", {})
                if scripts:
                    info.append("\n📜 可用腳本:")
                    for name, cmd in list(scripts.items())[:10]:
                        info.append(f"  {name:<20} {cmd[:60]}")

            except Exception as e:
                info.append(f"[警告] 無法解析 package.json: {e}")

        # Python 框架
        if (p / "requirements.txt").exists() or (p / "pyproject.toml").exists():
            try:
                reqs = ""
                if (p / "requirements.txt").exists():
                    reqs = (p / "requirements.txt").read_text()
                elif (p / "pyproject.toml").exists():
                    reqs = (p / "pyproject.toml").read_text()
                py_fw = []
                for fw in ["fastapi", "flask", "django", "starlette", "tornado"]:
                    if fw in reqs.lower():
                        py_fw.append(f"  ✓ {fw.capitalize()}")
                if py_fw:
                    info.append("\n🐍 Python 框架:\n" + "\n".join(py_fw))
            except Exception:
                pass

        # 健康度檢查
        checks = {
            "package.json":   "✓ package.json 存在",
            "package-lock.json": "✓ npm lock 存在",
            "yarn.lock":      "✓ yarn lock 存在",
            "pnpm-lock.yaml": "✓ pnpm lock 存在",
            ".env.local":     "✓ .env.local 存在",
            ".env":           "✓ .env 存在",
            ".gitignore":     "✓ .gitignore 存在",
            "README.md":      "✓ README.md 存在",
            "tsconfig.json":  "✓ tsconfig.json 存在",
            ".eslintrc*":     None,  # glob
        }
        health = []
        for fname, label in checks.items():
            if label and (p / fname).exists():
                health.append(f"  {label}")
        if health:
            info.append("\n🏥 專案健康度:\n" + "\n".join(health))

        return "\n".join(info)

    # ── read_package_json ─────────────────────────────────────

    def _read_package_json(self, path: str = ".") -> str:
        p = self._resolve(path) / "package.json"
        if not p.exists():
            return f"[找不到] {path}/package.json"
        try:
            pkg = json.loads(p.read_text())
            result = [f"📦 {pkg.get('name', '(unnamed)')}  v{pkg.get('version', '?')}"]
            if pkg.get("description"):
                result.append(f"   {pkg['description']}")
            result.append(f"\n腳本:\n" + "\n".join(
                f"  {k:<20} {v}" for k, v in pkg.get("scripts", {}).items()
            ))
            result.append(f"\n相依套件 ({len(pkg.get('dependencies', {}))}):\n" + "\n".join(
                f"  {k:<30} {v}" for k, v in list(pkg.get("dependencies", {}).items())[:20]
            ))
            if pkg.get("devDependencies"):
                result.append(f"\nDev 相依 ({len(pkg['devDependencies'])}):\n" + "\n".join(
                    f"  {k:<30} {v}" for k, v in list(pkg["devDependencies"].items())[:15]
                ))
            return "\n".join(result)
        except Exception as e:
            return f"[錯誤] 解析 package.json 失敗: {e}"

    # ── scaffold_project ──────────────────────────────────────

    def _scaffold_project(self, framework: str, name: str,
                          cwd: str = None, typescript: bool = True) -> str:
        work = str(Path(cwd).resolve() if cwd else self.workdir)
        ts_flag = "--typescript" if typescript else "--javascript"

        templates = {
            "nextjs":     f"npx create-next-app@latest {name} {ts_flag} --tailwind --eslint --app --no-git",
            "vite-react": f"npm create vite@latest {name} -- --template react{'-ts' if typescript else ''}",
            "vite-vue":   f"npm create vite@latest {name} -- --template vue{'-ts' if typescript else ''}",
            "nuxt":       f"npx nuxi@latest init {name}",
            "remix":      f"npx create-remix@latest {name}",
            "astro":      f"npm create astro@latest {name} -- --template minimal",
            "express":    None,  # 手動建立
            "fastapi":    None,
        }

        if framework == "express":
            # 手動建立 Express 骨架
            proj_path = Path(work) / name
            proj_path.mkdir(parents=True, exist_ok=True)
            pkg = {
                "name": name, "version": "1.0.0", "type": "module",
                "scripts": {"dev": "node --watch src/index.js", "start": "node src/index.js"},
                "dependencies": {"express": "^4.18.0"},
                "devDependencies": {"@types/express": "^4.17.0"} if typescript else {},
            }
            (proj_path / "package.json").write_text(json.dumps(pkg, indent=2))
            (proj_path / "src").mkdir(exist_ok=True)
            (proj_path / "src" / "index.js").write_text(
                "import express from 'express';\nconst app = express();\nconst PORT = process.env.PORT || 3000;\n"
                "app.use(express.json());\napp.get('/', (req, res) => res.json({ status: 'ok' }));\n"
                "app.listen(PORT, () => console.log(`Server on port ${PORT}`));\n"
            )
            return f"[成功] Express 專案建立於 {proj_path}"

        if framework == "fastapi":
            proj_path = Path(work) / name
            proj_path.mkdir(parents=True, exist_ok=True)
            (proj_path / "requirements.txt").write_text("fastapi>=0.110.0\nuvicorn[standard]>=0.27.0\npydantic>=2.0.0\n")
            (proj_path / "main.py").write_text(
                'from fastapi import FastAPI\napp = FastAPI(title="' + name + '")\n\n'
                '@app.get("/")\nasync def root():\n    return {"status": "ok"}\n'
            )
            (proj_path / ".gitignore").write_text("__pycache__/\n*.pyc\n.venv/\n.env\n")
            return f"[成功] FastAPI 專案建立於 {proj_path}"

        cmd = templates.get(framework)
        if not cmd:
            return f"[錯誤] 不支援的框架: {framework}。可用: {', '.join(templates.keys())}"

        return self._run_in(cmd, cwd=work, timeout=180)

    # ── check_port ────────────────────────────────────────────

    def _check_port(self, port: int) -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            in_use = s.connect_ex(("localhost", port)) == 0
        if not in_use:
            return f"[Port {port}] 空閒，可以使用"
        # 找出誰在用
        try:
            r = subprocess.run(f"lsof -i :{port} -n -P", shell=True,
                               capture_output=True, text=True, timeout=5)
            return f"[Port {port}] 已被佔用\n{r.stdout.strip()}"
        except Exception:
            return f"[Port {port}] 已被佔用（無法取得詳情）"

    # ── read_env ──────────────────────────────────────────────

    def _read_env(self, path: str = ".") -> str:
        p = self._resolve(path)
        env_files = [".env.local", ".env.development", ".env", ".env.example"]
        result = []
        for fname in env_files:
            fp = p / fname
            if fp.exists():
                try:
                    lines = fp.read_text().splitlines()
                    keys = []
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key = line.split("=")[0].strip()
                            keys.append(f"  {key}")
                    result.append(f"📄 {fname} ({len(keys)} 個變數):\n" + "\n".join(keys))
                except Exception as e:
                    result.append(f"[錯誤] 讀取 {fname}: {e}")
        return "\n\n".join(result) if result else f"[找不到] {path} 下沒有 .env 檔案"

    # ── write_env ─────────────────────────────────────────────

    def _write_env(self, vars: dict, file: str = ".env.local", path: str = ".") -> str:
        fp = self._resolve(path) / file
        existing = {}
        existing_lines = []
        if fp.exists():
            for line in fp.read_text().splitlines():
                existing_lines.append(line)
                if "=" in line and not line.startswith("#"):
                    k = line.split("=")[0].strip()
                    existing[k] = True

        new_lines = list(existing_lines)
        added, updated = [], []
        for k, v in vars.items():
            entry = f"{k}={v}"
            if k in existing:
                # 更新現有的
                new_lines = [entry if (l.split("=")[0].strip() == k and "=" in l and not l.startswith("#"))
                             else l for l in new_lines]
                updated.append(k)
            else:
                new_lines.append(entry)
                added.append(k)

        fp.write_text("\n".join(new_lines) + "\n")
        print(f"  {GREEN}✔ 寫入 {file}{RESET}")
        parts = []
        if added:   parts.append(f"新增: {', '.join(added)}")
        if updated: parts.append(f"更新: {', '.join(updated)}")
        return f"[成功] {file} · " + " · ".join(parts)

    # ── lint_and_typecheck ────────────────────────────────────

    def _lint_and_typecheck(self, cwd: str = None, fix: bool = False) -> str:
        work = str(Path(cwd).resolve() if cwd else self.workdir)
        results = []
        pkg_path = Path(work) / "package.json"

        if pkg_path.exists():
            try:
                pkg = json.loads(pkg_path.read_text())
                scripts = pkg.get("scripts", {})
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

                # TypeScript
                if "typescript" in deps or (Path(work) / "tsconfig.json").exists():
                    r = self._run_in("npx tsc --noEmit --pretty", cwd=work, timeout=60)
                    results.append(f"TypeScript:\n{r}")

                # ESLint
                if "eslint" in deps or "lint" in scripts:
                    fix_flag = "--fix" if fix else ""
                    if "lint" in scripts:
                        r = self._run_in(f"npm run lint {'-- --fix' if fix else ''}", cwd=work, timeout=60)
                    else:
                        r = self._run_in(f"npx eslint . {fix_flag} --ext .ts,.tsx,.js,.jsx", cwd=work, timeout=60)
                    results.append(f"ESLint:\n{r}")

            except Exception as e:
                results.append(f"[錯誤] {e}")

        return "\n\n".join(results) if results else "[跳過] 找不到 package.json 或無法執行 lint"


# ── 合併工具定義（基礎 + Web）─────────────────────────────────

from core.tools import ALL_TOOL_DEFS as BASE_TOOL_DEFS

WEB_DEV_ALL_TOOLS = BASE_TOOL_DEFS + WEB_TOOL_DEFS

WEB_DEV_ROLE_TOOLS = {
    "engineering": WEB_DEV_ALL_TOOLS,
    "devops":      WEB_DEV_ALL_TOOLS,
    "qa":          WEB_DEV_ALL_TOOLS,
    "ai_data":     WEB_DEV_ALL_TOOLS,
    "exec":        BASE_TOOL_DEFS[:4],   # 高層只需讀取類工具
    "product":     BASE_TOOL_DEFS[:6],
    "biz":         BASE_TOOL_DEFS[:6],
    "default":     WEB_DEV_ALL_TOOLS,
}

def get_webdev_tools(role: str = "default") -> list:
    return WEB_DEV_ROLE_TOOLS.get(role, WEB_DEV_ALL_TOOLS)
