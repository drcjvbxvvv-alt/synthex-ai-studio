"""
project_brain/context_result.py — ContextResult (P3-A)

Structured return from Brain queries so Agents can distinguish:
  - "Brain not initialized" (is_initialized=False)
  - "Brain empty — no relevant knowledge" (source_count=0, is_initialized=True)
  - "Found knowledge" (source_count>0, context non-empty)
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ContextResult:
    """
    Structured result from Brain.get_context() and BrainDB.search_nodes().

    Agent usage:
        result = Brain(".").query("JWT auth")
        if not result.is_initialized:
            print("Run: brain setup")
        elif result.source_count == 0:
            print("No relevant knowledge found")
        else:
            inject_into_prompt(result.context)
    """
    context:        str   = ""          # formatted context string for injection
    source_count:   int   = 0           # number of knowledge nodes found
    is_initialized: bool  = True        # False = brain.db does not exist
    confidence:     float = 0.0         # average confidence of returned nodes
    scope:          str   = "global"    # scope used for filtering
    causal_chains:  int   = 0           # number of causal relationships found
    nudges:         list  = field(default_factory=list)  # proactive warnings

    # ── helpers ──────────────────────────────────────────────────────────

    def __bool__(self) -> bool:
        """True if initialized and has knowledge."""
        return self.is_initialized and self.source_count > 0

    def __str__(self) -> str:
        """Returns the context string directly (backward compatible)."""
        return self.context

    def to_prompt(self) -> str:
        """Full context string including nudges (for LLM injection)."""
        parts = []
        if self.nudges:
            parts.append("## 🧠 Brain Warnings")
            for n in self.nudges:
                parts.append(f"  ⚠ {n}")
        if self.context:
            parts.append(self.context)
        return "\n".join(parts)

    def status_line(self) -> str:
        """One-line status for debugging."""
        if not self.is_initialized:
            return "Brain not initialized (run: brain setup)"
        if self.source_count == 0:
            return f"No knowledge found for scope={self.scope}"
        return (f"{self.source_count} nodes | "
                f"confidence={self.confidence:.2f} | "
                f"causal_chains={self.causal_chains} | "
                f"nudges={len(self.nudges)}")

    @classmethod
    def not_initialized(cls) -> "ContextResult":
        """Factory: Brain not set up yet."""
        return cls(
            context="",
            source_count=0,
            is_initialized=False,
            confidence=0.0,
        )

    @classmethod
    def empty(cls, scope: str = "global") -> "ContextResult":
        """Factory: Brain initialized but no relevant knowledge."""
        return cls(
            context="",
            source_count=0,
            is_initialized=True,
            confidence=0.0,
            scope=scope,
        )
