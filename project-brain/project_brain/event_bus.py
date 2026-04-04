"""
core/brain/event_bus.py — 事件驅動知識更新匯流排（v8.0）

## 設計哲學

Project Brain 的根本問題之一是「被動記憶」：
只有人呼叫 `brain scan`，才會學習新知識。

BrainEventBus 解決這個問題，讓外部事件（git commit、部署、檔案變更）
自動觸發知識更新，不需要人工介入。

## 架構

事件持久化到 `.brain/events.db`（SQLite），確保重啟後不遺漏。
Handler 是 Python 函數，通過 `@bus.on("git.commit")` 裝飾器註冊。
不依賴 Redis / Kafka，本地 SQLite 輪詢即可滿足個人和小團隊使用場景。

## 支援的事件類型

- `git.commit`    — git commit 完成（由 post-commit hook 觸發）
- `git.push`      — git push 完成
- `file.change`   — 監控目錄有檔案變更
- `deploy.before` — 部署前（手動呼叫）
- `deploy.after`  — 部署後（手動呼叫）
- `brain.scan`    — brain scan 完成
- `brain.learn`   — brain learn 完成

## 使用方式

    from project_brain.event_bus import BrainEventBus

    bus = BrainEventBus(brain_dir=Path(".brain"))

    @bus.on("git.commit")
    def on_commit(payload):
        print(f"新 commit：{payload['hash']}")

    # 觸發事件
    bus.emit("git.commit", {"hash": "abc123", "message": "Fix bug"})
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class BrainEvent:
    """單一事件記錄"""
    id:         int
    ts:         str
    event_type: str
    payload:    dict = field(default_factory=dict)
    processed:  bool = False


class BrainEventBus:
    """
    輕量事件匯流排（v8.0）。

    特性：
    - 事件持久化到 SQLite（重啟不遺漏）
    - 裝飾器式 handler 註冊
    - 執行緒安全（Lock 保護 handler 列表）
    - 自動重試失敗的 handler（最多 3 次）
    """

    VALID_EVENTS = {
        "git.commit", "git.push",
        "file.change",
        "deploy.before", "deploy.after",
        "brain.scan", "brain.learn",
    }

    def __init__(self, brain_dir: Path):
        self.brain_dir = Path(brain_dir)
        self._db       = self.brain_dir / "events.db"
        self._handlers: dict[str, list[Callable]] = {}
        self._lock     = threading.Lock()
        self._setup_db()

    # ── 公開 API ──────────────────────────────────────────────────────

    def on(self, event_type: str) -> Callable:
        """
        裝飾器：註冊事件 handler。

        用法：
            @bus.on("git.commit")
            def on_commit(payload: dict):
                print(f"Hash: {payload['hash']}")
        """
        def decorator(fn: Callable) -> Callable:
            with self._lock:
                self._handlers.setdefault(event_type, []).append(fn)
            logger.debug("EventBus: registered handler %s for %s", fn.__name__, event_type)
            return fn
        return decorator

    def register(self, event_type: str, fn: Callable) -> None:
        """直接登記 handler（非裝飾器版）"""
        with self._lock:
            self._handlers.setdefault(event_type, []).append(fn)

    def emit(self, event_type: str, payload: dict | None = None) -> int:
        """
        觸發事件。

        1. 持久化到 events.db
        2. 同步執行所有已登記的 handler
        3. 記錄失敗（不拋出，確保不阻斷主流程）

        Returns:
            int: 成功執行的 handler 數量
        """
        payload = payload or {}
        event_id = self._persist(event_type, payload)
        return self._dispatch(event_id, event_type, payload)

    def recent(self, event_type: str = "", limit: int = 20) -> list[BrainEvent]:
        """查詢最近事件"""
        conn = self._conn()
        if event_type:
            rows = conn.execute(
                "SELECT * FROM brain_events WHERE event_type=? ORDER BY ts DESC LIMIT ?",
                (event_type, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM brain_events ORDER BY ts DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def install_git_hook(self, workdir: Path | str) -> bool:
        """
        安裝 git post-commit hook，讓每次 commit 後自動觸發 brain learn。

        Args:
            workdir: 專案目錄

        Returns:
            bool: 是否成功安裝
        """
        git_dir = Path(workdir) / ".git"
        if not git_dir.exists():
            logger.warning("install_git_hook: %s 不是 git 倉庫", workdir)
            return False

        hook_path = git_dir / "hooks" / "post-commit"
        brain_path = Path(__file__).parent.parent.parent / "brain.py"

        hook_content = f"""#!/bin/sh
# Project Brain auto-learn hook (installed by brain install-hooks)
# 每次 git commit 後自動學習新知識

WORKDIR="$(git rev-parse --show-toplevel)"
BRAIN="{brain_path}"

if [ -f "$BRAIN" ]; then
    python "$BRAIN" learn --commit HEAD --workdir "$WORKDIR" 2>&1 | head -5
fi
"""
        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)
        logger.info("EventBus: git hook installed at %s", hook_path)
        return True

    # ── 內部實作 ──────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self._db), check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=3000")
        return c

    def _setup_db(self) -> None:
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS brain_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT NOT NULL DEFAULT (datetime('now')),
                event_type TEXT NOT NULL,
                payload    TEXT NOT NULL DEFAULT '{}',
                processed  INTEGER NOT NULL DEFAULT 0,
                error      TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_events_type ON brain_events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_ts   ON brain_events(ts DESC);
        """)
        conn.commit()

    def _persist(self, event_type: str, payload: dict) -> int:
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO brain_events(event_type, payload) VALUES(?,?)",
            (event_type, json.dumps(payload, ensure_ascii=False))
        )
        conn.commit()
        return cur.lastrowid

    def _dispatch(self, event_id: int, event_type: str, payload: dict) -> int:
        """
        在背景執行緒中執行所有 handler（v8.1 修補）。

        問題：舊版同步 retry 會阻塞 emit()，慢 handler（如 brain learn）
        會讓整個事件匯流排卡住。

        修補：每個 handler 在獨立的 daemon 執行緒中執行，
        主執行緒立即返回。失敗記錄到 events.db。
        """
        with self._lock:
            handlers = list(self._handlers.get(event_type, []) +
                            self._handlers.get("*", []))  # wildcard handlers

        if not handlers:
            self._conn().execute(
                "UPDATE brain_events SET processed=1 WHERE id=?", (event_id,)
            ).connection.commit()
            return 0

        import concurrent.futures
        results = {"success": 0}

        def _run_handler(handler, payload, event_id, attempt=0):
            """在背景執行緒執行單一 handler，失敗最多重試 2 次。"""
            try:
                handler(payload)
                results["success"] += 1
            except Exception as e:
                if attempt < 2:
                    import time; time.sleep(0.5 * (attempt + 1))
                    _run_handler(handler, payload, event_id, attempt + 1)
                else:
                    logger.error("EventBus handler %s failed: %s", handler.__name__, e)
                    try:
                        self._conn().execute(
                            "UPDATE brain_events SET error=? WHERE id=?",
                            (str(e)[:200], event_id)
                        ).connection.commit()
                    except Exception as _e:
                        logger.debug("event error update failed", exc_info=True)

        # 每個 handler 在獨立 daemon 執行緒執行（不阻塞主執行緒）
        threads = []
        for handler in handlers:
            t = threading.Thread(
                target=_run_handler,
                args=(handler, payload, event_id),
                daemon=True,
                name=f"brain-event-{handler.__name__}",
            )
            t.start()
            threads.append(t)

        # 標記事件已發送（handler 在背景繼續執行）
        try:
            self._conn().execute(
                "UPDATE brain_events SET processed=1 WHERE id=?", (event_id,)
            ).connection.commit()
        except Exception as _e:
            logger.debug("event processed mark failed", exc_info=True)

        return len(handlers)  # 返回啟動的 handler 數，不等待完成

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> BrainEvent:
        return BrainEvent(
            id         = row["id"],
            ts         = row["ts"],
            event_type = row["event_type"],
            payload    = json.loads(row["payload"] or "{}"),
            processed  = bool(row["processed"]),
        )
