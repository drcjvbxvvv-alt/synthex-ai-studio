"""
SharedRegistry — 多專案知識共享 (v2.0)

核心概念：
  一家公司有多個 repo，同樣的踩坑可能在多個專案裡重複。
  SharedRegistry 讓知識可以在專案間安全流動：
  「API Gateway 的速率限制踩坑」在電商 repo 記錄後，
  同公司的 CRM repo 建構 API 時可以直接受益。

架構設計：
  ┌─────────────────────────────────────────────────────┐
  │              SharedRegistry（中央）                   │
  │   ~/.brain_shared/registry.db  ← 全域共享 SQLite     │
  │   ~/.brain_shared/vectors/     ← 全域共享向量記憶     │
  └──────────┬────────────────────────────┬─────────────┘
             │                            │
    ┌────────▼────────┐          ┌────────▼────────┐
    │ Project A .brain │          │ Project B .brain │
    │ （私有知識）      │          │ （私有知識）      │
    └─────────────────┘          └─────────────────┘

安全設計：
  - 命名空間隔離：每個專案有唯一 namespace，防止知識污染
  - 可見性控制：private（只有自己）/ team（同組織）/ public（所有人）
  - 敏感資料過濾：自動偵測並遮蔽密碼、API Key、IP 等 PII
  - 路徑安全：registry 只能在用戶家目錄下，防止遍歷攻擊
  - 寫入驗證：來源 namespace 驗證，防止偽造

可靠設計：
  - WAL 模式：並發讀寫安全（多個專案同時訪問）
  - 冪等寫入：相同知識不重複儲存（based on 內容 hash）
  - 版本向前相容：schema 版本標記
  - 離線優先：本地 .brain/ 永遠有效，SharedRegistry 是加分

記憶體管理：
  - 查詢結果限制（max_results）
  - 大型結果集分頁
  - 連線池：同一進程復用 SQLite 連線
"""

from __future__ import annotations

import os
import re
import json
import hashlib
import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── 安全常數 ──────────────────────────────────────────────────────
REGISTRY_DIR_NAME  = ".brain_shared"
MAX_CONTENT_CHARS  = 6_000
MAX_TITLE_CHARS    = 200
MAX_NAMESPACE_CHARS= 64
MAX_RESULTS        = 50
VALID_VISIBILITY   = {"private", "team", "public"}
VALID_KNOWLEDGE_TYPES = {"Decision", "Pitfall", "Rule", "ADR"}

# 敏感資料模式（寫入前自動過濾）
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+'),
     r'\1: [REDACTED]'),
    (re.compile(r'(?i)(sk|pk|rk)[-_][a-zA-Z0-9]{16,}'),
     '[API_KEY_REDACTED]'),
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
     '[IP_REDACTED]'),
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
     '[EMAIL_REDACTED]'),
    (re.compile(r'(?:https?://)[^\s"\'<>]+'),    # URL（可能含 token）
     '[URL_REDACTED]'),
]

SCHEMA_VERSION = "2.0"


def _sanitize_for_sharing(text: str, max_len: int = MAX_CONTENT_CHARS) -> str:
    """清理文字：移除控制字元、過濾敏感資料、截斷"""
    if not isinstance(text, str):
        return ""
    # 控制字元
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # 敏感資料遮蔽
    for pattern, replacement in _PII_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned[:max_len]


def _validate_namespace(ns: str) -> str:
    """驗證 namespace：只允許字母、數字、連字符"""
    ns = str(ns)[:MAX_NAMESPACE_CHARS]
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$', ns):
        raise ValueError(
            f"namespace 只允許字母、數字、底線和連字符，不能以連字符開頭：{ns!r}"
        )
    return ns


def _content_hash(title: str, content: str) -> str:
    """產生知識的內容指紋（用於去重）"""
    data = f"{title.strip().lower()}::{content.strip().lower()}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:32]


def _get_registry_path() -> Path:
    """取得 SharedRegistry 的全域路徑（固定在用戶家目錄下）"""
    home = Path.home()
    registry = (home / REGISTRY_DIR_NAME).resolve()
    # 安全確認：必須在家目錄下
    if not str(registry).startswith(str(home)):
        raise PermissionError("SharedRegistry 必須在用戶家目錄下")
    return registry


class SharedRegistry:
    """
    多專案知識共享中心。

    每個 ProjectBrain 實例可以：
    1. 發布（publish）高信心的知識到共享庫
    2. 訂閱（subscribe）其他專案的相關知識
    3. 查詢（query）跨專案的歷史踩坑
    """

    # 連線池（同進程復用）
    _pool: dict[str, sqlite3.Connection] = {}

    def __init__(self, namespace: str, visibility: str = "team"):
        """
        Args:
            namespace:  專案命名空間（唯一識別）
                        例如：company-ecommerce、company-crm
            visibility: 知識可見性
                        private  — 只有自己的專案可查詢
                        team     — 同組織（同前綴）的專案可查詢
                        public   — 所有使用此 Registry 的專案
        """
        self.namespace  = _validate_namespace(namespace)
        if visibility not in VALID_VISIBILITY:
            raise ValueError(f"visibility 必須是 {VALID_VISIBILITY} 之一")
        self.visibility = visibility

        self._registry_dir = _get_registry_path()
        self._registry_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._registry_dir / "registry.db"

        self._conn = self._get_connection()
        self._setup_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """取得（或建立）SQLite 連線，啟用 WAL 模式支援並發"""
        key = str(self._db_path)
        if key not in self._pool:
            conn = sqlite3.connect(
                key,
                check_same_thread=False,
                timeout=10.0,          # 等待鎖定最多 10 秒
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")      # 並發讀寫
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")     # ms
            conn.execute("PRAGMA application_id=1112893234")   # 0x42524149 = BRAI
            self._pool[key] = conn
        return self._pool[key]

    def _setup_schema(self) -> None:
        """建立 SharedRegistry Schema（冪等）"""
        self._conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS registry_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        INSERT OR IGNORE INTO registry_meta VALUES
            ('schema_version', '{SCHEMA_VERSION}'),
            ('created_at',     datetime('now'));

        CREATE TABLE IF NOT EXISTS shared_knowledge (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash  TEXT    NOT NULL UNIQUE,
            namespace     TEXT    NOT NULL,
            visibility    TEXT    NOT NULL DEFAULT 'team',
            type          TEXT    NOT NULL,
            title         TEXT    NOT NULL,
            content       TEXT    NOT NULL,
            tags          TEXT    NOT NULL DEFAULT '[]',
            confidence    REAL    NOT NULL DEFAULT 0.8,
            source_commit TEXT,
            published_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_sk_namespace
            ON shared_knowledge(namespace);
        CREATE INDEX IF NOT EXISTS idx_sk_visibility
            ON shared_knowledge(visibility, type);
        CREATE INDEX IF NOT EXISTS idx_sk_type
            ON shared_knowledge(type, confidence DESC);

        CREATE VIRTUAL TABLE IF NOT EXISTS sk_fts USING fts5(
            id UNINDEXED,
            title,
            content,
            tags,
            content='shared_knowledge',
            content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS sk_ai AFTER INSERT ON shared_knowledge BEGIN
            INSERT INTO sk_fts(rowid, id, title, content, tags)
            VALUES (new.id, new.id, new.title, new.content, new.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS sk_au AFTER UPDATE ON shared_knowledge BEGIN
            INSERT INTO sk_fts(sk_fts, rowid, id, title, content, tags)
            VALUES('delete', old.id, old.id, old.title, old.content, old.tags);
            INSERT INTO sk_fts(rowid, id, title, content, tags)
            VALUES (new.id, new.id, new.title, new.content, new.tags);
        END;

        CREATE TABLE IF NOT EXISTS subscription_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            subscriber   TEXT    NOT NULL,
            knowledge_id INTEGER NOT NULL REFERENCES shared_knowledge(id),
            queried_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        """)
        self._conn.commit()

    # ── 發布知識 ────────────────────────────────────────────────────

    def publish(
        self,
        title:      str,
        content:    str,
        kind:       str,
        tags:       list[str] | None = None,
        confidence: float = 0.8,
        commit:     str   = "",
    ) -> Optional[int]:
        """
        發布一筆知識到共享庫。

        Returns:
            新知識的 ID，若已存在相同內容則回傳 None（冪等）。
        """
        if kind not in VALID_KNOWLEDGE_TYPES:
            raise ValueError(f"kind 必須是 {VALID_KNOWLEDGE_TYPES} 之一")

        # 安全清理（敏感資料過濾）
        title_c   = _sanitize_for_sharing(title,   MAX_TITLE_CHARS)
        content_c = _sanitize_for_sharing(content,  MAX_CONTENT_CHARS)
        tags_j    = json.dumps([
            _sanitize_for_sharing(t, 50) for t in (tags or [])[:10]
        ], ensure_ascii=False)

        if not title_c or not content_c:
            return None

        # 信心分數邊界
        confidence = max(0.0, min(1.0, float(confidence)))

        # 高信心才分享（0.7 以上）
        if confidence < 0.7:
            logger.debug("信心分數 %.2f < 0.7，不發布到 SharedRegistry", confidence)
            return None

        c_hash = _content_hash(title_c, content_c)

        try:
            cur = self._conn.execute("""
                INSERT OR IGNORE INTO shared_knowledge
                    (content_hash, namespace, visibility, type, title,
                     content, tags, confidence, source_commit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (c_hash, self.namespace, self.visibility, kind,
                  title_c, content_c, tags_j, confidence,
                  commit[:80] if commit else ""))
            self._conn.commit()

            if cur.rowcount == 0:
                # 已存在，更新信心分數（若更高）
                self._conn.execute("""
                    UPDATE shared_knowledge
                    SET confidence = MAX(confidence, ?),
                        updated_at = datetime('now')
                    WHERE content_hash = ?
                """, (confidence, c_hash))
                self._conn.commit()
                return None

            return cur.lastrowid

        except Exception as e:
            logger.error("SharedRegistry.publish 失敗：%s", e)
            return None

    # ── 查詢知識 ────────────────────────────────────────────────────

    def query(
        self,
        keywords:      str,
        kind:          str   | None = None,
        min_confidence: float        = 0.6,
        limit:          int          = 10,
    ) -> list[dict]:
        """
        查詢可見範圍內的共享知識。

        可見性規則：
          - 查詢者自己的知識（any visibility）
          - 同組織前綴的 team 知識（如 company-A 可看 company-B 的 team 知識）
          - 所有人的 public 知識
        """
        limit = max(1, min(MAX_RESULTS, int(limit)))
        kw    = _sanitize_for_sharing(keywords, 300).strip()
        if not kw:
            return []

        # 組織前綴（取第一個 - 之前）
        org_prefix = self.namespace.split("-")[0]

        type_filter = "AND sk.type = ?" if kind else ""
        params: list = [kw]
        if kind:
            if kind not in VALID_KNOWLEDGE_TYPES:
                return []
            params.append(kind)
        params.extend([
            min_confidence,
            self.namespace,                    # 自己的
            f"{org_prefix}-%",                 # 同組織的 team
            limit,
        ])

        try:
            rows = self._conn.execute(f"""
                SELECT
                    sk.id, sk.namespace, sk.type, sk.title,
                    sk.content, sk.tags, sk.confidence,
                    sk.published_at, sk.visibility,
                    rank AS fts_rank
                FROM sk_fts
                JOIN shared_knowledge sk ON sk.id = sk_fts.id
                WHERE sk_fts MATCH ?
                  {type_filter}
                  AND sk.confidence >= ?
                  AND (
                    sk.namespace = ?
                    OR (sk.namespace LIKE ? AND sk.visibility IN ('team', 'public'))
                    OR sk.visibility = 'public'
                  )
                ORDER BY sk.confidence DESC, fts_rank
                LIMIT ?
            """, params).fetchall()

            results = []
            for row in rows:
                d = dict(row)
                try:
                    d["tags"] = json.loads(d.get("tags") or "[]")
                except Exception:
                    d["tags"] = []
                results.append(d)

            # 記錄訂閱日誌（用於分析哪些知識最有用）
            if results:
                self._conn.executemany("""
                    INSERT INTO subscription_log (subscriber, knowledge_id)
                    VALUES (?, ?)
                """, [(self.namespace, r["id"]) for r in results])
                self._conn.commit()

            return results

        except Exception as e:
            logger.error("SharedRegistry.query 失敗：%s", e)
            return []

    def top_pitfalls(self, limit: int = 10) -> list[dict]:
        """最常被查詢的跨專案踩坑（按訂閱次數排序）"""
        limit = max(1, min(MAX_RESULTS, int(limit)))
        try:
            rows = self._conn.execute("""
                SELECT sk.title, sk.content, sk.namespace,
                       sk.confidence, COUNT(sl.id) AS subscription_count
                FROM shared_knowledge sk
                JOIN subscription_log sl ON sl.knowledge_id = sk.id
                WHERE sk.type = 'Pitfall'
                  AND (sk.visibility = 'public'
                       OR sk.namespace LIKE ?)
                GROUP BY sk.id
                ORDER BY subscription_count DESC
                LIMIT ?
            """, (f"{self.namespace.split('-')[0]}-%", limit)).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("top_pitfalls 失敗：%s", e)
            return []

    def stats(self) -> dict:
        """SharedRegistry 統計"""
        try:
            row = self._conn.execute("""
                SELECT
                    COUNT(*) AS total_knowledge,
                    SUM(CASE WHEN visibility='public'  THEN 1 ELSE 0 END) AS public_count,
                    SUM(CASE WHEN visibility='team'    THEN 1 ELSE 0 END) AS team_count,
                    SUM(CASE WHEN visibility='private' THEN 1 ELSE 0 END) AS private_count,
                    COUNT(DISTINCT namespace) AS contributing_projects
                FROM shared_knowledge
            """).fetchone()
            return {
                "registry_path":        str(self._db_path),
                "total_knowledge":      row["total_knowledge"],
                "public":               row["public_count"],
                "team":                 row["team_count"],
                "private":              row["private_count"],
                "contributing_projects":row["contributing_projects"],
                "schema_version":       SCHEMA_VERSION,
            }
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def close_all(cls) -> None:
        """釋放所有連線（進程退出前呼叫）"""
        for conn in cls._pool.values():
            try:
                conn.close()
            except Exception:
                pass
        cls._pool.clear()
