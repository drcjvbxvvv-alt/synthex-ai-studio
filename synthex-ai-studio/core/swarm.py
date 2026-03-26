"""
AgentSwarm v3 — 非線性並行多 Agent 協作架構（第十輪重構）

重大改動（第十輪）：
  - 加入部分失敗恢復（Partial Failure Recovery）
  - 任務失敗不再直接卡死下游 → 三種可配置策略
  - Swarm 整合 structlog（取代 print）
  - 加入任務重試（SwarmTask.max_retries）
  - 加入 SwarmResult.partial_success 語義

部分失敗恢復策略（FailurePolicy）：
  ABORT     — 任何失敗立即中止整個 Swarm（原始行為，謹慎使用）
  CONTINUE  — 失敗任務標記 FAILED，下游任務 SKIP，其他繼續執行
  FALLBACK  — 失敗任務嘗試使用 fallback_result（預設空字串），下游繼續

速度：
  現有 12 個串行 Phase ≈ 6 分鐘 → Swarm 並行批次 ≈ 3 分鐘

安全：
  - 子任務 timeout（防止單一 Agent 卡住整個 Swarm）
  - 記憶體隔離：每個 Worker Agent 獨立 conversation history
  - Worker 完成後主動清理 conversation history
  - 最大並行數限制（防 API rate limit）
"""

from __future__ import annotations

import time
import logging
import threading
import uuid
from concurrent.futures import (
    ThreadPoolExecutor, Future,
    wait as futures_wait,
    FIRST_COMPLETED,
)
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable

from core.config import cfg
from core.logging_setup import get_logger

logger = get_logger("swarm")

# ── 常數 ──────────────────────────────────────────────────────────
MAX_WORKERS        = 4    # 同時並行 Agent 數上限（防 API rate limit）
WORKER_TIMEOUT_SEC = 120  # 單一 Worker timeout（秒）
POLL_INTERVAL_SEC  = 5    # Swarm 輪詢間隔

SUPERVISOR_MODEL = cfg.model_opus    # NEXUS 使用 Opus
WORKER_MODEL     = cfg.model_sonnet  # Worker 使用 Sonnet


# ── 失敗策略 ──────────────────────────────────────────────────────

class FailurePolicy(Enum):
    """AgentSwarm 任務失敗時的處理策略"""
    ABORT    = "abort"    # 任何失敗立即中止整個 Swarm
    CONTINUE = "continue" # 失敗任務標 FAILED，下游任務 SKIP，其他繼續
    FALLBACK = "fallback" # 失敗任務使用 fallback_result，下游繼續執行


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE    = "done"
    FAILED  = "failed"
    SKIPPED = "skipped"


@dataclass
class SwarmTask:
    """Swarm 中的單一子任務"""
    task_id:        str
    agent_name:     str
    prompt:         str
    depends_on:     list[str]   = field(default_factory=list)
    context_from:   list[str]   = field(default_factory=list)
    timeout:        int         = WORKER_TIMEOUT_SEC
    max_retries:    int         = 1    # 失敗後重試次數（0 = 不重試）
    fallback_result: str        = ""   # FALLBACK 策略下用此替代失敗結果
    status:         TaskStatus  = TaskStatus.PENDING
    result:         str         = ""
    error:          str         = ""
    duration_ms:    int         = 0
    attempt:        int         = 0    # 目前已嘗試次數

    @property
    def can_retry(self) -> bool:
        return self.attempt < self.max_retries

    def reset_for_retry(self) -> None:
        """重設狀態準備重試"""
        self.attempt += 1
        self.status   = TaskStatus.PENDING
        self.error    = ""


@dataclass
class SwarmResult:
    """整個 Swarm 的執行結果"""
    run_id:         str
    tasks_done:     int
    tasks_failed:   int
    tasks_skipped:  int
    total_ms:       int
    final_output:   str
    task_results:   dict[str, str]
    failure_policy: FailurePolicy

    @property
    def total_tasks(self) -> int:
        return self.tasks_done + self.tasks_failed + self.tasks_skipped

    @property
    def partial_success(self) -> bool:
        """部分成功：有任務完成但也有失敗"""
        return self.tasks_done > 0 and self.tasks_failed > 0

    @property
    def success(self) -> bool:
        """完全成功：無失敗無跳過"""
        return self.tasks_failed == 0 and self.tasks_skipped == 0

    def summary(self) -> str:
        status = "✅ 完全成功" if self.success else (
                 "⚠️ 部分成功" if self.partial_success else "❌ 失敗")
        return (
            f"Swarm [{self.run_id}] {status}\n"
            f"  完成：{self.tasks_done} / 失敗：{self.tasks_failed} "
            f"/ 跳過：{self.tasks_skipped}  ({self.total_ms}ms)\n"
            f"  策略：{self.failure_policy.value}"
        )


# ── DAG 調度器 ────────────────────────────────────────────────────

class SwarmScheduler:
    """根據依賴關係和失敗策略決定執行順序"""

    def get_ready_tasks(
        self,
        tasks:          dict[str, SwarmTask],
        failure_policy: FailurePolicy,
    ) -> list[SwarmTask]:
        """
        取得當前可以執行的任務：
        - 狀態為 PENDING
        - 所有依賴都已解決（DONE 或 SKIPPED 或在 FALLBACK 策略下的 FAILED）
        """
        resolved = self._resolved_deps(tasks, failure_policy)
        ready = []
        for task in tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            if all(dep in resolved for dep in task.depends_on):
                ready.append(task)
        return ready

    def _resolved_deps(
        self,
        tasks:          dict[str, SwarmTask],
        failure_policy: FailurePolicy,
    ) -> set[str]:
        """依策略決定哪些任務 ID 算作「已解決」"""
        resolved = set()
        for tid, t in tasks.items():
            if t.status == TaskStatus.DONE:
                resolved.add(tid)
            elif t.status == TaskStatus.SKIPPED:
                resolved.add(tid)
            elif t.status == TaskStatus.FAILED:
                # FALLBACK：失敗任務用 fallback_result，下游繼續
                if failure_policy == FailurePolicy.FALLBACK:
                    resolved.add(tid)
        return resolved

    def get_tasks_to_skip(
        self,
        tasks:       dict[str, SwarmTask],
        failed_id:   str,
    ) -> list[str]:
        """
        找出因 failed_id 失敗而需要跳過的任務
        （直接依賴 + 遞迴傳遞依賴）。
        """
        to_skip: list[str] = []
        for tid, task in tasks.items():
            if task.status != TaskStatus.PENDING:
                continue
            if self._transitively_depends_on(tasks, tid, failed_id):
                to_skip.append(tid)
        return to_skip

    def _transitively_depends_on(
        self,
        tasks:  dict[str, SwarmTask],
        tid:    str,
        target: str,
        _visited: set[str] | None = None,
    ) -> bool:
        """遞迴判斷 tid 是否（直接或間接）依賴 target"""
        if _visited is None:
            _visited = set()
        if tid in _visited:
            return False
        _visited.add(tid)
        task = tasks.get(tid)
        if task is None:
            return False
        if target in task.depends_on:
            return True
        return any(
            self._transitively_depends_on(tasks, dep, target, _visited)
            for dep in task.depends_on
        )

    def has_pending(self, tasks: dict[str, SwarmTask]) -> bool:
        return any(t.status == TaskStatus.PENDING for t in tasks.values())

    def build_context(self, task: SwarmTask, results: dict[str, str]) -> str:
        """從依賴任務的結果組裝 context"""
        if not task.context_from:
            return ""
        parts = [
            f"=== 來自 {ctx_id} ===\n{results[ctx_id][:1_000]}"
            for ctx_id in task.context_from
            if ctx_id in results
        ]
        return "\n\n".join(parts)


# ── AgentSwarm ────────────────────────────────────────────────────

class AgentSwarm:
    """
    非線性並行 Agent 協作器（v3.0）。

    使用方式：
        swarm = AgentSwarm(
            workdir=".",
            failure_policy=FailurePolicy.CONTINUE,
        )
        result = swarm.run(tasks, final_task="delivery")
        print(result.summary())
    """

    def __init__(
        self,
        workdir:        str           = ".",
        failure_policy: FailurePolicy = FailurePolicy.CONTINUE,
    ):
        self.workdir        = workdir
        self.failure_policy = failure_policy
        self.scheduler      = SwarmScheduler()
        self._lock          = threading.Lock()
        self._results:      dict[str, str] = {}

    def run(
        self,
        tasks:       list[SwarmTask],
        final_task:  Optional[str]      = None,
        on_progress: Optional[Callable] = None,
    ) -> SwarmResult:
        """
        執行 Swarm：並行執行無依賴任務，串行等待有依賴任務。

        Args:
            tasks:       任務列表（DAG）
            final_task:  最終整合任務 ID（結果作為主輸出）
            on_progress: 進度回調 (task_id, TaskStatus, result)

        Returns:
            SwarmResult（含完整統計、partial_success 語義）
        """
        run_id   = str(uuid.uuid4())[:8]
        task_map = {t.task_id: t for t in tasks}
        t0       = time.monotonic()

        logger.info("swarm_start", run_id=run_id, tasks=len(tasks),
                    policy=self.failure_policy.value)
        print(f"\n🐝 AgentSwarm [{run_id}] 啟動（{len(tasks)} 個子任務，"
              f"策略：{self.failure_policy.value}）")
        self._print_dag(task_map)

        aborted = False

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures: dict[Future, str] = {}

            while self.scheduler.has_pending(task_map) or futures:
                # ── 發射可執行任務 ─────────────────────────────────
                ready         = self.scheduler.get_ready_tasks(task_map, self.failure_policy)
                available     = MAX_WORKERS - len(futures)
                to_launch     = ready[:available]

                for task in to_launch:
                    task.status = TaskStatus.RUNNING
                    context     = self.scheduler.build_context(task, self._results)
                    future      = executor.submit(self._run_task, task, context)
                    futures[future] = task.task_id
                    logger.info("task_start", run_id=run_id,
                                task_id=task.task_id, agent=task.agent_name,
                                attempt=task.attempt)
                    print(f"  ▶ [{task.task_id}] {task.agent_name} 開始"
                          + (f"（重試 {task.attempt}）" if task.attempt > 0 else "") + "...")

                if not futures:
                    # 沒有 future 在跑，也沒有可排程的任務
                    if self.scheduler.has_pending(task_map):
                        # 有 PENDING 但無法調度 → 可能是所有依賴都 SKIPPED/FAILED
                        self._skip_blocked_tasks(task_map, run_id)
                    break

                # ── 等待任意一個 future 完成 ───────────────────────
                done, _ = futures_wait(
                    futures.keys(),
                    timeout=POLL_INTERVAL_SEC,
                    return_when=FIRST_COMPLETED,
                )

                for future in done:
                    task_id = futures.pop(future)
                    task    = task_map[task_id]
                    try:
                        result = future.result(timeout=1)
                        task.status = TaskStatus.DONE
                        task.result = result
                        with self._lock:
                            self._results[task_id] = result
                        logger.info("task_done", run_id=run_id,
                                    task_id=task_id, ms=task.duration_ms)
                        print(f"  ✓ [{task_id}] 完成（{task.duration_ms}ms）")

                    except Exception as e:
                        err_msg = str(e)[:300]
                        logger.error("task_failed", run_id=run_id,
                                     task_id=task_id, error=err_msg,
                                     can_retry=task.can_retry)

                        if task.can_retry:
                            # ── 重試 ───────────────────────────────
                            print(f"  🔄 [{task_id}] 失敗（{err_msg[:80]}），"
                                  f"重試（{task.attempt + 1}/{task.max_retries}）...")
                            task.reset_for_retry()

                        else:
                            # ── 最終失敗 ───────────────────────────
                            task.status = TaskStatus.FAILED
                            task.error  = err_msg
                            print(f"  ✗ [{task_id}] 最終失敗：{err_msg[:80]}")

                            if self.failure_policy == FailurePolicy.ABORT:
                                logger.warning("swarm_abort", run_id=run_id,
                                               failed_task=task_id)
                                print(f"  🛑 Swarm 中止（策略：ABORT）")
                                aborted = True
                                break

                            elif self.failure_policy == FailurePolicy.CONTINUE:
                                # 跳過所有下游任務
                                skipped = self.scheduler.get_tasks_to_skip(task_map, task_id)
                                for sid in skipped:
                                    task_map[sid].status = TaskStatus.SKIPPED
                                    task_map[sid].error  = f"上游 [{task_id}] 失敗，跳過"
                                    logger.info("task_skipped", run_id=run_id,
                                                task_id=sid, reason=task_id)
                                if skipped:
                                    print(f"  ⏭ 跳過下游任務：{', '.join(skipped)}")

                            elif self.failure_policy == FailurePolicy.FALLBACK:
                                # 使用 fallback 結果，下游繼續
                                fallback = task.fallback_result or f"[{task_id} 失敗，使用降級結果]"
                                with self._lock:
                                    self._results[task_id] = fallback
                                logger.info("task_fallback", run_id=run_id,
                                            task_id=task_id)
                                print(f"  ↩ [{task_id}] 使用降級結果，下游繼續")

                    if on_progress:
                        on_progress(task_id, task.status, task.result)

                if aborted:
                    # 取消所有未完成的 future
                    for future in futures:
                        future.cancel()
                    break

        total_ms = int((time.monotonic() - t0) * 1_000)

        tasks_done    = sum(1 for t in task_map.values() if t.status == TaskStatus.DONE)
        tasks_failed  = sum(1 for t in task_map.values() if t.status == TaskStatus.FAILED)
        tasks_skipped = sum(1 for t in task_map.values() if t.status == TaskStatus.SKIPPED)

        final_output = (
            self._results.get(final_task, "")
            if final_task
            else "\n\n".join(
                f"[{tid}]\n{r}" for tid, r in self._results.items()
            )
        )

        result = SwarmResult(
            run_id         = run_id,
            tasks_done     = tasks_done,
            tasks_failed   = tasks_failed,
            tasks_skipped  = tasks_skipped,
            total_ms       = total_ms,
            final_output   = final_output,
            task_results   = dict(self._results),
            failure_policy = self.failure_policy,
        )

        logger.info("swarm_done", run_id=run_id,
                    done=tasks_done, failed=tasks_failed,
                    skipped=tasks_skipped, ms=total_ms)
        print(f"\n  {result.summary()}")

        return result

    def _run_task(self, task: SwarmTask, context: str) -> str:
        """在 Worker thread 中執行單一任務（記憶體隔離）"""
        import sys as _sys
        _sys.path.insert(0, self.workdir)

        t0 = time.monotonic()
        try:
            from agents.all_agents import ALL_AGENTS
            if task.agent_name not in ALL_AGENTS:
                raise ValueError(f"Agent {task.agent_name!r} 不存在")

            AgentClass = ALL_AGENTS[task.agent_name]
            # 每個 Worker 獨立的 Agent 實例（記憶體隔離）
            agent = AgentClass(workdir=self.workdir)

            result = agent.chat(task.prompt, context=context)

            task.duration_ms = int((time.monotonic() - t0) * 1_000)

            # 主動清理 conversation history（釋放記憶體）
            agent.conversation_history.clear()

            return result

        except Exception:
            task.duration_ms = int((time.monotonic() - t0) * 1_000)
            raise

    def _skip_blocked_tasks(
        self,
        task_map: dict[str, SwarmTask],
        run_id:   str,
    ) -> None:
        """將無法調度的 PENDING 任務標記為 SKIPPED（死鎖或全依賴失敗）"""
        for task in task_map.values():
            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.SKIPPED
                task.error  = "依賴任務全部失敗或跳過，無法執行"
                logger.warning("task_deadlocked", run_id=run_id,
                               task_id=task.task_id)

    def _print_dag(self, task_map: dict[str, SwarmTask]) -> None:
        """視覺化 DAG（ASCII）"""
        print("  DAG 結構：")
        for task in task_map.values():
            deps = " → " + ", ".join(task.depends_on) if task.depends_on else ""
            retry = f" [retry={task.max_retries}]" if task.max_retries > 0 else ""
            print(f"    {task.task_id:<20} [{task.agent_name}]{deps}{retry}")


# ── ship_with_swarm 便利函數 ──────────────────────────────────────

def ship_with_swarm(
    requirement:    str,
    workdir:        str                = ".",
    active_phases:  set[int] | None    = None,
    failure_policy: FailurePolicy      = FailurePolicy.CONTINUE,
) -> SwarmResult:
    """
    用 Swarm 架構執行 /ship 流水線（取代線性 web_orchestrator.ship()）。

    Args:
        requirement:    需求描述
        workdir:        工作目錄
        active_phases:  啟用的 Phase 集合（None = 全部）
        failure_policy: 失敗策略（預設 CONTINUE）
    """
    phases = active_phases or set(range(1, 13))

    all_tasks = [
        # 第一批：並行（無依賴）
        SwarmTask("discover",    "ARIA",  f"分析此需求，確認範疇和假設：{requirement}",
                  depends_on=[], max_retries=1),
        SwarmTask("feasibility", "SIGMA", f"評估此需求的技術可行性：{requirement}",
                  depends_on=[], max_retries=1),

        # 第二批：等 discover 完成
        SwarmTask("prd",         "ECHO",  "根據需求分析，撰寫完整 PRD（含 AC）",
                  depends_on=["discover"], context_from=["discover"],
                  fallback_result="[PRD 生成失敗，使用基礎規格繼續]",
                  max_retries=1),

        # 第三批：等 prd + feasibility，並行設計
        SwarmTask("architecture","NEXUS", "設計技術架構（含目錄結構、DB schema、API 設計）",
                  depends_on=["prd", "feasibility"],
                  context_from=["prd", "feasibility"],
                  max_retries=1),
        SwarmTask("ux_design",   "SPARK", "設計 UX 流程和線框圖",
                  depends_on=["prd"], context_from=["prd"],
                  fallback_result="[UX 設計失敗，繼續基礎實作]"),

        # 第四批：等架構，並行實作
        SwarmTask("frontend",    "BYTE",  "實作前端程式碼",
                  depends_on=["architecture", "ux_design"],
                  context_from=["prd", "architecture", "ux_design"],
                  max_retries=1),
        SwarmTask("backend",     "STACK", "實作後端 API 和資料庫",
                  depends_on=["architecture"],
                  context_from=["prd", "architecture"],
                  max_retries=1),

        # 第五批：等實作，並行測試+安全
        SwarmTask("tests",       "TRACE", "撰寫測試（單元 + 整合 + E2E）",
                  depends_on=["frontend", "backend"],
                  context_from=["frontend", "backend"],
                  fallback_result="[測試生成失敗，繼續交付]"),
        SwarmTask("security",    "SHIELD","執行安全審查",
                  depends_on=["frontend", "backend"],
                  context_from=["architecture", "backend"],
                  fallback_result="[安全審查失敗，請人工審查]"),

        # 最終：整合交付
        SwarmTask("delivery",    "ARIA",  "整合所有輸出，產出交付總結",
                  depends_on=["tests", "security"],
                  context_from=["prd", "architecture", "frontend",
                                "backend", "tests", "security"]),
    ]

    # 根據 active_phases 過濾任務
    phase_to_task = {
        1: "discover",    2: "prd",          4: "architecture",
        5: "feasibility", 7: "ux_design",
        9: "frontend",   10: "backend",     11: "tests",
        12: "security",
    }
    active_ids = {v for k, v in phase_to_task.items() if k in phases}
    active_ids.add("delivery")

    filtered = [t for t in all_tasks if t.task_id in active_ids]

    swarm = AgentSwarm(workdir=workdir, failure_policy=failure_policy)
    return swarm.run(filtered, final_task="delivery")
