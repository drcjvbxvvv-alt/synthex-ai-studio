"""
project_brain/integrations/ingest/base.py — E-04: Ingestion data models

Shared dataclasses used across all ingestion sources (files, GitHub, etc.)
and the IngestPipeline orchestrator.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RawDocument:
    """A raw document chunk before knowledge extraction.

    Produced by ingestion sources (LocalFilesIngestSource, GitHubIngestSource).
    Consumed by IngestPipeline for LLM extraction or heuristic classification.
    """
    source: str         # origin identifier: "file:docs/auth.md#section-2"
    title: str          # heading or issue title
    content: str        # body text
    url: str            # local file path or web URL
    metadata: dict = field(default_factory=dict)
    # metadata examples:
    #   files:  {"file_path": "docs/auth.md", "section": "JWT 驗證"}
    #   github: {"issue_number": 123, "labels": ["bug"], "state": "closed"}


@dataclass
class KnowledgeCandidate:
    """A knowledge item extracted from a RawDocument, ready for dedup + write.

    Produced by IngestPipeline (LLM extraction or heuristic).
    Written to L3 (engine.add_knowledge) or KRB staging (review_board.submit).
    """
    title: str
    content: str
    kind: str           # Rule / Pitfall / Decision / Note
    confidence: float   # 0.0-1.0
    source: str         # trace back to RawDocument.source
    tags: list[str] = field(default_factory=list)


@dataclass
class IngestResult:
    """Summary of an ingestion run."""
    documents_scanned: int = 0
    candidates_extracted: int = 0
    duplicates_skipped: int = 0
    written_to_l3: int = 0
    written_to_staging: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_written(self) -> int:
        return self.written_to_l3 + self.written_to_staging
