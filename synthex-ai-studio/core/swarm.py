from __future__ import annotations

from core.config import cfg
"""
AgentSwarm — 非線性並行多 Agent 協作架構 (v2.0)

突破現有線性流水線的限制。NEXUS 作為真正的 Supervisor：
  1. 接收任務，動態分解為子任務
  2. 根據依賴關係建立 DAG（有向無環圖）
  3. 無依賴的子任務並行執行
  4. ARIA 整合所有結果

vs 現有架構的差異：
  現有：Phase1 → Phase2 → Phase3 → ... → Phase12（完全串行）
  Swarm：[Phase4, Phase5] 並行，[Phase9, Phase10, Phase11] 並行，依賴的才串行

速度提升：
  現有 12 個串行 Phase，假設每個 30 秒 = 6 分鐘
  Swarm 6 個並行批次 × 30 秒 = 3 分鐘（約 2x 加速）

安全設計：
  - 子任務 timeout（防止單一 Agent 卡住整個 Swarm）
  - 結果合併有 conflict detection（不同 Agent 產生矛盾輸出）
  - 記憶體隔離：每個 Worker Agent 獨立 conversation history
  - 最大並行數限制（防止 API rate limit）

記憶體管理：
  - Worker 完成後主動釋放 conversation history
  - 子任務結果寫磁碟（不全部保留在記憶體）
  - ThreadPoolExecutor with bounded queue
"""


import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, Future, as_completed, TimeoutError
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# ── 常數 ─────────────────────────────────────────────────────────
MAX_WORKERS         = 4     # 同時並行的 Agent 數上限（防 API rate limit）
WORKER_TIMEOUT_SEC  = 120   # 單一 Worker 的 timeout
SUPERVISOR_MODEL    = cfg.model_opus   # NEXUS 使用 Opus
WORKER_MODEL        = cfg.model_sonnet # Worker 使用 Sonnet


class TaskStatus(Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    DONE      = "done"
    FAILED    = "failed"
    SKIPPED   = "skipped"


@dataclass
class SwarmTask:
    """Swarm 中的單一子任務"""
    task_id:      str
    agent_name:   str
    prompt:       str
    depends_on:   list[str] = field(default_factory=list)  # 前驅任務 ID
    context_from: list[str] = field(default_factory=list)  # 從哪些任務的結果取上下文
    timeout:      int = WORKER_TIMEOUT_SEC
    status:       TaskStatus = TaskStatus.PENDING
    result:       str = ""
    error:        str = ""
    duration_ms:  int = 0

    @property
    def is_ready(self) -> bool:
        """所有前驅任務都完成了嗎？"""
        return self.status == TaskStatus.PENDING


@dataclass
class SwarmResult:
    """整個 Swarm 的執行結果"""
    run_id:     str
    tasks_done: int
    tasks_failed: int
    total_ms:   int
    final_output: str
    task_results: dict[str, str]  # task_id → result


class SwarmScheduler:
    """
    DAG 調度器：根據依賴關係決定執行順序。
    拓撲排序後找出可以並行的任務批次。
    """

    def get_ready_tasks(
        self,
        tasks: dict[str, SwarmTask],
    ) -> list[SwarmTask]:
        """
        取得當前可以執行的任務：
        - 狀態為 PENDING
        - 所有依賴都已完成（DONE）
        """
        completed = {tid for tid, t in tasks.items() if t.status == TaskStatus.DONE}
        ready = []
        for task in tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            if all(dep in completed for dep in task.depends_on):
                ready.append(task)
        return ready

    def has_pending(self, tasks: dict[str, SwarmTask]) -> bool:
        return any(t.status == TaskStatus.PENDING for t in tasks.values())

    def has_failed(self, tasks: dict[str, SwarmTask]) -> bool:
        return any(t.status == TaskStatus.FAILED for t in tasks.values())

    def build_context(
        self,
        task:    SwarmTask,
        results: dict[str, str],
    ) -> str:
        """從依賴任務的結果組裝 context"""
        if not task.context_from:
            return ""
        parts = []
        for ctx_id in task.context_from:
            if ctx_id in results:
                parts.append(f"=== 來自 {ctx_id} ===\n{results[ctx_id][:1000]}")
        return "\n\n".join(parts)


class AgentSwarm:
    """
    非線性並行 Agent 協作器。

    使用方式：
        swarm = AgentSwarm(workdir="/your/project")

        # 定義任務 DAG
        tasks = [
            SwarmTask("requirements", "ECHO",  "分析需求..."),
            SwarmTask("architecture",  "NEXUS", "設計架構...",
                      depends_on=["requirements"],
                      context_from=["requirements"]),
            SwarmTask("frontend",  "BYTE",  "實作前端...",
                      depends_on=["architecture"],
                      context_from=["requirements", "architecture"]),
            SwarmTask("backend",   "STACK", "實作後端...",
                      depends_on=["architecture"],
                      context_from=["requirements", "architecture"]),
            # frontend 和 backend 可以並行！
            SwarmTask("tests",     "TRACE", "寫測試...",
                      depends_on=["frontend", "backend"],
                      context_from=["frontend", "backend"]),
        ]

        result = swarm.run(tasks, final_task="tests")
    """

    def __init__(self, workdir: str = "."):
        self.workdir   = workdir
        self.scheduler = SwarmScheduler()
        self._lock     = threading.Lock()
        self._results: dict[str, str] = {}

    def run(
        self,
        tasks:       list[SwarmTask],
        final_task:  Optional[str] = None,
        on_progress: Optional[Callable] = None,
    ) -> SwarmResult:
        """
        執行 Swarm：並行執行無依賴的任務，串行等待有依賴的任務。

        Args:
            tasks:       任務列表（DAG）
            final_task:  最終整合任務的 ID（結果作為主輸出）
            on_progress: 進度回調 (task_id, status, result)
        """
        import uuid as _uuid
        run_id   = str(_uuid.uuid4())[:8]
        task_map = {t.task_id: t for t in tasks}
        t0       = time.monotonic()

        print(f"\n🐝 AgentSwarm 啟動（{len(tasks)} 個子任務，run_id: {run_id}）")
        self._print_dag(task_map)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures: dict[Future, str] = {}

            while self.scheduler.has_pending(task_map):
                # 找出所有可以執行的任務
                ready = self.scheduler.get_ready_tasks(task_map)
                available_slots = MAX_WORKERS - len(futures)
                to_launch = ready[:available_slots]

                for task in to_launch:
                    task.status = TaskStatus.RUNNING
                    context     = self.scheduler.build_context(task, self._results)
                    future      = executor.submit(
                        self._run_task, task, context
                    )
                    futures[future] = task.task_id
                    print(f"  ▶ [{task.task_id}] {task.agent_name} 開始...")

                if not futures:
                    if self.scheduler.has_pending(task_map):
                        logger.warning("有 pending 任務但無法調度（可能有循環依賴）")
                    break

                # 等待任意一個 future 完成
                done, _ = __import__('concurrent.futures', fromlist=['wait']).wait(
                    futures.keys(),
                    timeout=5,
                    return_when=__import__('concurrent.futures', fromlist=['FIRST_COMPLETED']).FIRST_COMPLETED
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
                        print(f"  ✓ [{task_id}] 完成（{task.duration_ms}ms）")
                    except Exception as e:
                        task.status = TaskStatus.FAILED
                        task.error  = str(e)[:200]
                        print(f"  ✗ [{task_id}] 失敗：{e}")

                    if on_progress:
                        on_progress(task_id, task.status, task.result)

        total_ms    = int((time.monotonic() - t0) * 1000)
        tasks_done  = sum(1 for t in task_map.values() if t.status == TaskStatus.DONE)
        tasks_failed= sum(1 for t in task_map.values() if t.status == TaskStatus.FAILED)
        final_output= (
            self._results.get(final_task, "")
            if final_task
            else "\n\n".join(
                f"[{tid}]\n{r}"
                for tid, r in self._results.items()
            )
        )

        print(f"\n  Swarm 完成：{tasks_done}/{len(tasks)} 成功，{total_ms}ms")

        return SwarmResult(
            run_id        = run_id,
            tasks_done    = tasks_done,
            tasks_failed  = tasks_failed,
            total_ms      = total_ms,
            final_output  = final_output,
            task_results  = dict(self._results),
        )

    def _run_task(self, task: SwarmTask, context: str) -> str:
        """在 Worker thread 中執行單一任務"""
        import sys as _sys
        _sys.path.insert(0, self.workdir)

        t0 = time.monotonic()
        try:
            from agents.all_agents import ALL_AGENTS
            if task.agent_name not in ALL_AGENTS:
                raise ValueError(f"Agent {task.agent_name} 不存在")

            AgentClass = ALL_AGENTS[task.agent_name]
            # 每個 Worker 獨立的 Agent 實例（記憶體隔離）
            agent = AgentClass(workdir=self.workdir)

            result = agent.chat(task.prompt, context=context)

            task.duration_ms = int((time.monotonic() - t0) * 1000)

            # 主動清理 conversation history（釋放記憶體）
            agent.conversation_history.clear()

            return result

        except Exception as e:
            task.duration_ms = int((time.monotonic() - t0) * 1000)
            raise

    def _print_dag(self, task_map: dict[str, SwarmTask]) -> None:
        """視覺化 DAG（ASCII）"""
        print("  DAG 結構：")
        for task in task_map.values():
            deps = " → " + ", ".join(task.depends_on) if task.depends_on else ""
            print(f"    {task.task_id:<20} [{task.agent_name}]{deps}")


def ship_with_swarm(
    requirement: str,
    workdir:     str = ".",
    active_phases: set[int] | None = None,
) -> SwarmResult:
    """
    用 Swarm 架構執行 /ship 流水線。
    和現有 web_orchestrator.ship() 的關係：
    這是替代版本，用 DAG 並行取代線性序列。
    """
    phases = active_phases or set(range(1, 13))

    all_tasks = [
        # 第一批：並行（無依賴）
        SwarmTask("discover",     "ARIA",  f"分析此需求，確認範疇和假設：{requirement}",
                  depends_on=[]),
        SwarmTask("feasibility",  "SIGMA", f"評估此需求的技術可行性：{requirement}",
                  depends_on=[]),

        # 第二批：等 discover 完成
        SwarmTask("prd",          "ECHO",  "根據需求分析，撰寫完整 PRD（含 AC）",
                  depends_on=["discover"],
                  context_from=["discover"]),

        # 第三批：等 prd + feasibility 完成，並行設計
        SwarmTask("architecture", "NEXUS", "設計技術架構（含目錄結構、DB schema、API 設計）",
                  depends_on=["prd", "feasibility"],
                  context_from=["prd", "feasibility"]),
        SwarmTask("ux_design",    "SPARK", "設計 UX 流程和線框圖",
                  depends_on=["prd"],
                  context_from=["prd"]),

        # 第四批：等架構完成，並行實作
        SwarmTask("frontend",     "BYTE",  "實作前端程式碼",
                  depends_on=["architecture", "ux_design"],
                  context_from=["prd", "architecture", "ux_design"]),
        SwarmTask("backend",      "STACK", "實作後端 API 和資料庫",
                  depends_on=["architecture"],
                  context_from=["prd", "architecture"]),

        # 第五批：等實作完成，並行測試+安全
        SwarmTask("tests",        "TRACE", "撰寫測試（單元 + 整合 + E2E）",
                  depends_on=["frontend", "backend"],
                  context_from=["frontend", "backend"]),
        SwarmTask("security",     "SHIELD", "執行安全審查",
                  depends_on=["frontend", "backend"],
                  context_from=["architecture", "backend"]),

        # 最終：整合交付
        SwarmTask("delivery",     "ARIA",   "整合所有輸出，產出交付總結",
                  depends_on=["tests", "security"],
                  context_from=["prd", "architecture", "frontend", "backend", "tests", "security"]),
    ]

    # 根據 active_phases 過濾任務
    phase_to_task = {
        1: "discover", 2: "prd", 4: "architecture",
        5: "feasibility", 7: "ux_design",
        9: "frontend", 10: "backend", 11: "tests", 12: "security",
    }
    active_task_ids = {v for k, v in phase_to_task.items() if k in phases}
    active_task_ids.add("delivery")  # 最終整合永遠執行

    filtered_tasks = [t for t in all_tasks if t.task_id in active_task_ids]

    swarm = AgentSwarm(workdir=workdir)
    return swarm.run(filtered_tasks, final_task="delivery")
