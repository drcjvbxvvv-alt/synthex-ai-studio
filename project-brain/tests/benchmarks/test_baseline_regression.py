"""
tests/benchmarks/test_baseline_regression.py

MEDIUM-07 — benchmark_recall 對比 baseline.json 的迴歸測試
(ARCHITECTURE_REVIEW.md §3 MEDIUM-07, §8.4 v0.34)

問題：tests/benchmarks/ 下已有 benchmark_recall.py，但無 CI baseline 對比，
效能或召回率退化無法及時發現。

修法：
  1. benchmark_recall.compute_metrics() 回傳結構化指標
  2. tests/benchmarks/baseline.json 儲存門檻（min_value / max_value）
  3. 本檔案以 pytest test 形式跑 benchmark 並斷言指標未退化

以 ``@pytest.mark.benchmark`` 標記，可用 ``pytest -m benchmark`` 單獨執行。
若 embedder 不可用（無 model 下載 / sentence-transformers 未安裝），測試會
skip 而非 fail，避免乾淨環境誤觸警報。

更新 baseline 的方式：``python tests/benchmarks/update_baseline.py``
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import pytest

BASELINE_PATH = Path(__file__).parent / "baseline.json"


# ══════════════════════════════════════════════════════════════════
#  共用 helper
# ══════════════════════════════════════════════════════════════════

def _load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        pytest.fail(f"baseline.json 不存在於 {BASELINE_PATH}")
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def benchmark_metrics() -> dict:
    """
    執行一次 benchmark 並把結果共享給所有 test（昂貴操作只做一次）。

    若 embedder 載入失敗，整組測試 skip。
    """
    try:
        from tests.benchmarks.benchmark_recall import compute_metrics
        return compute_metrics()
    except Exception as e:
        pytest.skip(f"benchmark_recall 無法執行（embedder 不可用？）：{e}")


# ══════════════════════════════════════════════════════════════════
#  迴歸測試
# ══════════════════════════════════════════════════════════════════

@pytest.mark.benchmark
def test_recall_no_regression(benchmark_metrics: dict):
    """
    召回率不應低於 baseline.json 的 min_value。

    這是最重要的迴歸守門員 — 召回率掉就代表 retrieval pipeline 有問題
    （embedder / FTS5 / scoring 任一環節）。
    """
    baseline = _load_baseline()
    spec     = baseline["metrics"]["recall_at_3"]
    actual   = benchmark_metrics["recall_at_3"]
    minimum  = float(spec["min_value"])
    assert actual >= minimum, (
        f"recall@3 退化：actual={actual:.3f} < baseline.min={minimum:.3f}\n"
        f"  embedder={benchmark_metrics.get('embedder_class')}"
        f" {benchmark_metrics.get('embedder_model', '')}\n"
        f"  hits/total = {benchmark_metrics.get('recall_at_3', 0)*benchmark_metrics.get('query_count',0):.0f}"
        f"/{benchmark_metrics.get('query_count')}\n"
        f"  → 確認 retrieval pipeline 是否變更 / embedder model 是否退版"
    )


@pytest.mark.benchmark
def test_avg_latency_no_regression(benchmark_metrics: dict):
    """
    平均單次查詢延遲不應超過 baseline.json 的 max_value。
    """
    baseline = _load_baseline()
    spec     = baseline["metrics"]["avg_query_ms"]
    actual   = benchmark_metrics["avg_query_ms"]
    maximum  = float(spec["max_value"])
    assert actual <= maximum, (
        f"avg_query_ms 退化：actual={actual:.1f}ms > baseline.max={maximum:.1f}ms\n"
        f"  → 確認 search_nodes / context build / embedder 是否引入新瓶頸"
    )


@pytest.mark.benchmark
def test_p100_latency_no_regression(benchmark_metrics: dict):
    """
    最慢單次查詢延遲（p100）不應超過 baseline.json 的 max_value。
    捕捉「平均看似正常但有 outlier」的情境。
    """
    baseline = _load_baseline()
    spec     = baseline["metrics"]["max_query_ms"]
    actual   = float(benchmark_metrics["max_query_ms"])
    maximum  = float(spec["max_value"])
    assert actual <= maximum, (
        f"max_query_ms 退化：actual={actual:.0f}ms > baseline.max={maximum:.0f}ms\n"
        f"  → 至少有一次查詢 latency 異常，可能是 embedder 冷啟動或 FTS5 plan 變差"
    )


@pytest.mark.benchmark
def test_metric_envelope_sanity(benchmark_metrics: dict):
    """快速 sanity check — 確保 compute_metrics() 回傳的 dict 結構符合預期。"""
    expected_keys = {
        "recall_at_3", "avg_query_ms", "max_query_ms",
        "node_count", "query_count", "embedder_class", "embedder_model",
    }
    missing = expected_keys - set(benchmark_metrics.keys())
    assert not missing, f"compute_metrics() 缺欄位：{missing}"
    # 數值區間
    assert 0.0 <= benchmark_metrics["recall_at_3"] <= 1.0
    assert benchmark_metrics["avg_query_ms"] >= 0
    assert benchmark_metrics["max_query_ms"] >= benchmark_metrics["avg_query_ms"]
    assert benchmark_metrics["query_count"] > 0
