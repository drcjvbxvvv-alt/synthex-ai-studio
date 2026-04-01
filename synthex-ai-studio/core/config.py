"""
core/config.py — SYNTHEX 集中設定管理 (v0.0.0)

設計原則：
  1. 單一真相來源（Single Source of Truth）：所有模型版本、超時值、成本設定
     都在這個檔案，不需要 grep 整個程式碼庫
  2. 啟動 fail-fast：必要設定在啟動時立即驗證，不等到第一次 API 呼叫才報錯
  3. 型別安全：pydantic-settings 提供型別驗證和環境變數自動讀取
  4. 可覆蓋：支援 .env 檔案、環境變數、程式碼覆蓋（測試用）

模型版本管理：
  - HAIKU 3 已於 2026-04-19 退役，全面遷移到 Haiku 4.5
  - 使用 ModelID 常數而非字串，一次修改全部生效
  - 每個 Tier 的最大 token 上限、context window 都集中定義

使用方式：
  from core.config import cfg, ModelID, Tier

  # 取得 Sonnet 模型 ID
  model = cfg.model_for_tier(Tier.SONNET)

  # 取得 Context Window 上限
  ctx_limit = cfg.context_window(model)

  # 驗證設定（啟動時呼叫）
  cfg.validate_startup()
"""

from __future__ import annotations

import os
import sys
from enum import Enum
from typing import Optional
from pathlib import Path

try:
    from pydantic import Field, field_validator, model_validator
    from pydantic_settings import BaseSettings, SettingsConfigDict
    _HAS_PYDANTIC = True
except ImportError:
    _HAS_PYDANTIC = False


# ── 模型 ID 常數（唯一定義，2026-03 現行版本）──────────────────
class ModelID:
    """
    Anthropic 模型版本集中管理。
    
    模型選型依據（2026-03）：
      OPUS_46：最強推理，Agent Team，50% 任務時間範圍 14.5 小時，1M context
      SONNET_46：均衡效能，1M context beta，Extended Thinking，速度快
      SONNET_45：穩定生產，Structured Output GA，工具調用最佳化
      HAIKU_45：快速低成本，Near-frontier，適合高頻低複雜度任務
    
    已退役（2026-04-19）：
      claude-3-haiku-20240307（Haiku 3）→ 全面遷移到 Haiku 4.5
    """
    # ── 現行推薦（2026-03）────────────────────────────────────────
    OPUS_46    = "claude-opus-4-6"     # 旗艦，Agent Team，14.5h 任務
    SONNET_46  = "claude-sonnet-4-6"   # 均衡，1M context beta，Adaptive Thinking
    SONNET_45  = "claude-sonnet-4-5"   # 生產穩定，Structured Output GA
    HAIKU_45   = "claude-haiku-4-5"    # 快速低成本（取代已退役的 Haiku 3）

    # ── 仍可用（legacy）─────────────────────────────────────────
    OPUS_45    = "claude-opus-4-5"
    OPUS_46_FULL = "claude-opus-4-6"

    # ── 已退役（不可使用）───────────────────────────────────────
    # HAIKU_3  = "claude-3-haiku-20240307"  # 2026-04-19 退役
    # SONNET_35 = "claude-3-5-sonnet-20241022"  # 已退役


class Tier(Enum):
    """Agent 工作負荷等級"""
    OPUS   = "opus"    # 複雜推理、架構設計、深度分析（NEXUS/SIGMA/ATOM）
    SONNET = "sonnet"  # 主要開發工作（BYTE/STACK/TRACE/ECHO 等）
    HAIKU  = "haiku"   # 快速輔助任務（RELAY/BRIDGE/PROBE 等）


# ── Context Window 限制（token）──────────────────────────────────
# 2026-03-13：Opus 4.6 + Sonnet 4.6 的 1M context 正式 GA
# 無溢價，不需要 beta header，標準費率計費
CONTEXT_WINDOWS: dict[str, int] = {
    ModelID.OPUS_46:   1_000_000,   # 1M GA（2026-03-13 起，全平台）
    ModelID.SONNET_46: 1_000_000,   # 1M GA（2026-03-13 起）
    ModelID.SONNET_45:  200_000,
    ModelID.HAIKU_45:   200_000,
    ModelID.OPUS_45:    200_000,
}

# ── 安全輸入 Token 上限（實際 context window 的 80%，留緩衝）───
SAFE_INPUT_LIMITS: dict[str, int] = {
    k: int(v * 0.80) for k, v in CONTEXT_WINDOWS.items()
}

# ── 輸出 Token 上限 ──────────────────────────────────────────────
MAX_OUTPUT_TOKENS: dict[str, int] = {
    ModelID.OPUS_46:   32_000,
    ModelID.SONNET_46: 16_000,
    ModelID.SONNET_45:  8_192,
    ModelID.HAIKU_45:   8_192,
    ModelID.OPUS_45:   32_000,
}

# ── 每百萬 token 成本（USD，2026-03 參考）────────────────────────
MODEL_COSTS_PER_MTK: dict[str, dict[str, float]] = {
    ModelID.OPUS_46:   {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    ModelID.SONNET_46: {"input":  3.0, "output": 15.0, "cache_write":  3.75, "cache_read": 0.30},
    ModelID.SONNET_45: {"input":  3.0, "output": 15.0, "cache_write":  3.75, "cache_read": 0.30},
    ModelID.HAIKU_45:  {"input":  0.8, "output":  4.0, "cache_write":  1.00, "cache_read": 0.08},
    ModelID.OPUS_45:   {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
}

# ── Agent Tier 對應（集中定義，取代各處硬編碼）──────────────────
AGENT_TIER_MAP: dict[str, Tier] = {
    # Opus：需要最深推理的 Agent
    "NEXUS": Tier.OPUS, "SIGMA": Tier.OPUS, "ATOM": Tier.OPUS,
    "NOVA":  Tier.OPUS, "ARIA":  Tier.OPUS,
    # Sonnet：主要開發工作
    "ECHO":  Tier.SONNET, "BYTE": Tier.SONNET, "STACK": Tier.SONNET,
    "TRACE": Tier.SONNET, "FORGE":Tier.SONNET, "SHIELD":Tier.SONNET,
    "SPARK": Tier.SONNET, "VISTA":Tier.SONNET, "PRISM": Tier.SONNET,
    "VOLT":  Tier.SONNET, "FLUX": Tier.SONNET, "PROBE": Tier.SONNET,
    "MEMO":  Tier.SONNET, "QUANT":Tier.SONNET, "LUMI":  Tier.SONNET,
    "RIFT":  Tier.SONNET, "KERN": Tier.SONNET,
    # Haiku：快速輔助
    "RELAY": Tier.HAIKU, "BRIDGE":Tier.HAIKU, "WIRE": Tier.HAIKU,
    "BOLT":  Tier.HAIKU, "ATLAS": Tier.HAIKU, "PULSE":Tier.HAIKU,
}

# ── Adaptive Thinking Agent（使用 type=auto）───────────────────
ADAPTIVE_THINKING_AGENTS: frozenset[str] = frozenset({
    "NEXUS", "SIGMA", "ARIA", "NOVA", "ATOM"
})

# ── 超時設定（秒，集中管理）─────────────────────────────────────
TIMEOUTS = {
    "phase_default":   300,   # 一般 Phase
    "phase_long":      600,   # 長時間 Phase（實作類）
    "phase_parallel":  600,   # 並行 Phase timeout
    "agent_run":       300,   # 單次 Agent run()
    "agent_chat":      120,   # 單次 Agent chat()
    "tool_default":     60,   # 工具執行
    "tool_long":       180,   # 長時間工具（測試/部署）
    "http_request":     30,   # HTTP 請求
    "git_operation":    60,   # git 操作
}


# ── 主設定類 ──────────────────────────────────────────────────────

if _HAS_PYDANTIC:
    class SynthexConfig(BaseSettings):
        """
        SYNTHEX 集中設定（pydantic-settings 驗證）。
        
        優先順序：環境變數 > .env 檔案 > 預設值
        啟動時呼叫 validate_startup() 確保關鍵設定存在。
        """

        model_config = SettingsConfigDict(
            env_file        = ".env",
            env_file_encoding = "utf-8",
            case_sensitive  = False,
            extra           = "ignore",
        )

        # ── 必要設定 ────────────────────────────────────────────
        anthropic_api_key: str = Field(
            default="",
            description="Anthropic API Key（必要）",
        )

        # ── 模型設定 ────────────────────────────────────────────
        model_opus:   str = Field(default=ModelID.OPUS_46)
        model_sonnet: str = Field(default=ModelID.SONNET_46)
        model_haiku:  str = Field(default=ModelID.HAIKU_45)

        # ── 效能設定 ────────────────────────────────────────────
        max_tokens_default: int = Field(default=8_192, ge=256, le=64_000)
        cache_ttl_minutes:  int = Field(default=60,    ge=5,   le=60)  # 1h default
        swarm_max_workers:  int = Field(default=4,     ge=1,   le=8)

        # ── 成本控制 ────────────────────────────────────────────
        budget_usd:         float = Field(default=5.0,  ge=0.1, le=100.0)

        # ── 工作目錄 ────────────────────────────────────────────
        workdir:            str   = Field(default=".")
        log_level:          str   = Field(default="WARNING")
        log_format:         str   = Field(default="json")   # json | text

        @field_validator("anthropic_api_key")
        @classmethod
        def api_key_format(cls, v: str) -> str:
            if v and not (v.startswith("sk-ant-") or v.startswith("sk-")):
                raise ValueError(
                    "ANTHROPIC_API_KEY 格式無效（應以 sk-ant- 或 sk- 開頭）"
                )
            return v

        @field_validator("model_opus", "model_sonnet", "model_haiku")
        @classmethod
        def valid_model(cls, v: str) -> str:
            valid = {
                ModelID.OPUS_46, ModelID.OPUS_45,
                ModelID.SONNET_46, ModelID.SONNET_45,
                ModelID.HAIKU_45,
            }
            if v not in valid:
                raise ValueError(f"無效的模型 ID：{v!r}，有效值：{valid}")
            return v

        # ── 公開方法 ────────────────────────────────────────────

        def model_for_tier(self, tier: Tier) -> str:
            """根據 Tier 回傳對應的模型 ID"""
            return {
                Tier.OPUS:   self.model_opus,
                Tier.SONNET: self.model_sonnet,
                Tier.HAIKU:  self.model_haiku,
            }[tier]

        def model_for_agent(self, agent_name: str) -> str:
            """根據 Agent 名稱回傳對應的模型 ID"""
            tier = AGENT_TIER_MAP.get(agent_name, Tier.SONNET)
            return self.model_for_tier(tier)

        def context_window(self, model: str) -> int:
            return CONTEXT_WINDOWS.get(model, 200_000)

        def safe_input_limit(self, model: str) -> int:
            return SAFE_INPUT_LIMITS.get(model, 160_000)

        def max_output_tokens(self, model: str) -> int:
            return MAX_OUTPUT_TOKENS.get(model, 8_192)

        def calc_cost(
            self,
            model:        str,
            input_tokens: int,
            output_tokens:int,
            cache_read:   int = 0,
            cache_write:  int = 0,
        ) -> float:
            """精確計算 API 呼叫成本（USD）"""
            costs = MODEL_COSTS_PER_MTK.get(model, MODEL_COSTS_PER_MTK[ModelID.SONNET_45])
            return (
                input_tokens  * costs["input"]        / 1_000_000
                + output_tokens * costs["output"]      / 1_000_000
                + cache_read    * costs["cache_read"]  / 1_000_000
                + cache_write   * costs["cache_write"] / 1_000_000
            )

        def validate_startup(self) -> None:
            """
            啟動 fail-fast 驗證。在 main() 最開始呼叫。
            有問題立即報錯，不等到第一次 API 呼叫。
            """
            errors = []

            if not self.anthropic_api_key:
                errors.append(
                    "ANTHROPIC_API_KEY 未設定。"
                    "請設定環境變數或建立 .env 檔案。"
                )

            if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
                errors.append(f"LOG_LEVEL 無效：{self.log_level!r}")

            if errors:
                msg = "\n".join(f"  [設定錯誤] {e}" for e in errors)
                print(f"[SYNTHEX] 設定驗證失敗：\n{msg}", file=sys.stderr)
                sys.exit(1)

        def cache_control_block(self) -> dict:
            """
            回傳 Prompt Cache control dict。
            1 小時 TTL（ephemeral）已 GA，不需要 beta header。
            """
            return {"type": "ephemeral"}

else:
    # pydantic-settings 未安裝時的 fallback
    class SynthexConfig:  # type: ignore
        def __init__(self):
            self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            self.model_opus        = ModelID.OPUS_46
            self.model_sonnet      = ModelID.SONNET_46
            self.model_haiku       = ModelID.HAIKU_45
            self.max_tokens_default= 8_192
            self.cache_ttl_minutes = 60
            self.swarm_max_workers = 4
            self.budget_usd        = 5.0
            self.workdir           = "."
            self.log_level         = "WARNING"
            self.log_format        = "json"

        def model_for_tier(self, tier):
            return {Tier.OPUS: self.model_opus,
                    Tier.SONNET: self.model_sonnet,
                    Tier.HAIKU: self.model_haiku}[tier]

        def model_for_agent(self, agent_name):
            tier = AGENT_TIER_MAP.get(agent_name, Tier.SONNET)
            return self.model_for_tier(tier)

        def context_window(self, model):
            return CONTEXT_WINDOWS.get(model, 200_000)

        def safe_input_limit(self, model):
            return SAFE_INPUT_LIMITS.get(model, 160_000)

        def max_output_tokens(self, model):
            return MAX_OUTPUT_TOKENS.get(model, 8_192)

        def calc_cost(self, model, input_tokens, output_tokens,
                      cache_read=0, cache_write=0):
            costs = MODEL_COSTS_PER_MTK.get(model, MODEL_COSTS_PER_MTK[ModelID.SONNET_45])
            return (input_tokens * costs["input"] / 1_000_000
                    + output_tokens * costs["output"] / 1_000_000)

        def validate_startup(self):
            if not self.anthropic_api_key:
                print("[SYNTHEX] ANTHROPIC_API_KEY 未設定", file=sys.stderr)
                sys.exit(1)

        def cache_control_block(self):
            return {"type": "ephemeral"}


# ── 全域單例 ─────────────────────────────────────────────────────
try:
    cfg = SynthexConfig()  # type: ignore
except Exception as e:
    # 設定載入失敗時，提供最小可用設定（不 exit，讓 validate_startup 決定）
    cfg = SynthexConfig.__new__(SynthexConfig)  # type: ignore
    cfg.__dict__.update({
        "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "model_opus": ModelID.OPUS_46,
        "model_sonnet": ModelID.SONNET_46,
        "model_haiku": ModelID.HAIKU_45,
        "max_tokens_default": 8_192,
        "cache_ttl_minutes": 60,
        "swarm_max_workers": 4,
        "budget_usd": 5.0,
        "workdir": ".",
        "log_level": "WARNING",
        "log_format": "json",
    })
