"""
core/observability.py — 輕量觀測性中間層 (v3.0)

問題：SYNTHEX 的觀測性完全空白（0 trace / 0 metric / 0 結構化日誌）。
生產環境中「哪個 Phase 最慢？」「這次 ship() 總成本？」完全無從回答。

解決方案：OpenTelemetry 相容的觀測性層。
  - Spans：每個 Phase 和 Agent 呼叫都有追蹤
  - Metrics：成本、延遲、成功率 per Phase/Agent
  - 結構化日誌：所有事件都以 JSON 格式輸出

設計：
  1. 零外部依賴（opentelemetry-sdk 是可選的）
  2. 降級優雅：沒有 OpenTelemetry 時回退到 structlog
  3. 效能安全：計量資料在記憶體中聚合，不影響 API 呼叫路徑
  4. Context Manager：用 with PhaseSpan(...) 自動記錄開始/結束

安全設計：
  - metrics 不包含用戶程式碼或 API 回應內容
  - 只記錄 token 數、延遲、成本、成功/失敗
  - GDPR 友善：無個人識別資訊

使用方式：
  from core.observability import telemetry, PhaseSpan, AgentSpan

  # 追蹤 Phase
  with PhaseSpan(phase=4, name="NEXUS 架構設計") as span:
      result = nexus.chat(prompt)
      span.set_cost(tokens_in=1234, tokens_out=567)

  # 取得摘要報告
  report = telemetry.summary()
"""

from __future__ import annotations

import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional, Any
from collections import defaultdict


# ── 資料結構 ──────────────────────────────────────────────────────

@dataclass
class SpanData:
    """單次操作的追蹤記錄"""
    name:          str
    kind:          str              # "phase" | "agent" | "tool"
    started_at:    float = field(default_factory=time.monotonic)
    ended_at:      float = 0.0
    success:       bool = True
    error:         str  = ""
    attributes:    dict = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        end = self.ended_at or time.monotonic()
        return int((end - self.started_at) * 1000)

    def finish(self, success: bool = True, error: str = "") -> None:
        self.ended_at = time.monotonic()
        self.success  = success
        self.error    = error[:200] if error else ""


@dataclass
class PhaseMetrics:
    """Phase 層級的累積指標"""
    phase:          int
    name:           str
    total_runs:     int   = 0
    success_runs:   int   = 0
    total_ms:       int   = 0
    total_cost_usd: float = 0.0
    total_in_tok:   int   = 0
    total_out_tok:  int   = 0
    cache_hits:     int   = 0


# ── 核心遙測收集器 ────────────────────────────────────────────────

class Telemetry:
    """
    輕量遙測收集器。全域單例。
    
    儲存最近 N 次 ship() 的指標（不無限增長）。
    """
    MAX_RUNS    = 100   # 最多保留 100 次執行記錄
    MAX_SPANS   = 5000  # 最多保留 5000 個 span

    def __init__(self):
        self._lock         = threading.Lock()
        self._spans:  list[SpanData]           = []
        self._phases: dict[int, PhaseMetrics]  = {}
        self._run_costs:   list[dict]          = []
        self._logger = None

    def _log(self) -> Any:
        if self._logger is None:
            try:
                from core.logging_setup import get_logger
                self._logger = get_logger("telemetry")
            except Exception:
                import logging
                self._logger = logging.getLogger("telemetry")
        return self._logger

    # ── Span 管理 ────────────────────────────────────────────────

    def start_span(self, name: str, kind: str, **attrs) -> SpanData:
        span = SpanData(name=name, kind=kind, attributes=attrs)
        with self._lock:
            self._spans.append(span)
            # 記憶體控制
            if len(self._spans) > self.MAX_SPANS:
                self._spans = self._spans[-self.MAX_SPANS:]
        return span

    def finish_span(
        self, span: SpanData,
        success:     bool = True,
        error:       str  = "",
        in_tokens:   int  = 0,
        out_tokens:  int  = 0,
        cache_read:  int  = 0,
        cost_usd:    float = 0.0,
    ) -> None:
        span.finish(success=success, error=error)

        # 記錄到結構化日誌
        self._log().info(
            "span_finish",
            name        = span.name,
            kind        = span.kind,
            duration_ms = span.duration_ms,
            success     = success,
            in_tokens   = in_tokens,
            out_tokens  = out_tokens,
            cache_read  = cache_read,
            cost_usd    = round(cost_usd, 6),
            error       = error[:100] if error else None,
        )

        # 更新 Phase 指標
        if span.kind == "phase":
            phase_num = span.attributes.get("phase_num", 0)
            with self._lock:
                if phase_num not in self._phases:
                    self._phases[phase_num] = PhaseMetrics(
                        phase=phase_num, name=span.name
                    )
                m = self._phases[phase_num]
                m.total_runs     += 1
                m.total_ms       += span.duration_ms
                m.total_cost_usd += cost_usd
                m.total_in_tok   += in_tokens
                m.total_out_tok  += out_tokens
                if success: m.success_runs += 1
                if cache_read > 0: m.cache_hits += 1

    def record_run(self, total_cost: float, phases_done: int, duration_ms: int) -> None:
        """記錄一次完整 ship() 執行"""
        record = {
            "timestamp":   time.time(),
            "total_cost":  round(total_cost, 4),
            "phases_done": phases_done,
            "duration_ms": duration_ms,
        }
        with self._lock:
            self._run_costs.append(record)
            if len(self._run_costs) > self.MAX_RUNS:
                self._run_costs = self._run_costs[-self.MAX_RUNS:]

        self._log().info("ship_complete", **record)

    # ── 報告 ─────────────────────────────────────────────────────

    def summary(self) -> dict:
        """產生可讀的效能報告"""
        with self._lock:
            phases = dict(self._phases)
            runs   = list(self._run_costs)

        report: dict = {
            "total_spans":  len(self._spans),
            "phases":       {},
            "recent_runs":  [],
            "totals":       {},
        }

        total_cost = 0.0
        total_tok  = 0

        for phase_num, m in sorted(phases.items()):
            avg_ms   = m.total_ms // max(1, m.total_runs)
            pass_rate = m.success_runs / max(1, m.total_runs)
            report["phases"][phase_num] = {
                "name":        m.name,
                "runs":        m.total_runs,
                "pass_rate":   f"{pass_rate:.0%}",
                "avg_ms":      avg_ms,
                "total_cost":  round(m.total_cost_usd, 4),
                "total_tokens":m.total_in_tok + m.total_out_tok,
                "cache_hits":  m.cache_hits,
            }
            total_cost += m.total_cost_usd
            total_tok  += m.total_in_tok + m.total_out_tok

        for run in runs[-10:]:
            from datetime import datetime
            report["recent_runs"].append({
                "time":    datetime.fromtimestamp(run["timestamp"]).strftime("%H:%M:%S"),
                "cost":    f"${run['total_cost']:.4f}",
                "phases":  run["phases_done"],
                "seconds": run["duration_ms"] // 1000,
            })

        report["totals"] = {
            "all_phases_cost_usd": round(total_cost, 4),
            "all_tokens":          total_tok,
            "ship_runs":           len(runs),
            "avg_run_cost":        round(
                sum(r["total_cost"] for r in runs) / max(1, len(runs)), 4
            ),
        }

        return report

    def format_report(self) -> str:
        """人類可讀的報告（終端機輸出）"""
        s = self.summary()
        lines = [
            "## SYNTHEX 觀測性報告",
            "",
            f"  追蹤記錄：{s['total_spans']} spans",
            f"  歷史執行：{s['totals']['ship_runs']} 次",
            f"  累計成本：${s['totals']['all_phases_cost_usd']:.4f} USD",
            f"  平均成本：${s['totals']['avg_run_cost']:.4f} USD/次",
            "",
            "Phase 效能：",
        ]
        for num, info in s["phases"].items():
            lines.append(
                f"  Phase {num:2d} {info['name']:<30}"
                f"通過率 {info['pass_rate']:>5}  "
                f"平均 {info['avg_ms']:>5}ms  "
                f"成本 ${info['total_cost']:.4f}"
            )
        if s["recent_runs"]:
            lines += ["", "最近執行："]
            for run in s["recent_runs"]:
                lines.append(
                    f"  {run['time']}  {run['cost']:>10}  "
                    f"{run['phases']} phases  {run['seconds']}s"
                )
        return "\n".join(lines)


# ── Context Manager ───────────────────────────────────────────────

class PhaseSpan:
    """
    Phase 追蹤的 Context Manager。

    用法：
        with PhaseSpan(phase=4, name="NEXUS 架構設計") as span:
            result = nexus.chat(prompt)
            span.add_tokens(in_tok=1234, out_tok=567, cost=0.023)
    """

    def __init__(self, phase: int, name: str, **attrs):
        self._phase = phase
        self._name  = name
        self._attrs = attrs
        self._span: Optional[SpanData] = None
        self._in_tok  = 0
        self._out_tok = 0
        self._cache   = 0
        self._cost    = 0.0
        self._error   = ""

    def __enter__(self) -> "PhaseSpan":
        self._span = telemetry.start_span(
            name      = self._name,
            kind      = "phase",
            phase_num = self._phase,
            **self._attrs,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._span:
            telemetry.finish_span(
                self._span,
                success     = exc_type is None,
                error       = str(exc_val)[:200] if exc_val else "",
                in_tokens   = self._in_tok,
                out_tokens  = self._out_tok,
                cache_read  = self._cache,
                cost_usd    = self._cost,
            )
        return False  # 不吞例外

    def add_tokens(
        self, in_tok: int = 0, out_tok: int = 0,
        cache_read: int = 0, cost: float = 0.0
    ) -> None:
        self._in_tok  += in_tok
        self._out_tok += out_tok
        self._cache   += cache_read
        self._cost    += cost


class AgentSpan:
    """Agent 呼叫追蹤"""

    def __init__(self, agent: str, model: str, task_type: str = "chat"):
        self._agent     = agent
        self._model     = model
        self._task_type = task_type
        self._span: Optional[SpanData] = None
        self._cost = 0.0

    def __enter__(self) -> "AgentSpan":
        self._span = telemetry.start_span(
            name       = f"{self._agent}.{self._task_type}",
            kind       = "agent",
            agent      = self._agent,
            model      = self._model,
            task_type  = self._task_type,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._span:
            telemetry.finish_span(
                self._span,
                success  = exc_type is None,
                error    = str(exc_val)[:200] if exc_val else "",
                cost_usd = self._cost,
            )
        return False

    def set_cost(self, cost: float) -> None:
        self._cost = cost


# ── 全域單例 ─────────────────────────────────────────────────────
telemetry = Telemetry()
