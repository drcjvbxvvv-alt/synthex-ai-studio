"""
core/brain/consolidation.py — 記憶整合器（v8.0）

## 問題

Project Brain 在 MemGPT 框架的評分只有 67%，主要缺口是：
- 缺乏 reflection（定期反思和整合記憶）
- L1a 工作記憶的 progress/notes 條目不會自動進入 L3 長期記憶

## 解法

MemoryConsolidator 仿 MemGPT 的 reflection 機制：
定期分析 L1a 工作記憶中有價值的條目，
用 LLM 提煉成結構化知識，送入 KRB Staging 等待人工審查。

## 觸發方式

    # 手動（CLI）
    brain consolidate --hours 24

    # 自動（cron）
    0 2 * * * brain consolidate --workdir /your/project

    # EventBus（brain.scan 事件後自動）
    @bus.on("brain.scan")
    def on_scan(payload):
        consolidator.consolidate(since_hours=1)

## 整合到 MemGPT 框架的位置

Atkinson-Shiffrin 多儲存模型：
  L1a（短期）→ [MemoryConsolidator] → L3（長期）
  ↑ 補上了 MemGPT 框架缺失的 "consolidation" 機制
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ConsolidationResult:
    """整合結果摘要"""
    def __init__(self):
        self.entries_analyzed: int = 0
        self.chunks_extracted: int = 0
        self.staged_to_krb:    int = 0
        self.skipped_low_value: int = 0
        self.elapsed_ms:        float = 0.0

    def __repr__(self) -> str:
        return (
            f"ConsolidationResult("
            f"analyzed={self.entries_analyzed}, "
            f"extracted={self.chunks_extracted}, "
            f"staged={self.staged_to_krb}, "
            f"skipped={self.skipped_low_value})"
        )


class MemoryConsolidator:
    """
    記憶整合器（v8.0）。

    把 L1a 工作記憶（progress/notes）提煉到 L3 長期記憶的橋樑。

    設計約束：
    - 提煉需要 LLM，有費用。只在 entries >= MIN_ENTRIES 時執行。
    - 提煉結果送 KRB Staging，不自動核准。人類決定是否長期保留。
    - 已整合的條目標記 consolidated=True，避免重複提煉。
    """

    MIN_ENTRIES    = 3    # 少於 3 條不值得整合
    MAX_ENTRIES    = 50   # 一次最多整合 50 條（控制費用）
    MIN_VALUE_LEN  = 20   # 少於 20 字的條目跳過

    def __init__(self, session_store, extractor, review_board):
        """
        Args:
            session_store: SessionStore 實例（L1a）
            extractor:     KnowledgeExtractor 實例（LLM 提煉）
            review_board:  KnowledgeReviewBoard 實例（KRB Staging）
        """
        self.session_store = session_store
        self.extractor     = extractor
        self.review_board  = review_board

    def consolidate(
        self,
        since_hours: int = 24,
        categories:  list[str] | None = None,
        dry_run:     bool = False,
    ) -> ConsolidationResult:
        """
        分析近期工作記憶，提煉有價值的知識到 KRB Staging。

        Args:
            since_hours: 分析多少小時前到現在的條目（預設 24 小時）
            categories:  要整合的 L1a 類別（預設 progress + notes）
            dry_run:     True=只統計，不實際送 KRB

        Returns:
            ConsolidationResult：整合統計
        """
        import time
        result = ConsolidationResult()
        start  = time.monotonic()

        cats = categories or ["progress", "notes"]
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=since_hours)
        ).isoformat()

        # 取得 L1a 條目
        entries = []
        for cat in cats:
            try:
                all_entries = self.session_store.list_all(category=cat)
                entries.extend(
                    e for e in all_entries
                    if e.created_at >= cutoff
                    and len(e.value) >= self.MIN_VALUE_LEN
                )
            except Exception as e:
                logger.warning("consolidate: list_all(%s) failed: %s", cat, e)

        result.entries_analyzed = min(len(entries), self.MAX_ENTRIES)
        entries = entries[:self.MAX_ENTRIES]

        if result.entries_analyzed < self.MIN_ENTRIES:
            logger.info(
                "consolidate: only %d entries, minimum is %d, skipping",
                result.entries_analyzed, self.MIN_ENTRIES
            )
            result.elapsed_ms = (time.monotonic() - start) * 1000
            return result

        # 組合文字供 LLM 提煉
        combined = "\n".join(
            f"[{e.category}] {e.value}"
            for e in entries
        )

        # 提煉（呼叫 LLM）
        try:
            chunks = self.extractor.extract_from_text(
                text        = combined,
                prompt_hint = (
                    "分析以下工作記憶條目，提煉出值得長期保留的知識。\n"
                    "只提煉：工程決策的原因、踩坑和解法、架構規律、值得記憶的教訓。\n"
                    "排除：臨時筆記、已完成的 TODO、無法複用的一次性資訊。\n"
                    "每條知識要有具體的標題和詳細的內容，以便未來的 AI 能理解背景。"
                ),
            )
        except Exception as e:
            logger.error("consolidate: LLM extraction failed: %s", e)
            result.elapsed_ms = (time.monotonic() - start) * 1000
            return result

        result.chunks_extracted = len(chunks)

        # 送 KRB Staging
        for chunk in chunks:
            title   = chunk.get("title", "")
            content = chunk.get("content", "")
            kind    = chunk.get("type", "Rule")

            if not title or not content:
                result.skipped_low_value += 1
                continue

            if dry_run:
                logger.info("consolidate [dry-run]: would stage '%s'", title[:40])
                result.staged_to_krb += 1
                continue

            try:
                self.review_board.submit(
                    title     = title,
                    content   = content,
                    kind      = kind,
                    source    = f"memory-consolidation:{cutoff[:10]}",
                    submitter = "memory-consolidator",
                )
                result.staged_to_krb += 1
            except Exception as e:
                logger.warning("consolidate: KRB submit failed for '%s': %s", title[:40], e)
                result.skipped_low_value += 1

        result.elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "consolidate: %s hours → analyzed=%d extracted=%d staged=%d",
            since_hours, result.entries_analyzed,
            result.chunks_extracted, result.staged_to_krb
        )
        return result

    def consolidate_on_scan(self, scan_result: dict) -> ConsolidationResult:
        """
        brain scan 完成後自動整合（由 BrainEventBus 觸發）。
        只整合最近 1 小時的條目（scan 期間產生的工作記憶）。
        """
        return self.consolidate(since_hours=1, dry_run=False)
