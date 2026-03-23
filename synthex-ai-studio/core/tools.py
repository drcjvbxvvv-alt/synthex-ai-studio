"""
SYNTHEX Tool Engine
每個 Agent 可調用的真實工具集 — 檔案系統、終端、搜尋
包含安全控制：危險操作前確認、危險命令封鎖
"""

import os
import re
import json
import stat
import shlex
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
GRAY   = "\033[90m"

# ── 危險指令黑名單 ────────────────────────────────────────────
BLOCKED_PATTERNS = [
    r"\brm\s+-rf\s+/",        # rm -rf /
    r"\bdd\b.*of=/dev/",      # dd to device
    r"\bmkfs\b",               # format disk
    r":\(\)\{.*\}",            # fork bomb
    r"\bcurl\b.*\|\s*bash",   # curl | bash
    r"\bwget\b.*\|\s*sh",     # wget | sh
    r">\s*/dev/sd[a-z]",      # write to disk
    r"\bchmod\s+777\s+/",     # chmod 777 /
    r"\bsudo\s+rm",            # sudo rm
]

# ── 需要確認的操作 ─────────────────────────────────────────────
CONFIRM_PATTERNS = [
    r"\brm\b(?!\s+-rf\s+/)",   # rm (non-root)
    r"\brmdir\b",
    r"\bdrop\s+table\b",        # SQL drop
    r"\btruncate\b",
]


def _is_blocked(cmd: str) -> bool:
    for pat in BLOCKED_PATTERNS:
        if re.search(pat, cmd, re.IGNORECASE):
            return True
    return False


def _needs_confirm(cmd: str) -> bool:
    for pat in CONFIRM_PATTERNS:
        if re.search(pat, cmd, re.IGNORECASE):
            return True
    return False


def _fmt_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


# ══════════════════════════════════════════════════════════════
#  TOOL DEFINITIONS  (Anthropic tool_use format)
# ══════════════════════════════════════════════════════════════

# 所有可用工具的完整定義
ALL_TOOL_DEFS = [
    {
        "name": "read_file",
        "description": "讀取檔案內容。支援文字檔案（程式碼、設定檔、文件等）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "檔案路徑（相對或絕對）"},
                "start_line": {"type": "integer", "description": "起始行號（選填，預設從頭讀）"},
                "end_line":   {"type": "integer", "description": "結束行號（選填，預設讀到尾）"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "寫入或覆寫檔案。自動建立父目錄。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "目標檔案路徑"},
                "content": {"type": "string", "description": "要寫入的完整內容"},
                "mode":    {"type": "string", "description": "'overwrite'（預設）或 'append'"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "列出目錄內容，包含檔案大小和修改時間。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":      {"type": "string", "description": "目錄路徑，預設為當前目錄"},
                "recursive": {"type": "boolean", "description": "是否遞迴列出（預設 false）"},
                "pattern":   {"type": "string",  "description": "過濾 glob pattern，例如 '*.py'"},
            },
            "required": [],
        },
    },
    {
        "name": "run_command",
        "description": "執行 shell 命令。會顯示輸出並回傳結果。危險命令會被封鎖。",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string",  "description": "要執行的 shell 命令"},
                "cwd":     {"type": "string",  "description": "執行目錄（預設為當前工作目錄）"},
                "timeout": {"type": "integer", "description": "超時秒數（預設 60）"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "search_files",
        "description": "在檔案中搜尋文字（類似 grep）。回傳含有關鍵字的行。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern":   {"type": "string", "description": "搜尋的文字或正規表達式"},
                "path":      {"type": "string", "description": "搜尋的目錄或檔案（預設當前目錄）"},
                "file_glob": {"type": "string", "description": "限定檔案類型，例如 '*.py'"},
                "max_results":{"type": "integer","description": "最多回傳幾筆結果（預設 20）"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "move_file",
        "description": "移動或重命名檔案/目錄。",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "來源路徑"},
                "dest":   {"type": "string", "description": "目標路徑"},
            },
            "required": ["source", "dest"],
        },
    },
    {
        "name": "delete_file",
        "description": "刪除檔案或目錄（刪除前會要求確認）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":      {"type": "string",  "description": "要刪除的路徑"},
                "recursive": {"type": "boolean", "description": "是否遞迴刪除目錄（預設 false）"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "get_project_info",
        "description": "取得當前專案的基本資訊：目錄結構、語言、主要設定檔。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "專案根目錄（預設當前目錄）"},
            },
            "required": [],
        },
    },
]


# ── 角色專用工具集 ─────────────────────────────────────────────
ROLE_TOOLS = {
    "default":     [t["name"] for t in ALL_TOOL_DEFS],  # 所有工具
    "exec":        ["read_file", "list_dir", "get_project_info", "search_files"],
    "product":     ["read_file", "write_file", "list_dir", "search_files"],
    "biz":         ["read_file", "write_file", "list_dir", "search_files"],
    "qa":          [t["name"] for t in ALL_TOOL_DEFS],  # QA 需要全套
    "devops":      [t["name"] for t in ALL_TOOL_DEFS],
    "engineering": [t["name"] for t in ALL_TOOL_DEFS],
    "ai_data":     [t["name"] for t in ALL_TOOL_DEFS],
}


def get_tools_for_role(role: str) -> list:
    """取得特定角色的工具定義列表"""
    allowed = ROLE_TOOLS.get(role, ROLE_TOOLS["default"])
    return [t for t in ALL_TOOL_DEFS if t["name"] in allowed]


# ══════════════════════════════════════════════════════════════
#  TOOL EXECUTOR
# ══════════════════════════════════════════════════════════════

class ToolExecutor:
    """執行 Agent 請求的工具，處理安全檢查和輸出格式化"""

    def __init__(self, workdir: str = None, auto_confirm: bool = False):
        self.workdir = Path(workdir) if workdir else Path.cwd()
        self.auto_confirm = auto_confirm

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """分派並執行工具，回傳字串結果"""
        handlers = {
            "read_file":       self._read_file,
            "write_file":      self._write_file,
            "list_dir":        self._list_dir,
            "run_command":     self._run_command,
            "search_files":    self._search_files,
            "move_file":       self._move_file,
            "delete_file":     self._delete_file,
            "get_project_info":self._get_project_info,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return f"[錯誤] 未知工具: {tool_name}"
        try:
            result = handler(**tool_input)
            return result
        except Exception as e:
            return f"[工具錯誤] {tool_name}: {e}"

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.workdir / p
        return p.resolve()

    # ── read_file ──────────────────────────────────────────────
    def _read_file(self, path: str, start_line: int = None, end_line: int = None) -> str:
        p = self._resolve(path)
        if not p.exists():
            return f"[錯誤] 檔案不存在: {path}"
        if not p.is_file():
            return f"[錯誤] 路徑不是檔案: {path}"
        size = p.stat().st_size
        if size > 1_000_000:
            return f"[警告] 檔案過大 ({_fmt_size(size)})，請使用 start_line/end_line 分段讀取"
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"[錯誤] 無法讀取: {e}"
        lines = text.splitlines()
        total = len(lines)
        if start_line or end_line:
            s = max(0, (start_line or 1) - 1)
            e = min(total, end_line or total)
            lines = lines[s:e]
            header = f"[{path}] 第 {s+1}~{e} 行 / 共 {total} 行\n"
        else:
            header = f"[{path}] 共 {total} 行 · {_fmt_size(size)}\n"
        numbered = "\n".join(f"{i+1:4d}  {l}" for i, l in enumerate(lines))
        return header + numbered

    # ── write_file ─────────────────────────────────────────────
    def _write_file(self, path: str, content: str, mode: str = "overwrite") -> str:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        if mode == "append":
            with open(p, "a", encoding="utf-8") as f:
                f.write(content)
            action = "追加至"
        else:
            p.write_text(content, encoding="utf-8")
            action = "更新" if existed else "建立"
        lines = content.count("\n") + 1
        print(f"  {GREEN}✔ {action} {path}{RESET} {DIM}({lines} 行, {_fmt_size(len(content.encode()))}){RESET}")
        return f"[成功] {action} {path} · {lines} 行 · {_fmt_size(len(content.encode()))}"

    # ── list_dir ───────────────────────────────────────────────
    def _list_dir(self, path: str = ".", recursive: bool = False, pattern: str = None) -> str:
        p = self._resolve(path)
        if not p.exists():
            return f"[錯誤] 路徑不存在: {path}"
        if not p.is_dir():
            return f"[錯誤] 不是目錄: {path}"

        lines = [f"📁 {p}\n"]
        SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache",
                ".pytest_cache", "dist", "build", ".DS_Store"}

        def _walk(d: Path, prefix: str = "", depth: int = 0):
            if depth > 5:
                return
            try:
                entries = sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            except PermissionError:
                return
            for entry in entries:
                if entry.name in SKIP or entry.name.startswith("."):
                    continue
                if pattern:
                    import fnmatch
                    if entry.is_file() and not fnmatch.fnmatch(entry.name, pattern):
                        if not recursive:
                            continue
                is_last = entry == entries[-1]
                connector = "└── " if is_last else "├── "
                if entry.is_dir():
                    lines.append(f"{prefix}{connector}📁 {entry.name}/")
                    if recursive:
                        ext = "    " if is_last else "│   "
                        _walk(entry, prefix + ext, depth + 1)
                else:
                    sz = _fmt_size(entry.stat().st_size)
                    lines.append(f"{prefix}{connector}{entry.name}  {DIM}({sz}){RESET}")

        _walk(p)
        return "\n".join(lines)

    # ── run_command ────────────────────────────────────────────
    def _run_command(self, command: str, cwd: str = None, timeout: int = 60) -> str:
        if _is_blocked(command):
            return f"[封鎖] 危險命令被阻止: {command}"

        if not self.auto_confirm and _needs_confirm(command):
            print(f"\n  {YELLOW}⚠ 確認執行：{BOLD}{command}{RESET}")
            ans = input("  確定執行? (y/N) ").strip().lower()
            if ans != "y":
                return "[取消] 使用者取消執行"

        work = Path(cwd).resolve() if cwd else self.workdir
        print(f"  {CYAN}$ {command}{RESET}  {DIM}(在 {work}){RESET}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=work,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out  = result.stdout.strip()
            err  = result.stderr.strip()
            code = result.returncode

            parts = []
            if out:
                parts.append(out)
                # echo to terminal
                for line in out.splitlines()[-30:]:
                    print(f"  {DIM}{line}{RESET}")
            if err:
                parts.append(f"[stderr]\n{err}")
                for line in err.splitlines()[-10:]:
                    print(f"  {YELLOW}{line}{RESET}")

            status = f"[exit {code}]"
            if code == 0:
                print(f"  {GREEN}✔ 命令完成{RESET}")
            else:
                print(f"  {YELLOW}⚠ exit code {code}{RESET}")

            return "\n".join(parts) + f"\n{status}" if parts else status

        except subprocess.TimeoutExpired:
            return f"[超時] 命令執行超過 {timeout} 秒"
        except Exception as e:
            return f"[錯誤] {e}"

    # ── search_files ───────────────────────────────────────────
    def _search_files(self, pattern: str, path: str = ".", file_glob: str = None, max_results: int = 20) -> str:
        import fnmatch
        p = self._resolve(path)
        SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv"}

        results = []
        try:
            pat_re = re.compile(pattern, re.IGNORECASE)
        except re.error:
            pat_re = re.compile(re.escape(pattern), re.IGNORECASE)

        def _search(d: Path):
            if len(results) >= max_results:
                return
            try:
                for entry in d.iterdir():
                    if entry.name in SKIP or entry.name.startswith("."):
                        continue
                    if entry.is_dir():
                        _search(entry)
                    elif entry.is_file():
                        if file_glob and not fnmatch.fnmatch(entry.name, file_glob):
                            continue
                        try:
                            text = entry.read_text(encoding="utf-8", errors="replace")
                            for i, line in enumerate(text.splitlines(), 1):
                                if pat_re.search(line):
                                    rel = entry.relative_to(p)
                                    results.append(f"{rel}:{i}  {line.strip()}")
                                    if len(results) >= max_results:
                                        return
                        except Exception:
                            pass
            except PermissionError:
                pass

        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if pat_re.search(line):
                        results.append(f"{p.name}:{i}  {line.strip()}")
            except Exception:
                pass
        else:
            _search(p)

        if not results:
            return f"[搜尋] 無結果: '{pattern}'"
        header = f"[搜尋] '{pattern}' — {len(results)} 筆結果:\n"
        return header + "\n".join(results)

    # ── move_file ──────────────────────────────────────────────
    def _move_file(self, source: str, dest: str) -> str:
        s = self._resolve(source)
        d = self._resolve(dest)
        if not s.exists():
            return f"[錯誤] 來源不存在: {source}"
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        print(f"  {GREEN}✔ 移動: {source} → {dest}{RESET}")
        return f"[成功] {source} → {dest}"

    # ── delete_file ────────────────────────────────────────────
    def _delete_file(self, path: str, recursive: bool = False) -> str:
        p = self._resolve(path)
        if not p.exists():
            return f"[錯誤] 路徑不存在: {path}"
        if not self.auto_confirm:
            print(f"\n  {RED}⚠ 即將刪除：{BOLD}{path}{RESET}")
            ans = input("  確定刪除? (y/N) ").strip().lower()
            if ans != "y":
                return "[取消] 使用者取消刪除"
        if p.is_dir():
            if not recursive:
                return f"[錯誤] {path} 是目錄，請加 recursive=true"
            shutil.rmtree(p)
        else:
            p.unlink()
        print(f"  {RED}✔ 已刪除: {path}{RESET}")
        return f"[成功] 已刪除 {path}"

    # ── get_project_info ───────────────────────────────────────
    def _get_project_info(self, path: str = ".") -> str:
        p = self._resolve(path)
        info = [f"📁 專案目錄: {p}\n"]

        # 偵測語言和框架
        indicators = {
            "package.json":     "Node.js / JavaScript",
            "tsconfig.json":    "+ TypeScript",
            "next.config.*":    "+ Next.js",
            "vite.config.*":    "+ Vite",
            "requirements.txt": "Python",
            "pyproject.toml":   "Python (pyproject)",
            "Cargo.toml":       "Rust",
            "go.mod":           "Go",
            "pom.xml":          "Java (Maven)",
            "build.gradle":     "Java/Kotlin (Gradle)",
            "Dockerfile":       "+ Docker",
            "docker-compose.*": "+ Docker Compose",
            ".github/workflows":"+ GitHub Actions",
            "k8s/":             "+ Kubernetes",
            "terraform/":       "+ Terraform",
        }
        found = []
        for fname, label in indicators.items():
            if "*" in fname:
                import glob
                matches = list(p.glob(fname))
                if matches:
                    found.append(f"  ✓ {label}  ({matches[0].name})")
            else:
                if (p / fname).exists():
                    found.append(f"  ✓ {label}")

        if found:
            info.append("🔍 偵測到的技術棧:\n" + "\n".join(found))

        # 統計檔案
        counts: dict = {}
        total_files = 0
        SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv"}
        try:
            for entry in p.rglob("*"):
                if any(s in entry.parts for s in SKIP):
                    continue
                if entry.is_file():
                    total_files += 1
                    ext = entry.suffix.lower() or "(no ext)"
                    counts[ext] = counts.get(ext, 0) + 1
        except Exception:
            pass

        if counts:
            top = sorted(counts.items(), key=lambda x: -x[1])[:8]
            info.append(f"\n📊 檔案統計 (共 {total_files} 個):")
            for ext, cnt in top:
                info.append(f"  {ext:12s} {cnt} 個")

        # 重要設定檔內容摘要
        key_files = ["README.md", "package.json", "requirements.txt", "pyproject.toml"]
        for fname in key_files:
            fp = p / fname
            if fp.exists():
                try:
                    content = fp.read_text(encoding="utf-8", errors="replace")[:500]
                    info.append(f"\n📄 {fname} (摘要):\n{content}")
                except Exception:
                    pass

        return "\n".join(info)
