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
        self.db_path = brain_dir / "knowledge_graph.db"
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._setup_schema()

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
            meta        TEXT DEFAULT '{}'
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

        CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
            INSERT INTO nodes_fts(rowid, id, title, content, tags)
            VALUES (new.rowid, new.id, new.title, new.content, new.tags);
        END;
        """)
        self._conn.commit()

    # ── 節點操作 ──────────────────────────────────────────────────

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
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        self._conn.execute("""
            INSERT OR REPLACE INTO nodes
                (id, type, title, content, tags, source_url, author, meta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (node_id, node_type, title, content, tags_json, source_url, author, meta_json))
        self._conn.commit()
        return node_id

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

    def search_nodes(self, query: str, node_type: str = None, limit: int = 10) -> list:
        """
        全文搜尋節點（FTS5 + LIKE 雙重搜尋）

        FTS5 對中文的限制：unicode61 分詞器以空白為邊界，
        「等社群軟體會快取」是一個 token，無法搜尋其中的「快取」子詞。
        解法：FTS5 找不到時自動降級到 LIKE 模糊搜尋。
        """
        # Step 1: 嘗試 FTS5（精準，支援 AND 組合）
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
            if rows:
                return [dict(r) for r in rows]
        except Exception:
            pass  # FTS5 query 格式錯誤時降級

        # Step 2: FTS5 無結果 → 逐詞 LIKE 模糊搜尋
        # 把查詢拆成個別詞，每個詞用 LIKE 搜尋，取聯集
        import re
        words = [w for w in re.split(r'\s+', query.strip()) if w]
        if not words:
            return []

        seen_ids = set()
        results  = []
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

        return results[:limit]

    # ── 關係操作 ──────────────────────────────────────────────────

    def add_edge(
        self,
        source_id: str,
        relation:  str,
        target_id: str,
        weight:    float = 1.0,
        note:      str   = "",
    ) -> int:
        cur = self._conn.execute("""
            INSERT INTO edges (source_id, relation, target_id, weight, note)
            VALUES (?, ?, ?, ?, ?)
        """, (source_id, relation, target_id, weight, note))
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

    def close(self):
        self._conn.close()
