"""
tests/unit/test_ingest_files.py — E-04 LocalFilesIngestSource 測試

覆蓋：
  - scan Markdown files
  - heading extraction into RawDocuments
  - glob pattern filtering
  - nonexistent path
  - single file mode
  - empty files skipped
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from project_brain.integrations.ingest.files import LocalFilesIngestSource


class TestLocalFilesIngest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_scan_markdown_files(self):
        (self.root / "doc.md").write_text("# Auth\nJWT rules.\n\n## Tokens\nExpiry check.", encoding="utf-8")
        source = LocalFilesIngestSource()
        docs = source.fetch(self.root)
        self.assertGreater(len(docs), 0)
        titles = [d.title for d in docs]
        self.assertIn("Auth", titles)
        self.assertIn("Tokens", titles)

    def test_raw_document_fields(self):
        (self.root / "test.md").write_text("# Section\nContent here.", encoding="utf-8")
        docs = LocalFilesIngestSource().fetch(self.root)
        self.assertEqual(len(docs), 1)
        doc = docs[0]
        self.assertEqual(doc.title, "Section")
        self.assertIn("Content here", doc.content)
        self.assertTrue(doc.source.startswith("file:"))
        self.assertIn("test.md", doc.url)
        self.assertIn("file_path", doc.metadata)

    def test_nested_directories(self):
        sub = self.root / "sub"
        sub.mkdir()
        (sub / "nested.md").write_text("# Nested\nDeep content.", encoding="utf-8")
        docs = LocalFilesIngestSource().fetch(self.root, glob_pattern="**/*.md")
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].title, "Nested")

    def test_glob_filters_non_md(self):
        (self.root / "readme.md").write_text("# Readme\nInclude me.", encoding="utf-8")
        (self.root / "notes.txt").write_text("# Notes\nExclude me.", encoding="utf-8")
        docs = LocalFilesIngestSource().fetch(self.root, glob_pattern="**/*.md")
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].title, "Readme")

    def test_nonexistent_path(self):
        docs = LocalFilesIngestSource().fetch(self.root / "nope")
        self.assertEqual(docs, [])

    def test_single_file_mode(self):
        f = self.root / "single.md"
        f.write_text("# Only\nOne file.", encoding="utf-8")
        docs = LocalFilesIngestSource().fetch(f)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].title, "Only")

    def test_empty_file_skipped(self):
        (self.root / "empty.md").write_text("", encoding="utf-8")
        docs = LocalFilesIngestSource().fetch(self.root)
        self.assertEqual(docs, [])

    def test_no_heading_uses_filename(self):
        (self.root / "plain.md").write_text("Just plain text without headings.", encoding="utf-8")
        docs = LocalFilesIngestSource().fetch(self.root)
        self.assertEqual(len(docs), 1)
        # Title falls back to filename stem when chunk has no heading
        self.assertEqual(docs[0].title, "plain")

    def test_cjk_content(self):
        (self.root / "zh.md").write_text("# 認證規範\nJWT 必須使用 RS256 簽名。", encoding="utf-8")
        docs = LocalFilesIngestSource().fetch(self.root)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].title, "認證規範")
        self.assertIn("RS256", docs[0].content)

    def test_multiple_files_sorted(self):
        (self.root / "b.md").write_text("# B File\nB content.", encoding="utf-8")
        (self.root / "a.md").write_text("# A File\nA content.", encoding="utf-8")
        docs = LocalFilesIngestSource().fetch(self.root)
        # Should be sorted by path
        self.assertEqual(docs[0].title, "A File")
        self.assertEqual(docs[1].title, "B File")


if __name__ == "__main__":
    unittest.main()
