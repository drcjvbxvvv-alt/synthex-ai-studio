"""
core/brain/session_store.py — L1a Session Store（任意 LLM 可用）

## 設計理念

原本的 L1 工作記憶（BrainMemoryBackend）繼承 Anthropic Memory Tool 介面，
導致只有 Claude 能透過 tool_use 機制「原生」讀寫 L1。
Ollama、GPT、Gemini 存取 brain serve 時，L1 完全沉默。

本模組把 L1 拆成兩個獨立層：

  L1a  SessionStore（本檔）
       ─ 純 SQLite key-value，任何程式都能讀寫
       ─ 透過 brain serve 的 /v1/session 端點暴露給所有 LLM
       ─ 支援 TTL（pitfalls/decisions 保留 30 天，progress/notes 僅限當 session）
       ─ 完全不依賴 Anthropic SDK

  L1b  BrainMemoryBackend（memory_tool.py，選填）
       ─ 繼承 Anthropic BetaAbstractMemoryTool
       ─ 讓 Claude 的 tool_use 能呼叫
       ─ 底層讀寫委派給 L1a，保持資料一致

## REST API（由 brain serve 暴露）

  GET  /v1/session                   列出所有當前 session 條目
  GET  /v1/session/<key>             取得單一條目
  POST /v1/session                   寫入條目  { key, value, category?, ttl_days? }
  DELETE /v1/session/<key>           刪除條目
  POST /v1/session/search            搜尋條目  { q: "keyword" }
  GET  /v1/session/categories        列出所有分類及數量
  POST /v1/session/clear             清除當前 session（保留持久化條目）

## 分類與生命週期

  pitfalls   ─ 本次踩坑，保留 30 天
  decisions  ─ 本次決策，保留 30 天
  context    ─ 專案背景，保留 30 天
  progress   ─ 今天做到哪裡，session 結束清空
  notes      ─ 暫時筆記，session 結束清空

## 使用範例

  # 任何程式
  store = SessionStore(brain_dir=Path(".brain"))
  store.set("pitfalls/stripe_webhook", "Webhook 重複觸發，需 idempotency_key")
  entry = store.get("pitfalls/stripe_webhook")
  hits  = store.search("stripe")

  # Ollama 透過 REST
  curl http://localhost:7891/v1/session \\
       -X POST -H 'Content-Type: application/json' \\
       -d '{"key":"pitfalls/stripe","value":"Webhook 需冪等","category":"pitfalls"}'
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── 分類設定 ─────────────────────────────────────────────────
#   persistent=True  → TTL 為 ttl_days 天（跨 session 保留）
#   persistent=False → TTL 為 0（session 結束時清空）

CATEGORY_CONFIG: dict[str, dict] = {
    "pitfalls":  {"persistent": True,  "ttl_days": 30, "label": "踩坑記錄"},
    "decisions": {"persistent": True,  "ttl_days": 30, "label": "架構決策"},
    "context":   {"persistent": True,  "ttl_days": 30, "label": "專案背景"},
    "progress":  {"persistent": False, "ttl_days": 0,  "label": "進度筆記"},
    "notes":     {"persistent": False, "ttl_days": 0,  "label": "臨時筆記"},
}

DEFAULT_CATEGORY = "notes"


@dataclass
class SessionEntry:
    """單一 L1a 條目"""
    key:        str
    value:      str
    category:   str       = DEFAULT_CATEGORY
    session_id: str       = ""
    created_at: str       = ""
    expires_at: str       = ""          # ISO 8601，空字串 = 永不過期
    meta:       dict      = field(default_factory=dict)

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at)
            return datetime.now(timezone.utc) > exp
        except ValueError:
            return False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["expired"] = self.is_expired()
        return d


class SessionStore:
    """
    L1a 工作記憶儲存（任意 LLM 可用，不依賴 Anthropic SDK）

    底層使用 SQLite WAL 模式，讀寫速度 <5ms，
    支援 FTS5 全文搜尋（英文 + 中文子詞搜尋）。
    """

    SCHEMA_VERSION = "1.0"

    def __init__(
        self,
        brain_dir:  Path,
        session_id: str = "",
        auto_expire: bool = True,
    ):
        """
        Args:
            brain_dir:   .brain/ 目錄路徑
            session_id:  當前 session 識別碼（空字串 = 自動產生）
            auto_expire: 啟動時自動清除過期條目
        """
        self.brain_dir  = Path(brain_dir).resolve()
        self.session_id = session_id or self._new_session_id()
        self._db_path   = self.brain_dir / "session_store.db"
        import threading as _thr
        self._local = _thr.local()  # per-thread connections
        self._lock  = _thr.Lock()
        self._last_purge_ts: float = 0.0   # R-5: track periodic cleanup
        self._setup()
        if auto_expire:
            self._purge_expired()

    # ── 初始化 ────────────────────────────────────────────────

    def _new_session_id(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"{ts}_{uuid.uuid4().hex[:6]}"

    def _conn_(self) -> sqlite3.Connection:
        """Per-thread connection (WAL+busy_timeout=5s)"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            c = sqlite3.connect(str(self._db_path), check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=5000")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return self._local.conn

    @contextlib.contextmanager
    def _write_guard(self):
        """DEF-09 fix: cross-process advisory lock for SessionStore writes (Unix).
        Falls back to no-op on Windows (fcntl unavailable).
        """
        depth = getattr(self._local, "_wg_depth", 0)
        self._local._wg_depth = depth + 1
        if depth > 0:
            try:
                yield
            finally:
                self._local._wg_depth -= 1
            return
        try:
            import fcntl
            lf = open(str(self.brain_dir / ".session_write_lock"), "w")
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                self._local._wg_depth -= 1
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
                lf.close()
        except ImportError:
            # Windows: no fcntl, rely on SQLite busy_timeout
            try:
                yield
            finally:
                self._local._wg_depth -= 1

    def _setup(self) -> None:
        """建立 schema（冪等）"""
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        conn = self._conn_()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS session_entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                key         TEXT NOT NULL UNIQUE,
                value       TEXT NOT NULL DEFAULT '',
                category    TEXT NOT NULL DEFAULT 'notes',
                session_id  TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                expires_at  TEXT NOT NULL DEFAULT '',
                meta        TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_session_entries_key
                ON session_entries(key);
            CREATE INDEX IF NOT EXISTS idx_session_entries_category
                ON session_entries(category);
            CREATE INDEX IF NOT EXISTS idx_session_entries_session_id
                ON session_entries(session_id);
            CREATE INDEX IF NOT EXISTS idx_session_entries_expires_at
                ON session_entries(expires_at)
                WHERE expires_at != '';

            CREATE VIRTUAL TABLE IF NOT EXISTS session_entries_fts
                USING fts5(
                    key UNINDEXED,
                    value,
                    category UNINDEXED,
                    content='session_entries',
                    content_rowid='id'
                );

            CREATE TRIGGER IF NOT EXISTS session_entries_ai
                AFTER INSERT ON session_entries BEGIN
                    INSERT INTO session_entries_fts(rowid, key, value, category)
                    VALUES (new.id, new.key, new.value, new.category);
                END;

            CREATE TRIGGER IF NOT EXISTS session_entries_ad
                AFTER DELETE ON session_entries BEGIN
                    INSERT INTO session_entries_fts(session_entries_fts, rowid, key, value, category)
                    VALUES ('delete', old.id, old.key, old.value, old.category);
                END;

            CREATE TRIGGER IF NOT EXISTS session_entries_au
                AFTER UPDATE ON session_entries BEGIN
                    INSERT INTO session_entries_fts(session_entries_fts, rowid, key, value, category)
                    VALUES ('delete', old.id, old.key, old.value, old.category);
                    INSERT INTO session_entries_fts(rowid, key, value, category)
                    VALUES (new.id, new.key, new.value, new.category);
                END;

            CREATE TABLE IF NOT EXISTS session_store_meta (
                k TEXT PRIMARY KEY,
                v TEXT NOT NULL DEFAULT ''
            );

            INSERT OR IGNORE INTO session_store_meta VALUES ('schema_version', '1.0');
        """)
        conn.commit()
        logger.debug("session_store_ready: %s", self._db_path)

    def _purge_expired(self) -> int:
        """BUG-10 fix: also purge non-persistent entries from previous sessions.
        BUG-13 fix: use category filter instead of non-existent 'persistent' column.
        R-5: update _last_purge_ts so periodic callers can back off."""
        self._last_purge_ts = time.time()
        conn = self._conn_()
        now  = datetime.now(timezone.utc).isoformat()
        # Delete entries that have passed their explicit expiry time
        cur1 = conn.execute(
            "DELETE FROM session_entries WHERE expires_at != '' AND expires_at < ?",
            (now,)
        )
        # BUG-13 fix: derive non-persistent categories from CATEGORY_CONFIG
        # (replaces broken 'persistent = 0' which referenced a non-existent column)
        non_persistent = [k for k, v in CATEGORY_CONFIG.items() if not v["persistent"]]
        placeholders   = ",".join("?" * len(non_persistent))
        cur2 = conn.execute(
            f"DELETE FROM session_entries WHERE category IN ({placeholders}) AND session_id != ?",
            non_persistent + [self.session_id],
        )
        deleted = cur1.rowcount + cur2.rowcount
        conn.commit()
        if deleted:
            logger.info("session_store_purged: %d expired/non-persistent entries", deleted)
        return deleted

    # ── 核心讀寫 ──────────────────────────────────────────────

    def set(
        self,
        key:       str,
        value:     str,
        category:  str = DEFAULT_CATEGORY,
        ttl_days:  Optional[int] = None,
        meta:      Optional[dict] = None,
    ) -> SessionEntry:
        """
        寫入或更新一個條目。

        Args:
            key:      唯一識別鍵（建議格式：category/name，如 pitfalls/stripe_001）
            value:    條目內容
            category: 分類（pitfalls/decisions/context/progress/notes）
            ttl_days: 過期天數（None = 使用分類預設值）
            meta:     額外 JSON 中繼資料

        Returns:
            SessionEntry

        範例：
            store.set("pitfalls/jwt_rs256",
                      "JWT 必須用 RS256，HS256 不支援多服務驗證",
                      category="pitfalls")
        """
        cat_cfg  = CATEGORY_CONFIG.get(category, CATEGORY_CONFIG[DEFAULT_CATEGORY])
        now      = datetime.now(timezone.utc)
        now_iso  = now.isoformat()

        # 計算過期時間
        effective_ttl = ttl_days if ttl_days is not None else cat_cfg["ttl_days"]
        if effective_ttl > 0:
            expires_at = (now + timedelta(days=effective_ttl)).isoformat()
        else:
            expires_at = ""  # 空字串 = 永不過期（但 clear_session 時會清除非持久化類別）

        meta_json = json.dumps(meta or {}, ensure_ascii=False)

        # R-5: periodic expiry cleanup (at most once per hour per instance)
        if time.time() - self._last_purge_ts > 3600:
            self._purge_expired()

        conn = self._conn_()
        with self._write_guard():
            conn.execute("""
                INSERT INTO session_entries
                    (key, value, category, session_id, created_at, expires_at, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value      = excluded.value,
                    category   = excluded.category,
                    session_id = excluded.session_id,
                    expires_at = excluded.expires_at,
                    meta       = excluded.meta
            """, (key, value, category, self.session_id, now_iso, expires_at, meta_json))
            conn.commit()

        return SessionEntry(
            key=key, value=value, category=category,
            session_id=self.session_id, created_at=now_iso,
            expires_at=expires_at, meta=meta or {},
        )

    def get(self, key: str) -> Optional[SessionEntry]:
        """
        取得單一條目。不存在或已過期時回傳 None。

        範例：
            entry = store.get("pitfalls/jwt_rs256")
            if entry:
                print(entry.value)
        """
        conn = self._conn_()
        row  = conn.execute(
            "SELECT * FROM session_entries WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        entry = self._row_to_entry(row)
        if entry.is_expired():
            self.delete(key)
            return None
        return entry

    def delete(self, key: str) -> bool:
        """刪除單一條目，回傳是否實際刪除"""
        conn = self._conn_()
        with self._write_guard():
            cur  = conn.execute("DELETE FROM session_entries WHERE key = ?", (key,))
            conn.commit()
        return cur.rowcount > 0

    def list(
        self,
        category: Optional[str] = None,
        session_id: Optional[str] = None,
        include_expired: bool = False,
        limit: int = 100,
    ) -> list[SessionEntry]:
        """
        列出條目。

        Args:
            category:        過濾分類（None = 全部）
            session_id:      過濾 session（None = 全部）
            include_expired: 是否包含已過期條目
            limit:           最多回傳筆數

        範例：
            # 列出本 session 所有踩坑
            pitfalls = store.list(category="pitfalls", session_id=store.session_id)
        """
        now  = datetime.now(timezone.utc).isoformat()
        sql  = "SELECT * FROM session_entries WHERE 1=1"
        params: list = []

        if category:
            sql += " AND category = ?"
            params.append(category)
        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)
        if not include_expired:
            sql += " AND (expires_at = '' OR expires_at > ?)"
            params.append(now)

        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = self._conn_().execute(sql, params).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def search(self, query: str, limit: int = 10) -> list[SessionEntry]:
        """
        全文搜尋（FTS5 + LIKE 雙重搜尋，解決中文子詞問題）。

        Args:
            query: 搜尋關鍵字（支援中英文）
            limit: 最多回傳筆數

        範例：
            results = store.search("stripe webhook")
        """
        now = datetime.now(timezone.utc).isoformat()

        # Step 1: FTS5 精準查詢
        try:
            rows = self._conn_().execute("""
                SELECT e.* FROM session_entries e
                JOIN session_entries_fts f ON f.rowid = e.id
                WHERE session_entries_fts MATCH ?
                  AND (e.expires_at = '' OR e.expires_at > ?)
                ORDER BY rank LIMIT ?
            """, (query, now, limit)).fetchall()
            if rows:
                return [self._row_to_entry(r) for r in rows]
        except Exception:
            pass

        # Step 2: LIKE 模糊搜尋（中文子詞備援）
        seen_ids: set = set()
        results:  list = []
        for word in re.split(r'\s+', query.strip()):
            if not word:
                continue
            pattern = f"%{word}%"
            rows = self._conn_().execute("""
                SELECT * FROM session_entries
                WHERE (key LIKE ? OR value LIKE ?)
                  AND (expires_at = '' OR expires_at > ?)
                LIMIT ?
            """, (pattern, pattern, now, limit)).fetchall()
            for r in rows:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    results.append(self._row_to_entry(r))
            if len(results) >= limit:
                break

        return results[:limit]

    def clear_session(self, session_id: Optional[str] = None) -> int:
        """
        清除指定 session 的非持久化條目（progress/notes）。
        不傳 session_id 時清除當前 session。

        Returns:
            刪除的條目數量
        """
        sid   = session_id or self.session_id
        conn  = self._conn_()
        non_persistent = [k for k, v in CATEGORY_CONFIG.items() if not v["persistent"]]
        placeholders   = ",".join("?" * len(non_persistent))
        with self._write_guard():
            cur = conn.execute(
                f"DELETE FROM session_entries WHERE session_id = ? "
                f"AND category IN ({placeholders})",
                [sid] + non_persistent
            )
            conn.commit()
        return cur.rowcount

    def stats(self) -> dict:
        """回傳 L1a 統計資訊"""
        conn = self._conn_()
        now  = datetime.now(timezone.utc).isoformat()

        total = conn.execute(
            "SELECT COUNT(*) FROM session_entries WHERE expires_at='' OR expires_at>?",
            (now,)
        ).fetchone()[0]

        by_cat = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM session_entries "
            "WHERE expires_at='' OR expires_at>? GROUP BY category",
            (now,)
        ).fetchall()

        return {
            "total":      total,
            "session_id": self.session_id,
            "by_category": {r["category"]: r["cnt"] for r in by_cat},
            "db_path":    str(self._db_path),
        }

    # ── 輔助 ──────────────────────────────────────────────────

    def _row_to_entry(self, row: sqlite3.Row) -> SessionEntry:
        try:
            meta = json.loads(row["meta"] or "{}")
        except (json.JSONDecodeError, TypeError):
            meta = {}
        return SessionEntry(
            key        = row["key"],
            value      = row["value"],
            category   = row["category"],
            session_id = row["session_id"],
            created_at = row["created_at"],
            expires_at = row["expires_at"],
            meta       = meta,
        )

    def list_all(self, limit: int = 100) -> list[SessionEntry]:
        """列出所有活躍條目（不分 session）"""
        return self.list(limit=limit)

    def archive(
        self,
        session_id: str = "",
        output_dir: "Path | None" = None,
        older_than_days: int = 0,
    ) -> "Path | None":
        """FEAT-04: 將當前或指定 session 的條目匯出為 Markdown 檔案。

        Args:
            session_id:       要歸檔的 session（空字串 = 當前 session）
            output_dir:       輸出目錄（預設：.brain/sessions/）
            older_than_days:  清理超過 N 天的歸檔（0 = 不清理）

        Returns:
            輸出檔案路徑，若無條目則回傳 None
        """
        sid = session_id or self.session_id
        output_dir = Path(output_dir) if output_dir else (self.brain_dir / "sessions")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Auto-cleanup old archives
        if older_than_days > 0:
            self._cleanup_archives(output_dir, older_than_days)

        # Get entries for this session
        try:
            rows = self._conn_().execute(
                "SELECT * FROM session_entries WHERE session_id=? ORDER BY created_at ASC",
                (sid,)
            ).fetchall()
        except Exception:
            rows = []

        if not rows:
            return None

        ts       = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{sid}_{ts}.md"
        out_path = output_dir / filename

        lines = [f"# Session Archive: {sid}", f"", f"Archived: {ts}", f"Entries: {len(rows)}", f""]
        by_cat: dict[str, list] = {}
        for row in rows:
            r = dict(row)
            cat = r.get("category", "notes")
            by_cat.setdefault(cat, []).append(r)

        for cat, entries in sorted(by_cat.items()):
            lines.append(f"## {cat}")
            for e in entries:
                lines.append(f"- **{e.get('key','')}**: {e.get('value','')[:300]}")
            lines.append("")

        out_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("session_archived | path=%s entries=%d", out_path, len(rows))
        return out_path

    def _cleanup_archives(self, archive_dir: "Path", older_than_days: int) -> int:
        """FEAT-04: 清理超過指定天數的歸檔檔案"""
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        deleted = 0
        try:
            for f in archive_dir.glob("*.md"):
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    f.unlink()
                    deleted += 1
        except Exception as e:
            logger.debug("_cleanup_archives: %s", e)
        return deleted

    def close(self) -> None:
        """關閉資料庫連線"""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
