"""
project_brain/llm_judgment.py — backward-compat shim

ARCHITECTURE_REVIEW.md §6.2 重構：Layer 3 LLMJudgmentEngine 已移至
``project_brain/pipeline/llm_judgment.py``。本檔案僅 re-export 以保持
``from project_brain.llm_judgment import LLMJudgmentEngine`` 等既有 import 可用。
"""
from __future__ import annotations

from project_brain.pipeline.llm_judgment import (  # noqa: F401
    DEFAULT_HAIKU_MODEL,
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_URL,
    LLMJudgmentEngine,
    MAX_OUTPUT_TOKENS,
    MAX_RAW_CONTENT_CHARS,
    MAX_RELATED_NODES,
    MAX_SUMMARY_CHARS,
    _INJECTION_PATTERNS,
    _safe,
)

__all__ = [
    "LLMJudgmentEngine",
    "DEFAULT_MODEL",
    "DEFAULT_OLLAMA_URL",
    "DEFAULT_HAIKU_MODEL",
    "MAX_RAW_CONTENT_CHARS",
    "MAX_SUMMARY_CHARS",
    "MAX_RELATED_NODES",
    "MAX_OUTPUT_TOKENS",
]
