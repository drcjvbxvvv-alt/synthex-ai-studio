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
import logging
import os
import re
import json
from pathlib import Path
from .graph import KnowledgeGraph
from typing import TypedDict
if TYPE_CHECKING:
    from .vector_memory import VectorMemory


class NodeDict(TypedDict, total=False):
    """知識節點的型別定義，供 _node_priority 等內部方法使用。
    total=False 表示所有欄位為選填（與 SQLite Row → dict 的實際狀況一致）。
    """
    id:                     str
    type:                   str
    title:                  str
    content:                str
    confidence:             float
    effective_confidence:   float
    importance:             float
    is_pinned:              int
    access_count:           int
    emotional_weight:       float
    scope:                  str
    created_at:             str
    updated_at:             str
    is_deprecated:          int
    valid_until:            str
    applicability_condition:str
    invalidation_condition: str
    tags:                   str

logger = logging.getLogger(__name__)

# A-3/E-6: env-configurable — set BRAIN_MAX_TOKENS to override per deployment
MAX_CONTEXT_TOKENS = int(os.environ.get("BRAIN_MAX_TOKENS", "6000"))

# P-1: synonym expansion cap — set BRAIN_EXPAND_LIMIT to reduce noise
# Default 15 (was 30). Lower = less synonym noise, higher = better recall.
EXPAND_LIMIT = int(os.environ.get("BRAIN_EXPAND_LIMIT", "15"))

# RQ-1: semantic dedup threshold — set BRAIN_DEDUP_THRESHOLD to tune
# 0.85 = only deduplicate near-identical sections (default, conservative).
# Lower (e.g. 0.70) = more aggressive dedup, fewer redundant sections.
DEDUP_THRESHOLD = float(os.environ.get("BRAIN_DEDUP_THRESHOLD", "0.85"))


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
                except Exception as _e:
                    # STB-01: 不再靜默吞下，確保問題可觀察
                    logger.warning(
                        "ContextEngineer: BrainDB 初始化失敗，降級為 KnowledgeGraph-only 模式。"
                        "執行 brain doctor 查看詳情。錯誤：%s", _e
                    )
        self._brain_db = brain_db  # A-11/A-13

        # PH2-05: load custom synonyms from .brain/synonyms.json if present,
        # merging with the built-in map so built-in terms remain available.
        synonyms_path = Path(brain_dir) / "synonyms.json"
        if synonyms_path.exists():
            try:
                custom = json.loads(synonyms_path.read_text(encoding="utf-8"))
                if isinstance(custom, dict):
                    merged = dict(self._SYNONYM_MAP)
                    merged.update(custom)  # custom keys override built-in
                    self._SYNONYM_MAP = merged
            except Exception:
                pass  # 降級：沿用內建同義詞表

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
        self._budget_skipped  = 0   # STB-05: reset per build()
        _shown_node_ids: list[str] = []  # STAB-07: nodes actually shown in context
        logger.debug("context.build start: task=%r file=%r budget=%d", task[:60], current_file, budget)

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

            # Decay 即時化：取得 BrainDB._effective_confidence 靜態方法的參考
            # 讓 KnowledgeGraph 節點（無 effective_confidence 欄位）也能即時算 F1+F7
            try:
                from .brain_db import BrainDB as _BDB_ec
                _eff_conf_fn = _BDB_ec._effective_confidence
            except Exception:
                _eff_conf_fn = None

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
                pinned = 2.5 if (node.get("is_pinned") or 0) else 0.0
                # Decay 即時化：BrainDB 節點已有 effective_confidence；
                # KnowledgeGraph 節點無此欄位，即時用 F1+F7 計算
                if node.get("effective_confidence") is not None:
                    confidence = float(node["effective_confidence"])
                elif _eff_conf_fn is not None:
                    confidence = _eff_conf_fn(node)
                else:
                    confidence = float(node.get("confidence") or 0.8)
                importance  = float(node.get("importance") or 0.5)
                access_cnt  = int(node.get("access_count") or 0)
                # 正規化：50 次以上視為飽和（避免極端值主導）
                access_norm = min(1.0, access_cnt / 50.0)
                # BUG-11 fix: include emotional_weight in ranking
                ew          = float(node.get("emotional_weight") or 0.5)
                ew_boost    = (ew - 0.5) * 0.10   # range: -0.05 ~ +0.05
                return (
                    pinned
                    + confidence  * 0.35
                    + access_norm * 0.25
                    + importance  * 0.15
                    + ew_boost
                )

            # 所有節點放進 priority queue，高優先度先填
            all_nodes: list[tuple[float, str, dict]] = []
            for n in pitfalls:  all_nodes.append((_node_priority(n), "⚠ 已知踩坑", n))
            for n in rules:     all_nodes.append((_node_priority(n), "📋 業務規則", n))
            for n in decisions: all_nodes.append((_node_priority(n), "🎯 架構決策", n))
            for n in adrs:      all_nodes.append((_node_priority(n), "📄 ADR",      n))
            for n in notes:     all_nodes.append((_node_priority(n), "📝 筆記",     n))  # A-24

            all_nodes.sort(key=lambda x: x[0], reverse=True)  # 高分排前

            # STAB-07: track IDs of nodes that actually fit in budget (no title-matching)
            for priority, label, node in all_nodes:
                max_c = 800 if label == "📄 ADR" else 400
                s     = self._fmt_node(label, node, max_chars=max_c)
                prev_len = len(sections)
                budget   = self._add_if_budget(sections, s, budget)
                if len(sections) > prev_len and node.get('id'):
                    # Node made it into context — track for SR batch update below
                    _shown_node_ids.append(node['id'])

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

        # 5. 沒有找到任何知識時的提示（FLY-01：冷啟動引導）
        if not sections:
            _hint = (
                "---\n"
                "## 📖 Project Brain — 尚無相關知識\n\n"
                f"目前知識庫中找不到與「{task[:60]}」相關的記錄。\n\n"
                "建議立即記錄你遇到的問題或決策，讓 Brain 下次能提供幫助：\n"
                "```\n"
                f'brain add "遇到的問題或決策" --kind Pitfall\n'
                "```\n"
                "或透過 MCP：`add_knowledge(title=..., content=..., kind=\"Pitfall\")`\n"
                "---\n"
            )
            return _hint

        header = (
            "---\n"
            "## 📖 Project Brain — 專案歷史知識\n"
            "（以下是從程式碼歷史自動提取的相關知識，供參考）\n\n"
        )
        # STB-05: 截斷提示，讓 Agent 知道有更多知識未顯示
        _skipped = getattr(self, "_budget_skipped", 0)
        footer = (
            f"\n\n> ⚠ 另有 {_skipped} 筆相關知識因 context 長度限制未顯示，"
            f"執行 `brain search \"{task[:30]}\"` 查看完整結果。\n---\n"
            if _skipped > 0 else "\n---\n"
        )

        # A-3：輸出前語意去重（只在 scikit-learn 已安裝時啟用）
        # BUG-05 fix: pre-assign result so that any exception after this point
        # still has a valid string to return (avoids UnboundLocalError / None).
        result = header + "\n\n".join(sections) + footer
        try:
            sections = self._deduplicate_sections(sections)
            result   = header + "\n\n".join(sections) + footer
        except Exception as _de:
            logger.debug("context: dedup skipped (%s), using original result", _de)
        # Spaced Repetition: 批次記錄訪問（v9.0 修補 race condition）
        # STAB-07: use _shown_node_ids tracked during main loop; no title-substring matching
        try:
            _node_ids = _shown_node_ids
            if _node_ids:
                # DEF-10 fix: synchronous SR update via BrainDB._write_guard() (no daemon thread race)
                try:
                    if self._brain_db is not None:
                        with self._brain_db._write_guard():
                            self._brain_db.conn.executemany(
                                "UPDATE nodes SET access_count=access_count+1,"
                                " last_accessed=datetime('now') WHERE id=?",
                                [(nid,) for nid in _node_ids]
                            )
                            self._brain_db.conn.commit()
                    else:
                        self.graph._conn.executemany(
                            "UPDATE nodes SET access_count=access_count+1,"
                            " last_accessed=datetime('now') WHERE id=?",
                            [(nid,) for nid in _node_ids]
                        )
                        self.graph._conn.commit()
                except Exception as _e:
                    # STB-02: SR 失敗需可觀察
                    logger.debug("Spaced Repetition 批次更新失敗：%s", _e)
        except Exception as _se:
            logger.debug("context: SR block failed: %s", _se)
        # P1-B: prepend causal chain conclusions to result
        try:
            _db = getattr(self, '_brain_db', None)
            if _db is not None:
                _all_nodes = _db.all_nodes(limit=50)
                # Find nodes whose titles appear in this result (title-match heuristic)
                _ids = [n['id'] for n in _all_nodes
                        if n.get('title','') and n['title'] in result]
                _chain = self._build_causal_chain(_ids[:5], db=_db)
                if _chain:
                    result = _chain + result
        except Exception as _ce:
            logger.debug("context: causal chain failed: %s", _ce)
        # DEEP-01: append reasoning chain when edges exist
        try:
            _rc = self.build_reasoning_chain(task)
            if _rc:
                result = (result or "") + _rc
        except Exception as _re:
            logger.debug("context: reasoning chain failed: %s", _re)
        result = result or ""
        logger.debug("context.build done: sections=%d chars=%d", len(sections), len(result))
        return result  # BUG-05 fix: guarantee str return, never None

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
                    # H-3: label edge with semantic confidence tier
                    from project_brain.utils import confidence_label as _clabel
                    if tgt_conf is not None:
                        tgt_conf_str = f"conf={tgt_conf:.2f} {_clabel(tgt_conf)}"
                    else:
                        tgt_conf_str = "~ 推斷"   # H-3: unknown conf = inferred
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
                    if j not in dropped and sims[i][j] > DEDUP_THRESHOLD:  # RQ-1: env-configurable
                        dropped.add(j)
            return keep
        except ImportError:
            return sections  # scikit-learn 未安裝，跳過去重

    # ── 技術同義詞字典（不需 LLM，零成本擴展）────────────────────────────
    # REF-02: single source of truth in synonyms.py
    from .synonyms import SYNONYM_MAP as _SYNONYM_MAP_BASE  # noqa: E402
    _SYNONYM_MAP: dict = dict(_SYNONYM_MAP_BASE)  # mutable copy for custom merge


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
        # P-1: 原始詞彙優先加入，每個詞最多取 3 個同義詞，避免無關擴展雜訊
        for w in all_words:
            _add(w)
        for w in all_words:
            for syn in self._SYNONYM_MAP.get(w, [])[:3]:  # P-1: cap 3 synonyms/term
                _add(syn)

        return expanded[:EXPAND_LIMIT]  # P-1: env-configurable (was hardcoded 30)

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
        from project_brain.utils import confidence_label
        import datetime as _dt
        title   = node.get("title", "")
        content = node.get("content", "")
        if len(content) > max_chars:
            content = content[:max_chars] + "..."
        tags = node.get("tags", [])
        tag_str = " ".join(f"`{t}`" for t in tags[:3]) if tags else ""
        # H-1: attach semantic confidence tier so agents know how much to trust this node
        conf   = float(node.get("effective_confidence") or node.get("confidence") or 0.8)
        clabel = confidence_label(conf)
        # STB-03: 若無 effective_confidence（Decay Engine 從未執行）且節點超過 90 天，
        # 加上提示避免 Agent 對過時高分知識過度信任
        stale_warning = ""
        if not node.get("effective_confidence"):
            _raw_date = node.get("updated_at") or node.get("created_at") or ""
            if _raw_date:
                try:
                    _date = _dt.datetime.fromisoformat(_raw_date.replace("Z", "+00:00"))
                    _now  = _dt.datetime.now(_dt.timezone.utc)
                    if (_now - _date.replace(tzinfo=_date.tzinfo or _dt.timezone.utc)).days > 90:
                        stale_warning = " ⏰ 信心分數超過 90 天未更新，建議執行 brain decay"
                except Exception:
                    pass
        # v7.0 Meta-Knowledge (H-4 fix: meta was built but never included in output)
        ac = node.get("applicability_condition", "") or ""
        ic = node.get("invalidation_condition",  "") or ""
        meta = ""
        if ac: meta += f"\n  ⚠ 適用條件：{ac[:120]}"
        if ic: meta += f"\n  🚫 失效條件：{ic[:120]}"
        return f"### {label}：{title} [{clabel}{stale_warning}]\n{content}\n{tag_str}{meta}"

    def _format_pitfalls(self, pitfalls: list) -> str:
        lines = ["## ⚠ 已知陷阱（務必先看）"]
        for p in pitfalls[:3]:
            lines.append(f"**{p.get('title','')}**")
            lines.append(p.get("content","")[:300])
        return "\n".join(lines)

    def _add_if_budget(self, sections: list, section: str, budget: int) -> int:
        """如果還有 token 預算，加入此段落；否則累計跳過計數（STB-05）"""
        cost = _count_tokens(section)
        if cost <= budget:
            sections.append(section)
            return budget - cost
        # STB-05: 追蹤因 budget 被截掉的節點數
        self._budget_skipped = getattr(self, "_budget_skipped", 0) + 1
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
