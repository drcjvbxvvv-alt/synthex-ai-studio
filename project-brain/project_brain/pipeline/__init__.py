"""
project_brain.pipeline — Auto Knowledge Pipeline (Layer 1-4)

Package layout（ARCHITECTURE_REVIEW.md §6.2 重構）：

    signal.py       Layer 1/2  Signal / SignalKind / SignalQueue
    executor.py     Layer 4    NodeSpec / KnowledgeDecision / ExecutionResult / KnowledgeExecutor
    llm_judgment.py Layer 3    LLMJudgmentEngine
    worker.py       Layer 3.5  PipelineWorker / start_global_worker / stop_global_worker

本 __init__ 僅 re-export Layer 1/2 與 Layer 4 的核心符號，以維持既有
``from project_brain.pipeline import Signal, SignalQueue, KnowledgeExecutor, ...``
import 語法不中斷。

Layer 3 (llm_judgment) 與 Layer 3.5 (worker) 為可選載入模組，
保留各自的 ``from project_brain.pipeline.llm_judgment import ...`` /
``from project_brain.pipeline.worker import ...`` 用法。
"""
from __future__ import annotations

from project_brain.pipeline.executor import (
    ExecutionResult,
    KnowledgeDecision,
    KnowledgeExecutor,
    NodeSpec,
)
from project_brain.pipeline.signal import (
    Signal,
    SignalKind,
    SignalQueue,
)

__all__ = [
    # Layer 1/2
    "Signal",
    "SignalKind",
    "SignalQueue",
    # Layer 4
    "NodeSpec",
    "KnowledgeDecision",
    "ExecutionResult",
    "KnowledgeExecutor",
]
