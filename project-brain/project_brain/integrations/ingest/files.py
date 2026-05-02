"""
project_brain/integrations/ingest/files.py — E-04: Local Files Ingestion Source

Scans a directory for Markdown files, chunks them by heading, and produces
RawDocument objects for the IngestPipeline.

Usage::

    from project_brain.integrations.ingest.files import LocalFilesIngestSource

    source = LocalFilesIngestSource()
    docs = source.fetch(Path("./docs"), glob_pattern="**/*.md")
    # → list[RawDocument], one per heading section
"""
from __future__ import annotations

import logging
from pathlib import Path

from .base import RawDocument
from .chunker import chunk_markdown

logger = logging.getLogger(__name__)


class LocalFilesIngestSource:
    """Scan local Markdown files and produce RawDocuments."""

    def fetch(
        self,
        path: Path,
        glob_pattern: str = "**/*.md",
        max_tokens_per_chunk: int = 512,
    ) -> list[RawDocument]:
        """Recursively scan for Markdown files and chunk by heading.

        Args:
            path: Root directory to scan.
            glob_pattern: Glob pattern for file selection.
            max_tokens_per_chunk: Max estimated tokens per chunk.

        Returns:
            List of RawDocuments, one per heading section.
        """
        path = Path(path)
        if not path.exists():
            logger.warning("Ingest path does not exist: %s", path)
            return []

        if path.is_file():
            return self._process_file(path, max_tokens_per_chunk)

        docs: list[RawDocument] = []
        for file_path in sorted(path.glob(glob_pattern)):
            if file_path.is_file():
                docs.extend(self._process_file(file_path, max_tokens_per_chunk))

        logger.info("LocalFilesIngestSource: scanned %d files, produced %d documents",
                     sum(1 for _ in path.glob(glob_pattern) if _.is_file()), len(docs))
        return docs

    def _process_file(self, file_path: Path, max_tokens: int) -> list[RawDocument]:
        """Read and chunk a single Markdown file."""
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to read %s: %s", file_path, e)
            return []

        if not text.strip():
            return []

        chunks = chunk_markdown(text, max_tokens=max_tokens)
        docs: list[RawDocument] = []

        for i, chunk in enumerate(chunks):
            title = chunk.title or file_path.stem
            source = f"file:{file_path}"
            if chunk.title:
                source += f"#{chunk.title.lower().replace(' ', '-')}"

            docs.append(RawDocument(
                source=source,
                title=title,
                content=chunk.content,
                url=str(file_path),
                metadata={
                    "file_path": str(file_path),
                    "section": chunk.title,
                    "heading_level": chunk.level,
                    "chunk_index": i,
                },
            ))

        return docs
