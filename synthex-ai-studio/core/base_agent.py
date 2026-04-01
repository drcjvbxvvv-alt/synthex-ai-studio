"""
BaseAgent v5 (v0.0.0) — 生產就緒版（第十二輪重構）

重大改動：
  - 完全整合 core/config.py（移除重複的 PRICING/MODEL_STRATEGY）
  - structlog 取代內部 print() 日誌（保留 UI 彩色輸出）
  - TokenBudget 使用 cfg.calc_cost()（精確成本，含 cache read/write）
  - 修正 haiku → sonnet fallback 使用 ModelID 常數
  - TokenGuard 整合到 _build_system_prompt（防 context overflow）

安全：
  - 不使用 shell=True
  - conversation_history 主動截斷（MAX_HISTORY_LEN）
  - Budget Guard 超出預算即暫停
  - Circuit Breaker 防止級聯失敗
"""

from __future__ import annotations

import os
import json
import time
import anthropic
from pathlib import Path
from datetime import datetime

from core.tools import ToolExecutor, get_tools_for_role
from core.config import cfg, ModelID, AGENT_TIER_MAP, Tier, MODEL_COSTS_PER_MTK
from core.logging_setup import get_logger, TokenGuard

logger = get_logger("base_agent")

MEMORY_DIR = Path(__file__).parent.parent / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

# ── Beta Header 常數（集中管理，GA 後只需改這裡）──────────────────
# 追蹤狀態：https://docs.anthropic.com/en/docs/about-claude/models
#
# interleaved-thinking：允許 thinking 塊與 tool_use 交錯出現。
#   設為 None 可停用（純同步 thinking 不需要此 header）。
BETA_INTERLEAVED_THINKING: str | None = "interleaved-thinking-2025-05-14"

# context-management：Server-side tool result clearing，防止 context 爆炸。
#   設為 None 可停用（降級到純手動 compaction）。
BETA_CONTEXT_MANAGEMENT: str | None = "context-management-2025-06-27"

# ── 終端機 UI 顏色（保留，這是 CLI 產品的 UX）─────────────────────
RESET  = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
CYAN   = "\033[96m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
RED    = "\033[91m"; GRAY = "\033[90m"

# ── 常數 ──────────────────────────────────────────────────────────
DEFAULT_BUDGET_USD = 5.0
CACHE_MIN_TOKENS   = 1024
MAX_HISTORY_LEN    = 40

# Compaction：messages 超過此 token 數時觸發摘要（58.6% 平均節省）
COMPACTION_TOKEN_THRESHOLD = 80_000   # 保守值（context window 的 40%）
COMPACTION_SUMMARY_TOKENS  = 4_096    # 摘要輸出的 token 預算

# ── Thinking 設定 ─────────────────────────────────────────────────
ADAPTIVE_THINKING_AGENTS: frozenset[str] = frozenset({
    "NEXUS", "SIGMA", "ARIA", "NOVA", "ATOM",
})
THINKING_BUDGET = {
    "deep":   10_000,
    "normal":  5_000,
    "quick":   2_000,
}

# ── 模型查詢（委託給 config.py）──────────────────────────────────

def get_model_for_agent(agent_name: str) -> str:
    return cfg.model_for_agent(agent_name)


def _model_display_tag(model: str) -> str:
    tags = {
        ModelID.OPUS_46:   "Opus 4.6",
        ModelID.SONNET_46: "Sonnet 4.6",
        ModelID.SONNET_45: "Sonnet 4.5",
        ModelID.HAIKU_45:  "Haiku 4.5",
        ModelID.OPUS_45:   "Opus 4.5",
    }
    return tags.get(model, model.split("-")[1] if "-" in model else model)


# ══════════════════════════════════════════════════════════════════
#  CompactionManager — Context Compaction（長任務記憶體管理）
# ══════════════════════════════════════════════════════════════════

class CompactionManager:
    """
    為長時間運行的 agentic loop 提供 Context Compaction。

    策略（兩層）：
      1. Tool Result Clearing（輕量）：使用官方 context_management
         API，自動在 input_tokens 超過閾值時清除舊工具結果。
         保留最近 N 個工具調用，確保模型仍有足夠上下文。

      2. 手動摘要 Compaction（重量）：token 用量接近 safe_limit 時，
         呼叫 Claude 生成任務摘要，然後重置 messages。
         基於 Anthropic cookbook 的「58.6% token 節省」最佳實踐。

    安全設計：
      - 摘要前先記錄原始 messages 數量到 log
      - 摘要失敗（API 錯誤）→ 降級為截斷舊訊息，不崩潰
      - 不壓縮 system prompt（始終完整傳遞）
    """

    def __init__(self, model: str, agent_name: str = "?",
                 threshold: int = COMPACTION_TOKEN_THRESHOLD):
        self.model      = model
        self.agent_name = agent_name
        self.threshold  = threshold
        self._compacted_count = 0

    def should_compact(self, messages: list[dict],
                        input_tokens: int = 0) -> bool:
        """判斷是否需要觸發 compaction"""
        if input_tokens > 0:
            return input_tokens >= self.threshold
        # 無精確 token 數時，用字元數估算
        total_chars = sum(
            len(str(m.get("content", ""))) for m in messages
        )
        return total_chars >= self.threshold * 4  # 4 chars ≈ 1 token

    def build_context_management_params(self) -> dict:
        """
        建立 context_management 參數（server-side tool result clearing）。
        使用 BETA_CONTEXT_MANAGEMENT 常數（設為 None 可停用 beta header）。
        """
        params: dict = {}
        if BETA_CONTEXT_MANAGEMENT:
            params["betas"] = [BETA_CONTEXT_MANAGEMENT]
        params["context_management"] = {
                "edits": [{
                    "type": "clear_tool_uses_20250919",
                    "trigger": {
                        "type":  "input_tokens",
                        "value": self.threshold,
                    },
                    "keep": {
                        "type":  "tool_uses",
                        "value": 3,   # 保留最近 3 個工具調用
                    },
                    "clear_at_least": {
                        "type":  "input_tokens",
                        "value": 10_000,  # 最少清除 10K tokens
                    },
                }]
            }
        return params

    def compact(self, messages: list[dict],
                client, system_prompt) -> list[dict]:
        """
        手動 Compaction：生成任務摘要，重置 messages。
        返回壓縮後的 messages 列表。
        """
        if len(messages) < 4:
            return messages   # 太短，不壓縮

        original_count = len(messages)

        # 構建摘要請求
        summary_prompt = """請為到目前為止的任務進展生成一份結構化摘要。

包含以下部分：
1. 原始任務：一句話描述用戶要求什麼
2. 已完成：列出已完成的具體步驟和結果
3. 當前狀態：目前進行到哪裡
4. 待完成：還需要執行哪些步驟
5. 關鍵決策：做出的重要架構/設計決策
6. 已知問題：遇到的錯誤或限制

請保持簡潔，每部分不超過 3 個要點。"""

        try:
            resp = client.messages.create(
                model      = self.model,
                max_tokens = COMPACTION_SUMMARY_TOKENS,
                system     = system_prompt if isinstance(system_prompt, str)
                             else system_prompt[0].get("text", "") if system_prompt
                             else "",
                messages   = messages + [{
                    "role": "user", "content": summary_prompt
                }],
            )
            summary_text = next(
                (b.text for b in resp.content if hasattr(b, "text")),
                "[摘要生成失敗]"
            )

            # 重置 messages：只保留摘要
            compacted = [{
                "role": "user",
                "content": (
                    f"[Context Compaction — 以下為任務進展摘要，"
                    f"原始 {original_count} 條訊息已壓縮]\n\n"
                    f"{summary_text}"
                )
            }, {
                "role": "assistant",
                "content": "已了解任務進展摘要，繼續執行。"
            }]

            self._compacted_count += 1
            logger.info("compaction_done",
                        agent=self.agent_name,
                        original_messages=original_count,
                        compacted_to=len(compacted),
                        round=self._compacted_count)

            return compacted

        except Exception as e:
            # 降級：截斷舊訊息（保留最近 10 條）
            logger.warning("compaction_failed_fallback",
                           agent=self.agent_name, error=str(e)[:100])
            return messages[-10:]

    @property
    def compacted_count(self) -> int:
        return self._compacted_count


def _model_display_tag(model: str) -> str:
    """把模型 ID 縮短為顯示用標籤"""
    tags = {
        ModelID.OPUS_46:   "Opus 4.6",
        ModelID.SONNET_46: "Sonnet 4.6",
        ModelID.SONNET_45: "Sonnet 4.5",
        ModelID.HAIKU_45:  "Haiku 4.5",
        ModelID.OPUS_45:   "Opus 4.5",
    }
    return tags.get(model, model.split("-")[1] if "-" in model else model)


# ══════════════════════════════════════════════════════════════════
#  TokenBudget — 使用 cfg.calc_cost() 精確計算
# ══════════════════════════════════════════════════════════════════

class TokenBudget:
    """
    追蹤整個 session 的 Token 用量和成本。
    使用 config.py 的 MODEL_COSTS_PER_MTK（含 cache read/write 成本）。
    超出 budget 時自動暫停，防止失控燒錢。
    """

    def __init__(self, budget_usd: float = DEFAULT_BUDGET_USD,
                 model: str = ModelID.OPUS_46):
        self.budget_usd    = budget_usd
        self.model         = model
        self.total_input   = 0
        self.total_output  = 0
        self.total_cache_read  = 0
        self.total_cache_write = 0
        self.call_count    = 0
        self.session_start = datetime.now()
        self._log: list    = []

    def record(self, agent_name: str, input_tokens: int, output_tokens: int,
               cache_read: int = 0, cache_write: int = 0) -> None:
        self.total_input       += input_tokens
        self.total_output      += output_tokens
        self.total_cache_read  += cache_read
        self.total_cache_write += cache_write
        self.call_count        += 1
        cost = cfg.calc_cost(self.model, input_tokens, output_tokens,
                             cache_read, cache_write)
        self._log.append({
            "agent":       agent_name,
            "input":       input_tokens,
            "output":      output_tokens,
            "cache_read":  cache_read,
            "cache_write": cache_write,
            "cost":        cost,
            "at":          datetime.now().isoformat(),
        })
        logger.debug("token_usage", agent=agent_name,
                     input=input_tokens, output=output_tokens,
                     cache_read=cache_read, cost_usd=round(cost, 6))

    def _calc_cost(self, inp: int, out: int,
                   cache_read: int = 0, cache_write: int = 0) -> float:
        return cfg.calc_cost(self.model, inp, out, cache_read, cache_write)

    @property
    def total_cost_usd(self) -> float:
        return self._calc_cost(
            self.total_input, self.total_output,
            self.total_cache_read, self.total_cache_write
        )

    @property
    def budget_remaining(self) -> float:
        return self.budget_usd - self.total_cost_usd

    @property
    def over_budget(self) -> bool:
        return self.total_cost_usd >= self.budget_usd

    def check_budget(self) -> None:
        if self.over_budget:
            raise BudgetExceededError(
                f"Token 用量已超出預算 ${self.budget_usd:.2f} USD\n"
                f"  已用：${self.total_cost_usd:.4f} USD "
                f"({self.total_input:,} input + {self.total_output:,} output tokens)\n"
                f"  Cache 節省：{self.total_cache_read:,} read tokens\n"
                f"  呼叫次數：{self.call_count}\n"
                f"  執行時間：{(datetime.now() - self.session_start).seconds}s\n"
                f"  增加 budget：python synthex.py ship ... --budget 10.0"
            )

    def summary(self) -> str:
        elapsed = (datetime.now() - self.session_start).seconds
        cache_saved = self._calc_cost(self.total_cache_read, 0) * 0.9  # cache 節省 90%
        return (
            f"\n{CYAN}{'─'*54}\n"
            f"  💰 Token 用量報告\n"
            f"{'─'*54}{RESET}\n"
            f"  模型：{_model_display_tag(self.model)}\n"
            f"  Input tokens ：{self.total_input:,}\n"
            f"  Output tokens ：{self.total_output:,}\n"
            f"  Cache read    ：{self.total_cache_read:,} tokens（節省 ~${cache_saved:.4f}）\n"
            f"  總成本        ：${self.total_cost_usd:.4f} USD\n"
            f"  API 呼叫次數  ：{self.call_count}\n"
            f"  執行時間      ：{elapsed}s\n"
            f"  預算剩餘      ：${self.budget_remaining:.4f} / ${self.budget_usd:.2f}\n"
            f"{CYAN}{'─'*54}{RESET}"
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


# ══════════════════════════════════════════════════════════════════
#  Circuit Breaker — 防止 Agent 級聯失敗
# ══════════════════════════════════════════════════════════════════

class CircuitState:
    CLOSED = "closed"
    OPEN   = "open"
    HALF   = "half_open"

class CircuitBreaker:
    """
    為每個 Agent 的 API 呼叫加入 Circuit Breaker。
    連續失敗 3 次 → 熔斷 60 秒 → 試探性恢復。
    """

    def __init__(self, failure_threshold: int = 3,
                 recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout  = recovery_timeout
        self._failures: dict   = {}
        self._opened_at: dict  = {}
        self._state: dict      = {}

    def _get_state(self, agent: str) -> str:
        state = self._state.get(agent, CircuitState.CLOSED)
        if state == CircuitState.OPEN:
            if time.time() - self._opened_at.get(agent, 0) > self.recovery_timeout:
                self._state[agent] = CircuitState.HALF
                return CircuitState.HALF
        return state

    def call(self, agent: str, fn):
        state = self._get_state(agent)
        if state == CircuitState.OPEN:
            remaining = self.recovery_timeout - (time.time() - self._opened_at.get(agent, 0))
            raise RuntimeError(f"[Circuit Breaker] {agent} 熔斷中，{remaining:.0f}s 後恢復")

        try:
            result = fn()
            self._failures[agent] = 0
            if state == CircuitState.HALF:
                self._state[agent] = CircuitState.CLOSED
                print(f"\n{GREEN}✔ [{agent}] Circuit Breaker 恢復{RESET}")
            return result

        except Exception:
            self._failures[agent] = self._failures.get(agent, 0) + 1
            failures = self._failures[agent]
            if failures >= self.failure_threshold:
                self._state[agent]     = CircuitState.OPEN
                self._opened_at[agent] = time.time()
                logger.error("circuit_open", agent=agent, failures=failures,
                             recovery_in=self.recovery_timeout)
                print(f"\n{RED}⚡ [{agent}] Circuit Breaker 熔斷"
                      f"（連續失敗 {failures} 次）{RESET}")
            raise


_circuit_breaker = CircuitBreaker()


# ══════════════════════════════════════════════════════════════════
#  重試機制（指數退避）
# ══════════════════════════════════════════════════════════════════

def _api_call_with_retry(fn, max_retries: int = 4, agent_name: str = "?"):
    """
    帶重試的 API 呼叫包裝器。
    - RateLimitError (429)：指數退避 2/4/8/16 秒
    - APIConnectionError：最多 3 次，1/2/4 秒
    - APIStatusError 5xx：最多 2 次，2/4 秒
    - 其他例外：直接拋出
    """
    for attempt in range(max_retries):
        try:
            return fn()

        except anthropic.RateLimitError:
            wait = 2 ** attempt
            if attempt < max_retries - 1:
                logger.warning("rate_limit", agent=agent_name, wait_s=wait, attempt=attempt+1)
                print(f"\n{YELLOW}  ⚠ [{agent_name}] Rate Limit，{wait}s 後重試 ({attempt+1}/{max_retries})...{RESET}")
                time.sleep(wait)
            else:
                raise

        except anthropic.APIConnectionError:
            wait = 2 ** min(attempt, 3)
            if attempt < min(max_retries - 1, 2):
                logger.warning("conn_error", agent=agent_name, wait_s=wait)
                print(f"\n{YELLOW}  ⚠ [{agent_name}] 連線錯誤，{wait}s 後重試...{RESET}")
                time.sleep(wait)
            else:
                raise

        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                wait = 2 ** attempt
                if attempt < min(max_retries - 1, 1):
                    logger.warning("server_error", agent=agent_name,
                                   status=e.status_code, wait_s=wait)
                    print(f"\n{YELLOW}  ⚠ [{agent_name}] 伺服器錯誤 ({e.status_code})，{wait}s 後重試...{RESET}")
                    time.sleep(wait)
                else:
                    raise
            elif e.status_code == 529:
                wait = 5 * (attempt + 1)
                if attempt < max_retries - 1:
                    time.sleep(wait)
                else:
                    raise
            else:
                raise  # 4xx 客戶端錯誤不重試


# ══════════════════════════════════════════════════════════════════
#  全域 Session Budget
# ══════════════════════════════════════════════════════════════════

_session_budget: TokenBudget | None = None

def get_session_budget() -> TokenBudget:
    global _session_budget
    if _session_budget is None:
        _session_budget = TokenBudget()
    return _session_budget

def init_session_budget(budget_usd: float = DEFAULT_BUDGET_USD,
                        model: str = ModelID.OPUS_46) -> TokenBudget:
    global _session_budget
    _session_budget = TokenBudget(budget_usd=budget_usd, model=model)
    return _session_budget


# ══════════════════════════════════════════════════════════════════
#  BaseAgent v4
# ══════════════════════════════════════════════════════════════════

class BaseAgent:
    name:     str  = "AGENT"
    title:    str  = "Agent"
    dept:     str  = "default"
    emoji:    str  = "🤖"
    color:    str  = "\033[37m"
    skills:   list = []
    personality_traits: dict = {}
    system_prompt: str = ""

    def __init__(self, workdir: str | None = None, auto_confirm: bool = False,
                 budget_usd: float | None = None):
        self.client   = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY", "")
        )
        # 模型選擇完全委託給 config.py
        self.model    = cfg.model_for_agent(self.name)
        self.workdir  = workdir or os.getcwd()
        self.executor = ToolExecutor(workdir=self.workdir, auto_confirm=auto_confirm)
        self.memory_file          = MEMORY_DIR / f"{self.name.lower()}_memory.json"
        self.conversation_history = self._load_memory()
        self._budget              = get_session_budget()

    # ── 記憶管理 ───────────────────────────────────────────────────

    def _load_memory(self) -> list:
        if self.memory_file.exists():
            try:
                return json.loads(self.memory_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("memory_load_failed", agent=self.name, error=str(e))
        return []

    def _save_memory(self) -> None:
        trimmed = self.conversation_history[-MAX_HISTORY_LEN:]
        # 原子寫入（防止中斷導致記憶檔損毀）
        tmp = self.memory_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(trimmed, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        tmp.replace(self.memory_file)

    def clear_memory(self) -> None:
        self.conversation_history = []
        if self.memory_file.exists():
            self.memory_file.unlink()
        self._print_system("記憶已清除")

    def set_workdir(self, path: str) -> None:
        self.workdir  = str(Path(path).resolve())
        self.executor = ToolExecutor(workdir=self.workdir,
                                     auto_confirm=self.executor.auto_confirm)
        self._print_system(f"工作目錄 → {self.workdir}")

    # ── 終端 UI ────────────────────────────────────────────────────

    def _header(self, mode: str = "") -> str:
        ts       = datetime.now().strftime("%H:%M:%S")
        mode_tag = f" [{mode}]" if mode else ""
        budget   = self._budget
        cost_str = f"${budget.total_cost_usd:.3f}/${budget.budget_usd:.1f}"
        return (
            f"\n{self.color}{BOLD}┌─ {self.emoji} {self.name}{RESET}"
            f"{DIM} · {self.title}{mode_tag} · "
            f"{_model_display_tag(self.model)} · {ts} · 💰{cost_str}{RESET}"
        )

    def _footer(self) -> str:
        return f"{self.color}└{'─'*58}{RESET}\n"

    def _print_system(self, msg: str) -> None:
        print(f"\n{DIM}  ⚙ [{self.name}] {msg}{RESET}")

    def _print_tool_call(self, name: str, inp: dict) -> None:
        args = ", ".join(f"{k}={repr(v)[:50]}" for k, v in inp.items())
        print(f"\n{self.color}│{RESET} {CYAN}🔧 {name}({args}){RESET}")

    def _print_tool_result(self, result: str) -> None:
        preview = result[:200].replace("\n", " ")
        suffix  = "..." if len(result) > 200 else ""
        print(f"{self.color}│{RESET} {DIM}   → {preview}{suffix}{RESET}")

    def _stream_text(self, text: str) -> None:
        print(f"{self.color}│{RESET} ", end="", flush=True)
        for ch in text:
            print(ch, end="", flush=True)
            if ch == "\n":
                print(f"{self.color}│{RESET} ", end="", flush=True)
        print()

    # ── History 截斷 ──────────────────────────────────────────────

    def _trim_history(self) -> None:
        if len(self.conversation_history) > MAX_HISTORY_LEN:
            self.conversation_history = self.conversation_history[-MAX_HISTORY_LEN:]

    # ── System Prompt 建構 ────────────────────────────────────────

    def _build_system_prompt(self, with_tools: bool = False,
                              use_cache: bool = True) -> list[dict] | str:
        """
        建立 system prompt。
        - TokenGuard：防止 context window 溢位
        - Prompt Caching（1h TTL，GA）：system prompt 固定部分快取後省 90%
        """
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

        prompt_text = f"""你是 SYNTHEX AI STUDIO 的 {self.emoji} {self.name}，職位：{self.title}。

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
        # TokenGuard：截斷過長的 system prompt
        guard = TokenGuard(self.model)
        if not guard.check(prompt_text):
            prompt_text = guard.truncate(prompt_text, label="system_prompt")

        # Prompt Caching（ephemeral = 1h TTL，已 GA）
        est_tokens = len(prompt_text) // 4
        if use_cache and est_tokens >= CACHE_MIN_TOKENS:
            return [{"type": "text", "text": prompt_text,
                     "cache_control": cfg.cache_control_block()}]
        return prompt_text

    def _build_run_params(self, tools: list, messages: list) -> dict:
        """建立 run() 的 API 參數（含 Adaptive Thinking + Prompt Cache）"""
        params: dict = dict(
            model      = self.model,
            max_tokens = cfg.max_output_tokens(self.model),
            system     = self._build_system_prompt(with_tools=True),
            tools      = tools,
            messages   = messages,
        )

        is_thinking_agent = self.name in ADAPTIVE_THINKING_AGENTS
        is_adaptive_model = self.model in (ModelID.OPUS_46, ModelID.SONNET_46)

        if is_thinking_agent:
            if is_adaptive_model:
                params["thinking"] = {"type": "auto"}
            else:
                params["thinking"] = {
                    "type":          "enabled",
                    "budget_tokens": THINKING_BUDGET["normal"],
                }
            # 注入 beta header（若已 GA 將 BETA_INTERLEAVED_THINKING 設為 None）
            if BETA_INTERLEAVED_THINKING:
                params["betas"] = [BETA_INTERLEAVED_THINKING]

        return params

    # ── 對話模式 ──────────────────────────────────────────────────

    def chat(self, user_message: str, context: str = "") -> str:
        """純對話模式 — 帶重試 + Token 追蹤 + Streaming"""
        self._budget.check_budget()

        full_msg = f"[上下文]\n{context}\n\n[問題]\n{user_message}" if context else user_message
        self.conversation_history.append({"role": "user", "content": full_msg})
        self._trim_history()
        print(self._header("對話"))

        response_text  = ""
        is_adaptive    = self.model in (ModelID.OPUS_46, ModelID.SONNET_46)
        use_thinking   = self.name in ADAPTIVE_THINKING_AGENTS
        thinking_chars = 0

        try:
            stream_params: dict = dict(
                model      = self.model,
                max_tokens = cfg.max_output_tokens(self.model),
                system     = self._build_system_prompt(with_tools=False),
                messages   = self.conversation_history,
            )
            if use_thinking:
                stream_params["thinking"] = (
                    {"type": "auto"} if is_adaptive
                    else {"type": "enabled",
                          "budget_tokens": THINKING_BUDGET["deep"]}
                )
                # Haiku 不支援 thinking → 升級到 Sonnet
                if stream_params["model"] == ModelID.HAIKU_45:
                    stream_params["model"] = ModelID.SONNET_46

            input_tokens = output_tokens = 0
            cache_read   = cache_write   = 0

            with self.client.messages.stream(**stream_params) as stream:
                for event in stream:
                    if hasattr(event, "type"):
                        # 思考塊：顯示進度點，不顯示內容
                        if event.type == "content_block_start":
                            cb = getattr(event, "content_block", None)
                            if cb and getattr(cb, "type", "") == "thinking":
                                print("💭", end="", flush=True)
                        # 文字串流
                        if event.type == "content_block_delta":
                            delta = getattr(event, "delta", None)
                            if delta:
                                if getattr(delta, "type", "") == "text_delta":
                                    chunk = delta.text
                                    response_text += chunk
                                    print(chunk, end="", flush=True)
                                elif getattr(delta, "type", "") == "thinking_delta":
                                    thinking_chars += len(getattr(delta, "thinking", ""))

                final_msg = stream.get_final_message()
                if hasattr(final_msg, "usage"):
                    u = final_msg.usage
                    input_tokens  = u.input_tokens
                    output_tokens = u.output_tokens
                    cache_read    = getattr(u, "cache_read_input_tokens", 0)
                    cache_write   = getattr(u, "cache_creation_input_tokens", 0)

            print(f"{RESET}")

            if use_thinking and thinking_chars:
                self._print_system(f"💭 思考過程：{thinking_chars:,} 字元")
            if cache_read:
                self._print_system(f"⚡ Cache 命中：{cache_read:,} tokens（節省費用）")

            if input_tokens or output_tokens:
                self._budget.record(self.name, input_tokens, output_tokens,
                                    cache_read, cache_write)
                cost = cfg.calc_cost(self.model, input_tokens, output_tokens,
                                     cache_read, cache_write)
                self._print_system(
                    f"tokens: {input_tokens:,}in + {output_tokens:,}out "
                    f"= ${cost:.4f}"
                )

            logger.info("chat_done", agent=self.name,
                        input_tokens=input_tokens, output_tokens=output_tokens,
                        cache_read=cache_read)

        except BudgetExceededError:
            raise
        except Exception as e:
            response_text = f"[API 錯誤] {e}"
            logger.error("chat_error", agent=self.name, error=str(e))
            print(f"{RED}  ✖ {response_text}{RESET}")

        print(self._footer())
        self.conversation_history.append({"role": "assistant", "content": response_text})
        self._save_memory()
        return response_text

    # ── Agentic 模式 ──────────────────────────────────────────────

    def run(self, task: str, context: str = "", max_iterations: int = 20,
            enable_compaction: bool = True) -> str:
        """
        Agentic 模式 — 帶重試 + Token 追蹤 + Budget Guard + Context Compaction。

        Args:
            task:               任務描述
            context:            額外上下文
            max_iterations:     最大工具循環次數
            enable_compaction:  啟用 Context Compaction（長任務建議保持 True）
        """
        self._budget.check_budget()

        tools       = get_tools_for_role(self.dept)
        full_task   = f"[上下文]\n{context}\n\n[任務]\n{task}" if context else task
        messages    = list(self.conversation_history) + [{"role": "user", "content": full_task}]
        compaction  = CompactionManager(
            model=self.model,
            agent_name=self.name,
            threshold=COMPACTION_TOKEN_THRESHOLD,
        ) if enable_compaction else None

        print(self._header("Agentic"))
        self._print_system(
            f"工具: {len(tools)} 個，最多 {max_iterations} 輪"
            + ("，Compaction: 開啟" if compaction else "")
        )

        final_text = ""
        iteration  = 0

        while iteration < max_iterations:
            iteration += 1
            self._budget.check_budget()

            # ── 建立 API 參數 ─────────────────────────────────────
            params = self._build_run_params(tools=tools, messages=messages)

            # 注入 Context Management（server-side tool result clearing）
            if compaction:
                cm_params = compaction.build_context_management_params()
                if "betas" in cm_params:
                    existing_betas = params.get("betas", [])
                    merged = list(set(existing_betas + cm_params["betas"]))
                    params["betas"] = merged
                if "context_management" in cm_params:
                    params["context_management"] = cm_params["context_management"]

            try:
                def _call(p=params):
                    return self.client.messages.create(**p)

                response = _circuit_breaker.call(
                    self.name,
                    lambda: _api_call_with_retry(_call, agent_name=self.name)
                )

                if hasattr(response, "usage"):
                    u = response.usage
                    in_tok     = u.input_tokens
                    out_tok    = u.output_tokens
                    cache_read = getattr(u, "cache_read_input_tokens", 0)
                    cache_write= getattr(u, "cache_creation_input_tokens", 0)
                    self._budget.record(self.name, in_tok, out_tok,
                                        cache_read, cache_write)

                    # 手動 Compaction 觸發（token 超過閾值時）
                    if (compaction and
                            compaction.should_compact(messages, in_tok) and
                            iteration % 3 == 0):   # 每 3 輪才觸發一次（避免頻繁）
                        self._print_system(
                            f"⟳ Context Compaction 觸發（{in_tok:,} tokens）"
                        )
                        sys_prompt = self._build_system_prompt(with_tools=True)
                        messages   = compaction.compact(messages, self.client, sys_prompt)

            except BudgetExceededError:
                raise
            except Exception as e:
                msg = f"[API 錯誤] {e}"
                logger.error("run_error", agent=self.name,
                             iteration=iteration, error=str(e))
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
                compact_info = (
                    f"，Compaction {compaction.compacted_count} 次"
                    if compaction and compaction.compacted_count else ""
                )
                self._print_system(f"✔ 完成（{iteration} 輪{compact_info}）")
                logger.info("run_done", agent=self.name, iterations=iteration,
                            compactions=compaction.compacted_count if compaction else 0)
                break
            elif response.stop_reason != "tool_use":
                self._print_system(f"停止: {response.stop_reason}")
                break
        else:
            self._print_system(f"⚠ 達到最大迭代次數 ({max_iterations})")
            logger.warning("max_iterations", agent=self.name, max=max_iterations)

        print(self._footer())
        self.conversation_history.append({"role": "user",      "content": task})
        self.conversation_history.append({"role": "assistant", "content": final_text or "[完成]"})
        self._save_memory()
        return final_text

    # ── 快捷方法 ──────────────────────────────────────────────────

    def review(self, content: str) -> str:
        return self.chat(f"請審查以下內容，提供專業意見和改進建議：\n\n{content}")

    def plan(self, task: str) -> str:
        return self.chat(f"請為以下任務制定詳細執行計畫：\n\n{task}")

    def do(self, task: str) -> str:
        return self.run(task)

    def explain(self, topic: str) -> str:
        return self.chat(f"請從你的專業角度解釋：{topic}")
