"""project_brain/utils.py — shared text utilities.

OPT-07: Single authoritative n-gram implementation used by both
brain_db.py (BrainDB._ngram) and graph.py (KnowledgeGraph._ngram_text).

H-1: confidence_label() provides a human-readable semantic tier for any
confidence float, used by context.py and nudge_engine.py to surface
the epistemic status of each knowledge node to the AI agent.
"""
from __future__ import annotations
import re

_CJK_RE   = re.compile(r"([\u4e00-\u9fff])")
_CJK_SEGS = re.compile(r"[\u4e00-\u9fff]+")


def confidence_label(conf: float) -> str:
    """H-1: Map a confidence float to a semantic tier label.

    Tiers (aligned with the four-level trust model):
      [0.0 – 0.3)  ⚠ 推測   — AI-generated, unverified speculation
      [0.3 – 0.6)  ~ 推斷   — Reasoned inference, not yet confirmed
      [0.6 – 0.8)  ✓ 已驗證  — Human-reviewed or empirically confirmed
      [0.8 – 1.0]  ✓✓ 權威  — Authoritative, pinned, or high-confidence rule

    Used by _fmt_node() in context.py and Nudge.to_dict() in nudge_engine.py
    so that AI agents can gauge how much to trust each piece of knowledge.
    """
    if conf < 0.3:
        return "⚠ 推測"
    if conf < 0.6:
        return "~ 推斷"
    if conf < 0.8:
        return "✓ 已驗證"
    return "✓✓ 權威"


def ngram_cjk(text: str) -> str:
    """OPT-07: Unified CJK bigram n-gram for FTS5 indexing and querying.

    Strategy:
      1. Space-separate each CJK character (unigram matching).
      2. Generate CJK bigrams (multi-char phrase matching).
         e.g. "中文搜尋" → "中 文 搜 尋 中文 文搜 搜尋"

    Used by BrainDB._ngram() and KnowledgeGraph._ngram_text().
    """
    if not text:
        return ""
    spaced  = _CJK_RE.sub(r" \1 ", text)
    bigrams: list[str] = []
    for seg in _CJK_SEGS.findall(text):
        bigrams.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return (spaced + " " + " ".join(bigrams)).strip() if bigrams else spaced.strip()
