"""
project_brain/memory_synthesizer.py — Memory Synthesizer (P4 / A-19)

Opt-in: set BRAIN_SYNTHESIZE=1 to enable.

Fuses L1+L2+L3 raw data into a single coherent tactical brief,
eliminating the cognitive load of contradictory multi-layer context.

Cost: ~1 LLM call per query (~$0.0002 with haiku, 0 with local Ollama).
"""
from __future__ import annotations

import json
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Hard token cap for the fused brief
MAX_BRIEF_TOKENS = 800

_FUSE_PROMPT = """You are a technical memory synthesizer for a software project.

You receive raw knowledge from three memory layers. Fuse them into ONE
coherent tactical brief (max 5 bullet points, plain text, no headers).

Rules:
- If layers contradict each other, prefer the most recent (L1 > L2 > L3).
- Focus only on what is directly relevant to the TASK.
- Output the brief ONLY — no explanation, no preamble.
- Each bullet: "• [type] statement" e.g. "• [WARNING] JWT must use RS256"

TASK: {task}

L1 WORKING MEMORY (most recent):
{l1}

L2 EPISODIC MEMORY (commit history):
{l2}

L3 SEMANTIC MEMORY (long-term rules):
{l3}

TACTICAL BRIEF:"""


def is_enabled() -> bool:
    return os.environ.get("BRAIN_SYNTHESIZE", "0").strip() in ("1", "true", "yes")


def _truncate(text: str, chars: int = 800) -> str:
    return text[:chars] + "..." if len(text) > chars else text


class MemorySynthesizer:
    """
    Fuses L1/L2/L3 memory layers into a single tactical brief.

    Usage:
        if MemorySynthesizer.is_enabled():
            synth = MemorySynthesizer()
            brief = synth.fuse(l1_data, l2_data, l3_data, task="refactor auth")
    """

    def __init__(self, workdir: str = "."):
        self.workdir = workdir

    def fuse(self, l1: Any, l2: Any, l3: str, task: str) -> str:
        """
        Fuse three memory layers into one tactical brief.

        Args:
            l1: L1 working memory (list of dicts or str)
            l2: L2 episodic memory (list of dicts or str)
            l3: L3 semantic context (str from ContextEngineer.build)
            task: The current task description

        Returns:
            Fused tactical brief as str. Falls back to raw concat on error.
        """
        if not is_enabled():
            return self._concat_fallback(l1, l2, l3)

        l1_text = self._layer_to_text(l1)
        l2_text = self._layer_to_text(l2)
        l3_text = l3 if isinstance(l3, str) else self._layer_to_text(l3)

        # Skip synthesis if all layers empty
        if not any([l1_text.strip(), l2_text.strip(), l3_text.strip()]):
            return ""

        prompt = _FUSE_PROMPT.format(
            task=task[:200],
            l1=_truncate(l1_text, 500),
            l2=_truncate(l2_text, 500),
            l3=_truncate(l3_text, 600),
        )

        try:
            brief = self._call_llm(prompt)
            return f"## 🧠 Brain Tactical Brief\n{brief}\n"
        except Exception as e:
            logger.warning("MemorySynthesizer LLM call failed: %s", e)
            return self._concat_fallback(l1, l2, l3)

    def _call_llm(self, prompt: str) -> str:
        """Call LLM for synthesis via brain_config。"""
        from project_brain.brain_config import load_config, _find_brain_dir
        cfg      = load_config(_find_brain_dir())
        provider = cfg.pipeline.llm.provider

        if provider in ("openai", "ollama"):
            return self._call_openai_compat(prompt, cfg)
        else:
            return self._call_anthropic(prompt, cfg)

    def _call_anthropic(self, prompt: str, cfg=None) -> str:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic(api_key=api_key)
        model  = cfg.pipeline.llm.model if cfg else os.environ.get("BRAIN_LLM_MODEL", "claude-haiku-4-5-20251001")
        msg = client.messages.create(
            model=model,
            max_tokens=MAX_BRIEF_TOKENS,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text.strip()

    def _call_openai_compat(self, prompt: str, cfg=None) -> str:
        from openai import OpenAI
        if cfg:
            base_url = cfg.pipeline.llm.base_url
            model    = cfg.pipeline.llm.model
        else:
            base_url = os.environ.get("BRAIN_LLM_BASE_URL", "http://localhost:11434/v1")
            model    = os.environ.get("BRAIN_LLM_MODEL", "gemma4:27b")
        url    = base_url if "/v1" in base_url else base_url.rstrip("/") + "/v1"
        client = OpenAI(base_url=url, api_key="ollama")
        resp = client.chat.completions.create(
            model=model,
            max_tokens=MAX_BRIEF_TOKENS,
            messages=[{"role": "user", "content": prompt}]
        )
        return resp.choices[0].message.content.strip()

    @staticmethod
    def _layer_to_text(data: Any) -> str:
        if isinstance(data, str):
            return data
        if isinstance(data, list):
            parts = []
            for item in data[:5]:
                if isinstance(item, dict):
                    parts.append(item.get("content", "") or item.get("title", "") or str(item))
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(data) if data else ""

    @staticmethod
    def _concat_fallback(l1: Any, l2: Any, l3: str) -> str:
        """Fallback: simple concatenation when synthesis is disabled or fails."""
        parts = []
        if l1:
            t = MemorySynthesizer._layer_to_text(l1)
            if t.strip():
                parts.append(f"## L1 Working Memory\n{t}")
        if l2:
            t = MemorySynthesizer._layer_to_text(l2)
            if t.strip():
                parts.append(f"## L2 Episodic\n{t}")
        if l3 and str(l3).strip():
            parts.append(str(l3))
        return "\n\n".join(parts)
