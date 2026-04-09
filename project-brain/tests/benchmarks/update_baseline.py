"""
tests/benchmarks/update_baseline.py

MEDIUM-07 helper: 重新跑 benchmark_recall 並把實測值寫入 baseline.json。

使用方式：
    python tests/benchmarks/update_baseline.py            # 更新 observed 區段
    python tests/benchmarks/update_baseline.py --tighten  # 同時收緊 min/max 門檻

baseline.json 的 metrics 區段語意：
    recall_at_3.min_value   - 最小可接受召回率（低於此值 → fail）
    avg_query_ms.max_value  - 最大可接受平均延遲
    max_query_ms.max_value  - 最大可接受 p100 延遲

預設不更動門檻（只更新 observed 區段）。`--tighten` 會把 min_value 往上推、
max_value 往下壓，貼近實際觀察值（留 30% 緩衝）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
BASELINE_PATH = ROOT / "baseline.json"


def _round(x: float, ndigits: int = 3) -> float:
    return round(float(x), ndigits)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="MEDIUM-07: refresh benchmark baseline.json from a fresh run."
    )
    ap.add_argument(
        "--tighten",
        action="store_true",
        help="Tighten min/max thresholds toward observed values (with 30%% buffer).",
    )
    args = ap.parse_args()

    # 確保可以 import benchmark_recall
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    try:
        from tests.benchmarks.benchmark_recall import compute_metrics
    except Exception as e:
        print(f"ERROR: 無法 import benchmark_recall: {e}", file=sys.stderr)
        return 2

    print("running benchmark_recall.compute_metrics()...", file=sys.stderr)
    metrics = compute_metrics()
    print("observed:", json.dumps(metrics, ensure_ascii=False, indent=2),
          file=sys.stderr)

    if not BASELINE_PATH.exists():
        print(f"ERROR: {BASELINE_PATH} 不存在", file=sys.stderr)
        return 2

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    baseline["updated_at"] = datetime.now(timezone.utc).isoformat()
    baseline["last_observed"] = {
        "recall_at_3":    _round(metrics["recall_at_3"]),
        "avg_query_ms":   _round(metrics["avg_query_ms"], 1),
        "max_query_ms":   int(metrics["max_query_ms"]),
        "embedder_class": metrics["embedder_class"],
        "embedder_model": metrics["embedder_model"],
    }

    if args.tighten:
        # 召回率往上靠 — 留 0.10 緩衝（不要超過 1.0）
        new_min_recall = max(0.0, min(1.0, _round(metrics["recall_at_3"] - 0.10, 2)))
        # 平均延遲往下壓 — 留 30% 緩衝
        new_max_avg = _round(metrics["avg_query_ms"] * 1.3, 1)
        # p100 延遲 — 留 50% 緩衝
        new_max_p100 = int(metrics["max_query_ms"] * 1.5)
        baseline["metrics"]["recall_at_3"]["min_value"]  = new_min_recall
        baseline["metrics"]["avg_query_ms"]["max_value"] = new_max_avg
        baseline["metrics"]["max_query_ms"]["max_value"] = float(new_max_p100)
        print(f"--tighten: min_recall={new_min_recall} "
              f"max_avg={new_max_avg}ms max_p100={new_max_p100}ms",
              file=sys.stderr)

    BASELINE_PATH.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"baseline.json updated → {BASELINE_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
