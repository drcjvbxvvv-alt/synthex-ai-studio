"""
BaseAgent v3 — 生產級重構版
P0 修復：
  - API 重試 + 指數退避 (Rate Limit / 暫時性錯誤)
  - Token 用量追蹤（每次呼叫、累計、成本估算）
  - Budget Guard（超出預算自動暫停）
"""

import os
import json
import time
import anthropic
from pathlib import Path
from datetime import datetime

from core.tools import ToolExecutor, get_tools_for_role

MEMORY_DIR = Path(__file__).parent.parent / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

RESET  = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
CYAN   = "\033[96m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
RED    = "\033[91m"; GRAY = "\033[90m"

# ── 定價（claude-opus-4-5，USD per 1M tokens）─────────────────
PRICING = {
    "claude-opus-4-5":     {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-5":   {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5":    {"input":  0.25, "output":  1.25},
}
DEFAULT_BUDGET_USD = 5.0   # 預設每次 /ship 的 budget 上限


# ══════════════════════════════════════════════════════════════
#  P0-1：Token 成本追蹤器
# ══════════════════════════════════════════════════════════════

class TokenBudget:
    """
    追蹤整個 session 的 Token 用量和成本。
    超出 budget 時自動暫停，防止失控燒錢。
    """

    def __init__(self, budget_usd: float = DEFAULT_BUDGET_USD, model: str = "claude-opus-4-5"):
        self.budget_usd     = budget_usd
        self.model          = model
        self.total_input    = 0
        self.total_output   = 0
        self.call_count     = 0
        self.session_start  = datetime.now()
        self._log: list     = []

    def record(self, agent_name: str, input_tokens: int, output_tokens: int):
        self.total_input  += input_tokens
        self.total_output += output_tokens
        self.call_count   += 1
        cost = self._calc_cost(input_tokens, output_tokens)
        self._log.append({
            "agent":  agent_name,
            "input":  input_tokens,
            "output": output_tokens,
            "cost":   cost,
            "at":     datetime.now().isoformat(),
        })

    def _calc_cost(self, inp: int, out: int) -> float:
        prices = PRICING.get(self.model, PRICING["claude-opus-4-5"])
        return (inp / 1_000_000 * prices["input"]) + (out / 1_000_000 * prices["output"])

    @property
    def total_cost_usd(self) -> float:
        return self._calc_cost(self.total_input, self.total_output)

    @property
    def budget_remaining(self) -> float:
        return self.budget_usd - self.total_cost_usd

    @property
    def over_budget(self) -> bool:
        return self.total_cost_usd >= self.budget_usd

    def check_budget(self):
        """超出 budget 時拋出例外"""
        if self.over_budget:
            raise BudgetExceededError(
                f"Token 用量已超出預算 ${self.budget_usd:.2f} USD\n"
                f"  已用：${self.total_cost_usd:.4f} USD "
                f"({self.total_input:,} input + {self.total_output:,} output tokens)\n"
                f"  呼叫次數：{self.call_count}\n"
                f"  執行時間：{(datetime.now() - self.session_start).seconds}s\n"
                f"  增加 budget：python synthex.py ship ... --budget 10.0"
            )

    def summary(self) -> str:
        elapsed = (datetime.now() - self.session_start).seconds
        return (
            f"\n{CYAN}{'─'*50}\n"
            f"  💰 Token 用量報告\n"
            f"{'─'*50}{RESET}\n"
            f"  模型：{self.model}\n"
            f"  Input tokens：{self.total_input:,}\n"
            f"  Output tokens：{self.total_output:,}\n"
            f"  總成本：${self.total_cost_usd:.4f} USD\n"
            f"  API 呼叫次數：{self.call_count}\n"
            f"  執行時間：{elapsed}s\n"
            f"  預算剩餘：${self.budget_remaining:.4f} USD / ${self.budget_usd:.2f}\n"
            f"{CYAN}{'─'*50}{RESET}"
        )

    def per_agent_summary(self) -> str:
        agents: dict = {}
        for entry in self._log:
            n = entry["agent"]
            if n not in agents:
                agents[n] = {"calls": 0, "input": 0, "output": 0, "cost": 0.0}
            agents[n]["calls"]  += 1
            agents[n]["input"]  += entry["input"]
            agents[n]["output"] += entry["output"]
            agents[n]["cost"]   += entry["cost"]

        lines = [f"\n{DIM}  按角色分配："]
        for name, d in sorted(agents.items(), key=lambda x: -x[1]["cost"]):
            lines.append(
                f"    {name:<8} ${d['cost']:.4f}  "
                f"({d['input']:,}in + {d['output']:,}out  ×{d['calls']}呼叫)"
            )
        lines.append(RESET)
        return "\n".join(lines)


class BudgetExceededError(Exception):
    pass


# ── 全域 session budget（所有 Agent 共享）────────────────────
_session_budget: TokenBudget = None

def get_session_budget() -> TokenBudget:
    global _session_budget
    if _session_budget is None:
        _session_budget = TokenBudget()
    return _session_budget

def init_session_budget(budget_usd: float = DEFAULT_BUDGET_USD, model: str = "claude-opus-4-5"):
    global _session_budget
    _session_budget = TokenBudget(budget_usd=budget_usd, model=model)
    return _session_budget


# ══════════════════════════════════════════════════════════════
#  P0-2：API 重試機制（指數退避）
# ══════════════════════════════════════════════════════════════

def _api_call_with_retry(fn, max_retries: int = 4, agent_name: str = "?"):
    """
    帶重試的 API 呼叫包裝器。

    重試策略：
    - RateLimitError (429)：指數退避，最多 4 次，等待 2/4/8/16 秒
    - APIConnectionError：最多 3 次，等待 1/2/4 秒
    - APIStatusError 5xx：最多 2 次，等待 2/4 秒
    - 其他例外：直接拋出，不重試
    """
    for attempt in range(max_retries):
        try:
            return fn()

        except anthropic.RateLimitError as e:
            wait = 2 ** attempt  # 2, 4, 8, 16 秒
            if attempt < max_retries - 1:
                print(f"\n{YELLOW}  ⚠ [{agent_name}] Rate Limit (429)，{wait}s 後重試 ({attempt+1}/{max_retries})...{RESET}")
                time.sleep(wait)
            else:
                raise

        except anthropic.APIConnectionError as e:
            wait = 2 ** min(attempt, 3)  # 1, 2, 4 秒
            if attempt < min(max_retries - 1, 2):
                print(f"\n{YELLOW}  ⚠ [{agent_name}] 連線錯誤，{wait}s 後重試...{RESET}")
                time.sleep(wait)
            else:
                raise

        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                wait = 2 ** attempt
                if attempt < min(max_retries - 1, 1):
                    print(f"\n{YELLOW}  ⚠ [{agent_name}] 伺服器錯誤 ({e.status_code})，{wait}s 後重試...{RESET}")
                    time.sleep(wait)
                else:
                    raise
            elif e.status_code == 529:  # Overloaded
                wait = 5 * (attempt + 1)
                if attempt < max_retries - 1:
                    print(f"\n{YELLOW}  ⚠ [{agent_name}] API 超載，{wait}s 後重試...{RESET}")
                    time.sleep(wait)
                else:
                    raise
            else:
                raise  # 4xx 客戶端錯誤不重試


# ══════════════════════════════════════════════════════════════
#  BaseAgent v3
# ══════════════════════════════════════════════════════════════

class BaseAgent:
    name:     str  = "AGENT"
    title:    str  = "Agent"
    dept:     str  = "default"
    emoji:    str  = "🤖"
    color:    str  = "\033[37m"
    skills:   list = []
    personality_traits: dict = {}
    system_prompt: str = ""

    def __init__(self, workdir: str = None, auto_confirm: bool = False,
                 budget_usd: float = None):
        self.client   = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.model    = "claude-opus-4-5"
        self.workdir  = workdir or os.getcwd()
        self.executor = ToolExecutor(workdir=self.workdir, auto_confirm=auto_confirm)
        self.memory_file          = MEMORY_DIR / f"{self.name.lower()}_memory.json"
        self.conversation_history = self._load_memory()
        # 使用全域 session budget，或建立獨立的
        self._budget = get_session_budget()

    # ── 記憶管理 ───────────────────────────────────────────────

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
        self.workdir  = str(Path(path).resolve())
        self.executor = ToolExecutor(workdir=self.workdir,
                                      auto_confirm=self.executor.auto_confirm)
        self._print_system(f"工作目錄 → {self.workdir}")

    # ── 顯示工具 ───────────────────────────────────────────────

    def _header(self, mode: str = "") -> str:
        ts       = datetime.now().strftime("%H:%M:%S")
        mode_tag = f" [{mode}]" if mode else ""
        budget   = self._budget
        cost_str = f"${budget.total_cost_usd:.3f}/${budget.budget_usd:.1f}"
        return (
            f"\n{self.color}{BOLD}┌─ {self.emoji} {self.name}{RESET}"
            f"{DIM} · {self.title}{mode_tag} · {ts} · 💰{cost_str}{RESET}"
        )

    def _footer(self) -> str:
        return f"{self.color}└{'─'*58}{RESET}\n"

    def _print_system(self, msg: str):
        print(f"\n{DIM}  ⚙ [{self.name}] {msg}{RESET}")

    def _print_tool_call(self, name: str, inp: dict):
        args = ", ".join(f"{k}={repr(v)[:50]}" for k, v in inp.items())
        print(f"\n{self.color}│{RESET} {CYAN}🔧 {name}({args}){RESET}")

    def _print_tool_result(self, result: str):
        preview = result[:200].replace("\n", " ")
        suffix  = "..." if len(result) > 200 else ""
        print(f"{self.color}│{RESET} {DIM}   → {preview}{suffix}{RESET}")

    def _stream_text(self, text: str):
        print(f"{self.color}│{RESET} ", end="", flush=True)
        for ch in text:
            print(ch, end="", flush=True)
            if ch == "\n":
                print(f"{self.color}│{RESET} ", end="", flush=True)
        print()

    # ── System Prompt ──────────────────────────────────────────

    def _build_system_prompt(self, with_tools: bool = False) -> str:
        skills_str = "\n".join(f"  • {s}" for s in self.skills)
        traits_str = "\n".join(f"  • {k}: {v}/100" for k, v in self.personality_traits.items())
        tool_sec   = f"""
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
{tool_sec}
【工作準則】
- 始終以 {self.name} 的身份和語氣回應
- 使用繁體中文（技術術語可保留英文）
- 提供具體可執行的方案，說明 trade-off
- 任務不在專業範疇時，明確指出並建議適合的同事

今天日期：{datetime.now().strftime('%Y-%m-%d')}
"""

    # ── 對話模式（無工具）──────────────────────────────────────

    def chat(self, user_message: str, context: str = "") -> str:
        """純對話模式 — 帶重試 + Token 追蹤"""
        # Budget 檢查
        self._budget.check_budget()

        full_msg = f"[上下文]\n{context}\n\n[問題]\n{user_message}" if context else user_message
        self.conversation_history.append({"role": "user", "content": full_msg})
        print(self._header("對話"))

        response_text = ""
        try:
            def _call():
                return self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=self._build_system_prompt(with_tools=False),
                    messages=self.conversation_history,
                )

            resp = _api_call_with_retry(_call, agent_name=self.name)

            # Token 追蹤
            if hasattr(resp, "usage"):
                self._budget.record(self.name, resp.usage.input_tokens, resp.usage.output_tokens)
                self._print_system(
                    f"tokens: {resp.usage.input_tokens}in + {resp.usage.output_tokens}out "
                    f"= ${self._budget._calc_cost(resp.usage.input_tokens, resp.usage.output_tokens):.4f}"
                )

            for block in resp.content:
                if hasattr(block, "text"):
                    response_text += block.text

            # 顯示輸出
            print(f"{self.color}│{RESET} ", end="", flush=True)
            for ch in response_text:
                print(ch, end="", flush=True)
                if ch == "\n":
                    print(f"{self.color}│{RESET} ", end="", flush=True)
            print()

        except BudgetExceededError:
            raise
        except Exception as e:
            response_text = f"[API 錯誤] {e}"
            print(f"{RED}  ✖ {response_text}{RESET}")

        print(self._footer())
        self.conversation_history.append({"role": "assistant", "content": response_text})
        self._save_memory()
        return response_text

    # ── Agentic 模式（有工具）──────────────────────────────────

    def run(self, task: str, context: str = "", max_iterations: int = 20) -> str:
        """Agentic 模式 — 帶重試 + Token 追蹤 + Budget Guard"""
        # Budget 檢查
        self._budget.check_budget()

        tools     = get_tools_for_role(self.dept)
        full_task = f"[上下文]\n{context}\n\n[任務]\n{task}" if context else task
        messages  = list(self.conversation_history) + [{"role": "user", "content": full_task}]

        print(self._header("Agentic"))
        self._print_system(f"工具: {len(tools)} 個，最多 {max_iterations} 輪")

        final_text = ""
        iteration  = 0

        while iteration < max_iterations:
            iteration += 1

            # Budget 檢查（每輪迭代都檢查）
            self._budget.check_budget()

            try:
                def _call():
                    return self.client.messages.create(
                        model=self.model,
                        max_tokens=8192,
                        system=self._build_system_prompt(with_tools=True),
                        tools=tools,
                        messages=messages,
                    )

                response = _api_call_with_retry(_call, agent_name=self.name)

                # Token 追蹤
                if hasattr(response, "usage"):
                    self._budget.record(
                        self.name,
                        response.usage.input_tokens,
                        response.usage.output_tokens
                    )

            except BudgetExceededError:
                raise
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
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     result,
                    })

            messages.append({"role": "assistant", "content": response.content})
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            if text_parts:
                final_text = "\n".join(text_parts)

            if response.stop_reason == "end_turn":
                self._print_system(f"✔ 完成（{iteration} 輪）")
                break
            elif response.stop_reason != "tool_use":
                self._print_system(f"停止: {response.stop_reason}")
                break
        else:
            self._print_system(f"⚠ 達到最大迭代次數 ({max_iterations})")

        print(self._footer())
        self.conversation_history.append({"role": "user",      "content": task})
        self.conversation_history.append({"role": "assistant", "content": final_text or "[完成]"})
        self._save_memory()
        return final_text

    # ── 快捷方法 ────────────────────────────────────────────────

    def review(self, content: str) -> str:
        return self.chat(f"請審查以下內容，提供專業意見和改進建議：\n\n{content}")

    def plan(self, task: str) -> str:
        return self.chat(f"請為以下任務制定詳細執行計畫：\n\n{task}")

    def do(self, task: str) -> str:
        return self.run(task)

    def explain(self, topic: str) -> str:
        return self.chat(f"請從你的專業角度解釋：{topic}")
