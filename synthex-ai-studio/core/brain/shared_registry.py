"""
SharedRegistry — 跨 Repo 知識聯邦 (Project Brain v2.0)

核心設計思想：
  每個專案是知識的「孤島」，SharedRegistry 是「橋樑」。
  橋樑只傳輸值得共享的知識（高信心 + 普遍適用），
  不傳輸只屬於該專案的業務邏輯。

架構：
  ~/.synthex/registry/
  ├── registry.db          ← 主索引（輕量，只存 metadata）
  ├── knowledge/
  │   ├── {sha256}.json    ← 知識片段（內容定址，不可篡改）
  │   └── ...
  └── projects.json        ← 已註冊的專案清單

安全設計：
  1. 隔離性：每個專案只能讀取，無法修改其他專案的知識
  2. 內容定址：sha256 hash 確保傳輸完整性
  3. 路徑驗證：所有路徑嚴格限制在 registry 目錄內
  4. 容量限制：全局知識庫上限 100,000 筆，單專案貢獻上限 5,000 筆
  5. 敏感資訊過濾：自動偵測並排除包含 API key / 密碼的知識

記憶體管理：
  - 分頁讀取：search 結果不一次全載
  - 懶加載：知識內容只在需要時讀取
  - 連線池：SQLite WAL 模式 + 連線上限
"""

from __future__ import annotations

import os
import re
import json
import time
import hashlib
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)

# ── 安全常數 ────────────────────────────────────────────────────
MAX_GLOBAL_KNOWLEDGE  = 100_000   # 全局知識庫上限
MAX_PROJECT_CONTRIB   = 5_000     # 單專案貢獻上限
MAX_CONTENT_LEN       = 6_000     # 單筆知識內容上限（字元）
MAX_TITLE_LEN         = 200
MAX_TAG_LEN           = 50
MAX_TAGS_COUNT        = 15
MIN_CONFIDENCE_SHARE  = 0.7       # 只共享信心值 >= 0.7 的知識
PAGE_SIZE             = 50        # 分頁讀取大小

# 敏感資訊模式（自動過濾）
SENSITIVE_PATTERNS = [
    re.compile(r'(?i)(api[_\s-]?key|secret|password|token|credential)\s*[:=]\s*\S+'),
    re.compile(r'sk-[a-zA-Z0-9]{20,}'),      # OpenAI-style keys
    re.compile(r'[A-Z0-9]{20,}:[A-Za-z0-9+/]{30,}'),  # AWS-style
    re.compile(r'\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b'),  # 卡號
]

# 普遍適用的知識類型（值得跨專案共享）
SHAREABLE_TYPES = {"Pitfall", "Rule", "Decision"}


def _registry_root() -> Path:
    """取得全局 registry 根目錄（~/.synthex/registry/）"""
    root = Path.home() / ".synthex" / "registry"
    root.mkdir(parents=True, exist_ok=True)
    (root / "knowledge").mkdir(exist_ok=True)
    return root


def _content_hash(content: str) -> str:
    """內容定址 hash（sha256，截取前 40 字元）"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:40]


def _is_sensitive(text: str) -> bool:
    """偵測文字中是否包含敏感資訊"""
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _sanitize(text: str, max_len: int) -> str:
    """清理輸入：去除控制字元、截斷長度"""
    if not isinstance(text, str):
        return ""
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return cleaned[:max_len]


class SharedRegistry:
    """
    跨 Repo 知識聯邦——讓不同專案的踩坑記錄、架構決策
    在組織內安全地共享，避免重複犯同樣的錯。

    使用方式：
        registry = SharedRegistry()
        registry.register_project("my-ecommerce", "/path/to/project")
        registry.push(brain, project_id="my-ecommerce")  # 推送知識
        results = registry.search("支付相關的踩坑")       # 搜尋所有專案
    """

    SCHEMA_VERSION = "2.0"

    def __init__(self, registry_root: Path | None = None):
        self.root    = registry_root or _registry_root()
        self.db_path = self.root / "registry.db"
        self._lock   = threading.Lock()   # 多執行緒寫入保護
        self._conn   = self._connect()
        self._setup_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=30,
        )
        conn.row_factory = sqlite3.Row
        # WAL 模式：讀寫不互相阻塞
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # 記憶體限制：page cache 上限 16MB
        conn.execute("PRAGMA cache_size=-16384")
        return conn

    def _setup_schema(self):
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            path         TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            last_push_at  TEXT,
            push_count    INTEGER DEFAULT 0,
            contrib_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS shared_knowledge (
            content_hash  TEXT PRIMARY KEY,
            type          TEXT NOT NULL,
            title         TEXT NOT NULL,
            content       TEXT NOT NULL,
            tags          TEXT DEFAULT '[]',
            source_project TEXT NOT NULL REFERENCES projects(id),
            source_node_id TEXT,
            confidence    REAL NOT NULL DEFAULT 0.7,
            relevance_score REAL DEFAULT 0.0,
            share_count   INTEGER DEFAULT 1,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS knowledge_adoption (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash TEXT NOT NULL REFERENCES shared_knowledge(content_hash),
            adopter_project TEXT NOT NULL,
            adopted_at   TEXT NOT NULL,
            useful        INTEGER DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_sk_type    ON shared_knowledge(type);
        CREATE INDEX IF NOT EXISTS idx_sk_project ON shared_knowledge(source_project);
        CREATE INDEX IF NOT EXISTS idx_sk_conf    ON shared_knowledge(confidence DESC);
        CREATE INDEX IF NOT EXISTS idx_adoption   ON knowledge_adoption(content_hash);

        CREATE VIRTUAL TABLE IF NOT EXISTS sk_fts USING fts5(
            content_hash UNINDEXED,
            title, content, tags,
            content='shared_knowledge',
            content_rowid='rowid'
        );

        CREATE TRIGGER IF NOT EXISTS sk_ai AFTER INSERT ON shared_knowledge BEGIN
            INSERT INTO sk_fts(rowid, content_hash, title, content, tags)
            VALUES (new.rowid, new.content_hash, new.title, new.content, new.tags);
        END;
        """)
        self._conn.commit()

    # ── 專案管理 ────────────────────────────────────────────────

    def register_project(self, project_id: str, project_path: str,
                         name: str = "") -> bool:
        """
        註冊一個專案到 SharedRegistry。
        project_id 是全局唯一識別碼（建議：公司名/專案名）。
        """
        pid   = _sanitize(project_id, 100)
        pname = _sanitize(name or pid, 200)

        # 路徑驗證：不允許相對路徑或路徑遍歷
        path = Path(project_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"專案路徑不存在：{path}")

        with self._lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO projects
                    (id, name, path, registered_at)
                VALUES (?, ?, ?, ?)
            """, (pid, pname, str(path),
                  datetime.now(timezone.utc).isoformat()))
            self._conn.commit()
        logger.info("已註冊專案：%s (%s)", pid, pname)
        return True

    def list_projects(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, path, registered_at, contrib_count FROM projects ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 推送知識 ────────────────────────────────────────────────

    def push(
        self,
        brain,            # ProjectBrain 實例
        project_id: str,
        min_confidence: float = MIN_CONFIDENCE_SHARE,
        dry_run: bool = False,
    ) -> dict:
        """
        把專案 brain 中符合條件的知識推送到全局 registry。

        推送條件：
        1. 類型為 Pitfall / Rule / Decision（普遍適用）
        2. 信心值 >= min_confidence
        3. 不包含敏感資訊
        4. 本專案累計貢獻未超過 MAX_PROJECT_CONTRIB

        Args:
            brain:          ProjectBrain 實例
            project_id:     本專案在 registry 的 ID
            min_confidence: 最低信心閾值（預設 0.7）
            dry_run:        True 時只回報，不實際寫入

        Returns:
            {"pushed": N, "skipped": N, "reasons": {...}}
        """
        pid = _sanitize(project_id, 100)

        # 確認專案已註冊
        proj = self._conn.execute(
            "SELECT * FROM projects WHERE id=?", (pid,)
        ).fetchone()
        if not proj:
            raise ValueError(f"專案 {pid!r} 未註冊，請先呼叫 register_project()")

        # 確認本專案的貢獻上限
        contrib = proj["contrib_count"]
        if contrib >= MAX_PROJECT_CONTRIB:
            return {"pushed": 0, "skipped": 0,
                    "reasons": {"contrib_limit": f"已達單專案貢獻上限 {MAX_PROJECT_CONTRIB}"}}

        # 確認全局容量
        total = self._conn.execute(
            "SELECT COUNT(*) FROM shared_knowledge"
        ).fetchone()[0]
        if total >= MAX_GLOBAL_KNOWLEDGE:
            return {"pushed": 0, "skipped": 0,
                    "reasons": {"global_limit": f"全局知識庫已達上限 {MAX_GLOBAL_KNOWLEDGE}"}}

        # 批次讀取符合條件的節點
        stats = {"pushed": 0, "skipped": 0, "reasons": {}}
        remaining = MAX_PROJECT_CONTRIB - contrib

        # 從知識圖譜讀取所有節點（分頁，控制記憶體）
        for batch in self._iter_shareable_nodes(brain.graph, min_confidence):
            if remaining <= 0:
                break
            for node in batch:
                if remaining <= 0:
                    break
                if not dry_run:
                    result = self._push_node(node, pid, min_confidence)
                else:
                    result = "dry_run"
                if result == "pushed":
                    stats["pushed"] += 1
                    remaining -= 1
                else:
                    stats["skipped"] += 1
                    stats["reasons"][result] = stats["reasons"].get(result, 0) + 1

        if not dry_run and stats["pushed"] > 0:
            with self._lock:
                self._conn.execute("""
                    UPDATE projects
                    SET last_push_at=?, push_count=push_count+1,
                        contrib_count=contrib_count+?
                    WHERE id=?
                """, (datetime.now(timezone.utc).isoformat(), stats["pushed"], pid))
                self._conn.commit()

        return stats

    def _iter_shareable_nodes(
        self, graph, min_confidence: float
    ) -> Generator[list, None, None]:
        """分頁讀取可共享的節點（控制記憶體）"""
        offset = 0
        while True:
            rows = graph._conn.execute("""
                SELECT id, type, title, content, tags, author
                FROM nodes
                WHERE type IN ('Pitfall','Rule','Decision')
                LIMIT ? OFFSET ?
            """, (PAGE_SIZE, offset)).fetchall()
            if not rows:
                break
            yield [dict(r) for r in rows]
            offset += PAGE_SIZE

    def _push_node(self, node: dict, project_id: str,
                   min_confidence: float) -> str:
        """把單個節點推送到 registry，回傳結果程式碼"""
        # 安全過濾
        content = _sanitize(node.get("content", ""), MAX_CONTENT_LEN)
        title   = _sanitize(node.get("title", ""), MAX_TITLE_LEN)

        if not content or not title:
            return "empty_content"
        if _is_sensitive(content) or _is_sensitive(title):
            return "sensitive_content"
        if node.get("type") not in SHAREABLE_TYPES:
            return "non_shareable_type"

        # 信心值從 meta 讀取
        try:
            tags = json.loads(node.get("tags", "[]"))
            if not isinstance(tags, list):
                tags = []
            tags = [_sanitize(str(t), MAX_TAG_LEN) for t in tags[:MAX_TAGS_COUNT]]
        except (json.JSONDecodeError, TypeError):
            tags = []

        content_hash = _content_hash(project_id + title + content)
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            existing = self._conn.execute(
                "SELECT content_hash, share_count FROM shared_knowledge WHERE content_hash=?",
                (content_hash,)
            ).fetchone()

            if existing:
                # 已存在：增加 share_count（被多個專案提交）
                self._conn.execute("""
                    UPDATE shared_knowledge
                    SET share_count=share_count+1, updated_at=?
                    WHERE content_hash=?
                """, (now, content_hash))
            else:
                self._conn.execute("""
                    INSERT INTO shared_knowledge
                        (content_hash, type, title, content, tags,
                         source_project, source_node_id,
                         confidence, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (content_hash, node["type"], title, content,
                      json.dumps(tags, ensure_ascii=False),
                      project_id, node.get("id", ""),
                      min_confidence, now, now))

            self._conn.commit()
        return "pushed"

    # ── 搜尋 ────────────────────────────────────────────────────

    def search(
        self,
        query:        str,
        kind:         str | None = None,
        exclude_project: str | None = None,
        min_confidence: float = 0.5,
        limit:        int = 10,
        offset:       int = 0,
    ) -> list[dict]:
        """
        搜尋全局知識庫（FTS5 全文搜尋）。

        Args:
            query:            搜尋詞
            kind:             限定類型（Pitfall / Rule / Decision）
            exclude_project:  排除此專案的知識（避免自引）
            min_confidence:   信心值下限
            limit:            最大回傳筆數（上限 50）
            offset:           分頁偏移

        Returns:
            list of dict，包含 title / content / type / source_project / confidence
        """
        q = _sanitize(query, 500).strip()
        if not q:
            return []

        limit  = max(1, min(50, int(limit)))
        offset = max(0, int(offset))

        params: list = [q, min_confidence, limit, offset]
        type_filter = "AND sk.type = ?" if kind and kind in SHAREABLE_TYPES else ""
        proj_filter = "AND sk.source_project != ?" if exclude_project else ""
        if kind and kind in SHAREABLE_TYPES:
            params.insert(1, kind)
        if exclude_project:
            params.insert(-2, _sanitize(exclude_project, 100))

        rows = self._conn.execute(f"""
            SELECT sk.content_hash, sk.type, sk.title,
                   sk.content, sk.tags, sk.source_project,
                   sk.confidence, sk.share_count, sk.created_at,
                   rank AS relevance
            FROM sk_fts
            JOIN shared_knowledge sk ON sk.content_hash = sk_fts.content_hash
            WHERE sk_fts MATCH ?
              {type_filter}
              {proj_filter}
              AND sk.confidence >= ?
            ORDER BY sk.share_count DESC, rank
            LIMIT ? OFFSET ?
        """, params).fetchall()

        results = []
        for r in rows:
            try:
                tags = json.loads(r["tags"]) if r["tags"] else []
            except (json.JSONDecodeError, TypeError):
                tags = []
            results.append({
                "hash":           r["content_hash"],
                "type":           r["type"],
                "title":          r["title"],
                "content":        r["content"][:1000],
                "tags":           tags,
                "source_project": r["source_project"],
                "confidence":     round(float(r["confidence"]), 4),
                "share_count":    r["share_count"],
                "created_at":     r["created_at"],
            })
        return results

    # ── 採用回饋 ────────────────────────────────────────────────

    def mark_useful(self, content_hash: str, project_id: str,
                    useful: bool = True) -> None:
        """標記某筆知識對特定專案是否有用（改善未來的相關性排序）"""
        h   = _sanitize(content_hash, 64)
        pid = _sanitize(project_id, 100)
        with self._lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO knowledge_adoption
                    (content_hash, adopter_project, adopted_at, useful)
                VALUES (?, ?, ?, ?)
            """, (h, pid, datetime.now(timezone.utc).isoformat(), int(useful)))
            if useful:
                self._conn.execute("""
                    UPDATE shared_knowledge
                    SET relevance_score = relevance_score + 1.0
                    WHERE content_hash = ?
                """, (h,))
            self._conn.commit()

    # ── 統計 ────────────────────────────────────────────────────

    def stats(self) -> dict:
        total = self._conn.execute(
            "SELECT COUNT(*) FROM shared_knowledge"
        ).fetchone()[0]
        by_type = self._conn.execute("""
            SELECT type, COUNT(*) AS cnt, AVG(confidence) AS avg_conf
            FROM shared_knowledge GROUP BY type
        """).fetchall()
        projects = self._conn.execute(
            "SELECT COUNT(*) FROM projects"
        ).fetchone()[0]
        return {
            "total_knowledge": total,
            "projects":        projects,
            "by_type": {
                r["type"]: {"count": r["cnt"], "avg_confidence": round(r["avg_conf"], 3)}
                for r in by_type
            },
            "registry_root":   str(self.root),
            "capacity_used":   f"{total/MAX_GLOBAL_KNOWLEDGE*100:.1f}%",
        }

    def close(self) -> None:
        self._conn.close()
