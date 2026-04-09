"""
project_brain/brain_config.py

統一配置載入器：brain.toml + 環境變數優先鏈 + LLM client factory

優先順序（高 → 低）：
  1. 環境變數（BRAIN_LLM_PROVIDER / BRAIN_LLM_MODEL / BRAIN_LLM_BASE_URL 等）
  2. .brain/brain.toml（專案層級）
  3. ~/.config/brain/brain.toml（全域層級）
  4. 程式碼預設值

不存在 brain.toml 時行為與舊版完全相同。
"""
from __future__ import annotations

import logging
import os
import tomllib
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── 程式碼預設值 ───────────────────────────────────────────────────────────────

_DEFAULT_OLLAMA_URL   = "http://localhost:11434"
_DEFAULT_OLLAMA_MODEL = "gemma4:27b"
_DEFAULT_HAIKU_MODEL  = "claude-haiku-4-5-20251001"

# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class LLMFallbackConfig:
    provider: str = "anthropic"
    model:    str = _DEFAULT_HAIKU_MODEL


@dataclass
class LLMConfig:
    provider:    str              = "ollama"
    model:       str              = _DEFAULT_OLLAMA_MODEL
    base_url:    str              = _DEFAULT_OLLAMA_URL
    timeout:     int              = 30
    max_retries: int              = 3
    fallback:    LLMFallbackConfig = field(default_factory=LLMFallbackConfig)


@dataclass
class ModelOverride:
    """單一任務的模型覆蓋（Phase 3+ 用）"""
    model:    str
    fallback: str = ""   # 模型名稱（先降這個再降全域 fallback）


@dataclass
class PipelineSignalsConfig:
    git_commit:    bool = True
    task_complete: bool = True
    test_failure:  bool = False
    mcp_tool_call: bool = False
    knowledge_gap: bool = False


@dataclass
class PipelineRetentionConfig:
    signal_queue_done_days: int = 30
    signal_log_days:        int = 0
    pipeline_metrics_days:  int = 90


@dataclass
class PipelineGatesConfig:
    test_failure_count: int = 3


@dataclass
class PipelineConfig:
    enabled:                 bool                   = True
    worker_interval_seconds: int                    = 60
    max_queue_size:          int                    = 500
    max_auto_confidence:     float                  = 0.85
    llm:                     LLMConfig              = field(default_factory=LLMConfig)
    signals:                 PipelineSignalsConfig  = field(default_factory=PipelineSignalsConfig)
    retention:               PipelineRetentionConfig= field(default_factory=PipelineRetentionConfig)
    gates:                   PipelineGatesConfig    = field(default_factory=PipelineGatesConfig)
    models:                  dict[str, ModelOverride] = field(default_factory=dict)


@dataclass
class EmbedderConfig:
    provider: str = "ollama"
    model:    str = "nomic-embed-text"
    url:      str = _DEFAULT_OLLAMA_URL
    fallback: str = "local"


@dataclass
class DecayConfig:
    enabled:             bool  = True
    run_interval_hours:  int   = 24
    weight_time:         float = 0.25
    weight_version_gap:  float = 0.20
    weight_git_activity: float = 0.15
    weight_contradiction: float = 0.15
    weight_code_ref:     float = 0.15
    weight_query_freq:   float = 0.10


@dataclass
class ReviewModelConfig:
    provider: str = "ollama"
    model:    str = "gemma4:31b"           # Dense 模型，品質優先
    base_url: str = _DEFAULT_OLLAMA_URL


@dataclass
class ReviewConfig:
    auto_approve_threshold: float = 0.80
    staging_ttl_days:       int   = 30
    min_confidence:         float = 0.50
    llm: ReviewModelConfig = field(default_factory=ReviewModelConfig)


@dataclass
class FederationConfig:
    enabled:               bool  = False
    min_export_confidence: float = 0.6
    max_export_nodes:      int   = 500


@dataclass
class MCPConfig:
    port:           int = 7891
    rate_limit_rpm: int = 60


@dataclass
class ObservabilityConfig:
    log_level:          str  = "INFO"
    log_context_builds: bool = True
    daily_token_limit:  int  = 0


@dataclass
class BrainCoreConfig:
    max_context_tokens:  int   = 6000
    freshness_warn_days: int   = 30
    dedup_threshold:     float = 0.85


@dataclass
class BrainConfig:
    brain:       BrainCoreConfig   = field(default_factory=BrainCoreConfig)
    pipeline:    PipelineConfig    = field(default_factory=PipelineConfig)
    embedder:    EmbedderConfig    = field(default_factory=EmbedderConfig)
    decay:       DecayConfig       = field(default_factory=DecayConfig)
    review:      ReviewConfig      = field(default_factory=ReviewConfig)
    federation:  FederationConfig  = field(default_factory=FederationConfig)
    mcp:         MCPConfig         = field(default_factory=MCPConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)


# ── TOML 載入 ──────────────────────────────────────────────────────────────────

def _load_toml(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning("brain.toml 讀取失敗 (%s): %s，使用預設值", path, e)
        return {}


def _merge(base: dict, override: dict) -> dict:
    """遞迴合併，override 優先。"""
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _merge(result[k], v)
        else:
            result[k] = v
    return result


def _find_brain_dir(start: Optional[Path] = None) -> Optional[Path]:
    """從 start 往上找 .brain/ 目錄。"""
    here = Path(start or os.getcwd()).resolve()
    for candidate in [here, *here.parents]:
        bd = candidate / ".brain"
        if bd.is_dir():
            return bd
    return None


def _global_config_path() -> Path:
    return Path.home() / ".config" / "brain" / "brain.toml"


def _build_config(raw: dict) -> BrainConfig:
    """從合併後的 dict 建立 BrainConfig，不存在的 key 使用 dataclass 預設值。"""
    cfg = BrainConfig()

    b = raw.get("brain", {})
    cfg.brain.max_context_tokens  = b.get("max_context_tokens",  cfg.brain.max_context_tokens)
    cfg.brain.freshness_warn_days = b.get("freshness_warn_days", cfg.brain.freshness_warn_days)
    cfg.brain.dedup_threshold     = b.get("dedup_threshold",     cfg.brain.dedup_threshold)

    p = raw.get("pipeline", {})
    cfg.pipeline.enabled                 = p.get("enabled",                 cfg.pipeline.enabled)
    cfg.pipeline.worker_interval_seconds = p.get("worker_interval_seconds", cfg.pipeline.worker_interval_seconds)
    cfg.pipeline.max_queue_size          = p.get("max_queue_size",          cfg.pipeline.max_queue_size)
    cfg.pipeline.max_auto_confidence     = p.get("max_auto_confidence",     cfg.pipeline.max_auto_confidence)

    pg = p.get("gates", {})
    cfg.pipeline.gates.test_failure_count = pg.get("test_failure_count", cfg.pipeline.gates.test_failure_count)

    ps = p.get("signals", {})
    cfg.pipeline.signals.git_commit    = ps.get("git_commit",    cfg.pipeline.signals.git_commit)
    cfg.pipeline.signals.task_complete = ps.get("task_complete", cfg.pipeline.signals.task_complete)
    cfg.pipeline.signals.test_failure  = ps.get("test_failure",  cfg.pipeline.signals.test_failure)
    cfg.pipeline.signals.mcp_tool_call = ps.get("mcp_tool_call", cfg.pipeline.signals.mcp_tool_call)
    cfg.pipeline.signals.knowledge_gap = ps.get("knowledge_gap", cfg.pipeline.signals.knowledge_gap)

    pr = p.get("retention", {})
    cfg.pipeline.retention.signal_queue_done_days = pr.get("signal_queue_done_days", cfg.pipeline.retention.signal_queue_done_days)
    cfg.pipeline.retention.signal_log_days        = pr.get("signal_log_days",        cfg.pipeline.retention.signal_log_days)
    cfg.pipeline.retention.pipeline_metrics_days  = pr.get("pipeline_metrics_days",  cfg.pipeline.retention.pipeline_metrics_days)

    pl = p.get("llm", {})
    cfg.pipeline.llm.provider    = pl.get("provider",    cfg.pipeline.llm.provider)
    cfg.pipeline.llm.model       = pl.get("model",       cfg.pipeline.llm.model)
    cfg.pipeline.llm.base_url    = pl.get("base_url",    cfg.pipeline.llm.base_url)
    cfg.pipeline.llm.timeout     = pl.get("timeout",     cfg.pipeline.llm.timeout)
    cfg.pipeline.llm.max_retries = pl.get("max_retries", cfg.pipeline.llm.max_retries)

    pf = pl.get("fallback", {})
    cfg.pipeline.llm.fallback.provider = pf.get("provider", cfg.pipeline.llm.fallback.provider)
    cfg.pipeline.llm.fallback.model    = pf.get("model",    cfg.pipeline.llm.fallback.model)

    for task_name, mv in p.get("models", {}).items():
        if isinstance(mv, dict):
            cfg.pipeline.models[task_name] = ModelOverride(
                model    = mv.get("model", cfg.pipeline.llm.model),
                fallback = mv.get("fallback", ""),
            )
        elif isinstance(mv, str):
            cfg.pipeline.models[task_name] = ModelOverride(model=mv)

    em = raw.get("embedder", {})
    cfg.embedder.provider = em.get("provider", cfg.embedder.provider)
    cfg.embedder.model    = em.get("model",    cfg.embedder.model)
    cfg.embedder.url      = em.get("url",      cfg.embedder.url)
    cfg.embedder.fallback = em.get("fallback", cfg.embedder.fallback)

    d = raw.get("decay", {})
    cfg.decay.enabled             = d.get("enabled",             cfg.decay.enabled)
    cfg.decay.run_interval_hours  = d.get("run_interval_hours",  cfg.decay.run_interval_hours)
    cfg.decay.weight_time         = d.get("weight_time",         cfg.decay.weight_time)
    cfg.decay.weight_version_gap  = d.get("weight_version_gap",  cfg.decay.weight_version_gap)
    cfg.decay.weight_git_activity = d.get("weight_git_activity", cfg.decay.weight_git_activity)
    cfg.decay.weight_contradiction= d.get("weight_contradiction", cfg.decay.weight_contradiction)
    cfg.decay.weight_code_ref     = d.get("weight_code_ref",     cfg.decay.weight_code_ref)
    cfg.decay.weight_query_freq   = d.get("weight_query_freq",   cfg.decay.weight_query_freq)

    # 衰減權重加總驗證
    total = sum([
        cfg.decay.weight_time, cfg.decay.weight_version_gap,
        cfg.decay.weight_git_activity, cfg.decay.weight_contradiction,
        cfg.decay.weight_code_ref, cfg.decay.weight_query_freq,
    ])
    if abs(total - 1.0) > 0.01:
        logger.warning("decay 六因子權重加總為 %.2f（應為 1.0），請檢查 brain.toml [decay]", total)

    rv = raw.get("review", {})
    cfg.review.auto_approve_threshold = rv.get("auto_approve_threshold", cfg.review.auto_approve_threshold)
    cfg.review.staging_ttl_days       = rv.get("staging_ttl_days",       cfg.review.staging_ttl_days)
    cfg.review.min_confidence         = rv.get("min_confidence",          cfg.review.min_confidence)
    rvl = rv.get("model", {})
    cfg.review.llm.provider = rvl.get("provider", cfg.review.llm.provider)
    cfg.review.llm.model    = rvl.get("model",    cfg.review.llm.model)
    cfg.review.llm.base_url = rvl.get("base_url", cfg.review.llm.base_url)

    fed = raw.get("federation", {})
    cfg.federation.enabled               = fed.get("enabled",               cfg.federation.enabled)
    cfg.federation.min_export_confidence = fed.get("min_export_confidence", cfg.federation.min_export_confidence)
    cfg.federation.max_export_nodes      = fed.get("max_export_nodes",      cfg.federation.max_export_nodes)

    mcp = raw.get("mcp", {})
    cfg.mcp.port           = mcp.get("port",           cfg.mcp.port)
    cfg.mcp.rate_limit_rpm = mcp.get("rate_limit_rpm", cfg.mcp.rate_limit_rpm)

    obs = raw.get("observability", {})
    cfg.observability.log_level          = obs.get("log_level",          cfg.observability.log_level)
    cfg.observability.log_context_builds = obs.get("log_context_builds", cfg.observability.log_context_builds)
    cfg.observability.daily_token_limit  = obs.get("daily_token_limit",  cfg.observability.daily_token_limit)

    return cfg


def load_config(brain_dir: Optional[Path] = None) -> BrainConfig:
    """
    載入配置，套用三層優先鏈：
      全域 (~/.config/brain/brain.toml) → 專案 (.brain/brain.toml) → env var 覆蓋
    """
    global_raw  = _load_toml(_global_config_path())
    project_raw = _load_toml((brain_dir or Path()) / "brain.toml") if brain_dir else {}
    merged      = _merge(global_raw, project_raw)
    cfg         = _build_config(merged)

    # env var 覆蓋（最高優先）
    provider = os.environ.get("BRAIN_LLM_PROVIDER", "").lower()
    if provider:
        cfg.pipeline.llm.provider = provider
    model = os.environ.get("BRAIN_LLM_MODEL", "")
    if model:
        cfg.pipeline.llm.model = model
    base_url = os.environ.get("BRAIN_LLM_BASE_URL", "")
    if base_url:
        cfg.pipeline.llm.base_url = base_url

    # 舊版 BRAIN_OLLAMA_* 相容
    ollama_url = os.environ.get("BRAIN_OLLAMA_URL", "")
    if ollama_url and not base_url:
        cfg.pipeline.llm.base_url = ollama_url
    ollama_model = os.environ.get("BRAIN_OLLAMA_MODEL", "")
    if ollama_model and not model:
        cfg.pipeline.llm.model = ollama_model

    return cfg


# ── Ollama 可用性偵測 ──────────────────────────────────────────────────────────

def _is_ollama_available(base_url: str, timeout: int = 2) -> bool:
    try:
        url = base_url.rstrip("/")
        # 支援 /v1 結尾（OpenAI-compat）和純 Ollama URL
        tags_url = url.replace("/v1", "") + "/api/tags"
        urllib.request.urlopen(tags_url, timeout=timeout).close()
        return True
    except Exception:
        return False


# ── LLM Client Factory ────────────────────────────────────────────────────────

def get_llm_client(task: str = "default",
                   brain_dir: Optional[Path] = None) -> tuple[Any, str]:
    """
    根據 task 名稱取得 LLM client 與 model 名稱。
    自動套用多層 fallback chain：
      任務覆蓋模型 → 任務中間降級 → 全域主模型 → 全域 fallback（Haiku）

    Returns: (client, model_name)
    """
    cfg = load_config(brain_dir)
    llm = cfg.pipeline.llm

    # 1. 決定目標模型
    override     = cfg.pipeline.models.get(task)
    target_model = override.model if override else llm.model
    mid_fallback = override.fallback if override else ""

    # 2. 嘗試 Ollama（主要 + 中間降級）
    if llm.provider in ("ollama", "openai"):
        base_url = llm.base_url
        if _is_ollama_available(base_url, timeout=2):
            client, model = _make_openai_client(base_url, target_model)
            return client, model

        # 中間降級（例如 31B 不存在，降 27B）
        if mid_fallback:
            if _is_ollama_available(base_url, timeout=2):
                client, model = _make_openai_client(base_url, mid_fallback)
                return client, model

    # 3. 全域 fallback（Anthropic Haiku）
    fb = llm.fallback
    if fb.provider == "anthropic":
        client = _make_anthropic_client(fb.model)
        if client:
            return client, fb.model

    # 4. 最後備援：OpenAI-compat with fallback model
    client, model = _make_openai_client(llm.base_url, llm.model)
    return client, model


def get_krb_client(brain_dir: Optional[Path] = None) -> tuple[Any, str]:
    """
    取得 KRB 審核用的 LLM client，讀取 [review.model] 設定。
    Ollama 不可用時自動 fallback 至 [pipeline.llm] 設定。

    Returns: (client, model_name)
    """
    cfg = load_config(brain_dir)
    rv  = cfg.review.llm

    if rv.provider in ("ollama", "openai"):
        if _is_ollama_available(rv.base_url, timeout=2):
            client, model = _make_openai_client(rv.base_url, rv.model)
            return client, model
        logger.debug("get_krb_client: [review.model] Ollama 不可用，fallback → pipeline.llm")

    # fallback：走 pipeline.llm（可能是 Ollama 27B 或 Haiku）
    return get_llm_client(task="default", brain_dir=brain_dir)


def _make_openai_client(base_url: str, model: str) -> tuple[Any, str]:
    from openai import OpenAI
    url = base_url if "/v1" in base_url else base_url.rstrip("/") + "/v1"
    return OpenAI(base_url=url, api_key="ollama"), model


def _make_anthropic_client(model: str) -> Any:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return None


# ── brain.toml 模板生成 ────────────────────────────────────────────────────────

BRAIN_TOML_TEMPLATE = """\
# .brain/brain.toml
# Project Brain 配置檔
# 版本：v0.1（對應 Project Brain v0.30+）
#
# 不存在此檔案時，所有設定使用程式碼預設值，行為與舊版完全相同。
# 環境變數（BRAIN_LLM_PROVIDER 等）仍可覆蓋此檔案的設定。

# ── 核心設定 ──────────────────────────────────────────────────
[brain]
max_context_tokens  = 6000       # context 最大 token 預算
freshness_warn_days = 30         # 超過幾天的知識顯示過時警告
dedup_threshold     = 0.85       # 語意去重 cosine 閾值

# ── 自動知識生產管線 ───────────────────────────────────────────
# v0.32+ Layer 3 (LLMJudgmentEngine) 已實作，worker 會真正消費 signal_queue。
# 設 enabled=false 可完全停用自動管線（signal 仍會入隊，但不會被分析）。
[pipeline]
enabled                 = true
worker_interval_seconds = 60     # worker 輪詢間隔（秒）
max_queue_size          = 500    # 佇列上限，超過丟棄低優先信號
max_auto_confidence     = 0.85   # 自動提取的信心上限

[pipeline.gates]
test_failure_count = 3           # TEST_FAILURE 累積幾次才觸發分析（Phase 2）

# ── 信號開關（true = 啟用）────────────────────────────────────
[pipeline.signals]
git_commit    = true             # Phase 1
task_complete = true             # Phase 1
test_failure  = false            # Phase 2，切 true 即啟用
mcp_tool_call = false            # Phase 2
knowledge_gap = false            # Phase 3+

# ── 信號保留時間 ───────────────────────────────────────────────
[pipeline.retention]
signal_queue_done_days  = 30     # 已處理信號保留天數（除錯用）
signal_log_days         = 0      # 0 = 永久保留（審計用）
pipeline_metrics_days   = 90     # 品質指標保留天數

# ── LLM 設定 ──────────────────────────────────────────────────
# 記憶體分層與 LLM 用途：
#
#   L1 工作記憶（Working Memory）
#      → sessions / 對話快取；純儲存，不呼叫 LLM。
#
#   L2 情節記憶（Episodic Memory）
#      → 時序圖（temporal graph）；
#        memory_synthesizer 合併片段時呼叫 LLM（下方 pipeline.llm）。
#        建議：gemma4:27b（MoE，速度快）；複雜摘要可改用 gemma4:31b。
#
#   L3 語意知識（Semantic Knowledge / BrainDB nodes）
#      → 自動管線的 ADD/SKIP 判斷呼叫 LLM（下方 pipeline.llm）。
#        Phase 1：gemma4:27b（MoE，零成本本地推理）。
#        Phase 3+ MERGE/SYNTHESIZE：建議切換至 gemma4:31b（Dense）。
#
[pipeline.llm]
provider     = "{provider}"
model        = "{model}"         # L2 合成 + L3 自動管線（Phase 1：gemma4:27b）
base_url     = "{base_url}"
timeout      = 30
max_retries  = 3

[pipeline.llm.fallback]          # 本地不可用時自動切換
provider     = "anthropic"
model        = "claude-haiku-4-5-20251001"
# api_key 從環境變數讀取：ANTHROPIC_API_KEY

# ── 各任務模型覆蓋（只寫與預設不同的任務）────────────────────
# Phase 3+ 複雜推理任務（MERGE / CONTRADICT / SYNTHESIS）使用更強的 Dense 模型
# [pipeline.models]
# merge      = {{ model = "gemma4:31b", fallback = "gemma4:27b" }}
# contradict = {{ model = "gemma4:31b", fallback = "gemma4:27b" }}
# synthesis  = {{ model = "gemma4:31b", fallback = "gemma4:27b" }}

# ── Embedder ──────────────────────────────────────────────────
# L3 向量搜尋（BrainDB semantic search）使用此 embedding 模型。
# L1 / L2 不使用向量嵌入。
[embedder]
provider = "ollama"              # ollama | openai | local（TF-IDF 零依賴）
model    = "nomic-embed-text"    # 768 維嵌入，適合程式碼 + 中文混合文字
url      = "{base_url}"
fallback = "local"               # Ollama 不可用 → TF-IDF（無需任何模型）

# ── 衰減引擎 ──────────────────────────────────────────────────
[decay]
enabled            = true
run_interval_hours = 24
# 六因子權重由系統自動計算，不建議手動調整（加總需為 1.0，否則結果不可預期）

# ── 知識審核委員會（KRB）────────────────────────────────────────
# KRB 負責把自動提取的候選知識（confidence 較低）過篩到正式 KB。
# 人工執行：brain review list / brain review approve <id>
[review]
auto_approve_threshold = 0.80   # 超過此信心值自動核准，無需人工審核
staging_ttl_days       = 30     # 候選知識在暫存區保留天數，到期自動清除
min_confidence         = 0.50   # 自動提取低於此值直接丟棄，不進暫存區

[review.model]
# KRB 是低頻但高品質要求的判斷（比較現有 KB、判斷重複與矛盾）
# 獨立於 pipeline.llm，建議使用推理能力較強的模型
provider    = "ollama"
model       = "gemma4:31b"      # Dense 模型，判斷品質優先
base_url    = "{base_url}"
# Ollama 不可用時 fallback 至 pipeline.llm 的設定

# ── Federation ────────────────────────────────────────────────
[federation]
enabled               = false
min_export_confidence = 0.6
max_export_nodes      = 500

# ── MCP Server ────────────────────────────────────────────────
[mcp]
port           = 7891
rate_limit_rpm = 60

# ── 可觀測性 ──────────────────────────────────────────────────
[observability]
log_level          = "INFO"      # DEBUG | INFO | WARNING
log_context_builds = true        # 記錄每次 context 組裝的 token 數
daily_token_limit  = 0           # 0 = 無限制；正數 = 達到後暫停管線
"""


def generate_brain_toml(brain_dir: Path, local_only: bool = False) -> Path:
    """
    在 brain_dir 下生成 brain.toml。
    local_only=True 時預填 Ollama 設定。
    已存在時不覆蓋（呼叫方決定是否覆蓋）。
    回傳 brain.toml 的路徑。
    """
    toml_path = brain_dir / "brain.toml"
    if local_only:
        provider = "ollama"
        model    = _DEFAULT_OLLAMA_MODEL
        base_url = _DEFAULT_OLLAMA_URL
    else:
        # 讀取現有 env var 作為初始值，方便使用者看到目前設定
        provider = os.environ.get("BRAIN_LLM_PROVIDER", "ollama").lower()
        model    = os.environ.get("BRAIN_LLM_MODEL",    _DEFAULT_OLLAMA_MODEL)
        base_url = os.environ.get("BRAIN_LLM_BASE_URL", _DEFAULT_OLLAMA_URL)

    content = BRAIN_TOML_TEMPLATE.format(
        provider=provider,
        model=model,
        base_url=base_url,
    )
    toml_path.write_text(content, encoding="utf-8")
    return toml_path
