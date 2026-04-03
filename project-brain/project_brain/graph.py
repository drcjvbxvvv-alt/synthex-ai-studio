"""
KnowledgeGraph — 輕量知識圖譜
使用 SQLite 實作，不需要外部資料庫，可直接嵌入專案目錄

節點類型：Component / Decision / Pitfall / Rule / ADR / Commit / Person
關係類型：DEPENDS_ON / CAUSED_BY / SOLVED_BY / APPLIES_TO / CONTRIBUTED_BY / SUPERSEDES
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional


class KnowledgeGraph:
    """
    本地知識圖譜（SQLite 為底層）

    設計原則：
    - 零外部依賴：只用 Python 標準庫的 sqlite3
    - 節點 + 關係：圖論的核心結構，支援多跳查詢
    - 時序感知：每個節點有 created_at，可以問「三個月前的決策」
    - 可匯出：能產生 Cypher / Mermaid / DOT 格式，和外部工具整合
    """

    # 節點類型
    TYPES = {
        "Component":  "系統組件（Service、Module、Database）",
        "Decision":   "架構決策（為什麼選這個方案）",
        "Pitfall":    "踩過的坑（避免重蹈覆轍）",
        "Rule":       "業務規則（必須遵守的約束）",
        "ADR":        "架構決策記錄（正式文件）",
        "Commit":     "程式提交（程式碼變更記錄）",
        "Person":     "貢獻者（知識的創造者）",
    }

    # 關係類型
    RELATIONS = {
        "DEPENDS_ON":      "A 依賴 B（A 改了可能影響 B）",
        "CAUSED_BY":       "A 的問題是由 B 引起的",
        "SOLVED_BY":       "A 的問題被 B 解法解決了",
        "APPLIES_TO":      "A 規則適用於 B 組件",
        "CONTRIBUTED_BY":  "A 知識由 B 人貢獻",
        "SUPERSEDES":      "A 取代了舊的 B（ADR 版本升級）",
        "REFERENCES":      "A 提到了 B",
        "TESTED_BY":       "A 組件被 B 測試覆蓋",
    }

    def __init__(self, brain_dir: Path):
        import threading as _thr
        self.db_path = brain_dir / "knowledge_graph.db"
        self._local  = _thr.local()  # per-thread connections
        self._setup_schema()
        self._migrate_schema()

    @property
    def _conn(self):
        """Per-thread SQLite connection (thread-safety fix)"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            c = sqlite3.connect(str(self.db_path), check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=5000")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return self._local.conn

    @_conn.setter
    def _conn(self, value):
        if not hasattr(self, "_local"):
            import threading
            self._local = threading.local()
        self._local.conn = value

    def _setup_schema(self):
        # P1-1：WAL 模式（多進程並發安全）
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id          TEXT PRIMARY KEY,
            type        TEXT NOT NULL,
            title       TEXT NOT NULL,
            content     TEXT,
            tags        TEXT DEFAULT '[]',
            source_url  TEXT,
            author      TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now')),
            meta        TEXT DEFAULT '{}',
            is_pinned              INTEGER DEFAULT 0,
            importance             REAL DEFAULT 0.5,
            confidence             REAL DEFAULT 0.8,
            applicability_condition TEXT DEFAULT '',
            invalidation_condition  TEXT DEFAULT '',
            perspective            TEXT DEFAULT '',
            access_count           INTEGER NOT NULL DEFAULT 0,
            last_accessed          TEXT DEFAULT '',
            emotional_weight       REAL NOT NULL DEFAULT 0.5
        );

        CREATE TABLE IF NOT EXISTS edges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id   TEXT NOT NULL REFERENCES nodes(id),
            relation    TEXT NOT NULL,
            target_id   TEXT NOT NULL REFERENCES nodes(id),
            weight      REAL DEFAULT 1.0,
            note        TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_nodes_type   ON nodes(type);
        CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
            id UNINDEXED, title, content, tags,
            content='nodes', content_rowid='rowid'
        );

        -- A-8: 不再用觸發器自動同步 FTS5
        -- 改為在 add_node 手動 INSERT（確保 N-gram 格式）
        -- 同時移除可能存在的舊觸發器
        DROP TRIGGER IF EXISTS nodes_ai;
        """)
        self._conn.commit()

    def _migrate_schema(self) -> None:
        """
        向後相容的 schema 遷移（冪等）。
        v5.1：補 is_pinned / importance
        v6.x：補 causal_direction / trigger_condition（CBRN 因果層）
        """
        conn = self._conn
        existing_nodes = {row[1] for row in conn.execute("PRAGMA table_info(nodes)")}
        if "is_pinned" not in existing_nodes:
            conn.execute("ALTER TABLE nodes ADD COLUMN is_pinned INTEGER DEFAULT 0")
        if "importance" not in existing_nodes:
            conn.execute("ALTER TABLE nodes ADD COLUMN importance REAL DEFAULT 0.5")
        if "confidence" not in existing_nodes:
            # 從 meta JSON 遷移既有 confidence 值到獨立欄位
            conn.execute("ALTER TABLE nodes ADD COLUMN confidence REAL DEFAULT 0.8")
            conn.execute("""
                UPDATE nodes
                SET confidence = CAST(
                    COALESCE(json_extract(meta, '$.confidence'), 0.8) AS REAL
                )
                WHERE confidence IS NULL OR confidence = 0.8
            """)
        if "applicability_condition" not in existing_nodes:
            conn.execute("ALTER TABLE nodes ADD COLUMN applicability_condition TEXT DEFAULT ''")
        if "invalidation_condition" not in existing_nodes:
            conn.execute("ALTER TABLE nodes ADD COLUMN invalidation_condition TEXT DEFAULT ''")
        if "perspective" not in existing_nodes:
            conn.execute("ALTER TABLE nodes ADD COLUMN perspective TEXT DEFAULT ''")

        # v6.x CBRN：edges 補充因果語意欄位
        existing_edges = {row[1] for row in conn.execute("PRAGMA table_info(edges)")}
        if "causal_direction" not in existing_edges:
            # BECAUSE / ENABLES / PREVENTS / CORRELATES
            conn.execute("ALTER TABLE edges ADD COLUMN causal_direction TEXT DEFAULT 'CORRELATES'")
        if "trigger_condition" not in existing_edges:
            # 「當版本 >= X 時失效」「當負載 > Y 時觸發」
            conn.execute("ALTER TABLE edges ADD COLUMN trigger_condition TEXT DEFAULT ''")
        if "confidence" not in existing_edges:
            conn.execute("ALTER TABLE edges ADD COLUMN confidence REAL DEFAULT 0.8")
        # v9.0: SR access_count 合入主表
        if 'access_count' not in existing_nodes:
            conn.execute("ALTER TABLE nodes ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0")
        if 'last_accessed' not in existing_nodes:
            conn.execute("ALTER TABLE nodes ADD COLUMN last_accessed TEXT DEFAULT ''")
        # v9.0: 情感重量（踩坑的痛苦程度影響記憶強度）
        if 'emotional_weight' not in existing_nodes:
            conn.execute("ALTER TABLE nodes ADD COLUMN emotional_weight REAL NOT NULL DEFAULT 0.5")
        conn.commit()


    def record_access(self, node_id: str) -> None:
        """記錄節點被訪問（Spaced Repetition，v9.0 合入主表）"""
        try:
            self._conn.execute("""
                UPDATE nodes
                SET access_count = access_count + 1,
                    last_accessed = datetime('now')
                WHERE id = ?
            """, (node_id,))
            self._conn.commit()
        except Exception:
            pass

    # ── 節點操作 ──────────────────────────────────────────────────

    @staticmethod
    def _ngram_text(text: str) -> str:
        """
        A-5：中文 N-gram 預處理，讓 FTS5 能搜尋中文子詞。

        FTS5 對中文的預設分詞是「整個字串當一個 token」，
        因此搜尋「連線」無法匹配「資料庫連線池設定」。

        解法：在每個中文字元前後插入空格，讓 FTS5 把每個字元視為獨立 token。
        「連線池」→「連 線 池」→ FTS5 可搜到「線」「連線」等子詞。

        英文詞不受影響（已有空格分詞）。
        """
        import re
        # 在中文字元之間插入空格
        return re.sub(r'([一-鿿])', r' \1 ', text)

    def search_nodes_multi(
        self,
        terms:     list[str],
        node_type: str = None,
        limit:     int = 10,
    ) -> list:
        """
        A-4：多詞 OR 搜尋 — 一次 SQL 查詢取代多次逐詞搜尋。

        把所有擴展詞合成一個 FTS5 OR 查詢：
          MATCH 'jwt OR token OR 令 OR 牌 OR 認 OR 證'

        比逐詞迴圈快 5-10x（1000 節點：60ms → <10ms）。

        Args:
            terms:     擴展詞列表（來自 _expand_query）
            node_type: 過濾類型（None = 全部）
            limit:     最多回傳筆數
        """
        if not terms:
            return []

        # 建立 FTS5 OR 查詢字串（每個詞用引號包圍防注入）
        import re as _re
        safe_terms = [_re.sub(r'[^\w\u4e00-\u9fff]', '', t) for t in terms]
        safe_terms = [t for t in safe_terms if len(t) >= 2][:20]  # 至少 2 字元
        if not safe_terms:
            return []

        # DEF-07 fix: expand each term through _ngram_text() for CJK sub-word matching
        _expanded_terms: list[str] = []
        for _st in safe_terms:
            _tokens = KnowledgeGraph._ngram_text(_st).split()
            _valid = [_tok for _tok in _tokens if len(_tok) >= 1]
            _expanded_terms.extend(_valid if _valid else [_st])
        # deduplicate preserving order
        _seen_terms: set = set()
        _deduped: list[str] = []
        for _term in _expanded_terms:
            if _term not in _seen_terms:
                _deduped.append(_term)
                _seen_terms.add(_term)
        safe_terms = _deduped if _deduped else safe_terms

        fts_query = " OR ".join(f'"{t}"' for t in safe_terms)

        try:
            if node_type:
                rows = self._conn.execute("""
                    SELECT n.id, n.type, n.title, n.content, n.tags,
                           n.confidence, n.importance, n.is_pinned,
                           n.access_count, n.emotional_weight,
                           n.applicability_condition, n.perspective
                    FROM   nodes_fts
                    JOIN   nodes n ON nodes_fts.rowid = n.rowid
                    WHERE  nodes_fts MATCH ?
                      AND  n.type = ?
                    ORDER  BY n.is_pinned DESC,
                              n.confidence DESC,
                              n.importance DESC
                    LIMIT  ?
                """, (fts_query, node_type, limit)).fetchall()
            else:
                rows = self._conn.execute("""
                    SELECT n.id, n.type, n.title, n.content, n.tags,
                           n.confidence, n.importance, n.is_pinned,
                           n.access_count, n.emotional_weight,
                           n.applicability_condition, n.perspective
                    FROM   nodes_fts
                    JOIN   nodes n ON nodes_fts.rowid = n.rowid
                    WHERE  nodes_fts MATCH ?
                    ORDER  BY n.is_pinned DESC,
                              n.confidence DESC,
                              n.importance DESC
                    LIMIT  ?
                """, (fts_query, limit)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            # FTS5 查詢語法錯誤時降級到逐詞搜尋
            for term in safe_terms[:5]:
                results = self.search_nodes(term, node_type=node_type, limit=limit)
                if results:
                    return results
            return []

    def add_node(
        self,
        node_id:    str,
        node_type:  str,
        title:      str,
        content:    str = "",
        tags:       list = None,
        source_url: str = "",
        author:     str = "",
        meta:       dict = None,
    ) -> str:
        tags_json  = json.dumps(tags or [], ensure_ascii=False)
        meta_dict  = meta or {}
        meta_json  = json.dumps(meta_dict, ensure_ascii=False)
        # Fix: sync confidence from meta dict to the independent column
        # Ensures decay_engine and context.py see consistent values
        confidence = float(meta_dict.get("confidence", 0.8))
        self._conn.execute("""
            INSERT OR REPLACE INTO nodes
                (id, type, title, content, tags, source_url, author, meta, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (node_id, node_type, title, content, tags_json,
              source_url, author, meta_json, confidence))
        # A-8: 直接 INSERT N-gram 格式到 FTS5（單次寫入，無 double write）
        try:
            fts_title   = self._ngram_text(title)
            fts_content = self._ngram_text(content or '')
            self._conn.execute(
                'INSERT INTO nodes_fts(rowid, id, title, content, tags) '
                'VALUES ((SELECT rowid FROM nodes WHERE id=?), ?, ?, ?, ?)',
                (node_id, node_id, fts_title, fts_content, tags_json)
            )
        except Exception:
            pass  # FTS5 INSERT 失敗不影響主流程
        self._conn.commit()
        return node_id

    def update_node(
        self,
        node_id:    str,
        title:      str  = None,
        content:    str  = None,
        confidence: float = None,
        importance: float = None,
    ) -> bool:
        """
        A-6：更新節點欄位，同步 FTS5 N-gram 索引。

        只更新指定的欄位（None = 不更新）。
        content 或 title 變更時自動更新 FTS5 N-gram 索引。

        Returns:
            True 如果節點存在並更新成功，False 如果節點不存在
        """
        existing = self.get_node(node_id)
        if not existing:
            return False

        updates, params = [], []
        if title is not None:
            updates.append("title = ?");      params.append(title)
        if content is not None:
            updates.append("content = ?");    params.append(content)
        if confidence is not None:
            updates.append("confidence = ?"); params.append(confidence)
        if importance is not None:
            updates.append("importance = ?"); params.append(importance)

        if not updates:
            return True

        params.append(node_id)
        self._conn.execute(
            f"UPDATE nodes SET {', '.join(updates)} WHERE id = ?",
            params
        )

        # 同步 FTS5 N-gram 索引（使用 FTS5 content 觸發器方式）
        if title is not None or content is not None:
            new_title   = title   if title   is not None else existing.get("title", "")
            new_content = content if content is not None else existing.get("content", "")
            try:
                # FTS5 的正確更新方式：先刪除再插入
                self._conn.execute(
                    "DELETE FROM nodes_fts WHERE rowid="
                    "(SELECT rowid FROM nodes WHERE id=?)", (node_id,)
                )
                self._conn.execute(
                    "INSERT INTO nodes_fts(rowid, id, title, content, tags) "
                    "SELECT rowid, id, ?, ?, tags FROM nodes WHERE id=?",
                    (self._ngram_text(new_title), self._ngram_text(new_content), node_id)
                )
            except Exception:
                pass  # FTS5 同步失敗不影響主流程

        self._conn.commit()
        return True

    def get_node(self, node_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["tags"] = json.loads(d["tags"])
        d["meta"] = json.loads(d["meta"])
        return d

    def search_nodes(
        self,
        query:     str,
        node_type: str  = None,
        limit:     int  = 10,
        pinned_first: bool = True,
    ) -> list:
        """
        全文搜尋節點（FTS5 + LIKE 雙重搜尋 + confidence/importance 加權排序）

        v5.1 改進：
        1. is_pinned=1 的節點永遠優先（免疫衰減的關鍵規則排最前）
        2. importance 欄位影響排序（高重要性排前）
        3. meta.confidence 影響排序（衰減後低信心的排後）
        4. FTS5 中文子詞問題：LIKE 備援

        Args:
            query:        搜尋關鍵字
            node_type:    過濾節點類型（None = 全部）
            limit:        最多回傳筆數
            pinned_first: 是否讓 is_pinned=1 的節點優先（預設 True）
        """
        import re, json

        def _sort_key(row: dict) -> tuple:
            """
            排序鍵（越小越優先）：
              (is_pinned DESC, importance DESC, confidence DESC)
            修補：直接讀取 confidence 欄位，不再 json.loads(meta)
            """
            pinned     = -(row.get("is_pinned") or 0)
            importance = -(row.get("importance") or 0.5)
            confidence = -(row.get("confidence") or 0.8)   # 直接讀欄位
            return (pinned, importance, confidence)

        # Step 1: FTS5 精準查詢
        rows = []
        try:
            if node_type:
                rows = self._conn.execute("""
                    SELECT n.* FROM nodes n
                    JOIN nodes_fts f ON f.id = n.id
                    WHERE nodes_fts MATCH ? AND n.type = ?
                    ORDER BY rank LIMIT ?
                """, (query, node_type, limit)).fetchall()
            else:
                rows = self._conn.execute("""
                    SELECT n.* FROM nodes n
                    JOIN nodes_fts f ON f.id = n.id
                    WHERE nodes_fts MATCH ?
                    ORDER BY rank LIMIT ?
                """, (query, limit)).fetchall()
        except Exception:
            pass

        if rows:
            result = [dict(r) for r in rows]
            return sorted(result, key=_sort_key)[:limit]

        # Step 2: LIKE 模糊備援（解決中文子詞問題）
        words = [w for w in re.split(r'\s+', query.strip()) if w]
        if not words:
            return []

        seen_ids: set = set()
        results:  list = []
        for word in words:
            pattern = f"%{word}%"
            if node_type:
                rows = self._conn.execute("""
                    SELECT * FROM nodes
                    WHERE (title LIKE ? OR content LIKE ?)
                      AND type = ?
                    LIMIT ?
                """, (pattern, pattern, node_type, limit)).fetchall()
            else:
                rows = self._conn.execute("""
                    SELECT * FROM nodes
                    WHERE title LIKE ? OR content LIKE ?
                    LIMIT ?
                """, (pattern, pattern, limit)).fetchall()
            for r in rows:
                d = dict(r)
                if d["id"] not in seen_ids:
                    seen_ids.add(d["id"])
                    results.append(d)
            if len(results) >= limit:
                break

        return sorted(results, key=_sort_key)[:limit]

    def pin_node(self, node_id: str, pinned: bool = True) -> bool:
        """
        設定節點為免疫衰減的釘選狀態（v5.1）。

        釘選的節點：
        - is_pinned=1，搜尋結果永遠排最前
        - DecayEngine 跳過此節點，不降低 confidence
        - 適用對象：CRITICAL 安全規則、不可違反的業務規則

        Args:
            node_id: 節點 ID
            pinned:  True=釘選，False=取消釘選

        Returns:
            bool：是否成功更新

        範例：
            graph.pin_node("rule_jwt_rs256", pinned=True)
        """
        cur = self._conn.execute(
            "UPDATE nodes SET is_pinned=? WHERE id=?",
            (1 if pinned else 0, node_id)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def set_importance(self, node_id: str, importance: float) -> bool:
        """
        設定節點重要性分數（v5.1），影響 Context 排序。

        Args:
            node_id:    節點 ID
            importance: 0.0（低）~ 1.0（高）

        Returns:
            bool：是否成功更新

        範例：
            graph.set_importance("pitfall_stripe", 0.9)  # 高重要性
        """
        imp = max(0.0, min(1.0, importance))
        cur = self._conn.execute(
            "UPDATE nodes SET importance=? WHERE id=?",
            (imp, node_id)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ── 關係操作 ──────────────────────────────────────────────────

    # Causal relation types (CBRN v6.x)
    CAUSAL_DIRECTIONS = {
        "BECAUSE":    "A 的存在/選擇是因為 B",
        "ENABLES":    "A 使得 B 成為可能",
        "PREVENTS":   "A 防止了 B 的發生",
        "CORRELATES": "A 和 B 相關（無明確因果方向，預設）",
    }

    def add_edge(
        self,
        source_id:         str,
        relation:          str,
        target_id:         str,
        weight:            float = 1.0,
        note:              str   = "",
        causal_direction:  str   = "CORRELATES",
        trigger_condition: str   = "",
        confidence:        float = 0.8,
    ) -> int:
        """
        新增知識圖譜邊（v6.x：支援因果語意）。

        Args:
            source_id:         來源節點 ID
            relation:          關係類型（DEPENDS_ON / CAUSED_BY 等）
            target_id:         目標節點 ID
            weight:            邊的權重（0.0~1.0，影響 blast_radius 計算）
            note:              關係說明
            causal_direction:  因果方向（BECAUSE/ENABLES/PREVENTS/CORRELATES）
            trigger_condition: 條件性觸發（「版本 >= 20 時失效」「負載 > 10k 觸發」）
            confidence:        因果關係的信心分數

        範例：
            graph.add_edge("jwt_rs256", "BECAUSE", "multi_service_auth",
                          causal_direction="BECAUSE",
                          note="多服務需要非對稱金鑰才能跨服務驗證")
        """
        cur = self._conn.execute("""
            INSERT INTO edges
                (source_id, relation, target_id, weight, note,
                 causal_direction, trigger_condition, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (source_id, relation, target_id, weight, note,
              causal_direction, trigger_condition, confidence))
        self._conn.commit()
        return cur.lastrowid

    def neighbors(self, node_id: str, relation: str = None, depth: int = 1) -> list:
        """找出 N 跳以內的相鄰節點"""
        if depth == 1:
            if relation:
                rows = self._conn.execute("""
                    SELECT n.*, e.relation, e.note
                    FROM edges e JOIN nodes n ON n.id = e.target_id
                    WHERE e.source_id = ? AND e.relation = ?
                """, (node_id, relation)).fetchall()
            else:
                rows = self._conn.execute("""
                    SELECT n.*, e.relation, e.note
                    FROM edges e JOIN nodes n ON n.id = e.target_id
                    WHERE e.source_id = ?
                """, (node_id,)).fetchall()
            return [dict(r) for r in rows]

        # BFS 多跳查詢
        visited = {node_id}
        frontier = [node_id]
        all_results = []
        for _ in range(depth):
            next_frontier = []
            for nid in frontier:
                neighbors = self.neighbors(nid, relation, depth=1)
                for nb in neighbors:
                    if nb["id"] not in visited:
                        visited.add(nb["id"])
                        next_frontier.append(nb["id"])
                        all_results.append(nb)
            frontier = next_frontier
        return all_results

    def find_path(self, source_id: str, target_id: str, max_depth: int = 4) -> list:
        """找出兩個節點之間的路徑（BFS）"""
        if source_id == target_id:
            return [source_id]
        visited = {source_id}
        queue = [(source_id, [source_id])]
        while queue:
            node, path = queue.pop(0)
            if len(path) > max_depth:
                break
            neighbors = self.neighbors(node)
            for nb in neighbors:
                nid = nb["id"]
                if nid == target_id:
                    return path + [nid]
                if nid not in visited:
                    visited.add(nid)
                    queue.append((nid, path + [nid]))
        return []

    # ── 查詢輔助 ──────────────────────────────────────────────────

    def impact_analysis(self, component_id: str) -> dict:
        """衝擊分析：修改 component 可能影響哪些地方"""
        direct    = self.neighbors(component_id, "DEPENDS_ON", depth=1)
        indirect  = self.neighbors(component_id, depth=2)
        pitfalls  = self.neighbors(component_id, "CAUSED_BY",  depth=1)
        rules     = [n for n in self.neighbors(component_id)
                     if n.get("type") == "Rule"]
        return {
            "target":    self.get_node(component_id),
            "direct":    direct,
            "indirect":  indirect,
            "pitfalls":  pitfalls,
            "rules":     rules,
        }

    def blast_radius(self, node_id: str) -> dict:
        """
        計算節點的「爆炸半徑」— 修改此節點會影響多少其他節點（v6.0）。

        使用圖論中心性指標，不需要呼叫 LLM，速度極快（<5ms）。
        作為 Counterfactual LLM 呼叫的前置過濾器：
          爆炸半徑 < threshold → 不值得觸發 LLM 反事實推演
          爆炸半徑 >= threshold → 觸發 LLM 深度分析

        計算指標：
          - degree_centrality：直接鄰居數 / 總節點數
          - affected_nodes：BFS 可達的節點總數（深度 <= 3）
          - risk_score：綜合分數（0.0 ~ 1.0）

        Returns:
            {
              "node_id": str,
              "affected_nodes": int,     # 可達節點數
              "direct_neighbors": int,   # 直接鄰居
              "degree_centrality": float,# 0.0~1.0
              "risk_score": float,       # 綜合風險分數 0.0~1.0
              "is_high_risk": bool,      # risk_score >= 0.3
            }
        """
        total_nodes = self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        if total_nodes == 0:
            return {"node_id": node_id, "affected_nodes": 0,
                    "direct_neighbors": 0, "degree_centrality": 0.0,
                    "risk_score": 0.0, "is_high_risk": False}

        # BFS 3 層內的可達節點
        # 修補：改為有向 BFS（只追蹤下游影響，不含上游）
        # 原本無向 BFS 會把「被誰依賴」和「依賴誰」混在一起，
        # 導致被大量節點參考的知識節點風險被嚴重高估。
        # 正確語意：修改 A，會影響哪些下游節點？（只往 target_id 走）
        visited: set = {node_id}
        frontier: set = {node_id}
        for _ in range(3):
            next_frontier: set = set()
            for nid in frontier:
                rows = self._conn.execute(
                    "SELECT target_id FROM edges WHERE source_id=?",
                    (nid,)
                ).fetchall()
                for r in rows:
                    if r[0] not in visited:
                        visited.add(r[0])
                        next_frontier.add(r[0])
            frontier = next_frontier
            if not frontier:
                break

        affected = len(visited) - 1  # 不含自身（下游影響數）
        # 出度（該節點往外指向幾個節點）— 代表直接影響範圍
        direct = self._conn.execute(
            "SELECT COUNT(*) FROM edges WHERE source_id=?",
            (node_id,)
        ).fetchone()[0]

        degree_c = direct / max(total_nodes - 1, 1)
        reach_r  = affected / max(total_nodes - 1, 1)
        risk     = min(1.0, 0.4 * degree_c + 0.6 * reach_r)

        return {
            "node_id":           node_id,
            "affected_nodes":    affected,
            "direct_neighbors":  direct,
            "degree_centrality": round(degree_c, 4),
            "risk_score":        round(risk, 4),
            "is_high_risk":      risk >= 0.3,
        }

    def causal_chain(
        self,
        node_id:   str,
        direction: str = "BECAUSE",
        depth:     int = 3,
    ) -> list[dict]:
        """
        追蹤因果鏈（CBRN v6.x）。

        從一個知識節點出發，沿因果方向追溯上游（BECAUSE）
        或下游（ENABLES / PREVENTS）節點，找出根本原因或影響範圍。

        Args:
            node_id:   起始節點 ID
            direction: 因果方向篩選（BECAUSE/ENABLES/PREVENTS/CORRELATES/全部）
            depth:     最大追溯深度（預設 3）

        Returns:
            list[dict]：節點鏈，每個元素包含 node + edge_info

        應用場景：
            # 「為什麼 JWT 要用 RS256？」— 追溯上游 BECAUSE 鏈
            chain = graph.causal_chain("jwt_rs256_rule", direction="BECAUSE")

            # 「修改認證模組會影響什麼？」— 追溯下游 ENABLES 鏈
            chain = graph.causal_chain("auth_module", direction="ENABLES")
        """
        visited: set = {node_id}
        chain:   list = []
        frontier = [node_id]

        for _ in range(depth):
            next_frontier = []
            for nid in frontier:
                if direction == "全部":
                    rows = self._conn.execute("""
                        SELECT n.*, e.relation, e.causal_direction,
                               e.trigger_condition, e.note
                        FROM edges e JOIN nodes n ON n.id = e.target_id
                        WHERE e.source_id = ?
                    """, (nid,)).fetchall()
                else:
                    rows = self._conn.execute("""
                        SELECT n.*, e.relation, e.causal_direction,
                               e.trigger_condition, e.note
                        FROM edges e JOIN nodes n ON n.id = e.target_id
                        WHERE e.source_id = ?
                          AND e.causal_direction = ?
                    """, (nid, direction)).fetchall()

                for r in rows:
                    d = dict(r)
                    if d["id"] not in visited:
                        visited.add(d["id"])
                        next_frontier.append(d["id"])
                        chain.append({
                            "node":              {k: v for k, v in d.items()
                                                  if k not in ("relation","causal_direction","trigger_condition","note")},
                            "causal_direction":  d.get("causal_direction", "CORRELATES"),
                            "trigger_condition": d.get("trigger_condition", ""),
                            "relation":          d.get("relation", ""),
                            "note":              d.get("note", ""),
                        })
            frontier = next_frontier
            if not frontier:
                break

        return chain

    def set_meta_knowledge(
        self,
        node_id:                  str,
        applicability_condition:  str = "",
        invalidation_condition:   str = "",
    ) -> bool:
        """
        設定知識節點的 Meta-Knowledge（知識的知識）— v7.0。

        解決「只知道是什麼，不知道在什麼條件下成立」的盲區：

        - applicability_condition：「在什麼條件下，這條知識才適用？」
          例："只有在多服務架構時才需要 RS256，單體應用 HS256 完全合理"
          例："負載 < 1萬/天時，這個快取策略才夠用"

        - invalidation_condition：「什麼情況下，這條知識就失效了？」
          例："升級到 Node.js 20+ 後，這個 polyfill 不再需要"
          例:"整合了只支援 HS256 的第三方服務時，這條規則需要重新評估"

        這兩個條件一起，讓 Agent 知道「什麼時候要思考這條規則的邊界」，
        而不是無條件套用。

        Args:
            node_id:                  節點 ID
            applicability_condition:  適用條件
            invalidation_condition:   失效條件

        Returns:
            bool：是否成功更新

        範例：
            graph.set_meta_knowledge(
                "jwt_rs256_rule",
                applicability_condition="只在多服務 / 微服務架構中需要",
                invalidation_condition="如果整合僅支援 HS256 的第三方服務時需重新評估",
            )
        """
        cur = self._conn.execute(
            """UPDATE nodes
               SET applicability_condition=?,
                   invalidation_condition=?,
                   updated_at=datetime('now')
               WHERE id=?""",
            (applicability_condition, invalidation_condition, node_id)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def set_perspective(
        self,
        node_id:     str,
        perspective: str,
    ) -> bool:
        """
        設定知識節點的觀點維度（修補）。

        解決「所有知識以客觀事實形式存入」的盲區：
        不同 Agent、不同工程師可能對同一件事有不同觀點。
        用 perspective 欄位標記這條知識代表「誰的觀點」。

        格式建議：
          "NEXUS:架構師觀點"       — Agent 觀點
          "ahern:個人經驗"         — 開發者觀點
          "team:共識"              — 團隊共識（最高可信度）
          "external:第三方文件"    — 外部參考（需驗證）

        不同觀點共存、不覆蓋：
          NEXUS 說「用微服務」，BYTE 說「單體先行」，
          兩條都存在，perspective 欄位讓 Agent 知道哪條代表誰。

        Args:
            node_id:     節點 ID
            perspective: 觀點描述

        Returns:
            bool：是否成功更新
        """
        cur = self._conn.execute(
            "UPDATE nodes SET perspective=? WHERE id=?",
            (perspective, node_id)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_meta_knowledge(self, node_id: str) -> dict:
        """
        取得節點的 Meta-Knowledge 欄位（v7.0）。

        Returns:
            {
              "applicability_condition": str,
              "invalidation_condition":  str,
              "has_meta":                bool,  # 是否有任何 meta-knowledge
            }
        """
        row = self._conn.execute(
            "SELECT applicability_condition, invalidation_condition FROM nodes WHERE id=?",
            (node_id,)
        ).fetchone()
        if not row:
            return {"applicability_condition": "", "invalidation_condition": "", "has_meta": False}
        ac = row["applicability_condition"] or ""
        ic = row["invalidation_condition"]  or ""
        return {
            "applicability_condition": ac,
            "invalidation_condition":  ic,
            "has_meta":                bool(ac or ic),
        }

    def all_pitfalls_for(self, component_id: str) -> list:
        return self.search_nodes(component_id, node_type="Pitfall")

    # ── 匯出格式 ──────────────────────────────────────────────────

    def to_mermaid(self, limit: int = 50) -> str:
        """匯出為 Mermaid 圖表（可嵌入 Markdown）"""
        nodes = self._conn.execute(
            "SELECT id, type, title FROM nodes LIMIT ?", (limit,)
        ).fetchall()
        edges = self._conn.execute(
            "SELECT source_id, relation, target_id FROM edges LIMIT ?", (limit,)
        ).fetchall()

        colors = {
            "Component": ":::comp",
            "Decision":  ":::dec",
            "Pitfall":   ":::pit",
            "Rule":      ":::rule",
        }

        lines = ["graph TD"]
        lines.append("    classDef comp fill:#dbeafe,stroke:#3b82f6")
        lines.append("    classDef dec  fill:#dcfce7,stroke:#22c55e")
        lines.append("    classDef pit  fill:#fee2e2,stroke:#ef4444")
        lines.append("    classDef rule fill:#fef9c3,stroke:#eab308")

        for n in nodes:
            nid   = n["id"].replace("-", "_").replace("/", "_")
            label = n["title"][:30]
            cls   = colors.get(n["type"], "")
            lines.append(f'    {nid}["{label}"]{cls}')

        for e in edges:
            src = e["source_id"].replace("-","_").replace("/","_")
            tgt = e["target_id"].replace("-","_").replace("/","_")
            rel = e["relation"]
            lines.append(f"    {src} -->|{rel}| {tgt}")

        return "\n".join(lines)

    def stats(self) -> dict:
        nodes_count = self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edges_count = self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        by_type     = self._conn.execute(
            "SELECT type, COUNT(*) as cnt FROM nodes GROUP BY type"
        ).fetchall()
        return {
            "nodes":   nodes_count,
            "edges":   edges_count,
            "by_type": {r["type"]: r["cnt"] for r in by_type},
        }

    def counterfactual_impact(self, hypothesis: str) -> list:
        """DEEP-03: 反事實推理 — 找出假設條件下需要重新評估的知識節點。

        Args:
            hypothesis: 假設條件描述（如「如果我們用 NoSQL 代替 PostgreSQL」）

        Returns:
            list[dict]: 受影響節點列表，含 id, title, type, confidence, reason
        """
        import re
        terms = re.findall(r"[a-zA-Z0-9_]{3,}|[\u4e00-\u9fff]{2,}", hypothesis)
        search_q = " ".join(terms[:8])
        affected = []
        seen_ids = set()
        try:
            hits = self.search_nodes(search_q, limit=8)
            for n in hits:
                nid = n["id"]
                if nid in seen_ids:
                    continue
                seen_ids.add(nid)
                affected.append({
                    "id": nid, "title": n.get("title",""),
                    "type": n.get("type","?"),
                    "confidence": n.get("confidence",0.8),
                    "reason": "直接匹配假設條件",
                })
                # Follow DEPENDS_ON / REQUIRES edges
                rows = self._conn.execute(
                    "SELECT n2.id, n2.type, n2.title, n2.confidence "
                    "FROM edges e JOIN nodes n2 ON e.target_id=n2.id "
                    "WHERE e.source_id=? AND e.relation IN ('DEPENDS_ON','REQUIRES')",
                    (nid,)
                ).fetchall()
                for r in rows:
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        affected.append({
                            "id": r["id"], "title": r["title"],
                            "type": r["type"],
                            "confidence": r["confidence"] or 0.8,
                            "reason": f"依賴受影響節點（{n.get('title','')[:30]}）",
                        })
        except Exception:
            pass
        return affected

    def close(self):
        self._conn.close()
