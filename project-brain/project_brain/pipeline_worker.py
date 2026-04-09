"""
project_brain/pipeline_worker.py — backward-compat shim

ARCHITECTURE_REVIEW.md §6.2 重構：Layer 3.5 PipelineWorker 已移至
``project_brain/pipeline/worker.py``。本檔案僅 re-export 以保持
``from project_brain.pipeline_worker import PipelineWorker`` 等既有 import 可用。
"""
from __future__ import annotations

from project_brain.pipeline.worker import (  # noqa: F401
    DEFAULT_BATCH_SIZE,
    DEFAULT_INTERVAL_SECONDS,
    STALE_CLEANUP_EVERY,
    PipelineWorker,
    start_global_worker,
    stop_global_worker,
)

__all__ = [
    "PipelineWorker",
    "start_global_worker",
    "stop_global_worker",
    "DEFAULT_INTERVAL_SECONDS",
    "DEFAULT_BATCH_SIZE",
    "STALE_CLEANUP_EVERY",
]
