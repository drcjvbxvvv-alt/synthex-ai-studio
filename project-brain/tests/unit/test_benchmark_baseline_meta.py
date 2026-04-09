"""
tests/unit/test_benchmark_baseline_meta.py

MEDIUM-07 — baseline.json 結構驗證（不執行 benchmark，永遠 cheap）
(ARCHITECTURE_REVIEW.md §3 MEDIUM-07)

這些測試在每次 unit test 跑都會執行，確保 baseline.json：
  1. 存在
  2. 是合法 JSON
  3. 含必要欄位 + 類型正確
  4. 門檻值在合理範圍

如此一來，若有人不小心搞壞 baseline.json，普通測試流程就會 fail，不需要
等到 benchmark 整套跑完才發現。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

BASELINE_PATH = (
    Path(__file__).parent.parent / "benchmarks" / "baseline.json"
)


class TestBaselineMeta(unittest.TestCase):

    def setUp(self):
        self.assertTrue(
            BASELINE_PATH.exists(),
            f"MEDIUM-07: baseline.json 不存在於 {BASELINE_PATH}",
        )
        self.data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    def test_M01_top_level_keys(self):
        for key in ("schema_version", "updated_at", "metrics"):
            self.assertIn(key, self.data, f"baseline.json 缺 {key}")
        self.assertEqual(self.data["schema_version"], 1)

    def test_M02_metrics_have_recall_threshold(self):
        rec = self.data["metrics"].get("recall_at_3", {})
        self.assertIn("min_value", rec)
        self.assertIsInstance(rec["min_value"], (int, float))
        self.assertGreaterEqual(rec["min_value"], 0.0)
        self.assertLessEqual(rec["min_value"],    1.0)

    def test_M03_metrics_have_latency_thresholds(self):
        for key in ("avg_query_ms", "max_query_ms"):
            spec = self.data["metrics"].get(key, {})
            self.assertIn("max_value", spec, f"{key} 缺 max_value")
            self.assertIsInstance(spec["max_value"], (int, float))
            self.assertGreater(spec["max_value"], 0)

    def test_M04_avg_threshold_lte_p100_threshold(self):
        """平均延遲門檻不可大於 p100 門檻（合理性檢查）"""
        avg_max = self.data["metrics"]["avg_query_ms"]["max_value"]
        p100_max = self.data["metrics"]["max_query_ms"]["max_value"]
        self.assertLessEqual(avg_max, p100_max,
                             "avg_query_ms.max 不應大於 max_query_ms.max")

    def test_M05_fixture_metadata_present(self):
        """記錄 benchmark 用什麼 fixture 跑出來的（重要的 reproducibility 線索）"""
        fix = self.data.get("fixture", {})
        self.assertIn("node_count",  fix)
        self.assertIn("query_count", fix)
        self.assertGreater(fix["node_count"],  0)
        self.assertGreater(fix["query_count"], 0)


if __name__ == "__main__":
    unittest.main()
