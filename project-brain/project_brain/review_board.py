"""
core/brain/review_board.py — Knowledge Review Board（v7.0）

## 問題

`brain scan` 提取的知識直接寫入 L3，沒有任何人工審查機會。
這導致：
- 已被 revert 的決策仍然存在知識庫
- 錯誤的技術判斷被 AI 學習並複用
- 聯邦知識的「毒化」風險無法被阻擋

## 解法：Staging 區 + 人工審批流程

新知識先進入 `staged_nodes` 暫存表（Staging），不進入 L3 正式圖譜。
人類審查後：
  approve → 移至 L3 正式節點（nodes 表）
  reject  → 標記原因後丟棄（或保留在 staging 供參考）

類比：GitHub 的 Pull Request 流程。

## 生命週期

  AUTO_SCAN / MANUAL_ADD
       ↓
  staged_nodes（status='pending'）
       ↓ brain review list
  人類審查
       ↓
  ┌─────────────────────┐
  │ approve             │ → nodes 表（L3 正式知識）
  │ reject              │ → staged_nodes（status='rejected'，保留記錄）
  │ request_changes     │ → staged_nodes（status='needs_changes'）
  └─────────────────────┘

## 使用方式

    from project_brain.review_board import KnowledgeReviewBoard
    from project_brain.graph import KnowledgeGraph
    from pathlib import Path

    graph = KnowledgeGraph(Path(".brain"))
    krb   = KnowledgeReviewBoard(Path(".brain"), graph)

    # 提交一筆知識到 Staging
    sid = krb.submit("JWT RS256 規則", "必須用非對稱金鑰", kind="Rule",
                     source="brain-scan", submitter="auto")

    # 列出待審知識
    pending = krb.list_pending()

    # 核准 → 移入 L3
    krb.approve(sid, reviewer="ahern", note="確認正確")

    # 拒絕
    krb.reject(sid, reviewer="ahern", reason="已被 revert，不再適用")
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from project_brain.brain_db import BrainDB  # BUG-07 fix: sync brain.db FTS5

logger = logging.getLogger(__name__)

# STAB-06: bump this when schema changes; tracked in schema_meta table
RB_SCHEMA_VERSION = 2

STATUS_PENDING  = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CHANGES  = "needs_changes"


@dataclass
class StagedNode:
    """Staging 區中的待審知識節點"""
    id:          str
    kind:        str
    title:       str
    content:     str
    tags:        str        = ""
    source:      str        = "manual"
    submitter:   str        = "user"
    status:      str        = STATUS_PENDING
    reviewer:    str        = ""
    review_note: str        = ""
    created_at:  str        = ""
    reviewed_at: str        = ""
    l3_node_id:  str        = ""    # 核准後在 L3 的節點 ID
    applicability_condition: str = ""
    invalidation_condition:  str = ""
    # PH3-03: AI 預篩欄位
    ai_recommendation: str  = ""   # "approve" | "review" | "reject" | ""
    ai_confidence:     float = 0.0
    ai_reasoning:      str  = ""
    ai_screened_at:    str  = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def summary_line(self) -> str:
        icons = {STATUS_PENDING: "🟡", STATUS_APPROVED: "✅",
                 STATUS_REJECTED: "❌", STATUS_CHANGES: "🔄"}
        icon = icons.get(self.status, "⬜")
        ts   = self.created_at[:16] if self.created_at else "?"
        base = f"{icon} [{self.id[:8]}] {self.kind:<12} {self.title[:40]:<40}  {ts}"
        # PH3-03: 附加 AI 預篩標籤
        if self.ai_recommendation:
            ai_icons = {"approve": "🤖✅", "review": "🤖⚠️", "reject": "🤖❌"}
            ai_tag = ai_icons.get(self.ai_recommendation, "🤖")
            conf   = f"{self.ai_confidence:.2f}"
            reason = f"  {self.ai_reasoning[:30]}" if self.ai_reasoning else ""
            base  += f"  [{ai_tag} {conf}{reason}]"
        return base


class KnowledgeReviewBoard:
    """
    知識審查委員會（v7.0）— Human-in-the-Loop 知識品質把關。

    所有透過自動化途徑（scan、learn、federation）進入的知識，
    都先存入 staging 暫存區，等待人工審查後才能正式進入 L3。

    手動 `brain add` 的知識預設直接進入 L3（trust_manual=True），
    但可以設定 strict_mode 讓所有知識都經過 Staging。
    """

    def __init__(
        self,
        brain_dir:    Path,
        graph,
        strict_mode:  bool = False,
    ):
        """
        Args:
            brain_dir:   .brain/ 目錄
            graph:       KnowledgeGraph 實例
            strict_mode: True = 連手動 add 也需要審查
        """
        self.brain_dir   = Path(brain_dir)
        self.graph       = graph
        self.strict_mode = strict_mode
        self._db_path    = self.brain_dir / "review_board.db"
        self._conn: Optional[sqlite3.Connection] = None
        self._setup()

    def _conn_(self) -> sqlite3.Connection:
        if self._conn is None:
            try:
                conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                self._conn = conn
            except sqlite3.DatabaseError as exc:
                # STAB-06: graceful error instead of raw stack trace
                logger.error(
                    "review_board.db 無法開啟（%s）。執行 `brain doctor` 查看詳情。",
                    exc,
                )
                raise RuntimeError(
                    f"KnowledgeReviewBoard 資料庫無法開啟：{exc}。"
                    f"執行 `brain doctor` 或刪除 {self._db_path} 後重新初始化。"
                ) from exc
        return self._conn

    def _setup(self) -> None:
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        try:
            conn = self._conn_()
        except RuntimeError:
            raise  # already logged; propagate with user-friendly message

        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS staged_nodes (
                    id           TEXT PRIMARY KEY,
                    kind         TEXT NOT NULL DEFAULT 'Rule',
                    title        TEXT NOT NULL,
                    content      TEXT NOT NULL DEFAULT '',
                    tags         TEXT NOT NULL DEFAULT '',
                    source       TEXT NOT NULL DEFAULT 'manual',
                    submitter    TEXT NOT NULL DEFAULT 'user',
                    status       TEXT NOT NULL DEFAULT 'pending',
                    reviewer     TEXT NOT NULL DEFAULT '',
                    review_note  TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                    reviewed_at  TEXT NOT NULL DEFAULT '',
                    l3_node_id   TEXT NOT NULL DEFAULT '',
                    applicability_condition TEXT NOT NULL DEFAULT '',
                    invalidation_condition  TEXT NOT NULL DEFAULT '',
                    ai_recommendation TEXT NOT NULL DEFAULT '',
                    ai_confidence     REAL NOT NULL DEFAULT 0.0,
                    ai_reasoning      TEXT NOT NULL DEFAULT '',
                    ai_screened_at    TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_staged_status
                    ON staged_nodes(status);
                CREATE INDEX IF NOT EXISTS idx_staged_created
                    ON staged_nodes(created_at);

                -- v8.0: 知識版本歷史（每次 approve 後修改，記錄 diff）
                CREATE TABLE IF NOT EXISTS knowledge_history (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    l3_node_id   TEXT NOT NULL,
                    staged_id    TEXT NOT NULL DEFAULT '',
                    action       TEXT NOT NULL,  -- approved / updated / rejected
                    title        TEXT NOT NULL DEFAULT '',
                    content      TEXT NOT NULL DEFAULT '',
                    reviewer     TEXT NOT NULL DEFAULT '',
                    note         TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_kh_node ON knowledge_history(l3_node_id);

                -- STAB-06: schema version tracking
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                );
            """)
            conn.commit()
        except sqlite3.DatabaseError as exc:
            # STAB-06: DB corrupted or locked — give actionable message
            logger.error(
                "review_board.db 初始化失敗（%s）。可能已損壞。"
                "執行 `brain doctor` 查看詳情，或刪除 %s 重新建立。",
                exc, self._db_path,
            )
            raise RuntimeError(
                f"review_board.db 初始化失敗：{exc}。"
                f"執行 `brain doctor` 或刪除 {self._db_path} 後重新初始化。"
            ) from exc

        # STAB-06: PH3-03 migration with observable logging
        _ai_cols = {
            "ai_recommendation": "TEXT NOT NULL DEFAULT ''",
            "ai_confidence":     "REAL NOT NULL DEFAULT 0.0",
            "ai_reasoning":      "TEXT NOT NULL DEFAULT ''",
            "ai_screened_at":    "TEXT NOT NULL DEFAULT ''",
        }
        existing_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(staged_nodes)").fetchall()
        }
        for col, typedef in _ai_cols.items():
            if col not in existing_cols:
                try:
                    conn.execute(
                        f"ALTER TABLE staged_nodes ADD COLUMN {col} {typedef}"
                    )
                except sqlite3.OperationalError as exc:
                    msg = str(exc).lower()
                    if "duplicate column" in msg or "already exists" in msg:
                        logger.debug("review_board migration: column %s already exists", col)
                    else:
                        logger.warning(
                            "review_board migration: 新增欄位 %s 失敗（%s）。"
                            "執行 `brain doctor` 查看詳情。", col, exc
                        )

        # STAB-06: record schema version
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
            (str(RB_SCHEMA_VERSION),)
        )
        conn.commit()

    # ── 提交（Staging 入口）─────────────────────────────────────

    def submit(
        self,
        title:    str,
        content:  str,
        kind:     str  = "Rule",
        tags:     str  = "",
        source:   str  = "manual",
        submitter: str = "user",
        applicability_condition: str = "",
        invalidation_condition:  str = "",
    ) -> str:
        """
        提交一筆知識到 Staging 暫存區。

        Returns:
            str：staged node ID（可用於後續 approve/reject）

        範例：
            sid = krb.submit(
                "Stripe Webhook 必須冪等",
                "重複觸發時要用 idempotency_key 防止雙扣款",
                kind="Pitfall", source="brain-scan",
                invalidation_condition="如果 Stripe API 版本 >= 2025-XX 支援原生冪等時"
            )
        """
        sid = str(uuid.uuid4())[:16]
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn_()
        conn.execute("""
            INSERT INTO staged_nodes
                (id, kind, title, content, tags, source, submitter,
                 status, created_at, applicability_condition, invalidation_condition)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (sid, kind, title, content, tags, source, submitter,
              STATUS_PENDING, now,
              applicability_condition, invalidation_condition))
        conn.commit()
        logger.info("krb_submit: id=%s kind=%s title=%s", sid[:8], kind, title[:30])
        return sid

    # ── 審查操作 ─────────────────────────────────────────────────

    def approve(
        self,
        staged_id: str,
        reviewer:  str = "human",
        note:      str = "",
    ) -> Optional[str]:
        """
        核准 Staging 節點，移入 L3 正式知識庫。

        Returns:
            str | None：L3 node_id（成功）或 None（不存在）

        範例：
            l3_id = krb.approve("abc12345", reviewer="ahern",
                                note="確認正確，已在生產驗證")
        """
        row = self._get_staged(staged_id)
        if not row:
            return None

        now = datetime.now(timezone.utc).isoformat()

        # v7.0.x 修補：核准前先做語意去重
        # 如果相同 title + 相似 content 已存在 L3，標記為重複並跳過
        existing = self._find_duplicate_in_l3(row["title"], row["content"] or "")
        if existing:
            logger.info(
                "krb_approve_duplicate: staged=%s existing=%s",
                staged_id[:8], existing[:20]
            )
            # 更新狀態為 approved（視為已被現有節點代替）
            self._conn_().execute("""
                UPDATE staged_nodes
                SET status='approved', reviewer=?, review_note=?,
                    reviewed_at=?, l3_node_id=?
                WHERE id=?
            """, (reviewer, f"[重複] 已存在節點：{existing}", now, existing, staged_id))
            self._conn_().commit()
            return existing  # 回傳現有節點的 ID

        # 寫入 L3（使用 add_node 正確的 positional 參數）
        l3_id = f"krb_{staged_id}"
        self.graph.add_node(
            node_id   = l3_id,
            node_type = row["kind"],
            title     = row["title"],
            content   = row["content"],
        )
        node_id = l3_id

        # BUG-07 fix: 同步寫入 brain.db 的 nodes_fts，確保 context.py 全文搜尋可見
        try:
            bdb = BrainDB(self.brain_dir)
            bdb.add_node(
                node_id   = l3_id,
                node_type = row["kind"],
                title     = row["title"],
                content   = row["content"] or "",
            )
        except Exception as _e:
            logger.warning("krb_approve: brain.db FTS 同步失敗（不影響核准）: %s", _e)

        # 設定 Meta-Knowledge
        if row["applicability_condition"] or row["invalidation_condition"]:
            self.graph.set_meta_knowledge(
                f"krb_{staged_id}",
                applicability_condition = row["applicability_condition"],
                invalidation_condition  = row["invalidation_condition"],
            )

        # 更新 Staging 狀態
        self._conn_().execute("""
            UPDATE staged_nodes
            SET status='approved', reviewer=?, review_note=?,
                reviewed_at=?, l3_node_id=?
            WHERE id=?
        """, (reviewer, note, now, f"krb_{staged_id}", staged_id))
        self._conn_().commit()

        # v8.0: 記錄初次核准歷史
        self._conn_().execute("""
            INSERT INTO knowledge_history
                (l3_node_id, staged_id, action, title, content, reviewer, note, created_at)
            VALUES (?, ?, 'approved', ?, ?, ?, ?, ?)
        """, (f"krb_{staged_id}", staged_id, row["title"], (row["content"] or "")[:500],
               reviewer, note, now))
        self._conn_().commit()

        logger.info("krb_approve: staged=%s l3=%s reviewer=%s",
                    staged_id[:8], f"krb_{staged_id}", reviewer)
        return f"krb_{staged_id}"

    def reject(
        self,
        staged_id: str,
        reviewer:  str = "human",
        reason:    str = "",
    ) -> bool:
        """
        拒絕 Staging 節點（保留記錄，不進入 L3）。

        範例：
            krb.reject("abc12345", reviewer="ahern",
                       reason="已被 git revert，不再適用")
        """
        row = self._get_staged(staged_id)
        if not row:
            return False

        now = datetime.now(timezone.utc).isoformat()
        self._conn_().execute("""
            UPDATE staged_nodes
            SET status='rejected', reviewer=?, review_note=?, reviewed_at=?
            WHERE id=?
        """, (reviewer, reason, now, staged_id))
        self._conn_().commit()
        logger.info("krb_reject: staged=%s reviewer=%s", staged_id[:8], reviewer)
        return True

    def request_changes(
        self,
        staged_id: str,
        reviewer:  str = "human",
        note:      str = "",
    ) -> bool:
        """標記為需要修改（status='needs_changes'）"""
        row = self._get_staged(staged_id)
        if not row:
            return False
        now = datetime.now(timezone.utc).isoformat()
        self._conn_().execute("""
            UPDATE staged_nodes
            SET status='needs_changes', reviewer=?, review_note=?, reviewed_at=?
            WHERE id=?
        """, (reviewer, note, now, staged_id))
        self._conn_().commit()
        return True

    def update_approved(
        self,
        l3_node_id:  str,
        new_title:   str = "",
        new_content: str = "",
        reviewer:    str = "human",
        note:        str = "",
    ) -> bool:
        """
        更新已核准進入 L3 的知識（修補）。

        解決 KRB 缺少更新路徑的問題：核准後的知識如果需要修改，
        不需要重新走 submit → approve 流程，可以直接更新並記錄歷史。

        Args:
            l3_node_id:  L3 節點 ID（krb_xxx 格式）
            new_title:   新標題（空字串 = 不修改）
            new_content: 新內容（空字串 = 不修改）
            reviewer:    修改者
            note:        修改說明

        Returns:
            bool：是否成功更新

        範例：
            krb.update_approved(
                "krb_abc12345",
                new_content="更新後的內容，加入了新的邊界條件",
                reviewer="ahern",
                note="技術環境更新，原內容已過時"
            )
        """
        # 讀取現有節點
        existing = self.graph.get_node(l3_node_id)
        if not existing:
            logger.warning("update_approved: node not found: %s", l3_node_id)
            return False

        now           = datetime.now(timezone.utc).isoformat()
        updated_title   = new_title   or existing.get("title", "")
        updated_content = new_content or existing.get("content", "")

        # 更新 L3
        conn = self.graph._conn
        conn.execute("""
            UPDATE nodes
            SET title=?, content=?, updated_at=datetime('now')
            WHERE id=?
        """, (updated_title, updated_content, l3_node_id))
        conn.commit()

        # 記錄歷史
        self._conn_().execute("""
            INSERT INTO knowledge_history
                (l3_node_id, action, title, content, reviewer, note, created_at)
            VALUES (?, 'updated', ?, ?, ?, ?, ?)
        """, (l3_node_id, updated_title, updated_content[:500],
               reviewer, note, now))
        self._conn_().commit()

        logger.info("krb_update: l3_id=%s reviewer=%s", l3_node_id, reviewer)
        return True

    def get_history(self, l3_node_id: str) -> list[dict]:
        """
        取得指定 L3 節點的完整修改歷史（修補）。

        Returns:
            list[dict]：修改記錄，按時間倒序排列

        範例：
            history = krb.get_history("krb_abc12345")
            for h in history:
                print(f"{h['created_at']} {h['action']} by {h['reviewer']}: {h['note']}")
        """
        rows = self._conn_().execute("""
            SELECT * FROM knowledge_history
            WHERE l3_node_id=?
            ORDER BY created_at DESC
        """, (l3_node_id,)).fetchall()
        return [dict(r) for r in rows]

    # ── 查詢 ─────────────────────────────────────────────────────

    def list_pending(self, limit: int = 50) -> list[StagedNode]:
        """列出所有待審節點（status='pending'）"""
        return self._list_by_status(STATUS_PENDING, limit)

    def list_all(
        self,
        status: Optional[str] = None,
        limit:  int = 100,
    ) -> list[StagedNode]:
        """列出 staging 中的節點（可按 status 過濾）"""
        if status:
            return self._list_by_status(status, limit)
        rows = self._conn_().execute(
            "SELECT * FROM staged_nodes ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [self._row_to_staged(r) for r in rows]

    def stats(self) -> dict:
        """回傳 KRB 統計資訊"""
        conn = self._conn_()
        total = conn.execute("SELECT COUNT(*) FROM staged_nodes").fetchone()[0]
        by_status = {
            r["status"]: r["cnt"]
            for r in conn.execute(
                "SELECT status, COUNT(*) as cnt FROM staged_nodes GROUP BY status"
            ).fetchall()
        }
        return {
            "total":   total,
            "pending":  by_status.get(STATUS_PENDING,  0),
            "approved": by_status.get(STATUS_APPROVED, 0),
            "rejected": by_status.get(STATUS_REJECTED, 0),
            "needs_changes": by_status.get(STATUS_CHANGES, 0),
        }

    # ── 內部輔助 ─────────────────────────────────────────────────

    def _find_duplicate_in_l3(self, title: str, content: str) -> str:
        """
        在 L3 中尋找語意重複的知識節點（v7.0.x 修補）。

        檢查邏輯：
        1. 完全相同的 title → 重複
        2. title 相似（Jaccard > 0.7）且 content 重疊 > 60% → 重複

        Returns:
            str：重複節點的 ID，或空字串（無重複）
        """
        # Step 1：精確 title 比對
        row = self.graph._conn.execute(
            "SELECT id FROM nodes WHERE title=? LIMIT 1", (title,)
        ).fetchone()
        if row:
            return row["id"]

        # Step 2：Jaccard title 相似度（字元 bigram）
        def _bigrams(text: str) -> set:
            t = text.lower()
            return {t[i:i+2] for i in range(len(t)-1)} if len(t) > 1 else set()

        title_bg = _bigrams(title)
        if not title_bg:
            return ""

        rows = self.graph._conn.execute(
            "SELECT id, title, content FROM nodes WHERE type NOT IN ('Component')"
        ).fetchall()

        for r in rows:
            candidate_bg = _bigrams(r["title"])
            if not candidate_bg:
                continue
            jaccard = len(title_bg & candidate_bg) / len(title_bg | candidate_bg)
            if jaccard > 0.7:
                # 進一步確認 content 重疊
                c1 = set((content or "").lower().split())
                c2 = set((r["content"] or "").lower().split())
                if c1 and c2:
                    overlap = len(c1 & c2) / max(len(c1), len(c2))
                    if overlap > 0.6:
                        return r["id"]

        return ""

    def _list_by_status(self, status: str, limit: int) -> list[StagedNode]:
        rows = self._conn_().execute(
            "SELECT * FROM staged_nodes WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (status, limit)
        ).fetchall()
        return [self._row_to_staged(r) for r in rows]

    def _get_staged(self, staged_id: str) -> Optional[sqlite3.Row]:
        return self._conn_().execute(
            "SELECT * FROM staged_nodes WHERE id=?", (staged_id,)
        ).fetchone()

    def _row_to_staged(self, row: sqlite3.Row) -> StagedNode:
        d = dict(row)
        return StagedNode(
            id          = d["id"],
            kind        = d["kind"],
            title       = d["title"],
            content     = d["content"],
            tags        = d["tags"],
            source      = d["source"],
            submitter   = d["submitter"],
            status      = d["status"],
            reviewer    = d["reviewer"],
            review_note = d["review_note"],
            created_at  = d["created_at"],
            reviewed_at = d["reviewed_at"],
            l3_node_id  = d["l3_node_id"],
            applicability_condition = d.get("applicability_condition") or "",
            invalidation_condition  = d.get("invalidation_condition")  or "",
            # PH3-03 AI 欄位（舊紀錄可能缺欄位，用 .get 安全存取）
            ai_recommendation = d.get("ai_recommendation") or "",
            ai_confidence     = float(d.get("ai_confidence") or 0.0),
            ai_reasoning      = d.get("ai_reasoning") or "",
            ai_screened_at    = d.get("ai_screened_at") or "",
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
