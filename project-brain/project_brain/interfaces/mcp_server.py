"""
Project Brain MCP Server (v1.2)

讓 Claude Code 直接呼叫 Project Brain 的能力，不需要透過命令列。

安全設計：
  - 所有輸入做嚴格型別和長度驗證
  - workdir 必須是已初始化的專案目錄（有 .brain/）
  - 不允許目錄遍歷（../）攻擊
  - Rate limiting：避免 AI 無限制呼叫消耗資源
  - 錯誤訊息不洩漏系統路徑和 stack trace

架構（v1.2 B-05）：
  - BrainServer class 封裝所有可變狀態（rate limiter、session tracking、
    daemon flags、brain cache），每個實例獨立，pytest 並行不互相干擾。
  - create_server() 工廠函式維持原有公開 API，無 breaking change。
  - 模組層級的 _rate_check / _call_times / _cleanup_expired_sessions 等
    保留為 backward-compatible 別名，供舊測試使用。

使用方式：
  # 在 Claude Code 的 MCP 設定中加入：
  # {
  #   "mcpServers": {
  #     "project-brain": {
  #       "command": "python",
  #       "args": ["-m", "project_brain.mcp_server"],
  #       "env": { "BRAIN_WORKDIR": "/your/project" }
  #     }
  #   }
  # }

  # 或直接執行：
  # python -m project_brain.mcp_server --workdir /your/project
"""

from __future__ import annotations

import os
import re
import sys
import time
import logging
import argparse
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 安全常數 ────────────────────────────────────────────────────
MAX_QUERY_LEN    = 500
MAX_CONTENT_LEN  = 2_000
MAX_TITLE_LEN    = 200
MAX_TAGS_COUNT   = 10
RATE_LIMIT_RPM   = int(os.environ.get("BRAIN_RATE_LIMIT_RPM", "60"))  # A-3: env-configurable
_call_times: list[float] = []      # Rate limiter 狀態
_rate_lock   = threading.Lock()    # BUG-04 fix: protect concurrent access

# VISION-01: session node tracking for auto-feedback on complete_task
_session_nodes: dict[str, list[str]] = {}
_snodes_lock = threading.Lock()

# MEM-03: session dedup — track served node IDs per workdir
_session_served: dict[str, set[str]] = {}
_session_served_ts: dict[str, float] = {}   # last-access timestamps for TTL cleanup
_sserved_lock = threading.Lock()
_SESSION_TTL_SECS = 1800  # 30 分鐘無呼叫自動清除
_CLEANUP_DAEMON_INTERVAL = 300  # 每 5 分鐘執行一次清理
_cleanup_daemon_started = False  # BUG-04: guard against multiple starts
_cleanup_daemon_lock = threading.Lock()
_DECAY_DAEMON_INTERVAL = int(os.environ.get("BRAIN_DECAY_INTERVAL", str(24 * 3600)))  # FEAT-01: daily decay
_decay_daemon_started = False
_decay_daemon_lock = threading.Lock()

# BLOCKER-01: Auto Knowledge Pipeline 背景 worker
_pipeline_worker_started = False
_pipeline_worker_lock = threading.Lock()


def _cleanup_expired_sessions() -> None:
    """MEM-03: 清除超過 TTL 的 session served sets，避免記憶體洩漏。"""
    now = time.monotonic()
    with _sserved_lock:
        expired = [k for k, ts in _session_served_ts.items()
                   if now - ts > _SESSION_TTL_SECS]
        for k in expired:
            _session_served.pop(k, None)
            _session_served_ts.pop(k, None)


def _adjust_signal_confidence(brain) -> dict:
    """C-05: If a signal kind has >30% negative feedback in 30 days, lower its auto-confidence.

    Reads from ``feedback_log`` (written by report_knowledge_outcome),
    grouped by ``signal_kind``. For each kind with negative_rate > 0.30,
    updates ``brain_meta`` with a lowered default confidence for that signal type.

    Returns dict of adjustments made: ``{signal_kind: new_confidence, ...}``.
    """
    THRESHOLD = 0.30
    FLOOR     = 0.3
    STEP      = 0.1
    adjustments: dict[str, float] = {}

    try:
        rows = brain.db.conn.execute(
            """SELECT signal_kind, COUNT(*) AS total,
                      SUM(CASE WHEN was_useful = 0 THEN 1 ELSE 0 END) AS negative
               FROM feedback_log
               WHERE signal_kind != ''
                 AND created_at >= datetime('now', '-30 days')
               GROUP BY signal_kind"""
        ).fetchall()
    except Exception:
        return adjustments

    for row in rows:
        kind = row[0]
        total = row[1]
        negative = row[2] or 0
        if total < 5:
            continue  # too few samples to be statistically meaningful
        neg_rate = negative / total
        if neg_rate <= THRESHOLD:
            continue

        # Read current auto_confidence for this kind from brain_meta
        meta_key = f"signal_confidence:{kind}"
        current = 0.85  # default
        try:
            r = brain.db.conn.execute(
                "SELECT value FROM brain_meta WHERE key=?", (meta_key,)
            ).fetchone()
            if r:
                current = float(r[0])
        except Exception:
            pass

        new_conf = max(FLOOR, current - STEP)
        if new_conf < current:
            try:
                brain.db.conn.execute(
                    "INSERT OR REPLACE INTO brain_meta(key,value) VALUES(?,?)",
                    (meta_key, str(round(new_conf, 2))),
                )
                brain.db.conn.commit()
                adjustments[kind] = new_conf
                logger.info(
                    "C-05: signal %s negative_rate=%.0f%% (%d/%d) → "
                    "auto_confidence lowered %.2f → %.2f",
                    kind, neg_rate * 100, negative, total, current, new_conf,
                )
            except Exception as _e:
                logger.debug("C-05: brain_meta update failed for %s: %s", kind, _e)

    return adjustments


def _run_maintenance_cycle(brain) -> dict:
    """B-01: 單次維護週期 — decay pass + KRB staging 清理。

    從 _decay_daemon_fn 提取出來以便單元測試直接呼叫，不需要等待 sleep interval。

    設計原則：
      - decay 與 KRB cleanup 各自有獨立 try/except，一個失敗不影響另一個
      - 兩個步驟都記 structured log（decay: INFO/DEBUG，cleanup: INFO/WARNING）
      - 回傳 dict 便於測試斷言，daemon fn 可忽略回傳值

    Returns:
        {
            "decay_ok":      bool,        # decay pass 是否成功
            "decay_error":   str | None,  # decay 失敗時的錯誤訊息
            "cleanup":       dict | None, # cleanup_expired_staging 回傳值
            "cleanup_error": str | None,  # cleanup 失敗時的錯誤訊息
        }
    """
    result: dict = {
        "decay_ok":        False,
        "decay_error":     None,
        "cleanup":         None,
        "cleanup_error":   None,
        "feedback_adj":    None,
        "feedback_error":  None,
    }

    # ── Step 1: Decay pass ────────────────────────────────────────
    try:
        from project_brain.decay_engine import DecayEngine as _DE
        _de = _DE(brain.graph, workdir=str(brain.workdir), db=brain.db)
        _de.run()
        result["decay_ok"] = True
        logger.info("FEAT-01: decay pass completed")
    except Exception as _e:
        result["decay_error"] = str(_e)
        logger.debug("FEAT-01: decay daemon error: %s", _e)

    # ── Step 2: KRB staging cleanup (B-01) ───────────────────────
    # Runs in the same cycle as decay so both maintenance tasks share one
    # 24-hour interval.  A cleanup failure is non-critical (nodes stay as-is)
    # and must never prevent the next decay pass from running.
    try:
        _cleanup_result = brain.review_board.cleanup_expired_staging()
        result["cleanup"] = _cleanup_result
        logger.info(
            "B-01: KRB staging cleanup completed "
            "pending_skipped=%d rejected_archived=%d ttl_days=%d",
            _cleanup_result.get("pending_skipped", 0),
            _cleanup_result.get("rejected_archived", 0),
            _cleanup_result.get("ttl_days", 30),
        )
    except Exception as _ke:
        result["cleanup_error"] = str(_ke)
        logger.warning("B-01: KRB staging cleanup error: %s", _ke)

    # ── Step 3: C-05 Feedback loop — adjust signal confidence ────
    try:
        result["feedback_adj"] = _adjust_signal_confidence(brain)
    except Exception as _fe:
        result["feedback_error"] = str(_fe)
        logger.debug("C-05: feedback adjustment error: %s", _fe)

    return result


def _rate_check() -> None:
    """
    滑動視窗 Rate Limiting（BUG-04 fix: thread-safe）。

    原實作的問題：_call_times 是 module-level list，多執行緒並發讀寫
    會導致 TOCTOU race condition，允許超過限制的請求通過。
    修復：用 threading.Lock() 使 read-check-append 成為原子操作。
    """
    now = time.monotonic()
    cutoff = now - 60.0
    with _rate_lock:
        _call_times[:] = [t for t in _call_times if t > cutoff]
        if len(_call_times) >= RATE_LIMIT_RPM:
            raise RuntimeError(f"Rate limit：每分鐘最多 {RATE_LIMIT_RPM} 次呼叫")
        _call_times.append(now)


def _safe_str(value: Any, max_len: int, field: str) -> str:
    """安全字串清理：型別檢查 + 長度限制 + 控制字元移除"""
    if not isinstance(value, str):
        raise TypeError(f"{field} 必須是字串，得到 {type(value).__name__}")
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', value)
    if len(cleaned) > max_len:
        raise ValueError(f"{field} 超過長度限制（{len(cleaned)} > {max_len}）")
    return cleaned


_FORBIDDEN_ROOTS: tuple[Path, ...] = tuple(
    Path(p) for p in ("/etc", "/sys", "/proc", "/dev", "/boot", "/run")
    if Path(p).exists()
)


def _validate_workdir(workdir: str) -> Path:
    """驗證工作目錄：存在、無路徑遍歷、已初始化"""
    if not workdir:
        raise ValueError("BRAIN_WORKDIR 未設定")

    # SEC-02: check for traversal BEFORE resolving symlinks
    raw = Path(workdir)
    if ".." in raw.parts:
        raise ValueError("工作目錄路徑不允許包含 ..")

    # SEC-01: resolve symlinks first, then validate resolved path
    path = raw.resolve()

    if not path.exists():
        raise FileNotFoundError(f"工作目錄不存在：{path}")

    if not path.is_dir():
        raise NotADirectoryError(f"工作目錄不是目錄：{path}")

    # SEC-01: block symlink-based traversal into forbidden system directories
    for forbidden in _FORBIDDEN_ROOTS:
        try:
            path.relative_to(forbidden)
            raise ValueError(f"工作目錄不允許位於系統目錄 {forbidden} 內")
        except ValueError as _ve:
            if "系統目錄" in str(_ve):
                raise

    # 確認已初始化
    brain_dir = path / ".brain"
    if not brain_dir.exists():
        raise FileNotFoundError(
            f".brain/ 不存在，請先執行：brain init"
        )

    return path


def _find_brain_root(start: str) -> Path | None:
    """從 start 往上找第一個含有 .brain/ 的目錄，找不到回傳 None"""
    p = Path(start).resolve()
    if p.is_file():
        p = p.parent
    for candidate in [p, *p.parents]:
        if (candidate / ".brain").is_dir():
            return candidate
    return None


# SEC-04: LRU cache with max size to prevent DoS via unlimited workdir creation
_MAX_BRAIN_CACHE = int(os.environ.get("BRAIN_CACHE_SIZE", "32"))
_brain_cache: "OrderedDict[str, Any]" = OrderedDict()  # LRU: oldest entry at front
_cache_lock  = threading.Lock()                         # SEC-05: protect _brain_cache concurrent writes


# ── BrainServer class (B-05) ───────────────────────────────────


class BrainServer:
    """Encapsulates all mutable MCP server state into an instance.

    Before B-05, rate-limiter lists, session tracking dicts, daemon flags,
    and the brain cache were module-level globals.  Two ``create_server()``
    calls in the same process (or pytest-xdist workers) shared them, causing
    cross-test pollution and subtle concurrency bugs.

    Each ``BrainServer`` now owns its own copy of every mutable variable.
    The public factory ``create_server(workdir)`` creates one internally and
    returns the FastMCP server — callers see no API change.
    """

    def __init__(self, workdir: str, *, mode: str = "standalone") -> None:
        self.work_path = _validate_workdir(workdir)
        self._mode = mode  # E-02: "standalone" or "central"

        # ── Rate limiter (was module-level _call_times / _rate_lock) ──
        self._call_times: list[float] = []
        self._rate_lock = threading.Lock()

        # ── Session node tracking (VISION-01) ──
        self._session_nodes: dict[str, list[str]] = {}
        self._snodes_lock = threading.Lock()

        # ── Session dedup (MEM-03) ──
        self._session_served: dict[str, set[str]] = {}
        self._session_served_ts: dict[str, float] = {}
        self._sserved_lock = threading.Lock()

        # ── Brain instance cache (SEC-04/05) ──
        self._brain_cache: "OrderedDict[str, Any]" = OrderedDict()
        self._cache_lock = threading.Lock()

        # ── Daemon flags (one set per server instance) ──
        self._cleanup_daemon_started = False
        self._cleanup_daemon_lock = threading.Lock()
        self._decay_daemon_started = False
        self._decay_daemon_lock = threading.Lock()
        self._pipeline_worker_started = False
        self._pipeline_worker_lock = threading.Lock()

        # ── Primary brain ──
        sys.path.insert(0, str(self.work_path.parent))
        from project_brain.engine import ProjectBrain
        _serialized = (mode == "central")
        self.brain = ProjectBrain(str(self.work_path), serialized_writes=_serialized)
        # E-02: expose brain_db ref for AuthMiddleware RBAC resolution
        self._brain_db_ref = self.brain.db if _serialized else None
        self._brain_cache[str(self.work_path)] = self.brain

        # ARCH-DEBT: optional embedder warmup — pre-load model in background
        if os.environ.get("BRAIN_EMBED_WARMUP", "") == "1":
            try:
                from project_brain.embedder import warmup_embedder
                warmup_embedder()
            except Exception:
                pass  # warmup failure must never block server startup

    # ── Instance methods (previously module-level helpers) ──────────

    def rate_check(self) -> None:
        """Sliding-window rate limiter (instance-scoped, thread-safe)."""
        now = time.monotonic()
        cutoff = now - 60.0
        with self._rate_lock:
            self._call_times[:] = [t for t in self._call_times if t > cutoff]
            if len(self._call_times) >= RATE_LIMIT_RPM:
                raise RuntimeError(f"Rate limit：每分鐘最多 {RATE_LIMIT_RPM} 次呼叫")
            self._call_times.append(now)

    def cleanup_expired_sessions(self) -> None:
        """MEM-03: evict sessions that exceeded TTL."""
        now = time.monotonic()
        with self._sserved_lock:
            expired = [k for k, ts in self._session_served_ts.items()
                       if now - ts > _SESSION_TTL_SECS]
            for k in expired:
                self._session_served.pop(k, None)
                self._session_served_ts.pop(k, None)

    def resolve_brain(self, caller_workdir: str) -> Any:
        """Return the Brain instance for *caller_workdir*, with LRU caching."""
        if not caller_workdir:
            return self.brain
        root = _find_brain_root(caller_workdir)
        if root is None or root == self.work_path:
            return self.brain
        key = str(root)
        with self._cache_lock:
            if key not in self._brain_cache:
                if len(self._brain_cache) >= _MAX_BRAIN_CACHE:
                    oldest_key, _ = self._brain_cache.popitem(last=False)
                    logger.debug("SEC-04: evicted brain cache entry %s", oldest_key)
                try:
                    from project_brain.engine import ProjectBrain
                    self._brain_cache[key] = ProjectBrain(key)
                except Exception as _e:
                    logger.warning("ProjectBrain init failed for %s, falling back: %s", key, _e)
                    return self.brain
            else:
                self._brain_cache.move_to_end(key)
            return self._brain_cache[key]

    # ── C-04: Signal emission helper ─────────────────────────────

    def emit_signal(self, kind: str, workdir: str, summary: str,
                    raw_content: str = "", metadata: dict | None = None,
                    priority: int = 5) -> None:
        """Non-blocking signal emission to the pipeline queue.

        Failures are silently logged — signal emission must never block
        or break the MCP tool response.
        """
        try:
            from project_brain.pipeline.signal import Signal, SignalKind
            sig = Signal(
                kind=SignalKind(kind),
                workdir=workdir,
                summary=summary[:500],
                raw_content=raw_content[:10_000],
                metadata=metadata or {},
                priority=priority,
            )
            # Enqueue via brain's DB connection
            from project_brain.pipeline.signal import SignalQueue
            sq = SignalQueue(self.brain.db.conn)
            sq.enqueue(sig)
        except Exception as _e:
            logger.debug("C-04: signal emission failed (non-fatal): %s", _e)

    # ── Daemon startup (per-instance) ──────────────────────────────

    def _start_daemons(self) -> None:
        """Start background daemons for this server instance."""
        self._start_decay_daemon()
        self._start_cleanup_daemon()
        self._start_pipeline_worker()

    def _start_decay_daemon(self) -> None:
        brain = self.brain
        with self._decay_daemon_lock:
            if self._decay_daemon_started:
                return
            def _decay_daemon_fn():
                while True:
                    time.sleep(_DECAY_DAEMON_INTERVAL)
                    _run_maintenance_cycle(brain)
            _dt = threading.Thread(
                target=_decay_daemon_fn, daemon=True, name="brain-decay",
            )
            _dt.start()
            self._decay_daemon_started = True
            logger.debug("FEAT-01: decay daemon started (interval=%ds)", _DECAY_DAEMON_INTERVAL)

    def _start_cleanup_daemon(self) -> None:
        with self._cleanup_daemon_lock:
            if self._cleanup_daemon_started:
                return
            srv = self  # prevent closure over `self` with a direct ref
            def _session_cleanup_daemon():
                while True:
                    time.sleep(_CLEANUP_DAEMON_INTERVAL)
                    try:
                        srv.cleanup_expired_sessions()
                    except Exception as _e:
                        logger.debug("session cleanup daemon error: %s", _e)
            _t = threading.Thread(
                target=_session_cleanup_daemon, daemon=True,
                name="brain-session-cleanup",
            )
            _t.start()
            self._cleanup_daemon_started = True
            logger.debug("BUG-04: session cleanup daemon started (interval=%ds)",
                         _CLEANUP_DAEMON_INTERVAL)

    def _start_pipeline_worker(self) -> None:
        with self._pipeline_worker_lock:
            if self._pipeline_worker_started:
                return
            try:
                from project_brain.pipeline_worker import start_global_worker
                _pw = start_global_worker(self.brain.db, brain_dir=self.brain.brain_dir)
                if _pw is not None:
                    self._pipeline_worker_started = True
            except Exception as _e:
                logger.debug("BLOCKER-01: pipeline worker bootstrap error: %s", _e)

    # ── MCP tool registration ─────────────────────────────────────

    def create_mcp_server(self) -> Any:
        """Build and return a FastMCP server with all tools registered."""
        try:
            from mcp.server.fastmcp import FastMCP
        except ImportError:
            raise ImportError("請安裝 mcp 套件：pip install mcp")

        # Alias instance attrs for closures
        srv = self
        brain = self.brain
        work_path = self.work_path

        # E-03: central brain overlay helper
        def _get_central_client():
            """Return a CentralBrainClient if team config enables it, else None."""
            try:
                from project_brain.brain_config import load_config
                cfg = load_config(work_path / ".brain" if (work_path / ".brain").exists() else None)
                if cfg.team.mode == "local-only" or not cfg.team.central_brain_url:
                    return None, cfg.team
                from project_brain.integrations.central_brain_client import CentralBrainClient
                client = CentralBrainClient(
                    url=cfg.team.central_brain_url,
                    api_key=cfg.team.central_brain_key,
                )
                return client, cfg.team
            except Exception as e:
                logger.debug("E-03: central brain client init failed: %s", e)
                return None, None

        # E-02: permission check helper (reads role from ContextVar)
        def _check_permission(tool_name: str) -> dict | None:
            """Return an error dict if the current role lacks permission, else None."""
            from project_brain.interfaces.http_transport import current_role
            from project_brain.rbac import has_permission, TOOL_PERMISSIONS
            role = current_role.get("admin")  # default "admin" for stdio mode
            required = TOOL_PERMISSIONS.get(tool_name)
            if required and not has_permission(role, required):
                return {
                    "error": "permission_denied",
                    "message": f"Role '{role}' cannot call {tool_name} (requires {required}+)",
                }
            return None

        # Minimal FastMCP init — different versions have different kwargs
        try:
            mcp = FastMCP(
                name        = "project-brain",
                description = "Project Brain — 專案知識記憶系統",
            )
        except TypeError:
            try:
                mcp = FastMCP(name="project-brain")
            except TypeError:
                mcp = FastMCP("project-brain")

        # ── Tool 1：取得 Context 注入 ────────────────────────────────
        @mcp.tool()
        def get_context(
            task: str,
            current_file: str = "",
            scope: str = "global",
            workdir: str = "",
            force: bool = False,
            detail_level: str = "full",
            current_context_tags: "list[str] | None" = None,
            ai_select: bool = False,
        ) -> str:
            """
            根據當前任務動態組裝最相關的專案知識，注入 AI 的 Context。

            Args:
                task:                 當前任務描述（自然語言）
                current_file:         當前操作的檔案路徑（選填，提升相關性）
                workdir:              Claude Code 當前工作目錄（選填，讓 Brain 自動找對應 .brain/）
                force:                MEM-03：True 時跳過 session 去重，重新顯示所有相關知識
                detail_level:         MEM-06：'summary' 只回 title+description；'full' 為完整內容（預設）
                current_context_tags: MEM-05：當前操作標籤，Rule/Decision 與標籤重疊時降權
                ai_select:            MEM-01：True 時啟用 AI 輔助相關性選取（需 Ollama 或 ANTHROPIC_API_KEY）

            Returns:
                格式化的知識注入字串，可直接加在 prompt 前面。
                若知識庫為空，回傳空字串。
            """
            try:
                srv.rate_check()
            except RuntimeError as _rl_err:
                # U-2: return informative message instead of empty string
                return f"[rate_limited] {_rl_err} — 請稍後再試"
            task_clean = _safe_str(task, MAX_QUERY_LEN, "task")
            file_clean = _safe_str(current_file, 500, "current_file") if current_file else ""

            # 防止目錄遍歷
            if ".." in file_clean:
                file_clean = ""

            b = srv.resolve_brain(workdir or file_clean)
            _wk = str(b.workdir)

            # MEM-03: session dedup
            srv.cleanup_expired_sessions()
            if force:
                _exclude: set[str] = set()
            else:
                with srv._sserved_lock:
                    _exclude = set(srv._session_served.get(_wk, set()))

            try:
                ctx = b.get_context(
                    task_clean, file_clean,
                    exclude_ids=_exclude if not force else None,
                    current_context_tags=current_context_tags,
                    detail_level=detail_level,
                ) or ""

                # MEM-03: update served set with IDs shown this call
                try:
                    _new_ids = set(getattr(b.context_engineer, '_last_shown_ids', []))
                    if _new_ids:
                        with srv._sserved_lock:
                            srv._session_served.setdefault(_wk, set()).update(_new_ids)
                            srv._session_served_ts[_wk] = time.monotonic()
                except Exception as _e:
                    logger.warning("session dedup update failed: %s", _e, exc_info=True)
                # A-19: apply Memory Synthesizer if BRAIN_SYNTHESIZE=1
                try:
                    from project_brain.memory_synthesizer import MemorySynthesizer, is_enabled
                    if is_enabled():
                        l1_data = []
                        try:
                            from project_brain.session_store import SessionStore
                            ss = SessionStore(brain_dir=b.brain_dir)
                            l1_data = [{"content": e.value, "category": e.category}
                                       for e in ss.list(limit=5)]
                        except Exception as _e:
                            logger.debug("session_store L1 read failed in get_context", exc_info=True)
                        l2_data = []
                        try:
                            l2_data = b.db.recent_episodes(limit=5)
                        except Exception as _e:
                            logger.debug("recent_episodes L2 read failed in get_context", exc_info=True)
                        synth = MemorySynthesizer(str(b.workdir))
                        ctx   = synth.fuse(l1_data, l2_data, ctx, task=task_clean) or ctx
                except Exception as _e:
                    logger.debug("synthesis failed, skipping", exc_info=True)  # synthesis failure must never break context delivery
                # P2-A: attach nudges to every MCP response
                # Agent cannot opt out — if it queries anything, nudges come with it
                try:
                    from project_brain.nudge_engine import NudgeEngine
                    nudge_eng = NudgeEngine(b.graph, brain_db=b.db)
                    nudges    = nudge_eng.check(task_clean, top_k=3)
                    if nudges:
                        nudge_block = "\n## 🧠 Brain Nudges（主動警告）\n"
                        for n in nudges:
                            _urgency = getattr(n, 'urgency', '')
                            _msg     = getattr(n, 'content', '') or getattr(n, 'message', '') or str(n)
                            _conf    = getattr(n, 'confidence', None)
                            _icon    = '⚠' if _urgency == 'high' else 'ℹ'
                            # 加信心標記：Agent 可依此判斷 nudge 可信度
                            _conf_str = f" [conf={_conf:.2f}]" if _conf is not None else ""
                            nudge_block += f"  {_icon}{_conf_str} {_msg}\n"
                        ctx = nudge_block + ctx if ctx else nudge_block
                except Exception as _e:
                    logger.debug("nudge block failed, skipping", exc_info=True)  # nudge failure must never break context delivery
                # DEEP-04: background AI auto-resolve low-confidence nodes (non-blocking)
                try:
                    import threading as _t
                    from project_brain.nudge_engine import NudgeEngine as _NE
                    def _bg_resolve():
                        try:
                            _ne = _NE(b.graph, brain_db=b.db)
                            _ne.auto_resolve_batch(task_clean, threshold=0.5, use_llm=False)
                        except Exception as _e:
                            logger.debug("bg_resolve auto_resolve_batch failed", exc_info=True)
                    _t.Thread(target=_bg_resolve, daemon=True).start()
                except Exception as _e:
                    logger.debug("auto-resolve thread start failed, skipping", exc_info=True)  # auto-resolve must never block context delivery
                # VISION-01: record recently updated node IDs for auto-feedback
                # ARCH-DEBT: reuse b.db singleton instead of creating new BrainDB
                try:
                    _recent_rows = b.db.conn.execute(
                        "SELECT id FROM nodes ORDER BY updated_at DESC LIMIT 10"
                    ).fetchall()
                    _wk2 = str(b.workdir)
                    with srv._snodes_lock:
                        srv._session_nodes[_wk2] = [r[0] for r in _recent_rows if r[0]]
                except Exception as _e:
                    logger.debug("session_nodes update failed", exc_info=True)

                # E-03: overlay — append central brain context if configured
                try:
                    _central, _team_cfg = _get_central_client()
                    if _central and _team_cfg:
                        _is_central_only = (_team_cfg.mode == "central-only")
                        _is_overlay = (_team_cfg.mode == "overlay")
                        # Count local sources (heuristic: count "Sources" node IDs)
                        _local_thin = not ctx or len(ctx) < 100
                        if _is_central_only:
                            ctx = _central.get_context(task_clean, current_file=file_clean)
                        elif _is_overlay and _local_thin:
                            _central_ctx = _central.get_context(task_clean, current_file=file_clean)
                            if _central_ctx:
                                ctx = (ctx or "") + "\n\n---\n## 🌐 Central Brain\n" + _central_ctx
                except Exception as _e:
                    logger.debug("E-03 overlay failed (non-fatal): %s", _e)

                return ctx
            except Exception as e:
                logger.error("get_context 內部錯誤：%s", e)
                return ""  # 降級：不回傳錯誤細節

        # ── Tool 2：語義搜尋知識庫 ──────────────────────────────────
        @mcp.tool()
        def search_knowledge(
            query:     str,
            kind:      str = "",
            top_k:     int = 5,
            author:    str = "",
        ) -> list[dict]:
            """
            語義搜尋專案知識庫。

            Args:
                query:  搜尋詞（自然語言）
                kind:   節點類型過濾（Decision / Pitfall / Rule / ADR，空字串=全部）
                top_k:  回傳筆數（1-10）
                author: E-02: 按來源過濾（例："telegram:@alice"，空字串=不過濾）

            Returns:
                知識片段列表，每筆包含 title / content / type / similarity / source。
            """
            srv.rate_check()
            q_clean = _safe_str(query, MAX_QUERY_LEN, "query")

            valid_kinds = {"", "Decision", "Pitfall", "Rule", "ADR",
                           "Component", "Commit", "Person"}
            if kind not in valid_kinds:
                raise ValueError(f"kind 必須是 {valid_kinds} 之一")

            top_k = max(1, min(10, int(top_k)))
            author_filter = _safe_str(author, 200, "author") if author else ""

            def _format_result(r: dict) -> dict:
                return {
                    "title":      r.get("title", ""),
                    "content":    (r.get("content", "") or "")[:500],
                    "type":       r.get("type", ""),
                    "similarity": r.get("similarity"),
                    "tags":       r.get("tags", []),
                    "source":     r.get("source_url", ""),
                }

            def _author_match(r: dict) -> bool:
                if not author_filter:
                    return True
                src = r.get("source_url", "") or ""
                return author_filter.lower() in src.lower()

            try:
                # 優先用向量搜尋，fallback 到 FTS5
                from project_brain.vector_memory import VectorMemory
                vm = VectorMemory(Path(str(work_path)) / ".brain")
                if vm.available:
                    results = vm.search(q_clean, top_k=top_k * 3 if author_filter else top_k,
                                        node_type=kind or None)
                    if results:
                        filtered = [r for r in results if _author_match(r)]
                        return [_format_result(r) for r in filtered[:top_k]]

                # Fallback：SQLite FTS5
                raw = brain.graph.search_nodes(
                    q_clean, node_type=kind or None,
                    limit=top_k * 3 if author_filter else top_k,
                )
                filtered = [r for r in raw if _author_match(r)]
                local_results = [_format_result(r) for r in filtered[:top_k]]

                # E-03: overlay — supplement with central brain results
                try:
                    _central, _team_cfg = _get_central_client()
                    if _central and _team_cfg:
                        if _team_cfg.mode == "central-only":
                            return _central.search_knowledge(q_clean, top_k=top_k, kind=kind)
                        if _team_cfg.mode == "overlay" and len(local_results) < top_k:
                            _need = top_k - len(local_results)
                            _central_results = _central.search_knowledge(q_clean, top_k=_need, kind=kind)
                            # Dedup: skip central results whose title matches a local result
                            _local_titles = {r["title"].lower() for r in local_results}
                            for cr in _central_results:
                                if cr.get("title", "").lower() not in _local_titles:
                                    cr["source"] = cr.get("source", "") + " [central]"
                                    local_results.append(cr)
                                if len(local_results) >= top_k:
                                    break
                except Exception as _e:
                    logger.debug("E-03 search overlay failed (non-fatal): %s", _e)

                return local_results
            except Exception as e:
                logger.error("search_knowledge 內部錯誤：%s", e)
                return []

        # ── Tool 3：衝擊分析 ────────────────────────────────────────
        @mcp.tool()
        def impact_analysis(component: str) -> dict:
            """
            分析修改某個組件可能影響的範圍。

            Args:
                component: 組件名稱（例如 "PaymentService"）

            Returns:
                包含直接依賴、間接依賴、相關踩坑、業務規則的分析結果。
            """
            srv.rate_check()
            comp = _safe_str(component, 200, "component")

            try:
                return brain.graph.impact_analysis(comp)
            except Exception as e:
                logger.error("impact_analysis 內部錯誤：%s", e)
                return {"error": "分析失敗，請確認組件名稱"}

        # ── Tool 4：手動加入知識 ────────────────────────────────────
        @mcp.tool()
        def add_knowledge(
            title:       str,
            content:     str,
            kind:        str = "Note",
            scope:       str = "global",
            tags:        "list[str] | None" = None,
            confidence:  float = 0.8,
            source:      str = "",
            workdir:     str = "",
            description: str = "",  # MEM-02: one-line summary for AI relevance selection
        ) -> dict:
            """
            手動加入一筆知識片段到知識庫。

            Args:
                title:       標題（簡短，< 200 字）
                content:     詳細說明（< 2000 字）
                kind:        類型（Note / Decision / Pitfall / Rule / ADR）
                scope:       模組作用域（"global" / "auth" / "payment_service" 等）
                confidence:  確信度 0.0~1.0（agent 發現 = 0.6, human verified = 0.9）
                tags:        標籤列表（最多 10 個）
                source:      E-02: 知識來源（例："telegram:@alice" / "cli:bob" / "agent:crawler"）
                workdir:     Claude Code 當前工作目錄（選填，讓 Brain 自動找對應 .brain/）
                description: MEM-02：一行摘要，供 AI 相關性選取使用（空白時自動截取 content 前 100 字）

            Returns:
                {"node_id": "...", "success": true}
            """
            perm_err = _check_permission("add_knowledge")
            if perm_err:
                return perm_err
            srv.rate_check()

            title_c   = _safe_str(title,   MAX_TITLE_LEN, "title")
            content_c = _safe_str(content, MAX_CONTENT_LEN, "content")
            desc_c    = _safe_str(description, 300, "description") if description else ""  # MEM-02

            valid_kinds = {"Note", "Decision", "Pitfall", "Rule", "ADR", "Component"}
            kind = kind if kind in valid_kinds else "Note"

            safe_tags = []
            for tag in (tags or [])[:MAX_TAGS_COUNT]:
                t = _safe_str(str(tag), 50, "tag")
                if t:
                    safe_tags.append(t)

            source_c = _safe_str(source, 200, "source") if source else ""

            b = srv.resolve_brain(workdir)
            try:
                node_id = b.add_knowledge(
                    title       = title_c,
                    content     = content_c,
                    kind        = kind,
                    tags        = safe_tags,
                    confidence  = max(0.0, min(1.0, confidence)),
                    source      = source_c,
                    description = desc_c,  # MEM-02
                )
                # A-21: write scope to BrainDB (P1-A integration)
                # BUG-A01 fix: use WHERE id=? (not title=?) — title is non-unique
                if scope and scope != "global" and node_id:
                    try:
                        b.db.conn.execute(
                            "UPDATE nodes SET scope=? WHERE id=?",
                            (scope, node_id)
                        )
                        b.db.conn.commit()
                    except Exception as e:
                        logger.warning("scope update failed for node %s: %s", node_id, e)
                # C-04: emit MCP_TOOL_CALL signal (non-blocking)
                srv.emit_signal(
                    "mcp_tool_call", str(b.workdir),
                    f"add_knowledge kind={kind} title={title_c[:80]}",
                    raw_content=f"title: {title_c}\ncontent: {content_c[:500]}",
                    metadata={"tool": "add_knowledge", "kind": kind, "node_id": node_id},
                    priority=7,
                )
                # C-04: background conflict detection → emit KNOWLEDGE_CONFLICT
                def _bg_conflict_check():
                    try:
                        conflicts = b.db.find_conflicts_for_node(
                            node_id, similarity_threshold=0.6, candidates_per_anchor=10,
                        )
                        if conflicts:
                            srv.emit_signal(
                                "knowledge_conflict", str(b.workdir),
                                f"conflict: {title_c[:80]} vs {len(conflicts)} existing",
                                raw_content="\n".join(
                                    f"[{c.get('type','')}] {c.get('title_b','')}: {c.get('reason','')}"
                                    for c in conflicts[:3]
                                ),
                                metadata={"node_id": node_id, "conflict_count": len(conflicts)},
                                priority=4,
                            )
                    except Exception:
                        pass
                threading.Thread(target=_bg_conflict_check, daemon=True).start()
                return {"node_id": node_id, "success": True, "scope": scope, "confidence": confidence, "source": source_c}
            except Exception as e:
                logger.error("add_knowledge 內部錯誤：%s", e)
                return {"node_id": "", "success": False, "error": "加入失敗"}

        # ── Tool 4b：批量加入知識 (FEAT-02) ────────────────────────
        @mcp.tool()
        def batch_add_knowledge(
            items:   "list[dict]",
            workdir: str = "",
        ) -> dict:
            """
            批量加入多筆知識到知識庫（單次呼叫，降低 MCP round-trip 開銷）。

            Args:
                items:   知識清單，每筆格式與 add_knowledge 相同：
                         {"title": str, "content": str, "kind": str,
                          "scope": str, "tags": list, "confidence": float,
                          "description": str}
                         最多 50 筆。
                workdir: Claude Code 當前工作目錄

            Returns:
                {"ok": true, "created": N, "node_ids": [...], "errors": [...]}
            """
            srv.rate_check()
            MAX_BATCH = 50
            raw_items = items[:MAX_BATCH] if isinstance(items, list) else []
            b = srv.resolve_brain(workdir)
            valid_kinds = {"Note", "Decision", "Pitfall", "Rule", "ADR", "Component"}
            node_ids: list[str] = []
            errors:   list[str] = []

            for idx, item in enumerate(raw_items):
                if not isinstance(item, dict):
                    errors.append(f"item[{idx}] is not a dict")
                    continue
                try:
                    title_c   = _safe_str(str(item.get("title", "")),   MAX_TITLE_LEN,   "title")
                    content_c = _safe_str(str(item.get("content", "")), MAX_CONTENT_LEN, "content")
                    desc_c    = _safe_str(str(item.get("description", "")), 300, "description")
                    kind      = item.get("kind", "Note")
                    kind      = kind if kind in valid_kinds else "Note"
                    scope     = str(item.get("scope", "global"))
                    conf      = float(max(0.0, min(1.0, item.get("confidence", 0.8))))
                    safe_tags = [
                        _safe_str(str(t), 50, "tag")
                        for t in (item.get("tags") or [])[:MAX_TAGS_COUNT]
                        if t
                    ]
                    node_id = b.add_knowledge(
                        title=title_c, content=content_c, kind=kind,
                        tags=safe_tags, confidence=conf, description=desc_c,
                    )
                    if scope and scope != "global" and node_id:
                        try:
                            b.db.conn.execute(
                                "UPDATE nodes SET scope=? WHERE id=?", (scope, node_id)
                            )
                            b.db.conn.commit()
                        except Exception as _se:
                            logger.warning("batch scope update failed for %s: %s", node_id, _se)
                    node_ids.append(node_id)
                except Exception as _e:
                    errors.append(f"item[{idx}]: {_e}")
                    logger.warning("FEAT-02: batch_add item[%d] failed: %s", idx, _e)

            return {"ok": True, "created": len(node_ids), "node_ids": node_ids, "errors": errors}

        # ── Tool 5：知識庫狀態 ──────────────────────────────────────
        @mcp.tool()
        def brain_status(workdir: str = "") -> str:
            """
            查看 Project Brain 知識庫的目前狀態。

            Returns:
                統計摘要字串（節點數、邊數、最近新增的知識）。
            """
            srv.rate_check()
            b = srv.resolve_brain(workdir)
            try:
                return b.status()
            except Exception as e:
                logger.error("brain_status 內部錯誤：%s", e)
                return "狀態查詢失敗"

        # ── Resource：知識圖譜視覺化 ─────────────────────────────────
        @mcp.resource("brain://graph/mermaid")
        def graph_mermaid() -> str:
            """以 Mermaid 格式回傳知識圖譜（可直接在 Claude Code 渲染）"""
            try:
                return brain.export_mermaid(limit=30)
            except Exception as e:
                logger.error("graph_mermaid 內部錯誤：%s", e)
                return "graph TD\n    Error[\"圖譜載入失敗\"]"

        # ── Tool：時間機器查詢 ──────────────────────────────────────────
        @mcp.tool()
        def temporal_query(
            at_time:    str = "",
            git_branch: str = "HEAD",
            limit:      int = 20,
        ) -> str:
            """
            Time-machine read — query the knowledge graph at a specific point in time.

            Use this when working on old versions or legacy branches to avoid
            getting rules that didn't exist at that time.

            Args:
                at_time:    ISO timestamp (e.g. "2024-06-01T00:00:00").
                            Empty = current time.
                git_branch: Git branch name for context (e.g. "v1-legacy").
                            Used to resolve approximate timestamp if at_time is empty.
                limit:      Max results (default 20).

            Returns:
                JSON with temporal edges valid at the requested time.
            """
            srv.rate_check()
            import json
            from pathlib import Path as _P

            wd = os.environ.get("BRAIN_WORKDIR", str(work_path))
            db_path = _P(wd) / ".brain" / "brain.db"
            if not db_path.exists():
                return json.dumps({"error": "Brain not initialized", "edges": []})

            # BUG-A05: validate git_branch format before passing to subprocess
            if git_branch and git_branch != "HEAD":
                import re as _re
                if not _re.match(r'^[a-zA-Z0-9._\-/]+$', git_branch):
                    return json.dumps({"error": "git_branch 格式無效", "edges": []})

            try:
                # ARCH-01 fix: use singleton via resolve_brain instead of new BrainDB
                db = srv.resolve_brain(wd).db

                resolved_time = at_time.strip() or None
                if not resolved_time and git_branch and git_branch != "HEAD":
                    try:
                        import subprocess
                        r = subprocess.run(
                            ["git", "log", "-1", "--format=%aI", git_branch],
                            capture_output=True, text=True, cwd=wd, timeout=5
                        )
                        if r.returncode == 0 and r.stdout.strip():
                            resolved_time = r.stdout.strip()
                    except Exception as _e:
                        logger.debug("git log date resolution failed in temporal_query", exc_info=True)

                edges = db.temporal_query(at_time=resolved_time, limit=limit)
                # FEAT-03: also return nodes valid at the given time
                nodes = db.nodes_at_time(resolved_time or datetime.now(timezone.utc).isoformat(),
                                         limit=limit)
                return json.dumps({
                    "at_time":    resolved_time or "current",
                    "git_branch": git_branch,
                    "edge_count": len(edges),
                    "node_count": len(nodes),
                    "edges":      edges,
                    "nodes": [
                        {"id": n["id"], "type": n["type"], "title": n["title"],
                         "confidence": n["confidence"], "valid_from": n.get("valid_from")}
                        for n in nodes
                    ],
                }, ensure_ascii=False, indent=2)
            except Exception as e:
                return json.dumps({"error": str(e), "edges": []})

        # ── Tool：信心回饋 ─────────────────────────────────────────────
        @mcp.tool()
        def mark_helpful(
            node_id: str,
            helpful: bool = True,
        ) -> str:
            """
            Confidence feedback — call this after a piece of knowledge was actually useful.

            When helpful=True:  confidence += 0.03 (capped at 1.0)
            When helpful=False: confidence -= 0.05 (floored at 0.05)

            Args:
                node_id: The node ID returned by get_context or add_knowledge.
                helpful: True if the knowledge was correct/useful, False otherwise.

            Returns:
                JSON with updated confidence value.
            """
            srv.rate_check()
            import json
            from pathlib import Path as _P

            node_id = _safe_str(node_id, 100, "node_id")
            wd = os.environ.get("BRAIN_WORKDIR", str(work_path))
            db_path = _P(wd) / ".brain" / "brain.db"
            if not db_path.exists():
                return json.dumps({"error": "Brain not initialized"})

            try:
                # ARCH-01 fix: use singleton via resolve_brain instead of new BrainDB
                db       = srv.resolve_brain(wd).db
                new_conf = db.record_feedback(node_id, helpful=bool(helpful))
                return json.dumps({
                    "node_id":    node_id,
                    "helpful":    helpful,
                    "confidence": round(new_conf, 3),
                })
            except Exception as e:
                return json.dumps({"error": str(e)})

        # ── Tool: DEEP-01 推理鏈 ────────────────────────────────────────
        @mcp.tool()
        def reasoning_chain(task: str, workdir: str = "") -> str:
            """DEEP-01: 從任務關鍵字出發，遍歷知識圖譜，產生推理鏈。

            Args:
                task: 當前任務描述
                workdir: 工作目錄（選填）

            Returns:
                Markdown 格式推理鏈，顯示相關節點與邊的關係。
            """
            srv.rate_check()
            t_clean = _safe_str(task, MAX_QUERY_LEN, "task")
            b = srv.resolve_brain(workdir)
            try:
                from project_brain.context import ContextEngineer
                ce = ContextEngineer(b.graph, b.brain_dir, brain_db=b.db)
                return ce.build_reasoning_chain(t_clean) or "（無相關推理鏈）"
            except Exception as e:
                logger.error("reasoning_chain error: %s", e)
                return ""

        # ── Tool: DEEP-04 AI 自動確認 ─────────────────────────────────────
        @mcp.tool()
        def auto_resolve_knowledge(
            task:      str,
            threshold: float = 0.5,
            use_llm:   bool  = True,
            workdir:   str   = "",
        ) -> dict:
            """DEEP-04: AI 自動評估並修正低信心節點，無需人工介入。

            系統主目標是讓 AI 在長期大型企業專案中自主運作。
            此工具讓 AI 主動對知識庫中不確定的節點做出裁決：
            - Rule-based（零費用）：根據 adoption_count / access_count 自動裁決
            - LLM-assisted（可選）：規則無法裁決時，呼叫 Anthropic/Ollama 取得 AI 意見

            建議在 get_context() 之後呼叫，持續優化知識品質。

            Args:
                task:      當前任務描述（用於搜尋相關低信心節點）
                threshold: 信心門檻（低於此值觸發裁決，預設 0.5）
                use_llm:   是否允許呼叫 LLM（預設 True；rule-based 失敗時使用）
                workdir:   工作目錄（選填）

            Returns:
                {"resolved": N, "boosted": N, "downgraded": N, "deprecated": N,
                 "unchanged": N, "details": [...]}
            """
            srv.rate_check()
            t_clean = _safe_str(task, MAX_QUERY_LEN, "task")
            b = srv.resolve_brain(workdir)
            try:
                from project_brain.nudge_engine import NudgeEngine
                ne = NudgeEngine(b.graph, brain_db=b.db)
                return ne.auto_resolve_batch(
                    t_clean,
                    threshold=float(threshold),
                    use_llm=bool(use_llm),
                )
            except Exception as e:
                logger.error("auto_resolve_knowledge error: %s", e)
                return {"resolved": 0, "boosted": 0, "downgraded": 0,
                        "deprecated": 0, "unchanged": 0, "details": [], "error": str(e)}

        @mcp.tool()
        def generate_questions(task: str, threshold: float = 0.5,
                               workdir: str = "") -> list:
            """DEEP-04: 列出低信心節點供 AI 主動確認（明確確認路徑）。

            一般情況下 auto_resolve_knowledge() 會自動處理，
            此工具適合 AI 需要明確列出「尚不確定的知識」再逐一裁決時使用。

            Args:
                task:      當前任務描述
                threshold: 信心門檻（低於此值列出，預設 0.5）
                workdir:   工作目錄（選填）

            Returns:
                [{"node_id": ..., "question": "...", "current_confidence": 0.38}]
            """
            srv.rate_check()
            t_clean = _safe_str(task, MAX_QUERY_LEN, "task")
            b = srv.resolve_brain(workdir)
            try:
                from project_brain.nudge_engine import NudgeEngine
                ne = NudgeEngine(b.graph, brain_db=b.db)
                return ne.generate_questions(t_clean, threshold=float(threshold))
            except Exception as e:
                logger.error("generate_questions error: %s", e)
                return []

        @mcp.tool()
        def answer_question(
            node_id: str,
            answer: str,
            new_confidence: float = 0.9,
            workdir: str = "",
        ) -> dict:
            """DEEP-04: AI 回饋對特定節點的判斷，更新信心值並記錄學習事件。

            配合 generate_questions() 使用，也可以獨立呼叫。
            AI 自行判斷後直接呼叫此工具更新知識庫，形成完全自動的學習閉環。

            Args:
                node_id:        目標節點 ID
                answer:         AI 的判斷 / 補充說明
                new_confidence: 更新後信心值（預設 0.9）
                workdir:        工作目錄（選填）

            Returns:
                {"ok": True, "node_id": ..., "new_confidence": ...} or {"ok": False, "error": ...}
            """
            srv.rate_check()
            b = srv.resolve_brain(workdir)
            try:
                node_id_clean  = _safe_str(node_id, 128, "node_id")
                answer_clean   = _safe_str(answer, MAX_QUERY_LEN, "answer")
                conf           = float(max(0.0, min(1.0, new_confidence)))
                node = b.db.get_node(node_id_clean)
                if not node:
                    return {"ok": False, "error": f"node {node_id_clean!r} not found"}
                new_content = (node.get("content") or "") + f"\n[AI確認] {answer_clean}"
                b.db.update_node(
                    node_id_clean,
                    content=new_content,
                    confidence=conf,
                    changed_by="answer_question",
                    change_note=f"AI confirmation: {answer_clean[:80]}",
                )
                b.db.add_episode(
                    content=f"[AI主動確認] {node.get('title','')}: {answer_clean}",
                    source=f"answer_question:{node_id_clean}",
                    confidence=conf,
                )
                return {"ok": True, "node_id": node_id_clean, "new_confidence": conf}
            except Exception as e:
                logger.error("answer_question error: %s", e)
                return {"ok": False, "error": str(e)}

        # ── Tool: complete_task (PH1-02) ────────────────────────────────
        @mcp.tool()
        def complete_task(
            task_description: str,
            decisions: list[str] | None = None,
            lessons: list[str] | None = None,
            pitfalls: list[str] | None = None,
            workdir: str = "",
        ) -> dict:
            """
            Batch-write session learnings to L3 after completing a task.

            Call this at the end of EVERY non-trivial task. It creates permanent
            knowledge nodes from the work just done, closing the knowledge
            production loop so future agents benefit from this session.

            Args:
                task_description: One-sentence summary of what was accomplished.
                decisions: Architectural or design choices made during the task
                           (each item becomes a Decision node).
                lessons:   Things learned that would help future work — best
                           practices, non-obvious constraints, shortcuts found
                           (each item becomes a Rule node).
                pitfalls:  Mistakes encountered, near-misses, or traps to avoid
                           (each item becomes a Pitfall node).
                workdir:   Project working directory. Defaults to BRAIN_WORKDIR env var.

            Returns:
                {"ok": True, "created": N, "node_ids": [...]}
            """
            perm_err = _check_permission("complete_task")
            if perm_err:
                return perm_err
            srv.rate_check()

            wd_str = _safe_str(workdir or os.environ.get("BRAIN_WORKDIR", ""), 500, "workdir") or workdir
            b = srv.resolve_brain(wd_str)

            task_desc = _safe_str(task_description, MAX_CONTENT_LEN, "task_description")
            _decisions = [_safe_str(d, MAX_CONTENT_LEN, "decisions[i]") for d in (decisions or [])]
            _lessons   = [_safe_str(l, MAX_CONTENT_LEN, "lessons[i]")   for l in (lessons   or [])]
            _pitfalls  = [_safe_str(p, MAX_CONTENT_LEN, "pitfalls[i]")  for p in (pitfalls  or [])]

            created_ids: list[str] = []

            # AUTO-02: delegate to KnowledgeExtractor.from_session_log() for
            # consistent title extraction (first sentence, not truncation) and
            # single-source-of-truth knowledge production logic.
            from project_brain.extractor import KnowledgeExtractor as _KE
            _extractor = _KE(workdir=str(b.workdir))
            _source    = f"session:{datetime.now(timezone.utc).date()}"
            extracted  = _extractor.from_session_log(
                task_description=task_desc,
                decisions=_decisions,
                lessons=_lessons,
                pitfalls=_pitfalls,
                source=_source,
            )
            chunks = extracted.get("knowledge_chunks", [])

            # Always record at least the task itself if no sub-items were provided,
            # so the task is never silently swallowed.
            if not chunks:
                chunks = [{
                    "type":       "Decision",
                    "title":      task_desc[:60].strip(),
                    "content":    task_desc,
                    "tags":       ["session"],
                    "confidence": 0.75,
                    "source":     _source,
                }]

            for chunk in chunks:
                _title = chunk.get("title", task_desc[:60]).strip()
                try:
                    node_id = b.add_knowledge(
                        title=_title,
                        content=chunk.get("content", task_desc),
                        kind=chunk.get("type", "Decision"),
                        tags=chunk.get("tags", []) + ["auto:complete_task"],
                        confidence=chunk.get("confidence", 0.8),
                    )
                    created_ids.append(node_id)
                except Exception as e:
                    logger.warning("complete_task: failed to write node %r: %s", _title, e)

            # VISION-01: auto-feedback on session nodes based on task outcome
            _wk = str(b.workdir)
            _auto_nodes: list[str] = []
            with srv._snodes_lock:
                _auto_nodes = list(srv._session_nodes.pop(_wk, []))
            if _auto_nodes:
                _had_pitfalls = bool(_pitfalls)
                # ARCH-DEBT: reuse b.db singleton instead of creating new BrainDB
                try:
                    for _nid in _auto_nodes[:5]:  # cap at 5 to avoid over-feedback
                        b.db.record_feedback(_nid, helpful=not _had_pitfalls)
                    logger.debug(
                        "VISION-01 auto-feedback: %d nodes helpful=%s",
                        min(5, len(_auto_nodes)), not _had_pitfalls,
                    )
                except Exception as _fe:
                    logger.debug("VISION-01 auto-feedback failed: %s", _fe)

            # C-04: emit TEST_FAILURE signal when pitfalls or error lessons exist
            _error_lessons = [
                l for l in _pitfalls
                if any(kw in l.lower() for kw in ("test", "error", "fail", "bug", "crash"))
            ]
            if _error_lessons:
                srv.emit_signal(
                    "test_failure", str(b.workdir),
                    f"complete_task pitfall: {_error_lessons[0][:100]}",
                    raw_content="\n".join(_error_lessons[:3]),
                    metadata={"task": task_desc[:200], "pitfall_count": len(_pitfalls)},
                    priority=3,
                )

            return {"ok": True, "created": len(created_ids), "node_ids": created_ids}

        # ── Tool: report_knowledge_outcome (PH1-03) ──────────────────────
        @mcp.tool()
        def report_knowledge_outcome(
            node_id: str,
            was_useful: bool,
            notes: str = "",
            workdir: str = "",
        ) -> dict:
            """
            Close the knowledge feedback loop by reporting whether a retrieved
            knowledge node was actually useful.

            Call this after using knowledge returned by get_context:
            - was_useful=True  → confidence increases (node surfaces more often)
            - was_useful=False → confidence decreases (node surfaces less often)

            This drives the decay engine and keeps the knowledge base accurate
            over time. Without this feedback, stale or incorrect knowledge never
            gets deprioritised.

            Args:
                node_id:    The node ID from get_context or add_knowledge.
                was_useful: True if the knowledge helped; False if outdated/wrong.
                notes:      Optional explanation — especially important when
                            was_useful=False to document why the node is wrong.
                workdir:    Project working directory. Defaults to BRAIN_WORKDIR env var.

            Returns:
                {"ok": True, "node_id": "...", "confidence": 0.85, "delta": +0.03}
            """
            perm_err = _check_permission("report_knowledge_outcome")
            if perm_err:
                return perm_err
            srv.rate_check()

            node_id_clean = _safe_str(node_id, 100, "node_id")
            notes_clean   = _safe_str(notes, MAX_CONTENT_LEN, "notes") if notes else ""
            wd_str = _safe_str(workdir or os.environ.get("BRAIN_WORKDIR", ""), 500, "workdir") or workdir

            # ARCH-01 fix: use singleton via resolve_brain instead of new BrainDB
            b = srv.resolve_brain(wd_str)
            if not (b.brain_dir / "brain.db").exists():
                return {"ok": False, "error": "Brain not initialized — run brain init first"}

            try:
                db      = b.db
                delta   = 0.03 if was_useful else -0.05
                _conf_before = 0.0
                try:
                    _r = db.conn.execute(
                        "SELECT confidence FROM nodes WHERE id=?", (node_id_clean,)
                    ).fetchone()
                    _conf_before = float(_r[0]) if _r else 0.0
                except Exception:
                    pass
                new_conf = db.record_feedback(node_id_clean, helpful=bool(was_useful))
                # C-05: write to feedback_log for pipeline feedback loop
                try:
                    # Determine signal_kind from pipeline_metrics if available
                    _sig_kind = ""
                    try:
                        _pm = db.conn.execute(
                            "SELECT signal_id FROM pipeline_metrics WHERE node_id=? LIMIT 1",
                            (node_id_clean,),
                        ).fetchone()
                        if _pm:
                            _sq = db.conn.execute(
                                "SELECT kind FROM signal_queue WHERE id=? LIMIT 1",
                                (_pm[0],),
                            ).fetchone()
                            if _sq:
                                _sig_kind = _sq[0]
                    except Exception:
                        pass
                    db._feedback_tracker.log_feedback(
                        node_id_clean, was_useful,
                        signal_kind=_sig_kind,
                        notes=notes_clean,
                        conf_before=_conf_before,
                        conf_after=new_conf,
                    )
                except Exception as _fl:
                    logger.debug("C-05: feedback_log write failed: %s", _fl)
                # BUG-C fix: emit event so analytics_engine.useful_knowledge_rate() works
                try:
                    db.emit("knowledge_outcome", {
                        "node_id":    node_id_clean,
                        "was_useful": was_useful,
                        "notes":      notes_clean,
                        "confidence": round(new_conf, 3),
                    })
                except Exception as _e:
                    logger.debug("knowledge_outcome event emit failed", exc_info=True)
                # DEEP-05: update adoption_count in knowledge_graph so F6 decay factor can use it
                if was_useful:
                    try:
                        b.graph.increment_adoption(node_id_clean)
                    except Exception as _e:
                        logger.debug("increment_adoption failed", exc_info=True)

                # If notes provided and node is now low-confidence, append note to content
                if notes_clean and not was_useful:
                    try:
                        db.conn.execute(
                            "UPDATE nodes SET content = content || ? WHERE id = ?",
                            (f"\n\n[Feedback {_now_iso()}: {notes_clean}]", node_id_clean),
                        )
                        db.conn.commit()
                    except Exception as _e:
                        logger.debug("feedback note append failed", exc_info=True)  # non-critical

                return {
                    "ok":         True,
                    "node_id":    node_id_clean,
                    "was_useful": was_useful,
                    "confidence": round(new_conf, 3),
                    "delta":      delta,
                }
            except Exception as e:
                logger.error("report_knowledge_outcome error: %s", e)
                return {"ok": False, "error": str(e)}

        # ── Tool: push_to_central (E-05) ────────────────────────────────
        @mcp.tool()
        def push_to_central(
            node_ids: "list[str] | None" = None,
            kind: str = "",
            min_confidence: float = 0.8,
            max_nodes: int = 50,
            target_url: str = "",
            api_key: str = "",
            workdir: str = "",
        ) -> dict:
            """
            推送本地知識到 Central Brain。

            可指定 node_ids 推送特定節點，或用 kind/min_confidence 篩選。
            推送的知識進入 Central Brain 的 KRB Staging 待審。

            Args:
                node_ids:       指定推送的節點 ID（None = 使用 kind/confidence 篩選）
                kind:           節點類型篩選（Pitfall/Rule/Decision，空 = 全部）
                min_confidence: 最低信心度（預設 0.8）
                max_nodes:      最大推送數（預設 50）
                target_url:     Central Brain URL（空 = 從 brain.toml [team] 讀取）
                api_key:        API key（空 = 從 brain.toml [team] 或 BRAIN_API_KEY 讀取）
                workdir:        專案工作目錄

            Returns:
                {"ok": True, "pushed": N, "failed": M, "errors": [...]}
            """
            perm_err = _check_permission("push_to_central")
            if perm_err:
                return perm_err
            srv.rate_check()

            wd_str = _safe_str(workdir or os.environ.get("BRAIN_WORKDIR", ""), 500, "workdir") or workdir
            b = srv.resolve_brain(wd_str)

            # Resolve target URL
            _url = _safe_str(target_url, 500, "target_url")
            _key = _safe_str(api_key, 500, "api_key")
            if not _url:
                try:
                    from project_brain.brain_config import load_config
                    _cfg = load_config(b.brain_dir)
                    _url = _cfg.team.central_brain_url
                    if not _key:
                        _key = _cfg.team.central_brain_key
                except Exception:
                    pass
            if not _url:
                return {"ok": False, "error": "No target URL — set via argument or brain.toml [team]"}

            from project_brain.integrations.push_central import PushTransport
            from project_brain.integrations.central_brain_client import CentralBrainClient

            transport = PushTransport()
            client = CentralBrainClient(url=_url, api_key=_key)

            if node_ids:
                # Push specific nodes
                nodes = [b.db.get_node(nid) for nid in node_ids]
                nodes = [n for n in nodes if n is not None]
            else:
                nodes = transport.select_nodes(
                    b.db, kind=kind, min_confidence=min_confidence, max_nodes=max_nodes,
                )

            sanitized = transport.sanitize_nodes(nodes)
            result = transport.push(client, sanitized, source_label="mcp:push")

            return {
                "ok": result.pushed_fail == 0,
                "pushed": result.pushed_ok,
                "failed": result.pushed_fail,
                "total_selected": result.total_selected,
                "errors": result.errors[:10],
            }

        # ── Tool: krb_pre_screen (PH3-03) ───────────────────────────────
        @mcp.tool()
        def krb_pre_screen(
            limit:                   int   = 50,
            auto_approve_threshold:  float = 0.0,
            auto_reject_threshold:   float = 0.0,
            max_api_calls:           int   = 10,
            workdir:                 str   = "",
        ) -> dict:
            """
            AI-assisted KRB review — pre-screen pending staged nodes with Claude Haiku.

            Routes each pending knowledge node into one of three lanes:
              approve lane  — AI confident the knowledge is clear and actionable
              review lane   — needs human judgment (always used for Pitfall nodes)
              reject lane   — likely noise, too vague, or duplicate

            Call this after brain scan or any large batch import to reduce
            manual review burden. Human still has final say — auto-approve and
            auto-reject are OFF by default (set threshold > 0 to enable).

            Args:
                limit:                   Max pending nodes to process (default 50).
                auto_approve_threshold:  AI confidence ≥ this → auto-approve.
                                         0.0 = disabled (recommended default).
                                         Pitfall nodes are NEVER auto-approved.
                auto_reject_threshold:   AI confidence ≥ this AND recommends reject
                                         → auto-reject. 0.0 = disabled.
                max_api_calls:           Cost guard: max Haiku API calls (default 10).
                workdir:                 Project working directory (optional).

            Returns:
                {
                  "total":          nodes processed,
                  "approve_lane":   count routed to approve,
                  "review_lane":    count routed to human review,
                  "reject_lane":    count routed to reject,
                  "auto_approved":  count actually auto-approved,
                  "auto_rejected":  count actually auto-rejected,
                  "api_calls_used": Haiku API calls consumed,
                }
            """
            srv.rate_check()
            import os as _os

            api_key = _os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                return {"error": "ANTHROPIC_API_KEY 未設定，無法執行 AI 預篩"}

            b = srv.resolve_brain(workdir)
            bd = b.brain_dir

            try:
                import anthropic
                from project_brain.graph        import KnowledgeGraph
                from project_brain.review_board import KnowledgeReviewBoard
                from project_brain.krb_ai_assist import KRBAIAssistant

                graph  = KnowledgeGraph(bd)
                krb    = KnowledgeReviewBoard(bd, graph)
                client = anthropic.Anthropic(api_key=api_key)
                assist = KRBAIAssistant(krb, client)

                aa = auto_approve_threshold if auto_approve_threshold > 0.0 else None
                ar = auto_reject_threshold  if auto_reject_threshold  > 0.0 else None

                summary = assist.pre_screen(
                    limit                  = max(1, min(200, limit)),
                    auto_approve_threshold = aa,
                    auto_reject_threshold  = ar,
                    max_api_calls          = max(1, min(50, max_api_calls)),
                )
                # Strip non-serialisable AIScreenResult objects
                summary.pop("results", None)
                return summary

            except ImportError:
                return {"error": "anthropic 套件未安裝，請執行：pip install anthropic"}
            except Exception as e:
                logger.error("krb_pre_screen 內部錯誤：%s", e)
                return {"error": "預篩失敗，請檢查日誌"}

        # ── Tool: multi_brain_query (VISION-05) ─────────────────────────────────
        @mcp.tool()
        def multi_brain_query(
            task: str,
            extra_brain_dirs: list[str] | None = None,
            top_k: int = 5,
            workdir: str = "",
        ) -> str:
            """
            Query multiple .brain/ directories simultaneously — for monorepo scenarios.

            Merges knowledge from the primary Brain plus any additional Brain instances,
            ranks all results by confidence, and labels each result with its source project.

            Configure additional brains permanently via environment variable:
              BRAIN_EXTRA_DIRS=/path/to/project-a:/path/to/project-b

            Args:
                task:             Task description for context retrieval.
                extra_brain_dirs: Additional project directories containing .brain/
                                  (overrides BRAIN_EXTRA_DIRS env var when provided).
                top_k:            Max results to return per brain (default 5).
                workdir:          Primary project directory (optional).

            Returns:
                Merged context string with [source: project-name] labels per result.
                Empty string if no results found.
            """
            srv.rate_check()
            task_clean = _safe_str(task, MAX_QUERY_LEN, "task")
            top_k = max(1, min(20, int(top_k)))

            # Resolve list of brain dirs to query
            dirs_to_query: list[str] = []

            # 1. Primary brain
            primary_b = srv.resolve_brain(workdir)
            dirs_to_query.append(str(primary_b.workdir))

            # 2. Extra dirs from argument
            if extra_brain_dirs:
                for d in extra_brain_dirs[:10]:
                    try:
                        d_clean = _safe_str(str(d), 500, "extra_brain_dirs[i]")
                        if not d_clean:
                            continue
                        # HIGH-04: SEC-01 style check — resolve symlinks and block
                        # forbidden system roots.  ".." check alone is bypassable via
                        # symlinks (e.g. /tmp/evil -> /etc).
                        _raw = Path(d_clean)
                        if ".." in _raw.parts:
                            logger.warning("multi_brain_query: skipping traversal path %s", d_clean)
                            continue
                        _resolved = _raw.resolve()
                        _blocked = False
                        for _fr in _FORBIDDEN_ROOTS:
                            try:
                                _resolved.relative_to(_fr)
                                logger.warning(
                                    "multi_brain_query: skipping forbidden root path %s", d_clean
                                )
                                _blocked = True
                                break
                            except ValueError:
                                pass
                        if not _blocked:
                            dirs_to_query.append(d_clean)
                    except Exception as _e:
                        logger.debug("extra_brain_dirs entry parse failed", exc_info=True)
            else:
                # 3. Fall back to BRAIN_EXTRA_DIRS env var
                env_extra = os.environ.get("BRAIN_EXTRA_DIRS", "")
                if env_extra:
                    for d in env_extra.split(":"):
                        d = d.strip()
                        if not d or ".." in Path(d).parts:
                            continue
                        # HIGH-04: same forbidden-root check for env var paths
                        _resolved = Path(d).resolve()
                        _blocked = False
                        for _fr in _FORBIDDEN_ROOTS:
                            try:
                                _resolved.relative_to(_fr)
                                _blocked = True
                                break
                            except ValueError:
                                pass
                        if not _blocked:
                            dirs_to_query.append(d)

            # Deduplicate
            seen: set[str] = set()
            unique_dirs: list[str] = []
            for d in dirs_to_query:
                resolved = str(Path(d).resolve())
                if resolved not in seen:
                    seen.add(resolved)
                    unique_dirs.append(d)

            if len(unique_dirs) <= 1:
                # Single brain — delegate to standard get_context
                try:
                    return primary_b.get_context(task_clean) or ""
                except Exception as _e:
                    logger.debug("single brain get_context failed in answer_question", exc_info=True)
                    return ""

            # Query each brain
            all_results: list[dict] = []
            for d in unique_dirs:
                root = _find_brain_root(d)
                if root is None:
                    continue
                try:
                    key = str(root)
                    with srv._cache_lock:   # SEC-05: atomic read-check-write + SEC-04 LRU
                        if key not in srv._brain_cache:
                            if len(srv._brain_cache) >= _MAX_BRAIN_CACHE:
                                oldest_key, _ = srv._brain_cache.popitem(last=False)
                                logger.debug("SEC-04: evicted brain cache entry %s", oldest_key)
                            from project_brain.engine import ProjectBrain as _PB
                            srv._brain_cache[key] = _PB(key)
                        else:
                            srv._brain_cache.move_to_end(key)
                        b_inst = srv._brain_cache[key]
                    project_name = root.name
                    # Get context snippets
                    raw = b_inst.graph.search_nodes(task_clean, limit=top_k)
                    for node in raw:
                        all_results.append({
                            "source":     project_name,
                            "title":      node.get("title", ""),
                            "content":    (node.get("content", "") or "")[:400],
                            "kind":       node.get("type", ""),
                            "confidence": float(node.get("confidence", 0.5) or 0.5),
                        })
                except Exception as _me:
                    logger.debug("multi_brain_query: skipping %s — %s", d, _me)

            if not all_results:
                return ""

            # Sort by confidence descending
            all_results.sort(key=lambda x: x["confidence"], reverse=True)
            # Deduplicate by title across brains
            seen_titles: set[str] = set()
            deduped: list[dict] = []
            for r in all_results:
                t = r["title"].lower().strip()
                if t and t not in seen_titles:
                    seen_titles.add(t)
                    deduped.append(r)

            # Format output
            lines = [f"## 🔗 Multi-Brain Query: {task_clean!r} ({len(unique_dirs)} projects)\n"]
            for r in deduped[:top_k * len(unique_dirs)]:
                conf_str = f"conf={r['confidence']:.2f}"
                lines.append(
                    f"**[{r['source']}]** [{r['kind']}] {r['title']}  ({conf_str})\n"
                    f"{r['content'][:200]}\n"
                )

            return "\n".join(lines)

        # ── Tool: federation_sync (VISION-03) ────────────────────────────────────
        @mcp.tool()
        def federation_sync(
            dry_run:        bool  = False,
            min_confidence: float = 0.5,
            workdir:        str   = "",
        ) -> dict:
            """
            Sync knowledge from all configured federation sync_sources into KRB Staging.

            Reads sync_sources from .brain/federation.json and imports each enabled bundle
            file into the KRB Staging queue for human review before promotion to L3.

            To add a sync source permanently, use the CLI:
              brain fed sync --add-source "project-a:/path/to/federation_export.json"

            Args:
                dry_run:        Preview only — do not write to KRB Staging.
                min_confidence: Skip nodes below this confidence (default 0.5).
                workdir:        Project directory (auto-detected if omitted).

            Returns:
                {"synced": int, "skipped": int, "errors": int, "details": list}
            """
            srv.rate_check()
            # ARCH-DEBT: reuse resolve_brain singletons
            try:
                _b    = srv.resolve_brain(workdir)
                from project_brain.review_board  import KnowledgeReviewBoard as _KRB_FED
                from project_brain.federation    import FederationAutoSync
                _krb_f  = _KRB_FED(_b.db, _b.graph)
                syncer  = FederationAutoSync(_krb_f, _b.brain_dir)
                stats   = syncer.sync_all(dry_run=dry_run, min_confidence=min_confidence)
                logger.info(
                    "federation_sync: synced=%d skipped=%d errors=%d",
                    stats["synced"], stats["skipped"], stats["errors"],
                )
                return stats
            except Exception as e:
                logger.error("federation_sync 內部錯誤：%s", e)
                return {"error": str(e), "synced": 0, "skipped": 0, "errors": 1, "details": []}

        # ── Start background daemons ───────────────────────────────
        self._start_daemons()

        return mcp


# ── MCP Server 公開工廠函式 ────────────────────────────────────


def create_server(workdir: str) -> Any:
    """建立並回傳 MCP Server（公開 API，無 breaking change）。

    內部建立 BrainServer 實例，所有可變狀態封裝在該實例中。
    同一程序多次呼叫 create_server() 會建立獨立的狀態空間。
    """
    srv = BrainServer(workdir)
    return srv.create_mcp_server()


def create_http_server(
    workdir: str,
    *,
    bind: str = "127.0.0.1",
    port: int = 3000,
    auth_key: str | None = None,
    rate_limit_rpm: int = 60,
    allowed_origins: list[str] | None = None,
    transport: str = "streamable-http",
    mode: str = "standalone",
) -> "HTTPBrainServer":
    """E-01: 建立支援 HTTP/SSE 的 MCP Server（供遠端 Claude Code 連接）。

    Args:
        workdir: 專案工作目錄（需要有 .brain/）
        bind: 綁定地址（預設 127.0.0.1，生產環境用 0.0.0.0）
        port: 監聽 port（預設 3000）
        auth_key: API key（None = 不需認證，僅限本地開發）
        rate_limit_rpm: 每 IP 每分鐘最大請求數（預設 60）
        allowed_origins: CORS 白名單（None = 不設 CORS）
        transport: 傳輸方式（'streamable-http' 或 'sse'）

    Returns:
        HTTPBrainServer 實例，呼叫 .run() 啟動或 .create_app() 取得 ASGI app

    Example::

        # 遠端存取模式
        http = create_http_server(
            "/path/to/project",
            bind="0.0.0.0", port=3000,
            auth_key=os.environ["BRAIN_API_KEY"],
        )
        http.run()  # blocking — starts uvicorn

        # Claude Code 客戶端設定
        # {
        #   "mcpServers": {
        #     "company-brain": {
        #       "url": "http://brain.company.internal:3000/mcp",
        #       "headers": {"Authorization": "Bearer ${BRAIN_API_KEY}"}
        #     }
        #   }
        # }
    """
    from project_brain.interfaces.http_transport import HTTPBrainServer
    srv = BrainServer(workdir, mode=mode)
    return HTTPBrainServer(
        brain_server=srv,
        bind=bind,
        port=port,
        auth_key=auth_key,
        rate_limit_rpm=rate_limit_rpm,
        allowed_origins=allowed_origins,
        transport=transport,
        mode=mode,
    )


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    """MCP Server 主入口"""
    logging.basicConfig(
        level  = logging.WARNING,   # 生產環境不輸出 DEBUG
        format = "%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Project Brain MCP Server")
    parser.add_argument(
        "--workdir", "-w",
        default = os.environ.get("BRAIN_WORKDIR", os.getcwd()),
        help    = "專案工作目錄（需要有 .brain/），預設使用 BRAIN_WORKDIR 環境變數",
    )
    parser.add_argument(
        "--transport",
        default = "stdio",
        choices = ["stdio", "sse", "streamable-http"],
        help    = "傳輸方式（stdio 供本地 Claude Code，sse/streamable-http 供遠端連接）",
    )
    parser.add_argument(
        "--bind",
        default = "127.0.0.1",
        help    = "HTTP 綁定地址（預設 127.0.0.1，遠端存取用 0.0.0.0）",
    )
    parser.add_argument(
        "--port",
        type    = int,
        default = 3000,
        help    = "HTTP 監聽 port（預設 3000）",
    )
    parser.add_argument(
        "--auth-key",
        dest    = "auth_key",
        default = os.environ.get("BRAIN_API_KEY"),
        help    = "API key for HTTP auth（或設 BRAIN_API_KEY 環境變數）",
    )
    parser.add_argument(
        "--rate-limit-rpm",
        dest    = "rate_limit_rpm",
        type    = int,
        default = int(os.environ.get("BRAIN_RATE_LIMIT_RPM", "60")),
        help    = "每 IP 每分鐘最大請求數（預設 60）",
    )
    parser.add_argument(
        "--allow-origin",
        dest    = "allow_origins",
        action  = "append",
        default = None,
        help    = "CORS 允許的 origin（可多次指定）",
    )
    args = parser.parse_args()

    try:
        if args.transport in ("sse", "streamable-http"):
            # E-01: HTTP MCP mode
            http = create_http_server(
                args.workdir,
                bind=args.bind,
                port=args.port,
                auth_key=args.auth_key,
                rate_limit_rpm=args.rate_limit_rpm,
                allowed_origins=args.allow_origins,
                transport=args.transport,
            )
            logger.warning(
                "Project Brain HTTP MCP Server 啟動（workdir: %s, %s:%d）",
                args.workdir, args.bind, args.port,
            )
            http.run()
        else:
            mcp = create_server(args.workdir)
            logger.warning("Project Brain MCP Server 啟動（workdir: %s）", args.workdir)
            mcp.run(transport=args.transport)
    except FileNotFoundError as e:
        print(f"[錯誤] {e}", file=sys.stderr)
        sys.exit(1)
    except ImportError as e:
        print(f"[錯誤] 缺少依賴：{e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        logger.warning("MCP Server 已停止")


if __name__ == "__main__":
    main()

