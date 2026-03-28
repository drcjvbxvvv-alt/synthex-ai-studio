from __future__ import annotations
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


# Token 估算（粗略：4 字元 ≈ 1 token）
CHARS_PER_TOKEN = 4
MAX_CONTEXT_TOKENS = 6000   # 為任務本身留 2K


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
                 vector_memory: "VectorMemory | None" = None):
        self.graph     = graph
        self.brain_dir = brain_dir
        self.vm        = vector_memory   # v1.1 向量記憶（可為 None）

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
        keywords = self._extract_keywords(task)
        if keywords:
            pitfalls  = []
            decisions = []
            rules     = []
            adrs      = []

            # v1.1：向量語義搜尋（若 chromadb 已安裝）
            if self.vm and self.vm.available:
                vm_results = self.vm.search(task, top_k=8)
                pitfalls  = [r for r in vm_results if r.get("type") == "Pitfall"][:3]
                decisions = [r for r in vm_results if r.get("type") == "Decision"][:2]
                rules     = [r for r in vm_results if r.get("type") == "Rule"][:2]
                adrs      = [r for r in vm_results if r.get("type") == "ADR"][:1]

            # FTS5 備援：向量搜尋空結果或未安裝時啟用
            if not any([pitfalls, decisions, rules, adrs]):
                pitfalls  = self.graph.search_nodes(keywords, node_type="Pitfall",  limit=3)
                decisions = self.graph.search_nodes(keywords, node_type="Decision", limit=2)
                rules     = self.graph.search_nodes(keywords, node_type="Rule",     limit=2)
                adrs      = self.graph.search_nodes(keywords, node_type="ADR",      limit=1)

            for pitfall in pitfalls:
                s = self._fmt_node("⚠ 已知踩坑", pitfall)
                budget = self._add_if_budget(sections, s, budget)

            for rule in rules:
                s = self._fmt_node("📋 業務規則", rule)
                budget = self._add_if_budget(sections, s, budget)

            for dec in decisions:
                s = self._fmt_node("🎯 架構決策", dec)
                budget = self._add_if_budget(sections, s, budget)

            for adr in adrs:
                s = self._fmt_node("📄 ADR", adr, max_chars=800)
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

        return header + "\n\n".join(sections) + footer

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

    def _extract_keywords(self, task: str) -> str:
        """提取 FTS 搜尋關鍵字"""
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
        return f"### {label}：{title}\n{content}\n{tag_str}"

    def _format_pitfalls(self, pitfalls: list) -> str:
        lines = ["## ⚠ 已知陷阱（務必先看）"]
        for p in pitfalls[:3]:
            lines.append(f"**{p.get('title','')}**")
            lines.append(p.get("content","")[:300])
        return "\n".join(lines)

    def _add_if_budget(self, sections: list, section: str, budget: int) -> int:
        """如果還有 token 預算，加入此段落"""
        cost = len(section) // CHARS_PER_TOKEN
        if cost <= budget:
            sections.append(section)
            return budget - cost
        return budget

    def summarize_brain(self) -> str:
        """產生 Project Brain 的整體摘要（v4.0 彩色版）"""
        from core.brain import __version__
        from core.brain.status_renderer import render_status
        import os

        graphiti_url = os.environ.get("GRAPHITI_URL", "redis://localhost:6379")

        return render_status(
            graph        = self.graph,
            brain_dir    = self.graph.db_path.parent,
            graphiti_url = graphiti_url,
            version      = __version__,
        )
