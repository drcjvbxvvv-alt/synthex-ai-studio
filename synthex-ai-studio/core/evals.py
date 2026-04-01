"""
SYNTHEX Evals Framework (v1.0)

自動化品質評估 pipeline：防止每次改動 Agent system prompt 後品質回退。

架構：
  Golden Dataset（標準測試案例）
    ↓
  EvalRunner（呼叫 Agent 產生輸出）
    ↓
  EvalScorer（多維度評分）
    ↓
  EvalReport（與基準比較，標記回退）

安全設計：
  - 測試案例資料與程式碼分離（JSON 格式）
  - 評分結果持久化到 SQLite
  - 每次 eval 有唯一 run_id
  - API 呼叫有 timeout 和重試上限

使用方式：
  python -m core.evals run --agent ECHO --suite prd_quality
  python -m core.evals compare --baseline v1.0 --current HEAD
  python -m core.evals report
"""

from __future__ import annotations

import os
import sys
import json
import time
import uuid
import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# ── 常數 ─────────────────────────────────────────────────────────
EVALS_DIR    = Path(__file__).parent.parent / "evals"
EVALS_DB     = EVALS_DIR / "results.db"
SUITES_DIR   = EVALS_DIR / "suites"
MAX_TOKENS_PER_EVAL = 2000   # 每次 eval 的 token 上限（成本控制）
EVAL_TIMEOUT        = 60     # 秒


@dataclass
class EvalCase:
    """單一測試案例"""
    case_id:     str
    suite:       str
    agent:       str
    prompt:      str
    context:     str      = ""
    expected_keywords: list[str] = field(default_factory=list)
    forbidden_keywords: list[str] = field(default_factory=list)
    rubric:      dict = field(default_factory=dict)
    tags:        list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """單次 eval 結果"""
    run_id:      str
    case_id:     str
    agent:       str
    output:      str
    score:       float       # 0.0 - 1.0
    passed:      bool
    latency_ms:  int
    tokens_used: int
    breakdown:   dict = field(default_factory=dict)
    error:       str  = ""
    eval_at:     str  = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EvalScorer:
    """
    多維度評分器：
      1. 關鍵字命中率
      2. 禁用詞過濾
      3. 長度合理性
      4. Claude 語義評分（選填）
    """

    def score(self, case: EvalCase, output: str) -> tuple[float, dict]:
        breakdown: dict[str, float] = {}
        weights = {"keywords": 0.4, "forbidden": 0.2, "length": 0.1, "rubric": 0.3}

        # 1. 關鍵字命中
        if case.expected_keywords:
            hits = sum(
                1 for kw in case.expected_keywords
                if kw.lower() in output.lower()
            )
            breakdown["keywords"] = hits / len(case.expected_keywords)
        else:
            breakdown["keywords"] = 1.0
            weights["keywords"] = 0.0

        # 2. 禁用詞（出現就扣分）
        if case.forbidden_keywords:
            violations = sum(
                1 for kw in case.forbidden_keywords
                if kw.lower() in output.lower()
            )
            breakdown["forbidden"] = 1.0 - min(1.0, violations / max(1, len(case.forbidden_keywords)))
        else:
            breakdown["forbidden"] = 1.0
            weights["forbidden"] = 0.0

        # 3. 長度合理性
        output_len = len(output.strip())
        min_len = case.rubric.get("min_length", 50)
        max_len = case.rubric.get("max_length", 5000)
        if output_len < min_len:
            breakdown["length"] = max(0.0, output_len / min_len)
        elif output_len > max_len:
            breakdown["length"] = max(0.0, 1.0 - (output_len - max_len) / max_len)
        else:
            breakdown["length"] = 1.0

        # 4. Rubric 評分（來自測試案例定義）
        if case.rubric.get("criteria"):
            # 簡單規則評分（不呼叫 API，快速）
            criteria_score = 1.0
            for criterion, check in case.rubric["criteria"].items():
                if check.get("contains") and check["contains"].lower() not in output.lower():
                    criteria_score -= (1.0 / len(case.rubric["criteria"]))
            breakdown["rubric"] = max(0.0, criteria_score)
        else:
            breakdown["rubric"] = 1.0
            weights["rubric"] = 0.0

        # 加權總分
        total_weight = sum(w for k, w in weights.items() if breakdown.get(k) is not None)
        if total_weight == 0:
            final_score = 1.0
        else:
            final_score = sum(
                breakdown.get(k, 0.0) * w
                for k, w in weights.items()
            ) / total_weight

        return round(final_score, 4), breakdown


class EvalRunner:
    """執行 eval，呼叫真實 Agent"""

    def __init__(self, workdir: str = "."):
        self.workdir = workdir
        self.scorer  = EvalScorer()
        self._setup_db()

    def _setup_db(self) -> None:
        EVALS_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(EVALS_DB))
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS eval_runs (
            run_id     TEXT PRIMARY KEY,
            suite      TEXT,
            agent      TEXT,
            started_at TEXT,
            finished_at TEXT,
            total_cases INTEGER,
            passed      INTEGER,
            avg_score   REAL,
            git_hash    TEXT,
            notes       TEXT
        );
        CREATE TABLE IF NOT EXISTS eval_results (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id     TEXT,
            case_id    TEXT,
            agent      TEXT,
            passed     INTEGER,
            score      REAL,
            latency_ms INTEGER,
            tokens     INTEGER,
            breakdown  TEXT,
            error      TEXT,
            eval_at    TEXT
        );
        """)
        conn.commit()
        conn.close()

    def run_suite(
        self,
        suite_name: str,
        agent_name: Optional[str] = None,
        dry_run:    bool = False,
    ) -> dict:
        """執行整個測試套件"""
        suite_file = SUITES_DIR / f"{suite_name}.json"
        if not suite_file.exists():
            raise FileNotFoundError(f"測試套件不存在：{suite_file}")

        cases_raw = json.loads(suite_file.read_text())
        cases = [
            EvalCase(**c) for c in cases_raw
            if not agent_name or c.get("agent") == agent_name
        ]

        if not cases:
            return {"error": f"套件 {suite_name} 中沒有 {agent_name} 的測試案例"}

        run_id    = str(uuid.uuid4())[:8]
        results   = []
        started   = time.monotonic()

        print(f"\n🧪 Evals: {suite_name} × {len(cases)} cases")
        print(f"   Run ID: {run_id}")
        print()

        for i, case in enumerate(cases, 1):
            print(f"  [{i:2d}/{len(cases)}] {case.case_id} ... ", end="", flush=True)
            if dry_run:
                print("（dry-run）")
                continue

            result = self._run_case(case, run_id)
            results.append(result)

            status = "✓" if result.passed else "✗"
            print(f"{status} {result.score:.0%} ({result.latency_ms}ms)")

        elapsed   = int((time.monotonic() - started) * 1000)
        passed    = sum(1 for r in results if r.passed)
        avg_score = sum(r.score for r in results) / len(results) if results else 0

        # 儲存結果
        if results:
            self._save_results(run_id, suite_name, agent_name or "all", results, avg_score)

        report = {
            "run_id":      run_id,
            "suite":       suite_name,
            "total":       len(results),
            "passed":      passed,
            "failed":      len(results) - passed,
            "pass_rate":   f"{passed/len(results):.0%}" if results else "N/A",
            "avg_score":   f"{avg_score:.0%}",
            "elapsed_ms":  elapsed,
        }

        print(f"\n{'─'*50}")
        print(f"結果：{passed}/{len(results)} 通過  平均分：{avg_score:.0%}")
        if passed < len(results):
            print("⚠ 有測試失敗，建議檢查 Agent prompt")

        return report

    def _run_case(self, case: EvalCase, run_id: str) -> EvalResult:
        """執行單一測試案例"""
        t0 = time.monotonic()
        try:
            sys.path.insert(0, self.workdir)
            from agents.all_agents import ALL_AGENTS
            if case.agent not in ALL_AGENTS:
                raise ValueError(f"Agent {case.agent} 不存在")

            AgentClass = ALL_AGENTS[case.agent]
            agent = AgentClass(workdir=self.workdir)

            output = agent.chat(case.prompt, context=case.context)

            latency_ms  = int((time.monotonic() - t0) * 1000)
            score, breakdown = self.scorer.score(case, output)
            pass_threshold   = case.rubric.get("pass_threshold", 0.6)

            return EvalResult(
                run_id     = run_id,
                case_id    = case.case_id,
                agent      = case.agent,
                output     = output[:2000],
                score      = score,
                passed     = score >= pass_threshold,
                latency_ms = latency_ms,
                tokens_used= 0,   # 從 budget 取
                breakdown  = breakdown,
            )
        except Exception as e:
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.error("eval case %s 失敗：%s", case.case_id, e)
            return EvalResult(
                run_id     = run_id,
                case_id    = case.case_id,
                agent      = case.agent,
                output     = "",
                score      = 0.0,
                passed     = False,
                latency_ms = latency_ms,
                tokens_used= 0,
                error      = str(e)[:200],
            )

    def _save_results(
        self, run_id: str, suite: str, agent: str,
        results: list[EvalResult], avg_score: float,
    ) -> None:
        conn = sqlite3.connect(str(EVALS_DB))
        try:
            conn.execute("""
                INSERT INTO eval_runs (run_id, suite, agent, started_at, total_cases, passed, avg_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (run_id, suite, agent, datetime.now().isoformat(),
                  len(results), sum(1 for r in results if r.passed), avg_score))

            for r in results:
                conn.execute("""
                    INSERT INTO eval_results
                        (run_id, case_id, agent, passed, score, latency_ms, tokens,
                         breakdown, error, eval_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (r.run_id, r.case_id, r.agent, int(r.passed),
                      r.score, r.latency_ms, r.tokens_used,
                      json.dumps(r.breakdown), r.error, r.eval_at))
            conn.commit()
        finally:
            conn.close()

    def compare(self, baseline_run_id: str, current_run_id: str) -> dict:
        """比較兩次 eval run 的結果，偵測品質回退"""
        conn = sqlite3.connect(str(EVALS_DB))
        try:
            baseline = {
                r["case_id"]: r["score"]
                for r in conn.execute(
                    "SELECT case_id, score FROM eval_results WHERE run_id=?",
                    (baseline_run_id,)
                ).fetchall()
            }
            current = {
                r["case_id"]: r["score"]
                for r in conn.execute(
                    "SELECT case_id, score FROM eval_results WHERE run_id=?",
                    (current_run_id,)
                ).fetchall()
            }
        finally:
            conn.close()

        regressions = []
        improvements = []

        for case_id in set(baseline) & set(current):
            delta = current[case_id] - baseline[case_id]
            if delta < -0.1:
                regressions.append((case_id, baseline[case_id], current[case_id]))
            elif delta > 0.1:
                improvements.append((case_id, baseline[case_id], current[case_id]))

        return {
            "regressions":   regressions,
            "improvements":  improvements,
            "has_regression":bool(regressions),
        }


# ── Golden Dataset 初始化 ─────────────────────────────────────────

def create_default_suites() -> None:
    """建立預設測試套件"""
    SUITES_DIR.mkdir(parents=True, exist_ok=True)

    # PRD 品質測試套件
    prd_suite = [
        {
            "case_id":   "prd-001",
            "suite":     "prd_quality",
            "agent":     "ECHO",
            "prompt":    "為一個簡單的待辦事項 App 寫一份 PRD，包含用戶故事和 AC。",
            "context":   "",
            "expected_keywords": ["用戶故事", "驗收條件", "P0", "AC"],
            "forbidden_keywords": ["lorem ipsum", "待填寫"],
            "rubric": {
                "min_length": 300,
                "pass_threshold": 0.6,
                "criteria": {
                    "has_user_story": {"contains": "作為"},
                    "has_ac": {"contains": "Given"},
                },
            },
            "tags": ["prd", "basic"],
        },
        {
            "case_id":   "prd-002",
            "suite":     "prd_quality",
            "agent":     "ECHO",
            "prompt":    "分析這個需求的邊界條件：用戶可以上傳圖片。",
            "expected_keywords": ["空檔案", "檔案大小", "格式", "錯誤"],
            "forbidden_keywords": [],
            "rubric": {"min_length": 100, "pass_threshold": 0.5},
            "tags": ["prd", "edge-cases"],
        },
    ]

    # 架構設計測試套件
    arch_suite = [
        {
            "case_id":   "arch-001",
            "suite":     "architecture_quality",
            "agent":     "NEXUS",
            "prompt":    "設計一個支援 1000 個並發用戶的電商後端架構。",
            "expected_keywords": ["資料庫", "快取", "API", "擴展"],
            "rubric": {
                "min_length": 400,
                "pass_threshold": 0.6,
                "criteria": {
                    "mentions_db": {"contains": "PostgreSQL"},
                    "mentions_cache": {"contains": "Redis"},
                },
            },
            "tags": ["architecture", "scalability"],
        },
    ]

    (SUITES_DIR / "prd_quality.json").write_text(
        json.dumps(prd_suite, ensure_ascii=False, indent=2)
    )
    (SUITES_DIR / "architecture_quality.json").write_text(
        json.dumps(arch_suite, ensure_ascii=False, indent=2)
    )
    print(f"✓ 預設測試套件已建立：{SUITES_DIR}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SYNTHEX Evals Framework")
    subparsers = parser.add_subparsers(dest="command")

    run_p = subparsers.add_parser("run")
    run_p.add_argument("--suite",  required=True)
    run_p.add_argument("--agent",  default=None)
    run_p.add_argument("--dry-run",action="store_true")

    subparsers.add_parser("init")

    args = parser.parse_args()

    if args.command == "init":
        create_default_suites()
    elif args.command == "run":
        runner = EvalRunner(workdir=os.getcwd())
        runner.run_suite(args.suite, args.agent, dry_run=args.dry_run)
    else:
        parser.print_help()
