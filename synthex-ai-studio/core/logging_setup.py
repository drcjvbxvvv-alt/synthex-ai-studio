"""
core/logging_setup.py — 結構化日誌設定 (v3.0)

問題：SYNTHEX 有 209 個 print()，0 個 logger 呼叫。
    生產環境無法設定 log level，無法輸出到文件，無法整合監控系統。

解決方案：
  - structlog：結構化 JSON 日誌，每條都帶 timestamp/agent/phase/cost
  - 統一的 get_logger() 函數，取代 print()
  - 同時保留終端機彩色輸出（開發模式）和 JSON 輸出（生產模式）
  - Context Window 保護（TokenGuard）：在 API 呼叫前截斷過長文件

安全設計：
  - log 輸出不包含 API key、用戶程式碼、敏感業務邏輯
  - TokenGuard 截斷時保留文件頭部摘要 + 結尾（最重要的部分）
  - 成本估算即時附加到每條日誌

使用方式：
  from core.logging_setup import get_logger, TokenGuard

  log = get_logger("base_agent", agent="NEXUS")
  log.info("api_call", model="claude-opus-4-6", tokens=1234)
  log.warning("budget_warning", used=4.5, limit=5.0)

  # Context Window 保護
  guard = TokenGuard("claude-opus-4-6")
  safe_content = guard.truncate(large_document)
"""

from __future__ import annotations

import os
import sys
import logging
from typing import Any

try:
    import structlog
    _HAS_STRUCTLOG = True
except ImportError:
    _HAS_STRUCTLOG = False


# ── 字元到 Token 估算（粗略，4 chars ≈ 1 token）────────────────
# 更精確的方式是 Anthropic Token Counting API，但這個足夠做截斷保護
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """估算文字的 token 數（用於截斷保護，精確度 ±30%）"""
    return max(0, len(text) // _CHARS_PER_TOKEN)


# ── 全域日誌設定 ──────────────────────────────────────────────────

def setup_logging(
    level:  str = "WARNING",
    format: str = "json",        # "json" | "text"
) -> None:
    """
    初始化 structlog 日誌系統。
    在程式最開始呼叫一次（main() 或 synthex.py 頂部）。
    """
    if not _HAS_STRUCTLOG:
        logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
        return

    log_level = getattr(logging, level.upper(), logging.WARNING)

    # 基礎 Python logging 設定
    logging.basicConfig(
        format    = "%(message)s",
        stream    = sys.stderr,
        level     = log_level,
    )

    # 抑制第三方庫的詳細日誌
    for noisy in ("httpcore", "httpx", "anthropic", "chromadb", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Shared processors（所有日誌都經過）
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if format == "json":
        # 生產模式：每行一個 JSON 物件
        renderer = structlog.processors.JSONRenderer()
    else:
        # 開發模式：彩色可讀輸出
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors = shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class        = structlog.make_filtering_bound_logger(log_level),
        context_class        = dict,
        logger_factory       = structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use = True,
    )


def get_logger(name: str = "synthex", **initial_ctx) -> Any:
    """
    取得一個已帶有預設 context 的 logger。

    Args:
        name:        logger 名稱（通常是模組名）
        **initial_ctx: 每條日誌都會附帶的 context（如 agent="NEXUS", phase=4）

    Returns:
        structlog 的 BoundLogger，或 fallback 到 Python logging
    """
    if _HAS_STRUCTLOG:
        log = structlog.get_logger(name)
        if initial_ctx:
            log = log.bind(**initial_ctx)
        return log
    else:
        return logging.getLogger(name)


# ── 統一輸出函數（過渡期：取代 print() 的橋接）──────────────────

def log_ok(msg: str, **ctx) -> None:
    """成功訊息（取代 _ok()）"""
    get_logger("orchestrator").info("phase_ok", message=msg, **ctx)

def log_warn(msg: str, **ctx) -> None:
    """警告訊息（取代 _warn()）"""
    get_logger("orchestrator").warning("phase_warning", message=msg, **ctx)

def log_cost(agent: str, model: str, in_tok: int, out_tok: int, cost: float) -> None:
    """API 成本記錄"""
    get_logger("cost").info(
        "api_call",
        agent         = agent,
        model         = model,
        input_tokens  = in_tok,
        output_tokens = out_tok,
        cost_usd      = round(cost, 6),
    )

def log_phase(phase: int, name: str, status: str, duration_ms: int = 0) -> None:
    """Phase 狀態記錄"""
    get_logger("pipeline").info(
        "phase_status",
        phase       = phase,
        name        = name,
        status      = status,
        duration_ms = duration_ms,
    )


# ── Context Window 保護 ───────────────────────────────────────────

class TokenGuard:
    """
    Context Window 溢出保護。
    
    在把文件內容傳給 API 之前，確保 token 數不超過模型上限。
    截斷策略：保留前 40% + 後 30%，去掉中間（通常是較不重要的細節）。
    
    安全設計：
      - 不依賴外部 API（估算，不計費）
      - 截斷後保留 [TRUNCATED: N tokens removed] 標記
      - 永遠不截斷到 0（至少保留 500 tokens 的內容）
    """

    def __init__(self, model: str, reserve_output_tokens: int = 4_096):
        from core.config import SAFE_INPUT_LIMITS
        self.model     = model
        self.max_input = SAFE_INPUT_LIMITS.get(model, 160_000)
        self.reserve   = reserve_output_tokens   # 為輸出留的空間
        # budget 以字元為單位（safe_input_limit 是 tokens，轉為 chars）
        self.budget    = max(500 * _CHARS_PER_TOKEN,
                             (self.max_input - reserve_output_tokens) * _CHARS_PER_TOKEN)

    def check(self, *texts: str) -> bool:
        """檢查所有文字加總是否在限制內"""
        total = sum(estimate_tokens(t) for t in texts)
        return total <= self.max_input - self.reserve

    def truncate(self, text: str, label: str = "document") -> str:
        """
        截斷文字到安全長度。

        截斷策略：
          - 前 40%：架構說明、模組頭部（最重要）
          - 後 30%：結論、總結（次重要）
          - 中間 30%：丟棄（通常是細節實作）
        """
        if len(text) <= self.budget:
            return text

        tokens_est  = estimate_tokens(text)
        budget_tok  = self.max_input - self.reserve
        budget_char = budget_tok * _CHARS_PER_TOKEN

        head_chars = int(budget_char * 0.45)
        tail_chars = int(budget_char * 0.35)
        removed    = tokens_est - budget_tok

        head = text[:head_chars]
        tail = text[-tail_chars:] if tail_chars > 0 else ""

        truncation_note = (
            f"\n\n[TokenGuard: {label} 已截斷，移除約 {removed:,} tokens（中間部分）]\n\n"
        )

        result = head + truncation_note + tail

        get_logger("token_guard").warning(
            "content_truncated",
            label         = label,
            model         = self.model,
            original_tok  = tokens_est,
            budget_tok    = budget_tok,
            removed_tok   = removed,
        )

        return result

    def fit_messages(self, messages: list[dict], system_tokens: int = 0) -> list[dict]:
        """
        截斷 messages 列表使其符合 context window。
        策略：保留最新的訊息，截斷最舊的（歷史可以丟，最新任務不能丟）。
        """
        if not messages:
            return messages

        budget = self.max_input - self.reserve - system_tokens
        total  = 0
        result = []

        # 從最新往前加（保留最新）
        for msg in reversed(messages):
            content = msg.get("content", "")
            if isinstance(content, list):
                tok = sum(estimate_tokens(b.get("text", ""))
                          for b in content if isinstance(b, dict))
            else:
                tok = estimate_tokens(str(content))

            if total + tok > budget:
                break
            result.insert(0, msg)
            total += tok

        if len(result) < len(messages):
            dropped = len(messages) - len(result)
            get_logger("token_guard").warning(
                "messages_truncated",
                dropped        = dropped,
                kept           = len(result),
                total_tok_est  = total,
            )

        return result
