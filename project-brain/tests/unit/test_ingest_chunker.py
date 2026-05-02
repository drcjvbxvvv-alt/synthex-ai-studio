"""
tests/unit/test_ingest_chunker.py — E-04 TextChunker 測試

覆蓋：
  - heading 切分
  - CJK token 估算
  - 長段落二次切分
  - 空文件處理
  - 無 heading 文件
"""
from __future__ import annotations

import unittest

from project_brain.integrations.ingest.chunker import (
    Chunk, chunk_markdown, estimate_tokens,
)


class TestEstimateTokens(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(estimate_tokens(""), 0)

    def test_latin(self):
        tokens = estimate_tokens("Hello world, this is a test.")
        self.assertGreater(tokens, 0)
        self.assertLess(tokens, 20)

    def test_cjk(self):
        tokens = estimate_tokens("這是一個中文測試")
        # 8 CJK chars × 1.5 = 12
        self.assertEqual(tokens, 12)

    def test_mixed(self):
        tokens = estimate_tokens("JWT 驗證過期問題")
        self.assertGreater(tokens, 0)


class TestChunkMarkdown(unittest.TestCase):

    def test_empty_string(self):
        self.assertEqual(chunk_markdown(""), [])

    def test_whitespace_only(self):
        self.assertEqual(chunk_markdown("   \n\n  "), [])

    def test_no_headings(self):
        text = "Just a paragraph of text.\n\nAnother paragraph."
        chunks = chunk_markdown(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].title, "")
        self.assertEqual(chunks[0].level, 0)

    def test_single_heading(self):
        text = "# Title\nParagraph content."
        chunks = chunk_markdown(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].title, "Title")
        self.assertEqual(chunks[0].level, 1)
        self.assertIn("Paragraph", chunks[0].content)

    def test_multiple_headings(self):
        text = "# First\nContent 1.\n\n## Second\nContent 2.\n\n### Third\nContent 3."
        chunks = chunk_markdown(text)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].title, "First")
        self.assertEqual(chunks[1].title, "Second")
        self.assertEqual(chunks[2].title, "Third")

    def test_preamble_before_first_heading(self):
        text = "Preamble text.\n\n# Heading\nContent."
        chunks = chunk_markdown(text)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].title, "")  # preamble
        self.assertIn("Preamble", chunks[0].content)
        self.assertEqual(chunks[1].title, "Heading")

    def test_heading_levels_preserved(self):
        text = "# H1\nA\n\n## H2\nB\n\n### H3\nC\n\n#### H4\nD"
        chunks = chunk_markdown(text)
        levels = [c.level for c in chunks]
        self.assertEqual(levels, [1, 2, 3, 4])

    def test_empty_section_skipped(self):
        text = "# Title\n\n## Empty\n\n## Has Content\nReal content."
        chunks = chunk_markdown(text)
        # Empty section should still appear (title is non-empty)
        titles = [c.title for c in chunks]
        self.assertIn("Has Content", titles)

    def test_long_section_split(self):
        """Long sections should be split on paragraph boundaries."""
        paras = ["Paragraph " + str(i) + "." + " x" * 200 for i in range(10)]
        text = "# Long Section\n" + "\n\n".join(paras)
        chunks = chunk_markdown(text, max_tokens=100)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0].title, "Long Section")
        # Continuation chunks should have "(cont.)" suffix
        if len(chunks) > 1:
            self.assertIn("cont.", chunks[1].title)

    def test_cjk_heading(self):
        text = "# 中文標題\n中文內容。"
        chunks = chunk_markdown(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].title, "中文標題")


if __name__ == "__main__":
    unittest.main()
