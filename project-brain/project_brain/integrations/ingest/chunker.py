"""
project_brain/integrations/ingest/chunker.py — E-04: Markdown Text Chunker

Splits Markdown documents into sections by headings (# / ## / ###).
Each section becomes a separate RawDocument for knowledge extraction.

Features:
  - Splits on heading boundaries (ATX headings: # through ####)
  - Enforces max token budget per chunk (default 512)
  - CJK-aware token estimation (1 CJK char ≈ 1.5 tokens)
  - Preserves heading text as chunk title
  - Long sections are further split on paragraph boundaries
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Heading pattern: ATX-style (# through ####), capturing level and text
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)

# CJK Unicode ranges for token estimation
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


@dataclass
class Chunk:
    """A single chunk of text extracted from a Markdown document."""
    title: str       # heading text (empty string for preamble)
    content: str     # body text (without the heading line)
    level: int       # heading level (0 = preamble, 1-4 = h1-h4)


def estimate_tokens(text: str) -> int:
    """Estimate token count. CJK chars count ~1.5 tokens each, Latin ~0.25 per char."""
    if not text:
        return 0
    cjk_count = len(_CJK_RE.findall(text))
    latin_count = len(text) - cjk_count
    return int(cjk_count * 1.5 + latin_count * 0.25)


def chunk_markdown(text: str, max_tokens: int = 512) -> list[Chunk]:
    """Split Markdown text into chunks by headings.

    Args:
        text: Full Markdown document content.
        max_tokens: Maximum estimated tokens per chunk. Chunks exceeding this
                    are further split on paragraph boundaries.

    Returns:
        List of Chunk objects. The first chunk may have an empty title
        (preamble text before the first heading).
    """
    if not text or not text.strip():
        return []

    # Find all heading positions
    headings = list(_HEADING_RE.finditer(text))

    if not headings:
        # No headings — treat entire document as one chunk
        return _split_long(Chunk(title="", content=text.strip(), level=0), max_tokens)

    chunks: list[Chunk] = []

    # Preamble (text before first heading)
    preamble = text[:headings[0].start()].strip()
    if preamble:
        chunks.extend(_split_long(
            Chunk(title="", content=preamble, level=0), max_tokens,
        ))

    # Process each heading section
    for i, match in enumerate(headings):
        level = len(match.group(1))
        title = match.group(2).strip()

        # Section content: from end of heading line to start of next heading (or EOF)
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        content = text[start:end].strip()

        if not content and not title:
            continue

        chunks.extend(_split_long(
            Chunk(title=title, content=content, level=level), max_tokens,
        ))

    return chunks


def _split_long(chunk: Chunk, max_tokens: int) -> list[Chunk]:
    """Split a chunk that exceeds max_tokens on paragraph boundaries."""
    if estimate_tokens(chunk.content) <= max_tokens:
        return [chunk]

    paragraphs = re.split(r"\n\s*\n", chunk.content)
    result: list[Chunk] = []
    current_parts: list[str] = []
    current_tokens = 0
    part_idx = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        para_tokens = estimate_tokens(para)

        if current_tokens + para_tokens > max_tokens and current_parts:
            # Flush current accumulation
            title = chunk.title if part_idx == 0 else f"{chunk.title} (cont.)"
            result.append(Chunk(
                title=title,
                content="\n\n".join(current_parts),
                level=chunk.level,
            ))
            current_parts = []
            current_tokens = 0
            part_idx += 1

        current_parts.append(para)
        current_tokens += para_tokens

    # Flush remaining
    if current_parts:
        title = chunk.title if part_idx == 0 else f"{chunk.title} (cont.)"
        result.append(Chunk(
            title=title,
            content="\n\n".join(current_parts),
            level=chunk.level,
        ))

    return result if result else [chunk]
