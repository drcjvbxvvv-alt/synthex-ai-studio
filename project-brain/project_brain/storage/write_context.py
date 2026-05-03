"""
project_brain/storage/write_context.py — 共享寫入基礎設施

所有 Repository 共享的寫入基礎設施。提供：
  - conn: 共享 SQLite 連線
  - write_guard(): RLock context manager
  - execute_write(sql, params): 統一寫入入口（lock + commit + rollback）
  - execute_writescript(script): 多語句寫入入口

Repository 透過 ctx.execute_write() 寫入，不直接操作 conn.execute + commit。
"""
from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import queue
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


@dataclasses.dataclass
class _WriteRequest:
    """Internal message passed through the serialized write queue."""
    kind: str                          # "execute" | "executescript" | "callable"
    sql: str = ""
    params: tuple = ()
    fn: Callable | None = None
    result_event: threading.Event = dataclasses.field(default_factory=threading.Event)
    result_value: Any = None
    error: BaseException | None = None


class WriteContext:
    """Shared write infrastructure for all repositories.

    Manages:
      - SQLite connection (WAL mode, shared across threads)
      - RLock-based write serialization
      - Optional E-02 write queue for central brain mode
      - Trace sampling counter
    """

    def __init__(self, brain_dir: Path, *, serialized_writes: bool = False):
        self.brain_dir = Path(brain_dir)
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.brain_dir / "brain.db"
        self._write_lock = threading.RLock()
        self._trace_counter = 0
        self._trace_sample_rate = int(os.environ.get("BRAIN_TRACE_SAMPLE_RATE", "5"))
        self._serialized_writes = serialized_writes
        self._write_queue: queue.Queue[_WriteRequest | None] | None = None
        self._write_worker_thread: threading.Thread | None = None
        self._conn_obj: sqlite3.Connection = self._make_connection()

    def _make_connection(self) -> sqlite3.Connection:
        """Open the shared SQLite connection with WAL mode."""
        c = sqlite3.connect(str(self.db_path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn_obj

    def start_write_worker(self) -> None:
        """Start the E-02 background write worker. Call after schema setup."""
        if self._serialized_writes and self._write_queue is None:
            self._write_queue = queue.Queue()
            self._write_worker_thread = threading.Thread(
                target=self._write_worker, daemon=True, name="brain-write-worker",
            )
            self._write_worker_thread.start()

    def close(self) -> None:
        """Gracefully close connection and write worker."""
        if self._write_queue is not None:
            self._write_queue.put(None)  # poison pill
            if self._write_worker_thread is not None:
                self._write_worker_thread.join(timeout=5)
            self._write_queue = None
            self._write_worker_thread = None
        if self._conn_obj is None:
            return
        try:
            self._conn_obj.close()
        except Exception:
            pass
        self._conn_obj = None

    # ── Write guard ──────────────────────────────────────────────

    @contextlib.contextmanager
    def write_guard(self):
        """RLock-based write serialization (reentrant, cross-platform)."""
        with self._write_lock:
            yield

    # ── Write queue (E-02) ───────────────────────────────────────

    def is_write_worker(self) -> bool:
        return (self._write_worker_thread is not None
                and threading.current_thread() is self._write_worker_thread)

    def _write_worker(self) -> None:
        """Background thread draining the write queue serially."""
        while True:
            req = self._write_queue.get()
            if req is None:
                break
            try:
                if req.kind == "execute":
                    req.result_value = self._execute_write_direct(req.sql, req.params)
                elif req.kind == "executescript":
                    self._execute_writescript_direct(req.sql)
                elif req.kind == "callable" and req.fn is not None:
                    req.result_value = req.fn()
            except Exception as e:
                req.error = e
            finally:
                req.result_event.set()

    def _enqueue_write(self, kind: str, sql: str, params: tuple = ()) -> Any:
        req = _WriteRequest(kind=kind, sql=sql, params=params)
        self._write_queue.put(req)
        req.result_event.wait()
        if req.error:
            raise req.error
        return req.result_value

    def enqueue_write_fn(self, fn: Callable[..., _T]) -> _T:
        """Enqueue a callable to the write worker. Blocks until complete."""
        req = _WriteRequest(kind="callable", fn=fn)
        self._write_queue.put(req)
        req.result_event.wait()
        if req.error:
            raise req.error
        return req.result_value

    # ── Unified write entry points ───────────────────────────────

    def _execute_write_direct(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self.write_guard():
            try:
                cur = self.conn.execute(sql, params)
                self.conn.commit()
                return cur
            except Exception:
                try:
                    self.conn.rollback()
                except Exception as _rb_err:
                    logger.error("_execute_write: rollback failed: %s", _rb_err)
                raise

    def _execute_writescript_direct(self, script: str) -> None:
        with self.write_guard():
            try:
                self.conn.executescript(script)
            except Exception:
                try:
                    self.conn.rollback()
                except Exception as _rb_err:
                    logger.error("_execute_writescript: rollback failed: %s", _rb_err)
                raise

    def execute_write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Unified write entry point: lock + commit + rollback.

        In serialized_writes mode, enqueues to the write worker.
        """
        if self._serialized_writes and not self.is_write_worker():
            return self._enqueue_write("execute", sql, params)
        return self._execute_write_direct(sql, params)

    def execute_writescript(self, script: str) -> None:
        """Multi-statement write entry point."""
        if self._serialized_writes and not self.is_write_worker():
            self._enqueue_write("executescript", script)
            return
        self._execute_writescript_direct(script)

    # ── Trace sampling ───────────────────────────────────────────

    def should_trace(self) -> bool:
        """Return True if this operation should be recorded (1 in N sampling)."""
        self._trace_counter += 1
        return self._trace_counter % self._trace_sample_rate == 0

    @property
    def feedback_tracker(self):
        """Lazy-init FeedbackTracker (avoids circular import at module load)."""
        if not hasattr(self, '_feedback_tracker'):
            from project_brain.feedback_tracker import FeedbackTracker
            self._feedback_tracker = FeedbackTracker(self.conn)
        return self._feedback_tracker
