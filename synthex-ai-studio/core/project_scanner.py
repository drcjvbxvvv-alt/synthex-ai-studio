"""
SYNTHEX Project Scanner
弱項一解決方案：智能偵測新專案 vs 現有專案，分支處理

新專案  → scaffold 完整起點（Next.js 16 + 已驗證架構）
現有專案 → 深度掃描，理解現況，再針對性行動（新增功能/排查錯誤/重構）
"""

import os
import json
import subprocess
from pathlib import Path
from datetime import datetime

RESET  = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
CYAN   = "\033[96m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
RED    = "\033[91m"; PURPLE = "\033[35m"


# ══════════════════════════════════════════════════════════════
#  專案偵測
# ══════════════════════════════════════════════════════════════

class ProjectScanner:
    """
    偵測專案狀態，決定走「新建」還是「現有專案」路徑。
    新專案：幾乎空目錄，沒有 package.json / pyproject.toml
    現有專案：有程式碼、有 git 歷史、有依賴清單
    """

    def __init__(self, workdir: str):
        self.workdir = Path(workdir).resolve()

    def scan(self) -> dict:
        """完整掃描，回傳專案快照"""
        is_new = self._is_new_project()

        result = {
            "workdir":      str(self.workdir),
            "is_new":       is_new,
            "project_type": self._detect_type(),
            "tech_stack":   self._detect_stack(),
            "health":       self._health_check() if not is_new else {},
            "git_info":     self._git_info(),
            "file_count":   self._count_files(),
            "issues":       [],
        }

        if not is_new:
            result["issues"] = self._detect_issues(result)

        return result

    def _is_new_project(self) -> bool:
        """新專案判斷：沒有任何框架標記檔案，或目錄幾乎是空的"""
        markers = [
            "package.json", "pyproject.toml", "requirements.txt",
            "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
        ]
        for m in markers:
            if (self.workdir / m).exists():
                return False
        # 排除 CLAUDE.md 和 agents/ 這些 synthex 自己的檔案
        real_files = [
            f for f in self.workdir.rglob("*")
            if f.is_file()
            and ".git" not in f.parts
            and "CLAUDE.md" not in f.name
            and "agents" not in f.parts
        ]
        return len(real_files) < 3

    def _detect_type(self) -> str:
        p = self.workdir
        if (p / "package.json").exists():
            try:
                pkg = json.loads((p / "package.json").read_text())
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "next" in deps:      return "nextjs"
                if "nuxt" in deps:      return "nuxt"
                if "remix" in deps or "@remix-run/react" in deps: return "remix"
                if "astro" in deps:     return "astro"
                if "react" in deps:     return "react"
                if "vue" in deps:       return "vue"
                if "svelte" in deps:    return "svelte"
                if "express" in deps:   return "express"
                return "node"
            except Exception:
                return "node"
        if (p / "requirements.txt").exists() or (p / "pyproject.toml").exists():
            try:
                reqs = ""
                if (p / "requirements.txt").exists():
                    reqs = (p / "requirements.txt").read_text().lower()
                if "fastapi" in reqs:   return "fastapi"
                if "django" in reqs:    return "django"
                if "flask" in reqs:     return "flask"
                return "python"
            except Exception:
                return "python"
        return "unknown"

    def _detect_stack(self) -> dict:
        p    = self.workdir
        stack = {}
        if (p / "package.json").exists():
            try:
                pkg  = json.loads((p / "package.json").read_text())
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                stack["runtime"]    = f"Node {self._node_version()}"
                stack["typescript"] = "typescript" in deps
                stack["tailwind"]   = any("tailwind" in k for k in deps)
                stack["prisma"]     = "prisma" in deps or "@prisma/client" in deps
                stack["drizzle"]    = "drizzle-orm" in deps
                stack["nextauth"]   = "next-auth" in deps or "@auth/nextjs" in deps
                stack["testing"]    = [k for k in ["vitest","jest","playwright","cypress"] if k in deps]
                stack["orm"]        = "prisma" if stack["prisma"] else ("drizzle" if stack["drizzle"] else "none")
            except Exception:
                pass
        if (p / "prisma" / "schema.prisma").exists():
            stack["db_schema"] = "prisma"
        if (p / "drizzle.config.ts").exists():
            stack["db_schema"] = "drizzle"
        return stack

    def _node_version(self) -> str:
        try:
            r = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=3)
            return r.stdout.strip()
        except Exception:
            return "unknown"

    def _health_check(self) -> dict:
        p = self.workdir
        health = {
            "has_gitignore":       (p / ".gitignore").exists(),
            "has_env_example":     (p / ".env.local.example").exists() or (p / ".env.example").exists(),
            "has_readme":          (p / "README.md").exists(),
            "has_tests":           len(list(p.rglob("*.test.*"))) + len(list(p.rglob("*.spec.*"))) > 0,
            "has_ci":              (p / ".github" / "workflows").exists(),
            "has_docker":          (p / "Dockerfile").exists(),
            "has_types":           (p / "tsconfig.json").exists(),
            "lint_config":         (p / ".eslintrc.json").exists() or (p / "eslint.config.js").exists(),
            "has_observability":   self._check_observability(p),
        }
        health["score"] = round(sum(1 for v in health.values() if v is True) / 9 * 100)
        return health

    def _check_observability(self, p: Path) -> bool:
        try:
            if (p / "package.json").exists():
                pkg  = json.loads((p / "package.json").read_text())
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                return "@sentry/nextjs" in deps or "posthog-js" in deps or "@sentry/node" in deps
        except Exception:
            pass
        return False

    def _git_info(self) -> dict:
        def g(cmd):
            try:
                r = subprocess.run(cmd, shell=True, cwd=self.workdir,
                                   capture_output=True, text=True, timeout=5)
                return r.stdout.strip()
            except Exception:
                return ""

        return {
            "initialized": (self.workdir / ".git").exists(),
            "branch":      g("git branch --show-current"),
            "commits":     g("git rev-list --count HEAD 2>/dev/null"),
            "last_commit": g("git log -1 --format='%cr %s' 2>/dev/null"),
            "dirty":       bool(g("git status --porcelain")),
        }

    def _count_files(self) -> dict:
        SKIP = {".git", "__pycache__", "node_modules", ".next", ".venv", "dist", "build"}
        counts = {}
        try:
            for f in self.workdir.rglob("*"):
                if f.is_file() and not any(s in f.parts for s in SKIP):
                    ext = f.suffix.lower() or "(no ext)"
                    counts[ext] = counts.get(ext, 0) + 1
        except Exception:
            pass
        top = sorted(counts.items(), key=lambda x: -x[1])[:8]
        return {"by_ext": dict(top), "total": sum(counts.values())}

    def _detect_issues(self, scan: dict) -> list:
        """偵測現有專案的已知問題"""
        issues = []
        health = scan.get("health", {})
        stack  = scan.get("tech_stack", {})

        if not health.get("has_env_example"):
            issues.append({"severity": "medium", "issue": "缺少 .env.local.example",
                           "fix": "建立環境變數範本，讓新成員知道需要設定哪些 key"})
        if not health.get("has_tests"):
            issues.append({"severity": "high", "issue": "沒有測試檔案",
                           "fix": "至少為核心業務邏輯建立單元測試"})
        if not health.get("has_ci"):
            issues.append({"severity": "medium", "issue": "沒有 CI/CD",
                           "fix": "建立 .github/workflows/ci.yml"})
        if not health.get("has_observability"):
            issues.append({"severity": "high", "issue": "沒有可觀測性工具（Sentry/PostHog）",
                           "fix": "加入錯誤追蹤和使用分析，上線後才能知道發生什麼"})
        if not health.get("has_gitignore"):
            issues.append({"severity": "high", "issue": "沒有 .gitignore",
                           "fix": "可能誤提交 .env、node_modules"})
        if stack.get("orm") == "none" and scan.get("project_type") in ("nextjs", "express", "fastapi"):
            issues.append({"severity": "medium", "issue": "沒有 ORM（直接寫 SQL 或無資料庫）",
                           "fix": "考慮引入 Prisma 或 Drizzle 確保型別安全"})

        return issues

    def format_report(self, scan: dict) -> str:
        """格式化掃描結果為可讀報告"""
        is_new = scan["is_new"]
        lines  = []

        lines.append(f"\n{'='*60}")
        lines.append(f"  {'🆕 新專案' if is_new else '📁 現有專案'} — {scan['workdir']}")
        lines.append(f"{'='*60}")

        if not is_new:
            lines.append(f"\n專案類型：{scan['project_type']}")
            stack = scan['tech_stack']
            if stack:
                lines.append(f"技術棧：")
                for k, v in stack.items():
                    if v and v != "none":
                        lines.append(f"  {k}: {v}")

            health = scan['health']
            score  = health.get('score', 0)
            color  = GREEN if score >= 70 else (YELLOW if score >= 40 else RED)
            lines.append(f"\n健康度：{color}{score}/100{RESET}")
            for k, v in health.items():
                if k == "score": continue
                icon = f"{GREEN}✓{RESET}" if v else f"{RED}✗{RESET}"
                lines.append(f"  {icon} {k}")

            git = scan['git_info']
            if git.get('initialized'):
                lines.append(f"\nGit：{git.get('commits','?')} commits · {git.get('branch','?')} · {git.get('last_commit','?')}")

            files = scan['file_count']
            lines.append(f"檔案：共 {files.get('total',0)} 個")

            issues = scan.get('issues', [])
            if issues:
                lines.append(f"\n⚠ 發現 {len(issues)} 個問題：")
                for iss in issues:
                    sev   = iss['severity']
                    color = RED if sev == 'high' else YELLOW
                    lines.append(f"  {color}[{sev}]{RESET} {iss['issue']}")
                    lines.append(f"         → {iss['fix']}")

        return "\n".join(lines)
