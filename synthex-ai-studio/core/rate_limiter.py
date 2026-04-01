"""
core/rate_limiter.py — Client-side Rate Limiting (v3.0)

問題：AgentSwarm 4 個 Worker 並行打 API，沒有速率控制。
大量請求同時到達 → Anthropic 回傳 429 → 指數退避 → 整體更慢。

解決方案：Token Bucket 演算法（client side）。
  - 在打出 API 前做平滑處理
  - 多 Worker 共享同一個 bucket（thread-safe）
  - 區分不同模型的速率限制

設計：
  Anthropic 的速率限制（參考，2026-03）：
    Opus：    60 req/min,  40K tok/min（input）
    Sonnet：  300 req/min, 100K tok/min
    Haiku：   500 req/min, 200K tok/min
  
  Token Bucket：
    每秒補充 tokens_per_sec 個 token
    每次請求消耗 estimated_tokens 個 token
    bucket 空了就等待（sleep）而不是直接打 API

安全設計：
  - 跨 thread 共享：threading.Lock 保護 bucket 狀態
  - 最大等待時間：60 秒，超過就讓 API 自己決定
  - 不同模型獨立 bucket（Opus 和 Sonnet 不互相影響）

記憶體管理：
  - 每個模型一個 bucket（最多 4-5 個）
  - bucket 狀態只有 2 個 float，記憶體佔用極小
"""

from __future__ import annotations

import time
import threading
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── 速率設定（保守值，Anthropic 官方限制的 70%）────────────────
_RATE_CONFIG: dict[str, dict[str, float]] = {
    "claude-opus-4-6":   {"req_per_min": 40,  "tok_per_min": 28_000},
    "claude-opus-4-5":   {"req_per_min": 40,  "tok_per_min": 28_000},
    "claude-sonnet-4-6": {"req_per_min": 200, "tok_per_min": 70_000},
    "claude-sonnet-4-5": {"req_per_min": 200, "tok_per_min": 70_000},
    "claude-haiku-4-5":  {"req_per_min": 350, "tok_per_min": 140_000},
    "_default":          {"req_per_min": 100, "tok_per_min": 50_000},
}

MAX_WAIT_SECONDS = 60.0    # 最長等待時間
MIN_SLEEP_SECONDS = 0.05   # 最小 sleep 精度


@dataclass
class TokenBucket:
    """
    Token Bucket：雙令牌桶（Request + Token）。
    
    兩個維度同時控制：
      - 請求速率（每分鐘請求數）
      - Token 速率（每分鐘 token 數）
    
    取兩者的最嚴格限制。
    """
    req_per_sec:  float
    tok_per_sec:  float
    max_req_cap:  float  # 最大 request 容量（burst）
    max_tok_cap:  float  # 最大 token 容量（burst）

    req_tokens:   float = field(init=False)
    tok_tokens:   float = field(init=False)
    last_refill:  float = field(init=False)
    lock:         threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self):
        self.req_tokens  = self.max_req_cap
        self.tok_tokens  = self.max_tok_cap
        self.last_refill = time.monotonic()

    def _refill(self) -> None:
        """補充令牌（呼叫者必須持有 lock）"""
        now     = time.monotonic()
        elapsed = now - self.last_refill
        self.last_refill = now
        self.req_tokens  = min(self.max_req_cap, self.req_tokens + elapsed * self.req_per_sec)
        self.tok_tokens  = min(self.max_tok_cap, self.tok_tokens + elapsed * self.tok_per_sec)

    def acquire(self, estimated_tokens: int = 1000) -> float:
        """
        取得許可（阻塞直到獲得）。
        
        Args:
            estimated_tokens: 預估此次請求的 token 數
            
        Returns:
            實際等待秒數
        """
        start = time.monotonic()
        waited = 0.0

        while True:
            with self.lock:
                self._refill()
                if self.req_tokens >= 1.0 and self.tok_tokens >= estimated_tokens:
                    self.req_tokens  -= 1.0
                    self.tok_tokens  -= estimated_tokens
                    return waited

                # 計算需要等多久
                req_wait = (1.0 - self.req_tokens) / max(self.req_per_sec, 0.001)
                tok_wait = (estimated_tokens - self.tok_tokens) / max(self.tok_per_sec, 0.001)
                sleep_for = min(MAX_WAIT_SECONDS, max(MIN_SLEEP_SECONDS, max(req_wait, tok_wait)))

            # 超過最大等待時間就直接放行（讓 API 自己 throttle）
            if time.monotonic() - start > MAX_WAIT_SECONDS:
                logger.warning("rate_limiter: 超過最大等待時間 %ds，直接放行", MAX_WAIT_SECONDS)
                with self.lock:
                    self.req_tokens  = max(0.0, self.req_tokens)
                    self.tok_tokens  = max(0.0, self.tok_tokens)
                return time.monotonic() - start

            time.sleep(sleep_for)
            waited += sleep_for


class RateLimiter:
    """
    多模型 Rate Limiter。
    全域單例，跨 AgentSwarm Worker 共享。
    """
    _instance: "RateLimiter | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self._buckets: dict[str, TokenBucket] = {}
        self._bucket_lock = threading.Lock()

    @classmethod
    def get(cls) -> "RateLimiter":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _get_bucket(self, model: str) -> TokenBucket:
        with self._bucket_lock:
            if model not in self._buckets:
                cfg = _RATE_CONFIG.get(model, _RATE_CONFIG["_default"])
                rps = cfg["req_per_min"] / 60.0
                tps = cfg["tok_per_min"] / 60.0
                self._buckets[model] = TokenBucket(
                    req_per_sec = rps,
                    tok_per_sec = tps,
                    max_req_cap = max(5.0, rps * 5),   # 5 秒的 burst
                    max_tok_cap = max(10000.0, tps * 5),
                )
            return self._buckets[model]

    def acquire(self, model: str, estimated_tokens: int = 1000) -> float:
        """取得 API 呼叫許可，回傳等待秒數"""
        bucket = self._get_bucket(model)
        waited = bucket.acquire(estimated_tokens)
        if waited > 0.5:
            logger.info(
                "rate_limit_wait",
                model   = model,
                waited  = round(waited, 2),
                extra   = {"estimated_tokens": estimated_tokens},
            )
        return waited

    def stats(self) -> dict:
        """取得所有 bucket 的狀態"""
        with self._bucket_lock:
            return {
                model: {
                    "req_tokens": round(b.req_tokens, 2),
                    "tok_tokens": round(b.tok_tokens, 0),
                }
                for model, b in self._buckets.items()
            }


# 全域單例
rate_limiter = RateLimiter.get()
