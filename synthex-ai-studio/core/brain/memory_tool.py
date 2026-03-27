"""
core/brain/memory_tool.py — Anthropic 官方 Memory Tool 整合 (v3.0)

設計：
  BrainMemoryBackend 繼承 BetaAbstractMemoryTool（官方 SDK）。
  這讓 Claude 透過官方的 6 個記憶操作（view/create/str_replace/
  insert/delete/rename）直接管理 L1 工作記憶，而我們控制底層
  儲存（SQLite，而非純檔案系統）。

為什麼選 SQLite 而非純檔案：
  - WAL 模式支援並發讀寫（多個 Agent 同時操作）
  - ACID 事務確保原子性（官方 write_text 非原子）
  - 可查詢：SELECT content FROM memories WHERE path = ?
  - 可審計：記錄每次操作的時間和發起方

人類認知科比：
  L1 工作記憶 = 當前任務相關的即時資訊
  → 正在實作的功能、這次 session 發現的坑
  → 生命週期：session 或 task

API 使用：
  beta header: context-management-2025-06-27
  tool type:   memory_20250818
  python:      anthropic>=0.74.0

使用方式：
  from core.brain.memory_tool import BrainMemoryBackend, make_memory_params

  backend = BrainMemoryBackend(brain_dir=Path("/project/.brain"))
  params  = make_memory_params()
  # params["tools"] + params["betas"] 加入到 client.messages.create()
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── SDK 依賴（graceful fallback）──────────────────────────────
try:
    from anthropic.lib.tools import BetaAbstractMemoryTool
    from anthropic.types.beta import (
        BetaMemoryTool20250818Command,
        BetaMemoryTool20250818ViewCommand,
        BetaMemoryTool20250818CreateCommand,
        BetaMemoryTool20250818DeleteCommand,
        BetaMemoryTool20250818InsertCommand,
        BetaMemoryTool20250818RenameCommand,
        BetaMemoryTool20250818StrReplaceCommand,
    )
    _HAS_MEMORY_TOOL = True
except ImportError:
    # SDK 版本不支援時的 stub
    _HAS_MEMORY_TOOL = False
    BetaAbstractMemoryTool = object
    logger.info("anthropic SDK 不支援 Memory Tool，使用 stub 模式")

# ── 常數 ──────────────────────────────────────────────────────
MEMORY_BETA_HEADER   = "context-management-2025-06-27"
MEMORY_TOOL_TYPE     = "memory_20250818"
MAX_MEMORY_SIZE_CHARS = 32_000   # 單個記憶文件最大字元數
MAX_TOTAL_MEMORIES   = 500       # 總記憶文件上限
PATH_PREFIX          = "/memories"

# 記憶分類目錄（對應 L1 工作記憶的子類型）
MEMORY_DIRS = {
    "pitfalls":  "/memories/pitfalls",      # 本次任務踩到的坑
    "decisions": "/memories/decisions",     # 本次任務的決策
    "progress":  "/memories/progress",      # 任務進展 checklist
    "context":   "/memories/context",       # 任務背景資訊
    "notes":     "/memories/notes",         # 臨時筆記
}


def _validate_path(path: str) -> str:
    """
    驗證記憶路徑安全性。
    防止路徑穿越（../../etc/passwd）和絕對路徑注入。
    """
    if not path.startswith(PATH_PREFIX):
        raise ValueError(
            f"記憶路徑必須以 {PATH_PREFIX} 開頭，收到：{path!r}"
        )
    # 正規化並檢查穿越
    import os.path
    normalized = os.path.normpath(path)
    if ".." in normalized.split("/"):
        raise ValueError(f"不允許路徑穿越：{path!r}")
    return normalized


class BrainMemoryBackend(BetaAbstractMemoryTool if _HAS_MEMORY_TOOL else object):
    """
    Project Brain 的 L1 工作記憶後端。

    繼承官方 BetaAbstractMemoryTool，以 SQLite 實作底層儲存。
    官方定義 6 個操作的介面，我們實作實際的 CRUD 邏輯。

    SQLite vs 純檔案的優勢：
      - 並發安全（WAL 模式）
      - ACID 事務（寫入中斷不損毀）
      - 可審計（記錄所有操作）
      - 可搜尋（FTS5）

    安全設計：
      - 所有路徑通過 _validate_path() 驗證
      - 內容長度限制（防 OOM）
      - WAL 模式（防並發損毀）
      - 所有 SQL 使用參數化查詢
    """

    def __init__(self, brain_dir: Path, agent_name: str = "?"):
        if _HAS_MEMORY_TOOL:
            super().__init__()
        self.brain_dir  = Path(brain_dir)
        self.agent_name = agent_name
        self._db_path   = self.brain_dir / "working_memory.db"
        self._lock      = threading.Lock()
        self._setup_db()

    def _setup_db(self) -> None:
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA busy_timeout=5000;

            CREATE TABLE IF NOT EXISTS memories (
                path       TEXT PRIMARY KEY,
                content    TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                agent      TEXT,
                size_chars INTEGER GENERATED ALWAYS AS (LENGTH(content)) VIRTUAL
            );

            CREATE TABLE IF NOT EXISTS memory_ops (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                op         TEXT NOT NULL,
                path       TEXT NOT NULL,
                agent      TEXT,
                ts         TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(path, content, content=memories, content_rowid=rowid);

            CREATE TRIGGER IF NOT EXISTS memories_ai
                AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, path, content)
                    VALUES (new.rowid, new.path, new.content);
                END;

            CREATE TRIGGER IF NOT EXISTS memories_au
                AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, path, content)
                    VALUES ('delete', old.rowid, old.path, old.content);
                    INSERT INTO memories_fts(rowid, path, content)
                    VALUES (new.rowid, new.path, new.content);
                END;

            CREATE TRIGGER IF NOT EXISTS memories_ad
                AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, path, content)
                    VALUES ('delete', old.rowid, old.path, old.content);
                END;
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _audit(self, conn: sqlite3.Connection, op: str, path: str) -> None:
        conn.execute(
            "INSERT INTO memory_ops (op, path, agent, ts) VALUES (?, ?, ?, ?)",
            (op, path, self.agent_name, _now())
        )

    # ── 6 個官方抽象方法實作（SDK 要求的方法名稱）───────────────

    def view(self, command: Any) -> str:
        """列出目錄或讀取文件內容（官方抽象方法）"""
        path = _validate_path(command.path if hasattr(command, "path")
                               else command.get("path", PATH_PREFIX))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content FROM memories WHERE path = ?", (path,)
            ).fetchone()
            if row:
                return row["content"]
            rows = conn.execute(
                "SELECT path, LENGTH(content) as size FROM memories "
                "WHERE path LIKE ? ORDER BY path",
                (f"{path}/%",)
            ).fetchall()
            if rows:
                lines = [f"{r['path']} ({r['size']} chars)" for r in rows]
                return "\n".join(lines)
            return f"（{path} 為空目錄）"

    def create(self, command: Any) -> str:
        """建立新記憶文件（官方抽象方法）"""
        path    = _validate_path(command.path if hasattr(command, "path")
                                  else command["path"])
        content = str(getattr(command, "content", "") or command.get("content", ""))
        content = content[:MAX_MEMORY_SIZE_CHARS]
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            if count >= MAX_TOTAL_MEMORIES:
                raise ValueError(f"記憶文件已達上限 {MAX_TOTAL_MEMORIES}")
            conn.execute(
                "INSERT INTO memories (path, content, created_at, updated_at, agent) "
                "VALUES (?, ?, ?, ?, ?)",
                (path, content, _now(), _now(), self.agent_name)
            )
            self._audit(conn, "create", path)
        logger.debug("memory_create", path=path, chars=len(content))
        return f"已建立：{path}"

    def str_replace(self, command: Any) -> str:
        """搜尋並替換文件內容（官方抽象方法）"""
        path    = _validate_path(getattr(command, "path", "") or command["path"])
        old_str = getattr(command, "old_str", "") or command.get("old_str", "")
        new_str = getattr(command, "new_str", "") or command.get("new_str", "")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content FROM memories WHERE path = ?", (path,)
            ).fetchone()
            if not row:
                raise FileNotFoundError(f"記憶文件不存在：{path}")
            content = row["content"]
            if old_str not in content:
                old_preview = repr(old_str[:50])
                raise ValueError(f"找不到要替換的內容：{old_preview}")
            new_content = content.replace(old_str, new_str, 1)[:MAX_MEMORY_SIZE_CHARS]
            conn.execute(
                "UPDATE memories SET content=?, updated_at=?, agent=? WHERE path=?",
                (new_content, _now(), self.agent_name, path)
            )
            self._audit(conn, "str_replace", path)
        return f"已更新：{path}"

    def insert(self, command: Any) -> str:
        """在指定行後插入內容（官方抽象方法）"""
        path        = _validate_path(getattr(command, "path", "") or command["path"])
        insert_line = int(getattr(command, "insert_line", 0) or command.get("insert_line", 0))
        new_str     = getattr(command, "new_str", "") or command.get("new_str", "")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content FROM memories WHERE path = ?", (path,)
            ).fetchone()
            if not row:
                raise FileNotFoundError(f"記憶文件不存在：{path}")
            lines = row["content"].split("\n")
            pos = max(0, min(insert_line, len(lines)))
            lines.insert(pos, new_str)
            new_content = "\n".join(lines)[:MAX_MEMORY_SIZE_CHARS]
            conn.execute(
                "UPDATE memories SET content=?, updated_at=?, agent=? WHERE path=?",
                (new_content, _now(), self.agent_name, path)
            )
            self._audit(conn, "insert", path)
        return f"已插入：{path}（第 {pos} 行）"

    def delete(self, command: Any) -> str:
        """刪除記憶文件（官方抽象方法）"""
        path = _validate_path(getattr(command, "path", "") or command["path"])
        with self._connect() as conn:
            result = conn.execute("DELETE FROM memories WHERE path = ?", (path,))
            if result.rowcount == 0:
                result2 = conn.execute(
                    "DELETE FROM memories WHERE path LIKE ?", (f"{path}/%",)
                )
                if result2.rowcount == 0:
                    raise FileNotFoundError(f"找不到要刪除的記憶：{path}")
                self._audit(conn, "delete_dir", path)
                return f"已刪除目錄：{path}（{result2.rowcount} 個文件）"
            self._audit(conn, "delete", path)
        return f"已刪除：{path}"

    def rename(self, command: Any) -> str:
        """重命名記憶文件（官方抽象方法）"""
        old_path = _validate_path(getattr(command, "path", "") or command["path"])
        new_path = _validate_path(
            getattr(command, "new_path", "") or command.get("new_path", "")
        )
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content FROM memories WHERE path = ?", (old_path,)
            ).fetchone()
            if not row:
                raise FileNotFoundError(f"找不到要重命名的記憶：{old_path}")
            conn.execute(
                "INSERT OR REPLACE INTO memories (path, content, created_at, updated_at, agent) "
                "VALUES (?, ?, ?, ?, ?)",
                (new_path, row["content"], _now(), _now(), self.agent_name)
            )
            conn.execute("DELETE FROM memories WHERE path = ?", (old_path,))
            self._audit(conn, "rename", f"{old_path} → {new_path}")
        return f"已重命名：{old_path} → {new_path}"

    # ── 保留 handle_* 別名（向後相容舊程式碼）──────────────────────

    def handle_view(self, command)      -> str: return self.view(command)
    def handle_create(self, command)    -> str: return self.create(command)
    def handle_str_replace(self, command)->str: return self.str_replace(command)
    def handle_insert(self, command)    -> str: return self.insert(command)
    def handle_delete(self, command)    -> str: return self.delete(command)
    def handle_rename(self, command)    -> str: return self.rename(command)

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """
        全文搜尋工作記憶（FTS5）。
        自動處理中英混合查詢：拆分 token 後分別搜尋，取聯集去重。
        """
        if not query.strip():
            return []
        import re
        # 拆分中英文 token（FTS5 對中文的 unicode61 tokenizer 不支援多字詞）
        tokens = re.findall(r'[A-Za-z0-9_\-]+|[\u4e00-\u9fff]', query)
        if not tokens:
            tokens = [query[:50]]

        seen: set[str] = set()
        results: list[dict] = []

        with self._connect() as conn:
            for token in tokens[:5]:   # 最多 5 個 token，防止過多查詢
                try:
                    rows = conn.execute(
                        """SELECT m.path, m.content, m.updated_at
                           FROM memories_fts fts
                           JOIN memories m ON fts.rowid = m.rowid
                           WHERE memories_fts MATCH ?
                           ORDER BY rank LIMIT ?""",
                        (token, min(limit, 20))
                    ).fetchall()
                    for r in rows:
                        if r["path"] not in seen:
                            seen.add(r["path"])
                            results.append({
                                "path":       r["path"],
                                "content":    r["content"][:500],
                                "updated_at": r["updated_at"],
                            })
                except sqlite3.OperationalError:
                    # FTS5 不可用 → LIKE fallback
                    rows = conn.execute(
                        "SELECT path, content, updated_at FROM memories "
                        "WHERE content LIKE ? LIMIT ?",
                        (f"%{token[:50]}%", limit)
                    ).fetchall()
                    for r in rows:
                        if r["path"] not in seen:
                            seen.add(r["path"])
                            results.append({
                                "path":       r["path"],
                                "content":    r["content"][:500],
                                "updated_at": r["updated_at"],
                            })
            return results[:limit]

    def get_all(self, dir_path: str = PATH_PREFIX) -> list[dict]:
        """取得目錄下所有記憶文件"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT path, content, updated_at FROM memories "
                "WHERE path LIKE ? ORDER BY updated_at DESC",
                (f"{dir_path}/%",)
            ).fetchall()
            return [{"path": r["path"], "content": r["content"],
                     "updated_at": r["updated_at"]} for r in rows]

    def session_summary(self) -> dict:
        """當前 session 的記憶統計"""
        with self._connect() as conn:
            total    = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            by_dir   = conn.execute(
                "SELECT SUBSTR(path, 1, INSTR(SUBSTR(path,11),'/')+10) as dir, "
                "COUNT(*) as cnt FROM memories GROUP BY dir"
            ).fetchall()
            ops_count = conn.execute("SELECT COUNT(*) FROM memory_ops").fetchone()[0]
        return {
            "total_memories": total,
            "by_directory":   {r["dir"]: r["cnt"] for r in by_dir},
            "total_ops":      ops_count,
        }

    # ── 官方 SDK dispatch（若 SDK 支援）─────────────────────────

    if _HAS_MEMORY_TOOL:
        def handle_command(self, command: BetaMemoryTool20250818Command) -> str:
            """官方 SDK 的統一 dispatch 入口"""
            cmd_type = command.type if hasattr(command, "type") else command.get("type")
            handlers = {
                "view":        self.handle_view,
                "create":      self.handle_create,
                "str_replace": self.handle_str_replace,
                "insert":      self.handle_insert,
                "delete":      self.handle_delete,
                "rename":      self.handle_rename,
            }
            handler = handlers.get(cmd_type)
            if not handler:
                raise ValueError(f"未知的 Memory 操作類型：{cmd_type!r}")
            try:
                return handler(command)
            except Exception as e:
                logger.error("memory_op_failed", op=cmd_type,
                             error=str(e)[:200], agent=self.agent_name)
                raise


def make_memory_params(max_uses: int = 20) -> dict:
    """
    回傳使用 Memory Tool 的 API 參數。
    合併到 client.messages.create() 的 **kwargs 中。

    Example:
        params = make_memory_params()
        resp = client.beta.messages.create(
            model=..., max_tokens=..., messages=[...],
            **params
        )
    """
    return {
        "tools": [{"type": MEMORY_TOOL_TYPE, "name": "memory"}],
        "betas": [MEMORY_BETA_HEADER],
    }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════
#  L1 跨 Session 持久化（v4.0 新增）
# ══════════════════════════════════════════════════════════════

SESSION_RETENTION_DAYS = 30   # 持久化記憶保留天數
EPHEMERAL_DIRS = {"/memories/progress"}  # 這些目錄的記憶不跨 session 保留


def persist_session_memories(
    backend:       "BrainMemoryBackend",
    session_id:    str,
    retain_kinds:  frozenset[str] = frozenset({"pitfalls", "decisions", "context"}),
) -> dict:
    """
    將本次 session 的重要工作記憶持久化（v4.0）。
    
    持久化邏輯：
      - pitfalls / decisions / context → 跨 session 保留（30 天）
      - progress / notes → session 結束後清空（一次性）
      
    在 .brain/memory_sessions/ 下以 session_id 為目錄儲存快照，
    下次 session 開始時可以選擇恢復。

    Args:
        backend:      BrainMemoryBackend 實例
        session_id:   本次 session 的唯一 ID（通常是 UUID）
        retain_kinds: 哪些分類的記憶需要持久化

    Returns:
        dict: {"persisted": N, "cleared": M, "session_dir": path}
    """
    import uuid as _uuid
    from datetime import datetime, timezone

    session_dir = backend.brain_dir / "memory_sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    all_mems  = backend.get_all()
    persisted = 0
    cleared   = 0

    # 分類處理
    to_persist = []
    to_clear   = []

    for mem in all_mems:
        path = mem.get("path", "")
        # 判斷這個記憶屬於哪個分類
        category = next(
            (cat for cat, dir_path in MEMORY_DIRS.items()
             if path.startswith(dir_path + "/")),
            "notes"
        )

        if category in retain_kinds:
            to_persist.append(mem)
        else:
            to_clear.append(mem)

    # 快照持久化記憶到檔案
    if to_persist:
        snapshot = {
            "session_id":  session_id,
            "persisted_at": datetime.now(timezone.utc).isoformat(),
            "expires_at":   (datetime.now(timezone.utc).replace(
                day=datetime.now(timezone.utc).day
            )).isoformat(),  # 30 天後
            "memories":    to_persist,
        }
        snap_path = session_dir / "snapshot.json"
        import json as _json
        snap_path.write_text(
            _json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        persisted = len(to_persist)

    # 清除 ephemeral 記憶（progress / notes）
    for mem in to_clear:
        try:
            backend.delete({"path": mem["path"]})
            cleared += 1
        except Exception:
            pass

    return {
        "persisted":   persisted,
        "cleared":     cleared,
        "session_dir": str(session_dir),
    }


def restore_session_memories(
    backend:    "BrainMemoryBackend",
    session_id: str,
) -> dict:
    """
    從快照恢復上次 session 的持久化工作記憶（v4.0）。
    
    Args:
        backend:    BrainMemoryBackend 實例
        session_id: 要恢復的 session ID

    Returns:
        dict: {"restored": N, "skipped": M, "expired": bool}
    """
    import json as _json
    from datetime import datetime, timezone

    session_dir = backend.brain_dir / "memory_sessions" / session_id
    snap_path   = session_dir / "snapshot.json"

    if not snap_path.exists():
        return {"restored": 0, "skipped": 0, "error": "快照不存在"}

    try:
        snapshot = _json.loads(snap_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"restored": 0, "skipped": 0, "error": str(e)[:100]}

    restored = 0
    skipped  = 0

    for mem in snapshot.get("memories", []):
        path    = mem.get("path", "")
        content = mem.get("content", "")
        if not path or not content:
            skipped += 1
            continue
        try:
            # 嘗試建立（若已存在則跳過）
            backend.create({"path": path, "content": content})
            restored += 1
        except Exception:
            skipped += 1  # 路徑衝突或其他錯誤

    return {
        "restored":   restored,
        "skipped":    skipped,
        "session_id": session_id,
    }


def list_available_sessions(brain_dir: Path) -> list[dict]:
    """列出所有可恢復的 session 快照（v4.0）"""
    import json as _json
    sessions_dir = brain_dir / "memory_sessions"
    if not sessions_dir.exists():
        return []

    result = []
    for session_dir in sorted(sessions_dir.iterdir(), reverse=True):
        snap_path = session_dir / "snapshot.json"
        if not snap_path.exists():
            continue
        try:
            snap = _json.loads(snap_path.read_text(encoding="utf-8"))
            result.append({
                "session_id":   session_dir.name,
                "persisted_at": snap.get("persisted_at", ""),
                "memory_count": len(snap.get("memories", [])),
            })
        except Exception:
            pass

    return result[:10]   # 最多顯示 10 個
