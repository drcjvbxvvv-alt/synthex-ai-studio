"""
SYNTHEX Tool Engine
每個 Agent 可調用的真實工具集 — 檔案系統、終端、搜尋
包含安全控制：危險操作前確認、危險命令封鎖
"""

import os

# ── 安全命令執行 ────────────────────────────────────────────────
import shlex as _shlex, subprocess as _sub
MAX_CMD_OUTPUT_BYTES = 1_048_576   # 1MB
_REJECT_PATTERNS     = ["$(", "`", ";rm", "&&rm", "|rm", ">/dev", ">>/dev"]

def _safe_run(cmd, cwd, timeout=60, env=None):
    """shell=True 的安全替代方案：argv + 輸出截斷 + 危險字元過濾"""
    from pathlib import Path
    safe_cwd = str(Path(cwd).resolve())
    timeout  = max(1, min(300, int(timeout)))
    if isinstance(cmd, str):
        for pat in _REJECT_PATTERNS:
            if pat.replace(" ","") in cmd.replace(" ",""):
                return {"stdout":"","stderr":f"指令含危險字元 {pat}","returncode":126,"output":""}
        try:
            argv = _shlex.split(cmd)
        except ValueError as e:
            return {"stdout":"","stderr":f"指令解析失敗:{e}","returncode":1,"output":""}
    else:
        argv = list(cmd)
    try:
        r = _sub.run(argv, shell=False, cwd=safe_cwd, capture_output=True,
                     text=True, timeout=timeout, env=env)
        out = (r.stdout + r.stderr)
        if len(out.encode("utf-8","replace")) > MAX_CMD_OUTPUT_BYTES:
            out = out[:MAX_CMD_OUTPUT_BYTES//4] + "\n[輸出已截斷]"
        return {"stdout":r.stdout[:MAX_CMD_OUTPUT_BYTES//4],
                "stderr":r.stderr[:MAX_CMD_OUTPUT_BYTES//8],
                "output":out, "returncode":r.returncode}
    except _sub.TimeoutExpired:
        return {"stdout":"","stderr":f"超時({timeout}s)","returncode":124,"output":""}
    except FileNotFoundError:
        name = argv[0] if argv else "?"
        return {"stdout":"","stderr":f"命令不存在:{name}","returncode":127,"output":""}
    except Exception as e:
        return {"stdout":"","stderr":str(e)[:200],"returncode":1,"output":""}


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
    r"\bcurl\b.*\|\s*sh\b",   # curl | sh
    r"\bwget\b.*\|\s*sh\b",   # wget | sh
    r"\bwget\b.*\|\s*bash",   # wget | bash  ← 新增
    r"\bfetch\b.*\|\s*bash",  # fetch | bash
    r">\s*/dev/sd[a-z]",      # write to disk
    r"\bchmod\s+777\s+/",     # chmod 777 /
    r"\bsudo\s+rm",            # sudo rm
    r"\beval\s+\$\(",          # eval $(...)  ← 新增：動態執行
    r"\bbase64\b.*\|\s*bash", # base64 decode | bash  ← 新增
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
        # 防止路徑穿越攻擊：解析後必須在 workdir 內
        p = Path(path)
        if ".." in p.parts:
            raise PermissionError(f"[安全] 禁止路徑穿越: {path!r}")
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
            result = _safe_run(command, cwd=work, timeout=timeout)
            # _safe_run 回傳 dict，用 .get() 存取

            out  = result.get('stdout','').strip()
            err  = result.get('stderr','').strip()
            code = result.get('returncode',0)

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


# ══════════════════════════════════════════════════════════════
#  P0-2：Secret 掃描工具
#  P1-2：系統工程工具（韌體編譯、OpenOCD、效能分析）
# ══════════════════════════════════════════════════════════════

SECURITY_TOOL_DEFS = [
    {
        "name": "secret_scan",
        "description": "掃描專案中的 secret 洩漏（API key、密碼、token 誤提交到 git）。使用 gitleaks。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":   {"type": "string",  "description": "掃描路徑（預設當前目錄）"},
                "staged": {"type": "boolean", "description": "只掃描 staged 的變更（pre-commit 用）"},
            },
            "required": [],
        },
    },
    {
        "name": "sast_scan",
        "description": "靜態應用安全測試（SAST），用 Semgrep 掃描程式碼中的安全問題。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":   {"type": "string", "description": "掃描路徑"},
                "config": {"type": "string", "description": "規則集：auto、p/javascript、p/typescript、p/python（預設 auto）"},
            },
            "required": [],
        },
    },
    {
        "name": "dependency_audit",
        "description": "掃描依賴套件的已知漏洞（npm audit 或 pip-audit）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":     {"type": "string", "description": "專案路徑"},
                "fix":      {"type": "boolean","description": "嘗試自動修復（預設 false）"},
                "severity": {"type": "string", "description": "只顯示此嚴重等級以上：low/moderate/high/critical"},
            },
            "required": [],
        },
    },
]

SYSTEMS_TOOL_DEFS = [
    {
        "name": "firmware_build",
        "description": "編譯韌體專案（支援 CMake/Make/PlatformIO/Zephyr West/ESP-IDF）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "build_system": {"type": "string",
                                 "enum": ["cmake", "make", "platformio", "west", "espidf", "cargo"],
                                 "description": "建置系統"},
                "target":       {"type": "string",  "description": "建置目標（cmake：target name；west：board name）"},
                "cwd":          {"type": "string",  "description": "專案目錄"},
                "clean":        {"type": "boolean", "description": "先 clean 再建置（預設 false）"},
                "jobs":         {"type": "integer", "description": "並行編譯數（預設 CPU 核心數）"},
            },
            "required": ["build_system"],
        },
    },
    {
        "name": "firmware_flash",
        "description": "燒錄韌體到目標設備（OpenOCD 或 JLink 或 esptool）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool":      {"type": "string", "enum": ["openocd", "jlink", "esptool", "west", "pyocd"],
                              "description": "燒錄工具"},
                "binary":    {"type": "string", "description": "韌體二進位檔路徑（.bin/.hex/.elf）"},
                "target":    {"type": "string", "description": "目標晶片（OpenOCD 設定，例如 stm32f4x）"},
                "interface": {"type": "string", "description": "除錯介面（stlink、jlink、cmsis-dap）"},
                "port":      {"type": "string", "description": "串口（esptool 用，例如 /dev/ttyUSB0）"},
                "baud":      {"type": "integer","description": "燒錄速率（esptool 用）"},
            },
            "required": ["tool", "binary"],
        },
    },
    {
        "name": "serial_monitor",
        "description": "開啟串口監視器，讀取韌體輸出（限時讀取，不持續佔用）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "port":    {"type": "string",  "description": "串口路徑（/dev/ttyUSB0、/dev/cu.usbserial 等）"},
                "baud":    {"type": "integer", "description": "鮑率（預設 115200）"},
                "timeout": {"type": "integer", "description": "讀取秒數（預設 5）"},
            },
            "required": ["port"],
        },
    },
    {
        "name": "perf_profile",
        "description": "對 Linux 程序執行效能分析（perf record + flamegraph）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pid":      {"type": "integer", "description": "目標 PID（-1 表示系統全局）"},
                "command":  {"type": "string",  "description": "或直接執行命令（例如 './my_program arg1'）"},
                "duration": {"type": "integer", "description": "採樣秒數（預設 10）"},
                "output":   {"type": "string",  "description": "輸出目錄（預設 /tmp/perf_output）"},
            },
            "required": [],
        },
    },
    {
        "name": "memory_check",
        "description": "執行 Valgrind 記憶體錯誤檢查（記憶體洩漏、越界存取）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要檢查的命令（例如 './my_program'）"},
                "cwd":     {"type": "string",  "description": "執行目錄"},
                "tool":    {"type": "string",  "description": "valgrind tool：memcheck、massif、callgrind（預設 memcheck）"},
            },
            "required": ["command"],
        },
    },
]


class SecurityToolExecutor:
    """P0-2：安全掃描工具執行器"""

    def __init__(self, workdir: str, auto_confirm: bool = False):
        self.workdir      = workdir
        self.auto_confirm = auto_confirm

    def execute(self, tool_name: str, tool_input: dict) -> str:
        import subprocess
        from pathlib import Path

        cwd = tool_input.get("path", self.workdir) or self.workdir

        if tool_name == "secret_scan":
            return self._secret_scan(cwd, tool_input.get("staged", False))
        elif tool_name == "sast_scan":
            return self._sast_scan(cwd, tool_input.get("config", "auto"))
        elif tool_name == "dependency_audit":
            return self._dep_audit(cwd, tool_input.get("fix", False),
                                   tool_input.get("severity", "moderate"))
        return f"[錯誤] 未知工具：{tool_name}"

    def _run(self, cmd: str, cwd: str, timeout: int = 60) -> str:
        import subprocess
        print(f"  \033[96m$ {cmd}\033[0m")
        try:
            r = _safe_run(cmd, cwd=cwd, timeout=timeout)
            # _safe_run 回傳 dict，用 .get() 存取

            out = (r.get('stdout','') + r.get('stderr','')).strip()
            return f"{out}\n[exit {r.get('returncode',0)}]"
        except subprocess.TimeoutExpired:
            return f"[超時]"
        except Exception as e:
            return f"[錯誤] {e}"

    def _secret_scan(self, cwd: str, staged: bool) -> str:
        # 確認 gitleaks 可用
        check = self._run("which gitleaks", cwd, 3)
        if "exit 1" in check or "not found" in check.lower():
            # 嘗試安裝
            print("  \033[93m⚠ gitleaks 未安裝，嘗試安裝...\033[0m")
            self._run("brew install gitleaks 2>/dev/null || "
                      "curl -s https://raw.githubusercontent.com/gitleaks/gitleaks/main/scripts/install.sh | sh",
                      cwd, 30)

        flags = "--staged" if staged else "--no-git"
        result = self._run(f"gitleaks detect --source=. {flags} --verbose", cwd, 30)
        return f"[Secret 掃描]\n{result}"

    def _sast_scan(self, cwd: str, config: str) -> str:
        check = self._run("which semgrep", cwd, 3)
        if "exit 1" in check or "not found" in check.lower():
            self._run("pip install semgrep --break-system-packages -q", cwd, 60)

        result = self._run(
            f"semgrep --config={config} src/ --json --quiet 2>/dev/null | "
            "python3 -c \"import json,sys; d=json.load(sys.stdin); "
            "results=d.get('results',[]); "
            "print(f'發現 {len(results)} 個問題'); "
            "[print(f\\\"  [{r['extra']['severity']}] {r['path']}:{r['start']['line']} - {r['extra']['message']}\\\") for r in results[:20]]\"",
            cwd, 60
        )
        return f"[SAST 掃描 ({config})]\n{result}"

    def _dep_audit(self, cwd: str, fix: bool, severity: str) -> str:
        from pathlib import Path
        if (Path(cwd) / "package.json").exists():
            fix_flag = "--fix" if fix else ""
            result = self._run(f"npm audit {fix_flag} --audit-level={severity}", cwd, 30)
            return f"[依賴漏洞掃描 (npm)]\n{result}"
        elif (Path(cwd) / "requirements.txt").exists():
            check = self._run("which pip-audit", cwd, 3)
            if "exit 1" in check:
                self._run("pip install pip-audit --break-system-packages -q", cwd, 30)
            result = self._run("pip-audit", cwd, 30)
            return f"[依賴漏洞掃描 (pip)]\n{result}"
        return "[依賴漏洞掃描] 找不到 package.json 或 requirements.txt"


class SystemsToolExecutor:
    """P1-2：系統工程工具執行器"""

    def __init__(self, workdir: str):
        self.workdir = workdir

    def execute(self, tool_name: str, tool_input: dict) -> str:
        import subprocess, os
        from pathlib import Path

        if tool_name == "firmware_build":
            return self._build(**tool_input)
        elif tool_name == "firmware_flash":
            return self._flash(**tool_input)
        elif tool_name == "serial_monitor":
            return self._serial(**tool_input)
        elif tool_name == "perf_profile":
            return self._perf(**tool_input)
        elif tool_name == "memory_check":
            return self._memcheck(**tool_input)
        return f"[錯誤] 未知工具：{tool_name}"

    def _run(self, cmd: str, cwd: str = None, timeout: int = 300) -> str:
        import subprocess
        work = cwd or self.workdir
        print(f"  \033[96m$ {cmd}\033[0m  \033[2m(在 {work})\033[0m")
        try:
            r = _safe_run(cmd, cwd=work, timeout=timeout)
            # _safe_run 回傳 dict，用 .get() 存取

            out = (r.get('stdout','') + r.get('stderr','')).strip()
            for line in out.splitlines()[-20:]:
                print(f"  \033[2m{line}\033[0m")
            icon = "\033[92m✔\033[0m" if r.get('returncode',0) == 0 else f"\033[93m⚠ exit {r.get('returncode',0)}\033[0m"
            print(f"  {icon}")
            return f"{out}\n[exit {r.get('returncode',0)}]"
        except subprocess.TimeoutExpired:
            return f"[超時 >{timeout}s]"
        except Exception as e:
            return f"[錯誤] {e}"

    def _build(self, build_system: str, target: str = "", cwd: str = None,
               clean: bool = False, jobs: int = None) -> str:
        import os
        work  = cwd or self.workdir
        cores = jobs or os.cpu_count() or 4

        cmds = {
            "cmake":      f"{'cmake --build build --target clean && ' if clean else ''}cmake -B build -S . && cmake --build build -j{cores} {'--target ' + target if target else ''}",
            "make":       f"{'make clean && ' if clean else ''}make {target} -j{cores}",
            "platformio": f"pio run {'--target clean && pio run ' if clean else ''}{'-e ' + target if target else ''}",
            "west":       f"west build {'-p always ' if clean else ''}{'-b ' + target if target else ''}",
            "espidf":     f"{'idf.py fullclean && ' if clean else ''}idf.py {'build' if not target else target}",
            "cargo":      f"cargo build {'--release' if target == 'release' else ''} --target {target if target and '/' in target else 'thumbv7em-none-eabihf'}",
        }
        cmd = cmds.get(build_system, f"make {target}")
        return f"[韌體建置 ({build_system})]\n{self._run(cmd, work, 600)}"

    def _flash(self, tool: str, binary: str, target: str = "",
               interface: str = "stlink", port: str = "", baud: int = 460800) -> str:
        cmds = {
            "openocd": f"openocd -f interface/{interface}.cfg -f target/{target}.cfg "
                       f"-c 'program {binary} verify reset exit'",
            "jlink":   f"JLinkExe -commandfile /tmp/jlink_flash.jlink",
            "esptool": f"esptool.py --chip auto --port {port} --baud {baud} write_flash 0x0 {binary}",
            "west":    f"west flash --bin-file {binary}",
            "pyocd":   f"pyocd flash -t {target} {binary}",
        }
        cmd = cmds.get(tool, f"# 不支援的工具：{tool}")
        return f"[韌體燒錄 ({tool})]\n{self._run(cmd, self.workdir, 120)}"

    def _serial(self, port: str, baud: int = 115200, timeout: int = 5) -> str:
        cmd = f"timeout {timeout} python3 -c \"\nimport serial, sys, time\nser = serial.Serial('{port}', {baud}, timeout=1)\nstart = time.time()\nlines = []\nwhile time.time() - start < {timeout}:\n    line = ser.readline().decode('utf-8', errors='replace').strip()\n    if line:\n        lines.append(line)\n        print(line)\nser.close()\n\""
        return f"[串口監視 {port}@{baud}]\n{self._run(cmd, self.workdir, timeout + 3)}"

    def _perf(self, pid: int = -1, command: str = "", duration: int = 10,
              output: str = "/tmp/perf_output") -> str:
        import subprocess
        from pathlib import Path
        Path(output).mkdir(parents=True, exist_ok=True)

        if command:
            cmd = f"perf record -g -F 999 -o {output}/perf.data -- {command}"
        elif pid > 0:
            cmd = f"perf record -g -F 999 -p {pid} -o {output}/perf.data sleep {duration}"
        else:
            cmd = f"perf record -g -F 999 -a -o {output}/perf.data sleep {duration}"

        build_result = self._run(cmd, self.workdir, duration + 30)

        # 產生 flamegraph
        flamegraph_cmd = (
            f"perf script -i {output}/perf.data | "
            f"stackcollapse-perf.pl | flamegraph.pl > {output}/flamegraph.svg"
        )
        fg_result = self._run(flamegraph_cmd, self.workdir, 30)

        report = self._run(f"perf report -i {output}/perf.data --stdio --no-pager 2>&1 | head -40",
                           self.workdir, 30)

        return f"[效能分析]\n建置：{build_result}\nFlamegraph：{fg_result}\n報告前 40 行：\n{report}\n\n輸出目錄：{output}"

    def _memcheck(self, command: str, cwd: str = None, tool: str = "memcheck") -> str:
        work = cwd or self.workdir
        cmd  = f"valgrind --tool={tool} --leak-check=full --show-leak-kinds=all --track-origins=yes {command}"
        return f"[Valgrind {tool}]\n{self._run(cmd, work, 300)}"


# 更新 ALL_TOOL_DEFS（讓 Agent 可以使用新工具）
ALL_TOOL_DEFS.extend(SECURITY_TOOL_DEFS)
ALL_TOOL_DEFS.extend(SYSTEMS_TOOL_DEFS)

# 更新角色工具集
ROLE_TOOLS["devops"].extend([t["name"] for t in SECURITY_TOOL_DEFS])
ROLE_TOOLS["qa"].extend([t["name"] for t in SECURITY_TOOL_DEFS])
ROLE_TOOLS["systems"] = [t["name"] for t in ALL_TOOL_DEFS]  # 系統工程部門有全套


# ══════════════════════════════════════════════════════════════
#  P0-2：高頻必要工具（結構化版本）
#  取代散落的 run_command 呼叫，提供型別安全和結構化輸出
# ══════════════════════════════════════════════════════════════

WEBDEV_TOOL_DEFS = [
    {
        "name": "git_commit",
        "description": "執行 git add 和 git commit，帶有格式化的 commit message。",
        "input_schema": {
            "type": "object",
            "properties": {
                "message":  {"type": "string",  "description": "commit message（會自動格式化）"},
                "add_all":  {"type": "boolean", "description": "是否 git add -A（預設 true）"},
                "files":    {"type": "array",   "items": {"type": "string"},
                             "description": "指定要 add 的檔案路徑（add_all=false 時使用）"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "git_push",
        "description": "執行 git push，可以指定 remote 和 branch。",
        "input_schema": {
            "type": "object",
            "properties": {
                "remote": {"type": "string", "description": "remote 名稱（預設 origin）"},
                "branch": {"type": "string", "description": "branch 名稱（預設當前 branch）"},
                "force":  {"type": "boolean","description": "是否 force push（謹慎使用）"},
            },
            "required": [],
        },
    },
    {
        "name": "npm_install",
        "description": "安裝 npm 套件，支援 --save-dev、指定版本、多套件同時安裝。",
        "input_schema": {
            "type": "object",
            "properties": {
                "packages":  {"type": "array", "items": {"type": "string"},
                              "description": "套件名稱列表，例如 ['react', 'typescript@5.0']"},
                "dev":       {"type": "boolean", "description": "是否安裝為 devDependency"},
                "exact":     {"type": "boolean", "description": "是否安裝精確版本（--save-exact）"},
                "clean":     {"type": "boolean", "description": "是否先 rm -rf node_modules 再安裝"},
            },
            "required": ["packages"],
        },
    },
    {
        "name": "run_tests",
        "description": "執行測試套件，支援 vitest、jest、pytest、playwright。自動解析測試結果。",
        "input_schema": {
            "type": "object",
            "properties": {
                "framework": {"type": "string",
                              "enum": ["vitest", "jest", "pytest", "playwright", "auto"],
                              "description": "測試框架（auto 自動偵測）"},
                "pattern":   {"type": "string",  "description": "只跑符合此模式的測試"},
                "coverage":  {"type": "boolean", "description": "是否產生覆蓋率報告"},
                "watch":     {"type": "boolean", "description": "是否進入 watch 模式"},
                "bail":      {"type": "boolean", "description": "第一個失敗就停止"},
            },
            "required": [],
        },
    },
    {
        "name": "fetch_url",
        "description": "發送 HTTP 請求到指定 URL，支援 GET/POST/PUT/DELETE，回傳回應內容。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url":     {"type": "string",  "description": "目標 URL"},
                "method":  {"type": "string",  "enum": ["GET","POST","PUT","PATCH","DELETE"],
                            "description": "HTTP 方法（預設 GET）"},
                "headers": {"type": "object",  "description": "請求標頭"},
                "body":    {"type": "object",  "description": "請求 body（POST/PUT 用）"},
                "timeout": {"type": "integer", "description": "超時秒數（預設 10）"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "docker_build",
        "description": "建置 Docker 映像，支援指定 Dockerfile 和 build args。",
        "input_schema": {
            "type": "object",
            "properties": {
                "tag":        {"type": "string",  "description": "映像標籤，例如 myapp:latest"},
                "dockerfile": {"type": "string",  "description": "Dockerfile 路徑（預設 ./Dockerfile）"},
                "build_args": {"type": "object",  "description": "建置參數"},
                "no_cache":   {"type": "boolean", "description": "不使用快取"},
                "platform":   {"type": "string",  "description": "目標平台，例如 linux/amd64"},
            },
            "required": ["tag"],
        },
    },
    {
        "name": "send_notification",
        "description": "發送通知（Slack webhook 或 Email），用於重要事件（部署完成、錯誤告警）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel":  {"type": "string",
                             "enum": ["slack", "email"],
                             "description": "通知管道"},
                "message":  {"type": "string", "description": "通知內容"},
                "subject":  {"type": "string", "description": "主旨（email 用）"},
                "urgency":  {"type": "string",
                             "enum": ["info", "warning", "critical"],
                             "description": "緊急程度（影響顯示格式）"},
            },
            "required": ["channel", "message"],
        },
    },
    {
        "name": "lint_and_typecheck",
        "description": "執行 ESLint 和 TypeScript 型別檢查，回傳結構化的錯誤清單。",
        "input_schema": {
            "type": "object",
            "properties": {
                "fix":       {"type": "boolean", "description": "是否自動修復可修復的問題"},
                "strict":    {"type": "boolean", "description": "使用嚴格模式"},
                "path":      {"type": "string",  "description": "只檢查特定路徑"},
            },
            "required": [],
        },
    },
]


class WebDevToolExecutor(ToolExecutor):
    """擴充版工具執行器，加入高頻 Web 開發工具"""

    def execute(self, tool_name: str, tool_input: dict) -> str:
        # 優先處理新工具，其他交給父類別
        handlers = {
            "git_commit":       self._git_commit,
            "git_push":         self._git_push,
            "npm_install":      self._npm_install,
            "run_tests":        self._run_tests,
            "fetch_url":        self._fetch_url,
            "docker_build":     self._docker_build,
            "send_notification":self._send_notification,
            "lint_and_typecheck":self._lint_and_typecheck,
        }
        if tool_name in handlers:
            return handlers[tool_name](tool_input)
        return super().execute(tool_name, tool_input)

    def _sh(self, cmd: str, timeout: int = 120) -> dict:
        import subprocess
        r = _safe_run(cmd, cwd=self, timeout=timeout)
        # _safe_run 回傳 dict，用 .get() 存取

        return {"stdout": r.get('stdout','').strip(), "stderr": r.get('stderr','').strip(),
                "returncode": r.get('returncode',0), "success": r.get('returncode',0) == 0}

    def _git_commit(self, inp: dict) -> str:
        msg      = inp["message"]
        add_all  = inp.get("add_all", True)
        files    = inp.get("files", [])

        if add_all:
            self._sh("git add -A")
        elif files:
            self._sh(f"git add {' '.join(files)}")

        result = self._sh(f'git commit -m "{msg}"')
        if result["success"]:
            sha = self._sh("git rev-parse --short HEAD")["stdout"]
            return f"✔ Committed: {sha} — {msg}"
        if "nothing to commit" in result["stdout"] + result["stderr"]:
            return "ℹ 沒有變更需要提交"
        return f"✖ commit 失敗：{result['stderr']}"

    def _git_push(self, inp: dict) -> str:
        remote = inp.get("remote", "origin")
        branch = inp.get("branch", "")
        force  = "--force" if inp.get("force") else ""

        if not branch:
            branch = self._sh("git branch --show-current")["stdout"]

        result = self._sh(f"git push {force} {remote} {branch}")
        if result["success"]:
            return f"✔ Pushed to {remote}/{branch}"
        return f"✖ push 失敗：{result['stderr']}"

    def _npm_install(self, inp: dict) -> str:
        packages = inp["packages"]
        flags    = []
        if inp.get("dev"):   flags.append("--save-dev")
        if inp.get("exact"): flags.append("--save-exact")

        if inp.get("clean"):
            self._sh("rm -rf node_modules package-lock.json")

        pkg_str = " ".join(packages)
        flag_str = " ".join(flags)
        result   = self._sh(f"npm install {flag_str} {pkg_str}", timeout=180)

        if result["success"]:
            return f"✔ 安裝成功：{pkg_str}"
        return f"✖ 安裝失敗：{result['stderr'][-500:]}"

    def _run_tests(self, inp: dict) -> str:
        import json as _json
        from pathlib import Path

        framework = inp.get("framework", "auto")
        pattern   = inp.get("pattern", "")
        coverage  = inp.get("coverage", False)
        bail      = inp.get("bail", False)

        if framework == "auto":
            p = Path(self.workdir)
            if (p / "vitest.config.ts").exists() or (p / "vitest.config.js").exists():
                framework = "vitest"
            elif (p / "jest.config.js").exists():
                framework = "jest"
            elif (p / "requirements.txt").exists():
                framework = "pytest"
            elif (p / "playwright.config.ts").exists():
                framework = "playwright"
            else:
                framework = "vitest"  # Next.js 預設

        cmds = {
            "vitest":     f"npx vitest run {'--coverage' if coverage else ''} {pattern}",
            "jest":       f"npx jest {'--coverage' if coverage else ''} {'--bail' if bail else ''} {pattern}",
            "pytest":     f"python -m pytest -v {'--tb=short' if bail else ''} {pattern}",
            "playwright": f"npx playwright test {pattern}",
        }
        cmd    = cmds.get(framework, cmds["vitest"])
        result = self._sh(cmd, timeout=300)

        # 解析結果
        output = result["stdout"] + result["stderr"]
        lines  = output.splitlines()

        # 尋找測試結果摘要
        summary = []
        for line in lines:
            if any(k in line.lower() for k in ["pass", "fail", "error", "test", "suite", "✓", "✗", "×"]):
                summary.append(line)

        status = "✔ 測試通過" if result["success"] else "✖ 測試失敗"
        return (status + " (" + framework + ")\n" + "\n".join(summary[-20:] if summary else ["(無輸出)"]))

    def _fetch_url(self, inp: dict) -> str:
        import urllib.request, urllib.parse, json as _json

        url = inp["url"]
        # 安全驗證：scheme + SSRF 防護 + 長度限制
        if not isinstance(url, str) or not url.strip():
            return "✖ URL 不能為空"
        url = url.strip()[:2048]
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            return f"✖ 不允許的 URL scheme：{parsed.scheme!r}（只允許 http/https）"
        host = parsed.hostname or ""
        _blocked = {"localhost","127.0.0.1","0.0.0.0","169.254.169.254","metadata.google.internal"}
        if host.lower() in _blocked:
            return f"✖ 不允許存取此主機：{host!r}"
        if re.match(r"^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)", host):
            return f"✖ 不允許存取私有 IP：{host!r}"

        method  = inp.get("method", "GET").upper()
        headers = inp.get("headers", {})
        body    = inp.get("body")
        timeout = inp.get("timeout", 10)

        req = urllib.request.Request(url, method=method)
        for k, v in headers.items():
            req.add_header(k, v)

        if body:
            data = _json.dumps(body).encode()
            req.add_header("Content-Type", "application/json")
            req.data = data

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body    = resp.read().decode("utf-8", errors="replace")
                status  = resp.status
                return "HTTP " + str(status) + "\n" + body[:2000]
        except Exception as e:
            return f"✖ 請求失敗：{e}"

    def _docker_build(self, inp: dict) -> str:
        tag        = inp["tag"]
        dockerfile = inp.get("dockerfile", "Dockerfile")
        build_args = inp.get("build_args", {})
        no_cache   = "--no-cache" if inp.get("no_cache") else ""
        platform   = f"--platform {inp['platform']}" if inp.get("platform") else ""

        args_str = " ".join(f"--build-arg {k}={v}" for k, v in build_args.items())
        cmd      = f"docker build {no_cache} {platform} {args_str} -t {tag} -f {dockerfile} ."
        result   = self._sh(cmd, timeout=600)

        if result["success"]:
            return f"✔ Docker 映像建置成功：{tag}"
        return f"✖ 建置失敗：{result['stderr'][-500:]}"

    def _send_notification(self, inp: dict) -> str:
        import os, urllib.request, json as _json

        channel  = inp["channel"]
        message  = inp["message"]
        urgency  = inp.get("urgency", "info")

        emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(urgency, "ℹ️")
        text  = f"{emoji} {message}"

        if channel == "slack":
            webhook = os.environ.get("SLACK_WEBHOOK_URL")
            if not webhook:
                return "⚠ SLACK_WEBHOOK_URL 未設定，通知已跳過"
            try:
                data = _json.dumps({"text": text}).encode()
                req  = urllib.request.Request(webhook, data=data,
                       headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5)
                return f"✔ Slack 通知已發送（{urgency}）"
            except Exception as e:
                return f"✖ Slack 通知失敗：{e}"

        return f"⚠ 通知管道 {channel} 尚未設定"

    def _lint_and_typecheck(self, inp: dict) -> str:
        fix    = "--fix" if inp.get("fix") else ""
        path   = inp.get("path", ".")
        result_lint = self._sh(f"npx eslint {fix} {path} --format=compact", timeout=60)
        result_tsc  = self._sh("npx tsc --noEmit", timeout=60)

        output = []
        if result_lint["success"]:
            output.append("✔ ESLint：無錯誤")
        else:
            errors = [l for l in result_lint["stdout"].splitlines() if "error" in l.lower()]
            output.append("✖ ESLint：" + str(len(errors)) + " 個錯誤\n" + "\n".join(errors[:10]))

        if result_tsc["success"]:
            output.append("✔ TypeScript：無型別錯誤")
        else:
            ts_errors = result_tsc["stdout"].splitlines()[:15]
            output.append("✖ TypeScript：" + str(len(ts_errors)) + " 個錯誤\n" + "\n".join(ts_errors))

        return "\n".join(output)



# 加入工具定義到 ALL_TOOL_DEFS
ALL_TOOL_DEFS.extend(WEBDEV_TOOL_DEFS)

# 更新角色工具集
for dept in ["engineering", "devops", "qa"]:
    if dept in ROLE_TOOLS:
        ROLE_TOOLS[dept].extend([t["name"] for t in WEBDEV_TOOL_DEFS])

ROLE_TOOLS["webdev"] = [t["name"] for t in ALL_TOOL_DEFS]  # 全套工具給 webdev


# ══════════════════════════════════════════════════════════════
#  P0-1：補齊高頻必要工具
#  git / npm / test / fetch / search / docker / notify
# ══════════════════════════════════════════════════════════════

HIGH_FREQ_TOOL_DEFS = [
    {
        "name": "git_commit",
        "description": "執行 git add + commit，支援自動產生符合 Conventional Commits 格式的訊息。",
        "input_schema": {
            "type": "object",
            "properties": {
                "message":  {"type": "string",  "description": "commit 訊息（例：feat(auth): add JWT login）"},
                "files":    {"type": "array",   "items": {"type": "string"},
                             "description": "要加入的檔案列表，空陣列代表 git add -A"},
                "push":     {"type": "boolean", "description": "commit 後自動 push（預設 false）"},
                "branch":   {"type": "string",  "description": "push 到哪個分支（預設當前分支）"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "git_push",
        "description": "Push 到遠端，支援設定分支和 force push。",
        "input_schema": {
            "type": "object",
            "properties": {
                "branch":  {"type": "string",  "description": "目標分支（預設當前分支）"},
                "remote":  {"type": "string",  "description": "遠端名稱（預設 origin）"},
                "force":   {"type": "boolean", "description": "是否 force push（危險！預設 false）"},
                "set_upstream": {"type": "boolean", "description": "設定 upstream（預設 false）"},
            },
            "required": [],
        },
    },
    {
        "name": "npm_run",
        "description": "執行 package.json 中的 script（dev/build/test/lint/typecheck 等），回傳結果和 exit code。",
        "input_schema": {
            "type": "object",
            "properties": {
                "script":   {"type": "string",  "description": "要執行的 script 名稱（例：build、test、lint）"},
                "args":     {"type": "array",   "items": {"type": "string"},
                             "description": "額外的 CLI 參數（例：['--run', '--coverage']）"},
                "timeout":  {"type": "integer", "description": "超時秒數（預設 300）"},
            },
            "required": ["script"],
        },
    },
    {
        "name": "npm_install",
        "description": "安裝 npm 套件，支援 dev dependency 和指定版本。",
        "input_schema": {
            "type": "object",
            "properties": {
                "packages":  {"type": "array",   "items": {"type": "string"},
                              "description": "要安裝的套件列表，例：['react', 'typescript@5']"},
                "dev":        {"type": "boolean", "description": "安裝為 devDependency（預設 false）"},
                "save_exact": {"type": "boolean", "description": "固定版本號，不加 ^（預設 false）"},
                "ci":         {"type": "boolean", "description": "使用 npm ci 而非 npm install（預設 false）"},
            },
            "required": ["packages"],
        },
    },
    {
        "name": "run_tests",
        "description": "執行測試並回傳結構化結果（通過/失敗數、覆蓋率）。自動偵測測試框架（vitest/jest/pytest）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern":   {"type": "string",  "description": "測試檔案 glob（例：tests/**/*.test.ts）"},
                "coverage":  {"type": "boolean", "description": "是否產生覆蓋率報告（預設 false）"},
                "watch":     {"type": "boolean", "description": "watch 模式（預設 false）"},
                "timeout":   {"type": "integer", "description": "超時秒數（預設 120）"},
            },
            "required": [],
        },
    },
    {
        "name": "fetch_url",
        "description": "抓取 URL 的內容（HTML/JSON/文字），用於讀取文件、API 回應或網頁。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url":      {"type": "string",  "description": "要抓取的 URL"},
                "method":   {"type": "string",  "description": "HTTP 方法（預設 GET）"},
                "headers":  {"type": "object",  "description": "自訂 headers"},
                "body":     {"type": "string",  "description": "Request body（POST/PUT 用）"},
                "timeout":  {"type": "integer", "description": "超時秒數（預設 10）"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "search_web",
        "description": "搜尋網路，取得最新技術文件、API 用法或錯誤解法。使用 DuckDuckGo 即時搜尋。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query":    {"type": "string",  "description": "搜尋關鍵字"},
                "max_results": {"type": "integer", "description": "最多回傳幾筆（預設 5）"},
                "region":   {"type": "string",  "description": "地區（預設 tw-tzh，台灣繁中）"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "docker_build",
        "description": "建置 Docker image，支援多架構建置。",
        "input_schema": {
            "type": "object",
            "properties": {
                "tag":         {"type": "string",  "description": "Image 標籤（例：myapp:latest）"},
                "dockerfile":  {"type": "string",  "description": "Dockerfile 路徑（預設 ./Dockerfile）"},
                "context":     {"type": "string",  "description": "建置 context 目錄（預設 .）"},
                "platform":    {"type": "string",  "description": "目標平台（例：linux/amd64,linux/arm64）"},
                "no_cache":    {"type": "boolean", "description": "不使用 build cache（預設 false）"},
                "push":        {"type": "boolean", "description": "建置後推送到 registry（預設 false）"},
            },
            "required": ["tag"],
        },
    },
]


class HighFreqToolExecutor:
    """執行高頻必要工具"""

    def __init__(self, workdir: str, auto_confirm: bool = False):
        self.workdir      = workdir
        self.auto_confirm = auto_confirm

    def _run(self, cmd: str, timeout: int = 300) -> dict:
        import subprocess
        print(f"  \033[96m$ {cmd}\033[0m")
        try:
            r = _safe_run(cmd, cwd=self, timeout=timeout)
            # _safe_run 回傳 dict，用 .get() 存取

            out = (r.get('stdout','') + r.get('stderr','')).strip()
            for line in out.splitlines()[-8:]:
                print(f"  \033[2m{line}\033[0m")
            ok = r.get('returncode',0) == 0
            print(f"  \033[{'92' if ok else '93'}m{'✔' if ok else '⚠'} exit {r.get('returncode',0)}\033[0m")
            return {"success": ok, "output": out, "exit_code": r.get('returncode',0)}
        except subprocess.TimeoutExpired:
            return {"success": False, "output": "timeout", "exit_code": -1}
        except Exception as e:
            return {"success": False, "output": str(e), "exit_code": -1}

    def execute(self, tool_name: str, tool_input: dict) -> str:
        import json
        from pathlib import Path

        if tool_name == "git_commit":
            files = tool_input.get("files", [])
            msg   = tool_input["message"]
            push  = tool_input.get("push", False)
            branch= tool_input.get("branch", "")
            add_cmd = f"git add {' '.join(files)}" if files else "git add -A"
            self._run(add_cmd)
            result = self._run(f'git commit -m "{msg}"')
            if push and result["success"]:
                push_cmd = f"git push origin {branch}" if branch else "git push"
                self._run(push_cmd)
            return json.dumps(result)

        elif tool_name == "git_push":
            remote = tool_input.get("remote", "origin")
            branch = tool_input.get("branch", "")
            force  = tool_input.get("force", False)
            up     = tool_input.get("set_upstream", False)
            flags  = (" -f" if force else "") + (" --set-upstream" if up else "")
            cmd    = f"git push {remote} {branch}{flags}".strip()
            return json.dumps(self._run(cmd))

        elif tool_name == "npm_run":
            script  = tool_input["script"]
            args    = " ".join(tool_input.get("args", []))
            timeout = tool_input.get("timeout", 300)
            return json.dumps(self._run(f"npm run {script} -- {args}".strip(), timeout))

        elif tool_name == "npm_install":
            pkgs  = " ".join(tool_input["packages"])
            flags = (" -D" if tool_input.get("dev") else "") + \
                    (" -E" if tool_input.get("save_exact") else "")
            cmd   = f"npm ci" if tool_input.get("ci") else f"npm install {pkgs}{flags}"
            return json.dumps(self._run(cmd, 120))

        elif tool_name == "run_tests":
            p   = Path(self.workdir)
            pat = tool_input.get("pattern", "")
            cov = " --coverage" if tool_input.get("coverage") else ""
            timeout = tool_input.get("timeout", 120)

            # 自動偵測框架
            if (p / "vitest.config.ts").exists() or (p / "vitest.config.js").exists():
                cmd = f"npx vitest run {pat}{cov}"
            elif (p / "jest.config.js").exists() or (p / "jest.config.ts").exists():
                cmd = f"npx jest {pat}{cov}"
            elif (p / "pytest.ini").exists() or (p / "pyproject.toml").exists():
                cmd = f"python -m pytest {pat} -v"
            else:
                pkg = (p / "package.json")
                if pkg.exists():
                    import json as jj
                    scripts = jj.loads(pkg.read_text()).get("scripts", {})
                    if "test" in scripts:
                        cmd = f"npm run test -- --run {pat}"
                    else:
                        cmd = f"npx vitest run {pat}"
                else:
                    cmd = f"pytest {pat} -v"

            result = self._run(cmd, timeout)
            # 解析通過/失敗數
            import re
            passed = len(re.findall(r'✓|PASS|passed', result["output"]))
            failed = len(re.findall(r'✗|FAIL|failed', result["output"]))
            result["summary"] = {"passed": passed, "failed": failed}
            return json.dumps(result)

        elif tool_name == "fetch_url":
            import urllib.request, urllib.error
            url     = tool_input["url"]
            method  = tool_input.get("method", "GET")
            headers = tool_input.get("headers", {})
            body    = tool_input.get("body", "").encode() if tool_input.get("body") else None
            timeout = tool_input.get("timeout", 10)
            try:
                req = urllib.request.Request(url, data=body, method=method)
                req.add_header("User-Agent", "SYNTHEX/1.0")
                for k, v in headers.items():
                    req.add_header(k, v)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    content = resp.read().decode("utf-8", errors="replace")[:5000]
                    return json.dumps({"success": True, "status": resp.status, "content": content})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        elif tool_name == "search_web":
            query   = tool_input["query"]
            limit   = tool_input.get("max_results", 5)
            # DuckDuckGo instant search（無需 API key）
            encoded = query.replace(" ", "+")
            result  = self._run(
                f"curl -s 'https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1' 2>/dev/null | "
                f"python3 -c \"import json,sys; d=json.load(sys.stdin); "
                f"results=d.get('RelatedTopics',[])[:int('{limit}')]; "
                f"[print(r.get('Text','')[:100]) for r in results if isinstance(r,dict) and r.get('Text')]\"",
                15
            )
            if not result["output"]:
                # fallback：直接抓 DuckDuckGo HTML
                result = self._run(
                    f"curl -sA 'Mozilla/5.0' 'https://html.duckduckgo.com/html/?q={encoded}' 2>/dev/null | "
                    f"python3 -c \"import sys,re; "
                    f"text=sys.stdin.read(); "
                    f"results=re.findall(r'<a class=.*?result__a.*?>(.*?)</a>', text, re.S)[:5]; "
                    f"[print(re.sub(r'<.*?>','',r)[:100]) for r in results]\"",
                    15
                )
            return json.dumps({"query": query, "results": result["output"]})

        elif tool_name == "docker_build":
            tag        = tool_input["tag"]
            dockerfile = tool_input.get("dockerfile", "Dockerfile")
            context    = tool_input.get("context", ".")
            platform   = tool_input.get("platform", "")
            no_cache   = " --no-cache" if tool_input.get("no_cache") else ""
            push_flag  = " --push" if tool_input.get("push") else ""
            plat_flag  = f" --platform {platform}" if platform else ""
            cmd = f"docker build -t {tag} -f {dockerfile}{plat_flag}{no_cache}{push_flag} {context}"
            return json.dumps(self._run(cmd, 600))

        return json.dumps({"error": f"未知工具：{tool_name}"})


# 把新工具加入全域 ALL_TOOL_DEFS 和 ROLE_TOOLS
ALL_TOOL_DEFS.extend(HIGH_FREQ_TOOL_DEFS)
for role in ROLE_TOOLS:
    # 所有角色都能用高頻工具（除了 haiku 角色只給輕量工具）
    ROLE_TOOLS[role].extend([t["name"] for t in HIGH_FREQ_TOOL_DEFS])
