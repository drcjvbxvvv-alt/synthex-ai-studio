"""
BaseAgent v2 — Agentic 版本
支援真實工具呼叫：讀寫檔案、執行命令、搜尋代碼
Agent 會在工具呼叫循環中自主運作，直到任務完成
"""

import os
import json
from pathlib import Path
from datetime import datetime
import anthropic

from core.tools import ToolExecutor, get_tools_for_role

MEMORY_DIR = Path(__file__).parent.parent / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
GRAY   = "\033[90m"


class BaseAgent:
    name:     str  = "AGENT"
    title:    str  = "Agent"
    dept:     str  = "default"
    emoji:    str  = "🤖"
    color:    str  = "\033[37m"
    skills:   list = []
    personality_traits: dict = {}
    system_prompt: str = ""

    def __init__(self, workdir: str = None, auto_confirm: bool = False):
        self.client   = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.model    = "claude-opus-4-5"
        self.workdir  = workdir or os.getcwd()
        self.executor = ToolExecutor(workdir=self.workdir, auto_confirm=auto_confirm)
        self.memory_file = MEMORY_DIR / f"{self.name.lower()}_memory.json"
        self.conversation_history = self._load_memory()

    def _load_memory(self) -> list:
        if self.memory_file.exists():
            try:
                return json.loads(self.memory_file.read_text())
            except Exception:
                pass
        return []

    def _save_memory(self):
        trimmed = self.conversation_history[-40:]
        self.memory_file.write_text(json.dumps(trimmed, ensure_ascii=False, indent=2))

    def clear_memory(self):
        self.conversation_history = []
        if self.memory_file.exists():
            self.memory_file.unlink()
        self._print_system("記憶已清除")

    def set_workdir(self, path: str):
        self.workdir = str(Path(path).resolve())
        self.executor = ToolExecutor(workdir=self.workdir, auto_confirm=self.executor.auto_confirm)
        self._print_system(f"工作目錄切換至 {self.workdir}")

    def _header(self, mode: str = "") -> str:
        ts = datetime.now().strftime("%H:%M:%S")
        mode_tag = f" [{mode}]" if mode else ""
        return (
            f"\n{self.color}{BOLD}┌─ {self.emoji} {self.name}{RESET}"
            f"{DIM} · {self.title}{mode_tag} · {ts}{RESET}"
        )

    def _footer(self) -> str:
        return f"{self.color}└{'─'*54}{RESET}\n"

    def _print_system(self, msg: str):
        print(f"\n{DIM}  ⚙ [{self.name}] {msg}{RESET}")

    def _print_tool_call(self, name: str, inp: dict):
        args_str = ", ".join(f"{k}={repr(v)[:50]}" for k, v in inp.items())
        print(f"\n{self.color}│{RESET} {CYAN}🔧 {name}({args_str}){RESET}")

    def _print_tool_result(self, result: str):
        preview = result[:200].replace("\n", " ")
        suffix = "..." if len(result) > 200 else ""
        print(f"{self.color}│{RESET} {DIM}   → {preview}{suffix}{RESET}")

    def _stream_text(self, text: str):
        print(f"{self.color}│{RESET} ", end="", flush=True)
        for char in text:
            print(char, end="", flush=True)
            if char == "\n":
                print(f"{self.color}│{RESET} ", end="", flush=True)
        print()

    def _build_system_prompt(self, with_tools: bool = False) -> str:
        skills_str = "\n".join(f"  • {s}" for s in self.skills)
        traits_str = "\n".join(f"  • {k}: {v}/100" for k, v in self.personality_traits.items())
        tool_section = f"""
【工作環境】
- 當前工作目錄: {self.workdir}
- 你有真實工具可以操作檔案系統和執行命令
- 主動使用工具完成任務，不要只給建議
- 遇到錯誤要分析原因並嘗試修復
- 完成後簡要說明做了什麼
""" if with_tools else ""

        return f"""你是 SYNTHEX AI STUDIO 的 {self.emoji} {self.name}，職位：{self.title}。

【角色設定】
{self.system_prompt}

【核心技能】
{skills_str}

【性格特質】
{traits_str}
{tool_section}
【工作準則】
- 始終以 {self.name} 的身份和語氣回應
- 使用繁體中文（技術術語可保留英文）
- 提供具體可執行的方案，說明 trade-off
- 任務不在專業範疇時，明確指出並建議適合的同事

今天日期：{datetime.now().strftime('%Y-%m-%d')}
"""

    def chat(self, user_message: str, context: str = "") -> str:
        """純對話模式（無工具）"""
        full_message = f"[上下文]\n{context}\n\n[問題]\n{user_message}" if context else user_message
        self.conversation_history.append({"role": "user", "content": full_message})
        print(self._header("對話"))
        response_text = ""
        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=4096,
                system=self._build_system_prompt(with_tools=False),
                messages=self.conversation_history,
            ) as s:
                print(f"{self.color}│{RESET} ", end="", flush=True)
                for text in s.text_stream:
                    print(text, end="", flush=True)
                    response_text += text
                    if "\n" in text:
                        for _ in range(text.count("\n")):
                            print(f"{self.color}│{RESET} ", end="", flush=True)
                print()
        except Exception as e:
            response_text = f"[錯誤] {e}"
            print(f"{RED}  ✖ {response_text}{RESET}")
        print(self._footer())
        self.conversation_history.append({"role": "assistant", "content": response_text})
        self._save_memory()
        return response_text

    def run(self, task: str, context: str = "", max_iterations: int = 20) -> str:
        """Agentic 模式：自主使用工具完成任務"""
        tools = get_tools_for_role(self.dept)
        full_task = f"[上下文]\n{context}\n\n[任務]\n{task}" if context else task
        messages = list(self.conversation_history) + [{"role": "user", "content": full_task}]

        print(self._header("Agentic"))
        self._print_system(f"開始執行，工具: {len(tools)} 個，最多 {max_iterations} 輪")

        final_text = ""
        iteration  = 0

        while iteration < max_iterations:
            iteration += 1
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    system=self._build_system_prompt(with_tools=True),
                    tools=tools,
                    messages=messages,
                )
            except Exception as e:
                msg = f"[API 錯誤] {e}"
                print(f"{RED}  ✖ {msg}{RESET}")
                return msg

            tool_results = []
            text_parts   = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                    if block.text.strip():
                        self._stream_text(block.text)
                elif block.type == "tool_use":
                    self._print_tool_call(block.name, block.input)
                    result = self.executor.execute(block.name, block.input)
                    self._print_tool_result(result)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "assistant", "content": response.content})
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            if text_parts:
                final_text = "\n".join(text_parts)

            if response.stop_reason == "end_turn":
                self._print_system(f"✔ 任務完成（共 {iteration} 輪）")
                break
            elif response.stop_reason != "tool_use":
                self._print_system(f"停止: {response.stop_reason}")
                break
        else:
            self._print_system(f"⚠ 已達最大迭代次數 ({max_iterations})")

        print(self._footer())
        self.conversation_history.append({"role": "user", "content": task})
        self.conversation_history.append({
            "role": "assistant",
            "content": final_text or "[任務完成]",
        })
        self._save_memory()
        return final_text

    # 快捷方法
    def review(self, content: str) -> str:
        return self.chat(f"請審查以下內容，提供專業意見和具體改進建議：\n\n{content}")

    def plan(self, task: str) -> str:
        return self.chat(f"請為以下任務制定詳細執行計畫：\n\n{task}")

    def do(self, task: str) -> str:
        return self.run(task)

    def explain(self, topic: str) -> str:
        return self.chat(f"請從你的專業角度解釋：{topic}")
