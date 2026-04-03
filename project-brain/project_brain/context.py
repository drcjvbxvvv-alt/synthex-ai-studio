from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING

"""
ContextEngineer — 動態 Context 組裝引擎

根據當前任務，從知識圖譜和向量記憶中動態組裝
最相關的知識注入 AI 的 Context Window。

這是 Project Brain 最關鍵的組件：
不只是「找到知識」，而是「把正確的知識，在正確的時機，
以正確的密度注入 Context」。
"""
import os
import re
import json
from pathlib import Path
from .graph import KnowledgeGraph
if TYPE_CHECKING:
    from .vector_memory import VectorMemory


MAX_CONTEXT_TOKENS = 6000   # 為任務本身留 2K


def _count_tokens(text: str) -> int:
    """
    BUG-03 fix: CJK-aware token estimator (no external dependency).

    舊做法 len(text) // 4 對中文嚴重低估：
      - CJK 每字 ≈ 1 token（len=1 但 token=1）
      - ASCII 每字 ≈ 0.25 token（len=1 但 token≈0.25）
    實際超出 6000 預算 20-30%。

    新做法：分別統計 CJK 字元（1 token/char）與其餘字元（1 token/4 chars）。
    誤差 < 8%（不依賴 tiktoken，無需安裝額外套件）。
    """
    cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff'
              or '\u3000' <= ch <= '\u303f'
              or '\uff00' <= ch <= '\uffef')
    rest = len(text) - cjk
    return cjk + (rest // 4)


class ContextEngineer:
    """
    智能 Context 組裝器

    組裝策略（優先順序）：
    1. 直接相關的 Pitfall（避免踩坑，優先級最高）
    2. 適用的業務規則（必須遵守）
    3. 架構決策記錄（理解為什麼）
    4. 依賴關係（影響範圍分析）
    5. 最近的相關決策（近期上下文）
    """

    def __init__(self, graph: KnowledgeGraph, brain_dir: Path,
                 vector_memory: "VectorMemory | None" = None,
                 brain_db=None):
        self.graph      = graph
        self.brain_dir  = brain_dir
        self.vm        = vector_memory
        # A-13: auto-detect brain.db if not explicitly passed
        if brain_db is None:
            _db_path = Path(brain_dir) / 'brain.db'
            if _db_path.exists():
                try:
                    from .brain_db import BrainDB as _BDB
                    brain_db = _BDB(Path(brain_dir))
                except Exception:
                    pass
        self._brain_db = brain_db  # A-11/A-13

    def build(self, task: str, current_file: str = "") -> str:
        """
        為任務組裝最佳的 Context 注入片段。

        Args:
            task:         當前任務描述（自然語言）
            current_file: 當前操作的檔案路徑（選填）

        Returns:
            str: 格式化的 Context 字串，可直接注入 AI Prompt
        """
        sections = []
        budget   = MAX_CONTEXT_TOKENS

        # 1. 找出和任務/檔案相關的組件
        components = self._identify_components(task, current_file)

        # 2. 衝擊分析（這個組件改了會影響什麼）
        if components and current_file:
            for comp in components[:2]:
                impact = self.graph.impact_analysis(comp)
                if impact.get("pitfalls"):
                    section = self._format_pitfalls(impact["pitfalls"])
                    budget  = self._add_if_budget(sections, section, budget)

        # 3. 知識搜尋：v1.1 向量語義優先，FTS5 備援
        # BUG-05 fix: initialise all_nodes / result lists before the keywords
        # guard so that the spaced-repetition block below never hits NameError
        # when the task string yields no extractable keywords.
        pitfalls  = []
        decisions = []
        rules     = []
        adrs      = []
        notes     = []
        all_nodes: list[tuple[float, str, dict]] = []

        keywords = self._extract_keywords(task)
        if keywords:

            # v1.1：向量語義搜尋（若 chromadb 已安裝）
            if self.vm and self.vm.available:
                vm_results = self.vm.search(task, top_k=8)
                pitfalls  = [r for r in vm_results if r.get("type") == "Pitfall"][:3]
                decisions = [r for r in vm_results if r.get("type") == "Decision"][:2]
                rules     = [r for r in vm_results if r.get("type") == "Rule"][:2]
                adrs      = [r for r in vm_results if r.get("type") == "ADR"][:1]

            # FTS5 備援：向量搜尋空結果或未安裝時啟用
            # A-1：查詢擴展 — 多個搜尋詞 OR 組合，解決同義詞召回問題
            if not any([pitfalls, decisions, rules, adrs]):
                expanded_terms = self._expand_query(task)
                # 優先用擴展詞搜尋；若無結果則 fallback 到原始關鍵字
                # A-4：單一 OR 查詢取代多次逐詞搜尋，速度 60ms → <10ms
                def _search_batch(terms, node_type, limit):
                    # BUG-09 fix: merge BrainDB + KnowledgeGraph results (no early return)
                    # BUG-12 fix: always pass scope to search_nodes()
                    _scope = getattr(self, "_scope", None)
                    db_results: list = []
                    if self._brain_db is not None:
                        _q_vec = None
                        try:
                            from .embedder import get_embedder
                            _emb = get_embedder()
                            if _emb:
                                _q_vec = _emb.embed(" ".join(terms[:8]))
                        except Exception:
                            pass
                        if _q_vec:
                            db_results = self._brain_db.hybrid_search(
                                " ".join(terms[:8]), query_vector=_q_vec,
                                scope=_scope, limit=limit
                            )
                            db_results = [r for r in db_results if r.get("type") == node_type]
                        else:
                            db_results = self._brain_db.search_nodes(
                                " ".join(terms[:8]), node_type=node_type,
                                scope=_scope, limit=limit  # BUG-12 fix
                            )
                    # Always query KnowledgeGraph and merge (BUG-09 fix)
                    graph_results = self.graph.search_nodes_multi(
                        terms, node_type=node_type, limit=limit
                    )
                    # Deduplicate by id: BrainDB results take precedence
                    seen_ids: set = {r["id"] for r in db_results if "id" in r}
                    merged = list(db_results)
                    for r in graph_results:
                        if r.get("id") not in seen_ids:
                            merged.append(r)
                            seen_ids.add(r.get("id"))
                    return merged[:limit]
                pitfalls  = _search_batch(expanded_terms, node_type="Pitfall",  limit=3)
                decisions = _search_batch(expanded_terms, node_type="Decision", limit=2)
                rules     = _search_batch(expanded_terms, node_type="Rule",     limit=2)
                adrs      = _search_batch(expanded_terms, node_type="ADR",      limit=1)
                notes     = _search_batch(expanded_terms, node_type="Note",     limit=2)  # A-24

            # v5.1 修正：先到先服務偏見 → importance + confidence 加權排序後填充
            # 原本按搜尋順序直接填，導致長文低品質知識擠佔高品質短知識的 Budget
            import json as _json

            def _node_priority(node: dict) -> float:
                """
                A-2：access_count 納入排序（v9.0 優化）

                公式：
                  priority = pinned*2.5 + confidence*0.35 + access_norm*0.25 + importance*0.15

                理由：
                  - pinned 保持最高優先（人工判斷）
                  - confidence 降至 0.35（AI 給的分，不應完全主導）
                  - access_norm 0.25（實際被使用的知識應排更前）
                  - importance 0.15（人工設定，輔助參考）
                """
                pinned      = 2.5 if (node.get("is_pinned") or 0) else 0.0
                confidence  = float(node.get("confidence") or 0.8)
                importance  = float(node.get("importance") or 0.5)
                access_cnt  = int(node.get("access_count") or 0)
                # 正規化：50 次以上視為飽和（避免極端值主導）
                access_norm = min(1.0, access_cnt / 50.0)
                return (
                    pinned
                    + confidence  * 0.35
                    + access_norm * 0.25
                    + importance  * 0.15
                )

            # 所有節點放進 priority queue，高優先度先填
            all_nodes: list[tuple[float, str, dict]] = []
            for n in pitfalls:  all_nodes.append((_node_priority(n), "⚠ 已知踩坑", n))
            for n in rules:     all_nodes.append((_node_priority(n), "📋 業務規則", n))
            for n in decisions: all_nodes.append((_node_priority(n), "🎯 架構決策", n))
            for n in adrs:      all_nodes.append((_node_priority(n), "📄 ADR",      n))
            for n in notes:     all_nodes.append((_node_priority(n), "📝 筆記",     n))  # A-24

            all_nodes.sort(key=lambda x: x[0], reverse=True)  # 高分排前

            for priority, label, node in all_nodes:
                max_c = 800 if label == "📄 ADR" else 400
                s     = self._fmt_node(label, node, max_chars=max_c)
                # Phase 3: increment access_count for returned nodes
                try:
                    if self._brain_db and node.get('id'):
                        self._brain_db.conn.execute(
                            "UPDATE nodes SET access_count=access_count+1,"
                            " last_accessed=datetime('now') WHERE id=?",
                            (node['id'],)
                        )
                        self._brain_db.conn.commit()
                except Exception:
                    pass
                budget = self._add_if_budget(sections, s, budget)

        # 4. 依賴關係（當前檔案的相關組件）
        if components:
            deps = []
            for comp in components[:2]:
                neighbors = self.graph.neighbors(comp, "DEPENDS_ON")
                for nb in neighbors[:3]:
                    deps.append(f"- {comp} → {nb.get('title','?')}（{nb.get('note','依賴')}）")
            if deps:
                section = "## 依賴關係（修改時需注意影響範圍）\n" + "\n".join(deps)
                budget  = self._add_if_budget(sections, section, budget)

        # 5. 沒有找到任何知識時的提示
        if not sections:
            return ""

        header = (
            "---\n"
            "## 📖 Project Brain — 專案歷史知識\n"
            "（以下是從程式碼歷史自動提取的相關知識，供參考）\n\n"
        )
        footer = "\n---\n"

        # A-3：輸出前語意去重（只在 scikit-learn 已安裝時啟用）
        # BUG-05 fix: pre-assign result so that any exception after this point
        # still has a valid string to return (avoids UnboundLocalError / None).
        result = header + "\n\n".join(sections) + footer
        try:
            sections = self._deduplicate_sections(sections)
            result   = header + "\n\n".join(sections) + footer
        except Exception:
            pass  # dedup failure — use original result
        # Spaced Repetition: 批次記錄訪問（v9.0 修補 race condition）
        try:
            _node_ids = [
                n.get("id") for _, _, n in all_nodes
                if n.get("id") and any((n.get("title","") or "") in s for s in sections)
            ]
            if _node_ids:
                import threading
                def _sr_batch(node_ids):
                    try:
                        # 在單一事務中批次更新，避免多執行緒競爭
                        self.graph._conn.executemany("""
                            UPDATE nodes
                            SET access_count = access_count + 1,
                                last_accessed = datetime('now')
                            WHERE id = ?
                        """, [(nid,) for nid in node_ids])
                        self.graph._conn.commit()
                    except Exception:
                        pass  # SR 失敗不影響主流程
                threading.Thread(
                    target=_sr_batch, args=(_node_ids,), daemon=True
                ).start()
        except Exception:
            pass
        # P1-B: prepend causal chain conclusions to result
        try:
            _ids = []
            for _seg in result.split('\n'):
                # Extract node IDs referenced in the output
                pass
            # Use BrainDB edges if available
            _db = getattr(self, '_brain_db', None)
            if _db is not None:
                _all_nodes = _db.all_nodes(limit=50)
                # Find nodes whose titles appear in this result
                _ids = [n['id'] for n in _all_nodes
                        if n.get('title','') and n['title'] in result]
                _chain = self._build_causal_chain(_ids[:5], db=_db)
                if _chain:
                    result = _chain + result
        except Exception:
            pass
        # DEEP-01: append reasoning chain when edges exist
        try:
            _rc = self.build_reasoning_chain(task)
            if _rc:
                result = (result or "") + _rc
        except Exception:
            pass
        return result or ""  # BUG-05 fix: guarantee str return, never None

    def build_reasoning_chain(self, task: str) -> str:
        """DEEP-01: 從任務關鍵字出發，遍歷圖譜邊，產生推理鏈輸出。

        格式：
          task_keyword
            → REQUIRES → node_A (Rule, conf=0.9)
              ⚠ Pitfall: "warning text"
            → CAUSED_BY → incident_B
        """
        db = self._brain_db
        if db is None:
            return ""
        try:
            hits = db.search_nodes(task, limit=4)
            if not hits:
                return ""
            lines = [f"## ⛓ 推理鏈（Reasoning Chain）：{task[:40]}"]
            rel_icons = {
                "REQUIRES": "📌", "PREVENTS": "🛡", "CAUSES": "⚠",
                "BLOCKS": "🚫", "CAUSED_BY": "⬅", "SOLVED_BY": "✅",
                "DEPENDS_ON": "🔗",
            }
            included_types = {"REQUIRES","PREVENTS","CAUSES","BLOCKS",
                              "CAUSED_BY","SOLVED_BY","DEPENDS_ON"}
            for n in hits[:3]:
                nid  = n["id"]
                ntype = n.get("type","?")
                conf  = n.get("confidence", 0.8)
                lines.append(f"  {n['title'][:60]}  ({ntype}, conf={conf:.2f})")
                edges = db.conn.execute(
                    "SELECT e.relation, e.note, n2.title, n2.type, n2.confidence "
                    "FROM edges e JOIN nodes n2 ON e.target_id=n2.id "
                    "WHERE e.source_id=? AND e.relation IN "
                    "('REQUIRES','PREVENTS','CAUSES','BLOCKS','CAUSED_BY','SOLVED_BY','DEPENDS_ON')",
                    (nid,)
                ).fetchall()
                for edge in edges:
                    rel, note, tgt_title, tgt_type, tgt_conf = edge
                    icon = rel_icons.get(rel, "→")
                    tgt_conf_str = f"conf={tgt_conf:.2f}" if tgt_conf is not None else ""
                    lines.append(
                        f"    {icon} {rel} → \"{tgt_title[:50]}\"  ({tgt_type}, {tgt_conf_str})"
                        + (f"  — {note}" if note else "")
                    )
                    if tgt_type == "Pitfall":
                        lines.append(f"      ⚠ Pitfall 警告：注意相關風險")
            if len(lines) <= 1:
                return ""
            return "\n".join(lines) + "\n\n"
        except Exception:
            return ""

    def _build_causal_chain(self, node_ids: list, db=None) -> str:
        """
        P1-B: 遍歷知識圖譜的因果邊，產生預先推導好的結論。
        不讓 Agent 自己推理，把推理留在 Python 層。
        """
        if not node_ids:
            return ""

        lines = []
        g = db or self._brain_db

        if g is None:
            # Fallback: use graph edges
            for nid in node_ids[:4]:
                try:
                    node = self.graph.get_node(nid)
                    if not node:
                        continue
                    neighbors = self.graph._conn.execute(
                        "SELECT e.relation, e.note, n2.title, n2.type "
                        "FROM edges e JOIN nodes n2 ON e.target_id=n2.id "
                        "WHERE e.source_id=? AND e.relation IN ('PREVENTS','CAUSES','REQUIRES','BLOCKS')",
                        (nid,)
                    ).fetchall()
                    for edge in neighbors:
                        rel, note, target, ttype = edge
                        icon = {"PREVENTS":"🛡","CAUSES":"⚠","REQUIRES":"📌","BLOCKS":"🚫"}.get(rel,"→")
                        lines.append(
                            f"  {icon} [{node['title']}] {rel} [{target}]"
                            + (f"  ─ {note}" if note else "")
                        )
                except Exception:
                    pass
        else:
            for nid in node_ids[:4]:
                try:
                    node = g.get_node(nid)
                    if not node:
                        continue
                    edges = g.conn.execute(
                        "SELECT e.relation, e.note, n2.title, n2.type "
                        "FROM edges e JOIN nodes n2 ON e.target_id=n2.id "
                        "WHERE e.source_id=? AND e.relation IN ('PREVENTS','CAUSES','REQUIRES','BLOCKS')",
                        (nid,)
                    ).fetchall()
                    for edge in edges:
                        rel, note, target, ttype = edge
                        icon = {"PREVENTS":"🛡","CAUSES":"⚠","REQUIRES":"📌","BLOCKS":"🚫"}.get(rel,"→")
                        lines.append(
                            f"  {icon} [{node['title']}] {rel} [{target}]"
                            + (f"  ─ {note}" if note else "")
                        )
                except Exception:
                    pass

        if not lines:
            return ""
        return "\n## ⛓ 因果關係（Brain 預先推導）\n" + "\n".join(lines) + "\n"


    def _identify_components(self, task: str, file_path: str) -> list:
        """從任務描述和檔案路徑識別相關組件"""
        components = []

        # 從檔案路徑推斷
        if file_path:
            parts = Path(file_path).parts
            for part in parts:
                # 去掉副檔名，轉換為 PascalCase 查詢
                name = Path(part).stem
                if len(name) > 3 and name not in ("src", "lib", "app", "core"):
                    components.append(name)

        # 從任務文字提取 PascalCase 組件名稱
        for m in re.finditer(r'\b[A-Z][a-zA-Z]{3,}\b', task):
            components.append(m.group())

        return list(dict.fromkeys(components))[:4]  # 去重，最多 4 個

    def _deduplicate_sections(self, sections: list[str]) -> list[str]:
        """
        A-3：輸出前語意去重（v9.0 優化）

        如果兩個 section 的 cosine similarity > 0.85，只保留第一個。
        只在 scikit-learn 已安裝時啟用，否則直接返回原始列表。

        目的：避免「JWT RS256 規則」和「JWT 驗證規則」同時出現，
        浪費 context token budget。
        """
        if len(sections) <= 1:
            return sections
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            vec  = TfidfVectorizer(min_df=1).fit_transform(sections)
            sims = cosine_similarity(vec)
            keep = []
            dropped = set()
            for i, s in enumerate(sections):
                if i in dropped:
                    continue
                keep.append(s)
                # 標記和這個 section 高度相似的後續 sections 為 dropped
                for j in range(i + 1, len(sections)):
                    if j not in dropped and sims[i][j] > 0.85:
                        dropped.add(j)
            return keep
        except ImportError:
            return sections  # scikit-learn 未安裝，跳過去重

    # ── 技術同義詞字典（不需 LLM，零成本擴展）────────────────────────────
    _SYNONYM_MAP: dict = {
        # 認證 / 授權
        "token":         ["jwt","bearer","access_token","令牌","token"],
        "jwt":           ["token","bearer","令牌","rs256","hs256","驗證","auth"],
        "令牌":           ["jwt","token","bearer","驗證","auth","認證"],
        "認證":           ["jwt","token","auth","authentication","驗證","authorize"],
        "授權":           ["auth","authorization","rbac","permission","權限"],
        "auth":          ["jwt","token","認證","授權","authentication"],
        # 支付
        "支付":           ["stripe","payment","charge","扣款","收費"],
        "stripe":        ["webhook","payment","charge","idempotency","支付"],
        "webhook":       ["stripe","idempotency","冪等","callback","回調"],
        "冪等":           ["webhook","idempotency","idempotent","重複","duplicate"],
        "扣款":           ["stripe","charge","payment","支付","重複"],
        # 資料庫
        "資料庫":         ["postgres","postgresql","mysql","mongodb","sqlite","db","database"],
        "postgresql":    ["postgres","db","database","sql","acid","連線池","connection"],
        "postgres":      ["postgresql","db","database","sql","acid","連線池"],
        "連線":           ["connection","pool","連線池","database","db"],
        "資料庫連線":      ["connection","pool","postgresql","mysql","db"],
        "關係型":         ["postgresql","mysql","sql","acid","relational","table"],
        # 通用技術
        "api":           ["endpoint","rest","http","request","response","接口"],
        "cache":         ["redis","memcached","快取","緩存"],
        "快取":           ["cache","redis","ttl","expire","緩存"],
        "部署":           ["docker","deploy","kubernetes","k8s","container","ci"],
        "效能":           ["performance","latency","throughput","slow","timeout","優化"],
        "安全":           ["security","auth","xss","sql injection","ssl","tls","https"],
        "測試":           ["test","unit","integration","e2e","mock","assert"],
        "錯誤":           ["error","exception","bug","failure","crash","問題"],
        "問題":           ["error","bug","issue","problem","failure","crash"],
    }

    def _expand_query(self, task: str) -> list[str]:
        """
        查詢擴展（Query Expansion）——解決 FTS5 精確匹配的召回率問題。

        兩個層次的擴展：
        1. 字元 N-gram 拆分（2-4 字）：「令牌認證問題」→ 「令牌」「認證」「問題」「令牌認證」
        2. 同義詞查字典：「令牌」→ JWT、token、auth、RS256...

        零成本：純 Python，不需 LLM，<1ms 完成。
        """
        # 層次 1：拆分原始查詢成單詞
        raw_words  = re.findall(r'[a-zA-Z0-9_]+', task.lower())  # 英文詞
        cjk_chars  = re.findall(r'[\u4e00-\u9fff]+', task)       # 中文詞組
        # 中文切 2~4 字的 n-gram
        cjk_ngrams = []
        for seg in cjk_chars:
            for n in (2, 3, 4):
                for i in range(len(seg) - n + 1):
                    cjk_ngrams.append(seg[i:i+n].lower())

        all_words = raw_words + cjk_ngrams + [task.lower()]
        expanded  = []
        seen      = set()

        def _add(w):
            if w and w not in seen:
                seen.add(w)
                expanded.append(w)

        # 層次 2：查同義詞字典
        for w in all_words:
            _add(w)
            for syn in self._SYNONYM_MAP.get(w, []):
                _add(syn)

        return expanded[:30]  # 上限 30 個詞

    def _extract_keywords(self, task: str) -> str:
        """提取 FTS 搜尋關鍵字（含同義詞擴展）"""
        # 移除常見的停用詞
        stopwords = {"the","a","an","is","are","was","were","be","been","being",
                     "have","has","had","do","does","did","will","would","shall",
                     "should","can","could","may","might","must","to","of","in",
                     "for","on","with","at","by","from","this","that","these",
                     "those","i","we","you","he","she","it","they","my","our",
                     "your","his","her","its","their","請","我","你","它","的","是",
                     "了","在","和","這","那","要","有","個","一","不"}
        words = re.findall(r'\w{2,}', task.lower())
        keywords = [w for w in words if w not in stopwords]
        return " ".join(keywords[:8]) if keywords else ""

    def _fmt_node(self, label: str, node: dict, max_chars: int = 400) -> str:
        title   = node.get("title", "")
        content = node.get("content", "")
        if len(content) > max_chars:
            content = content[:max_chars] + "..."
        tags = node.get("tags", [])
        tag_str = " ".join(f"`{t}`" for t in tags[:3]) if tags else ""
        # v7.0 Meta-Knowledge
        ac = node.get("applicability_condition", "") or ""
        ic = node.get("invalidation_condition",  "") or ""
        meta = ""
        if ac: meta += f"\n  ⚠ 適用條件：{ac[:120]}"
        if ic: meta += f"\n  🚫 失效條件：{ic[:120]}"
        return f"### {label}：{title}\n{content}\n{tag_str}"

    def _format_pitfalls(self, pitfalls: list) -> str:
        lines = ["## ⚠ 已知陷阱（務必先看）"]
        for p in pitfalls[:3]:
            lines.append(f"**{p.get('title','')}**")
            lines.append(p.get("content","")[:300])
        return "\n".join(lines)

    def _add_if_budget(self, sections: list, section: str, budget: int) -> int:
        """如果還有 token 預算，加入此段落"""
        cost = _count_tokens(section)
        if cost <= budget:
            sections.append(section)
            return budget - cost
        return budget

    def summarize_brain(self) -> str:
        """產生 Project Brain 的整體摘要（v4.0 彩色版）"""
        from project_brain import __version__
        from project_brain.status_renderer import render_status
        import os

        graphiti_url = os.environ.get("GRAPHITI_URL", "redis://localhost:6379")

        return render_status(
            graph        = self.graph,
            brain_dir    = self.graph.db_path.parent,
            graphiti_url = graphiti_url,
            version      = __version__,
        )
