"""project_brain/utils.py — shared text utilities.

OPT-07: Single authoritative n-gram implementation used by both
brain_db.py (BrainDB._ngram) and graph.py (KnowledgeGraph._ngram_text).
"""
from __future__ import annotations
import re

_CJK_RE   = re.compile(r"([\u4e00-\u9fff])")
_CJK_SEGS = re.compile(r"[\u4e00-\u9fff]+")


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
