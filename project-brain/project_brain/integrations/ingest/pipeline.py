"""
project_brain/integrations/ingest/pipeline.py — E-04: Ingestion Pipeline Orchestrator

Coordinates the full ingestion flow:
  RawDocument[] → [LLM Extract / Heuristic] → [Dedup] → [Write L3 / Stage KRB]

Usage::

    from project_brain.integrations.ingest.pipeline import IngestPipeline
    from project_brain.engine import ProjectBrain

    brain = ProjectBrain("/path/to/project")
    pipeline = IngestPipeline(brain)
    result = pipeline.run(documents, dry_run=False)
    print(f"Written: {result.total_written}, Skipped: {result.duplicates_skipped}")
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional

from .base import IngestResult, KnowledgeCandidate, RawDocument

logger = logging.getLogger(__name__)

# LLM extraction prompt
_EXTRACT_PROMPT = """你是知識提取助手。從以下文件中提取可作為團隊知識保存的條目。

標題：{title}
內容：
{content}

規則：
- 若描述一個 bug、問題、或踩坑 → kind=Pitfall
- 若描述一個架構決策 → kind=Decision
- 若描述一個規範或約束 → kind=Rule
- 其他 → kind=Note
- confidence：0.5（一般）、0.7（有細節佐證）、0.9（有驗證）

輸出 JSON 陣列（可能為空）：
[{{"title": "...", "content": "...", "kind": "Pitfall|Decision|Rule|Note", "confidence": 0.5, "tags": ["tag1"]}}]

只輸出 JSON，不要其他文字。"""

# Keywords for heuristic kind detection
_KIND_KEYWORDS = {
    "Pitfall": {"bug", "error", "issue", "problem", "crash", "fail", "fix",
                "broken", "踩坑", "問題", "錯誤", "修復", "失敗"},
    "Decision": {"decision", "choose", "select", "adopt", "migrate", "switch",
                 "architecture", "決策", "選擇", "架構", "遷移"},
    "Rule": {"must", "always", "never", "require", "standard", "convention",
             "policy", "規則", "必須", "規範", "標準", "約束"},
}


class IngestPipeline:
    """Orchestrate document ingestion into Project Brain.

    Supports two extraction modes:
      1. LLM-based: uses LLMClient to extract structured knowledge (higher quality)
      2. Heuristic: keyword-based kind detection (no LLM needed, lower quality)
    """

    def __init__(
        self,
        brain: Any,
        llm_client: Any = None,
        llm_rate_limit_rpm: int = 10,
    ) -> None:
        self._brain = brain
        self._llm = llm_client
        self._llm_interval = 60.0 / max(1, llm_rate_limit_rpm)

    def run(
        self,
        documents: list[RawDocument],
        *,
        dry_run: bool = False,
        source_label: str = "ingest",
        auto_approve_threshold: float = 0.7,
    ) -> IngestResult:
        """Run the ingestion pipeline on a list of documents.

        Args:
            documents: RawDocuments to process.
            dry_run: If True, extract and dedup but don't write.
            source_label: Source label for staging (e.g., "ingest:files").
            auto_approve_threshold: Confidence threshold for direct L3 write.
                Candidates below this go to KRB staging.

        Returns:
            IngestResult with counts of written/skipped/errors.
        """
        result = IngestResult(documents_scanned=len(documents))

        # Step 1: Extract candidates from documents
        candidates: list[KnowledgeCandidate] = []
        for doc in documents:
            try:
                extracted = self._extract(doc)
                candidates.extend(extracted)
            except Exception as e:
                result.errors.append(f"Extract failed for {doc.source}: {e}")
                logger.warning("Extraction error for %s: %s", doc.source, e)

        result.candidates_extracted = len(candidates)

        if dry_run:
            return result

        # Step 2: Dedup + Write
        for cand in candidates:
            try:
                if self._is_duplicate(cand):
                    result.duplicates_skipped += 1
                    continue

                if cand.confidence >= auto_approve_threshold:
                    self._write_to_l3(cand, source_label)
                    result.written_to_l3 += 1
                else:
                    self._write_to_staging(cand, source_label)
                    result.written_to_staging += 1
            except Exception as e:
                result.errors.append(f"Write failed for '{cand.title}': {e}")
                logger.warning("Write error for '%s': %s", cand.title, e)

        return result

    # ── Extraction ──────────────────────────────────────────────

    def _extract(self, doc: RawDocument) -> list[KnowledgeCandidate]:
        """Extract knowledge candidates from a document."""
        if self._llm:
            return self._extract_llm(doc)
        return self._extract_heuristic(doc)

    def _extract_llm(self, doc: RawDocument) -> list[KnowledgeCandidate]:
        """Use LLM to extract structured knowledge."""
        prompt = _EXTRACT_PROMPT.format(
            title=doc.title[:200],
            content=doc.content[:2000],
        )

        try:
            raw = self._llm.complete(prompt, max_tokens=1024, temperature=0.1)
            # Rate limit
            time.sleep(self._llm_interval)
        except Exception as e:
            logger.warning("LLM extraction failed, falling back to heuristic: %s", e)
            return self._extract_heuristic(doc)

        # Parse JSON response
        try:
            # Strip markdown code fences if present
            cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
            cleaned = re.sub(r"\n?```\s*$", "", cleaned)
            items = json.loads(cleaned)
            if not isinstance(items, list):
                items = [items]
        except (json.JSONDecodeError, TypeError):
            logger.debug("LLM returned non-JSON, falling back to heuristic")
            return self._extract_heuristic(doc)

        candidates = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            content = str(item.get("content", "")).strip()
            if not title:
                continue
            candidates.append(KnowledgeCandidate(
                title=title[:200],
                content=content[:2000],
                kind=item.get("kind", "Note"),
                confidence=min(1.0, max(0.0, float(item.get("confidence", 0.5)))),
                source=doc.source,
                tags=[str(t) for t in item.get("tags", [])][:10],
            ))

        return candidates

    def _extract_heuristic(self, doc: RawDocument) -> list[KnowledgeCandidate]:
        """Keyword-based knowledge extraction (no LLM required)."""
        if not doc.content.strip() and not doc.title.strip():
            return []

        # Determine kind from keywords in title + content
        text_lower = (doc.title + " " + doc.content[:500]).lower()
        kind = "Note"
        best_score = 0
        for k, keywords in _KIND_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > best_score:
                best_score = score
                kind = k

        # Use metadata kind_hint if available (e.g., from GitHub labels)
        kind_hint = doc.metadata.get("kind_hint", "")
        if kind_hint and kind_hint in ("Pitfall", "Decision", "Rule", "Note"):
            kind = kind_hint

        # Confidence: heuristic is lower than LLM
        confidence = 0.5
        if best_score >= 3:
            confidence = 0.6
        if doc.metadata.get("state") == "closed" and doc.metadata.get("comments", 0) > 2:
            confidence = 0.65  # closed issue with discussion = higher signal

        title = doc.title[:200]
        content = doc.content[:2000]
        if not content:
            content = title  # use title as content if body is empty

        tags = doc.metadata.get("labels", [])
        if isinstance(tags, list):
            tags = [str(t) for t in tags[:10]]
        else:
            tags = []

        return [KnowledgeCandidate(
            title=title,
            content=content,
            kind=kind,
            confidence=confidence,
            source=doc.source,
            tags=tags,
        )]

    # ── Dedup ───────────────────────────────────────────────────

    def _is_duplicate(self, cand: KnowledgeCandidate) -> bool:
        """Check if a candidate duplicates existing knowledge."""
        try:
            # Exact title match
            existing = self._brain.db.conn.execute(
                "SELECT 1 FROM nodes WHERE title = ? LIMIT 1",
                (cand.title,),
            ).fetchone()
            if existing:
                logger.debug("Dedup: exact title match for '%s'", cand.title)
                return True

            # FTS5 similarity check
            results = self._brain.db.search_nodes(cand.title, limit=3)
            for r in results:
                # Jaccard token overlap
                a_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", cand.title.lower()))
                b_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", r.get("title", "").lower()))
                if a_tokens and b_tokens:
                    overlap = len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
                    if overlap >= 0.8:
                        logger.debug("Dedup: Jaccard %.2f for '%s' ≈ '%s'",
                                     overlap, cand.title, r.get("title"))
                        return True
        except Exception as e:
            logger.debug("Dedup check failed (non-fatal): %s", e)
        return False

    # ── Write ───────────────────────────────────────────────────

    def _write_to_l3(self, cand: KnowledgeCandidate, source_label: str) -> None:
        """Write high-confidence candidate directly to L3."""
        self._brain.add_knowledge(
            title=cand.title,
            content=cand.content,
            kind=cand.kind,
            tags=cand.tags,
            source=f"{source_label}:{cand.source}",
            confidence=cand.confidence,
        )

    def _write_to_staging(self, cand: KnowledgeCandidate, source_label: str) -> None:
        """Write low-confidence candidate to KRB staging for review."""
        try:
            krb = self._brain.krb
            if krb:
                krb.submit(
                    title=cand.title,
                    content=cand.content,
                    kind=cand.kind,
                    tags=",".join(cand.tags),
                    source=source_label,
                    submitter="ingest-pipeline",
                )
            else:
                # No KRB available — write to L3 anyway with low confidence
                self._write_to_l3(cand, source_label)
        except Exception as e:
            logger.warning("Staging write failed, writing to L3: %s", e)
            self._write_to_l3(cand, source_label)
