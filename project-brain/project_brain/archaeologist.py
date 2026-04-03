"""
ProjectArchaeologist — 舊專案考古重建引擎

針對沒有任何知識記錄的舊專案，透過分析：
1. Git 歷史（所有提交）
2. 程式碼結構（AST 依賴分析）
3. 注釋和文件
4. 目錄結構（推斷架構層次）

重建出一份完整的 Project Brain 知識庫。

考古策略：
- 越舊的提交，越可能包含「為什麼這樣做」的線索
- FIXME/HACK 注釋是已知問題的寶藏
- 複雜度高的函數是技術債的訊號
- 頻繁被修改的檔案是核心組件的指標
"""
import os
import re
import ast
import json
import subprocess
from pathlib import Path
from typing import Optional
from .extractor import KnowledgeExtractor
from .graph import KnowledgeGraph


class ProjectArchaeologist:
    """舊專案考古重建器"""

    # 支援的程式碼副檔名
    CODE_EXTENSIONS = {
        ".py", ".ts", ".tsx", ".js", ".jsx",
        ".go", ".rs", ".java", ".kt", ".swift",
        ".c", ".cpp", ".h", ".hpp",
    }

    # 排除的目錄
    SKIP_DIRS = {
        "node_modules", ".git", "__pycache__", ".next",
        "dist", "build", "target", "vendor", ".venv",
        "venv", "env", ".env", "coverage",
    }

    def __init__(self, workdir: str, graph: KnowledgeGraph,
                 extractor: KnowledgeExtractor, verbose: bool = True,
                 brain_db=None):
        self.workdir   = Path(workdir)
        self.graph     = graph
        self.extractor = extractor
        self.verbose   = verbose
        self._progress = []
        # DEEP-05: optional BrainDB reference for temporal edge auto-creation
        self._brain_db = brain_db

    def _log(self, msg: str):
        if self.verbose:
            print(f"  [考古] {msg}")
        self._progress.append(msg)

    # ── 主入口 ─────────────────────────────────────────────────────

    def scan(self, limit: int = 100) -> dict:
        """
        完整考古掃描。執行順序：
        1. 目錄結構分析（快速建立骨架）
        2. Git 歷史分析（提取決策知識）
        3. 程式碼掃描（依賴關係 + 注釋）
        4. 現有文件整合（README / docs / ADR）
        5. 產生考古報告
        """
        stats = {
            "components": 0,
            "decisions":  0,
            "pitfalls":   0,
            "rules":      0,
            "adrs":       0,
            "dependencies":0,
        }

        self._log("開始考古掃描...")

        # Step 1：目錄結構分析
        self._log("Step 1/5：分析目錄結構...")
        comp_count = self._scan_directory_structure()
        stats["components"] = comp_count

        # Step 2：Git 歷史
        self._log("Step 2/5：分析 Git 歷史...")
        git_stats = self._scan_git_history()
        stats["decisions"] += git_stats.get("decisions", 0)
        stats["pitfalls"]  += git_stats.get("pitfalls",  0)

        # Step 3：程式碼掃描
        self._log("Step 3/5：掃描程式碼文件...")
        code_stats = self._scan_code_files()
        stats["pitfalls"]    += code_stats.get("pitfalls",    0)
        stats["rules"]       += code_stats.get("rules",       0)
        stats["dependencies"] = code_stats.get("dependencies", 0)

        # Step 4：現有文件
        self._log("Step 4/5：整合現有文件...")
        doc_stats = self._scan_existing_docs()
        stats["adrs"] = doc_stats.get("adrs", 0)

        # Step 5：產生報告
        self._log("Step 5/5：產生考古報告...")
        report = self._generate_report(stats)

        self._log(f"考古完成！發現 {sum(stats.values())} 筆知識")
        return {"stats": stats, "report": report, "progress": self._progress}

    # ── Step 1：目錄結構 ───────────────────────────────────────────

    def _scan_directory_structure(self) -> int:
        """分析目錄結構，識別主要組件"""
        count = 0
        structure = []

        for path in sorted(self.workdir.iterdir()):
            if path.name.startswith(".") or path.name in self.SKIP_DIRS:
                continue
            if path.is_dir():
                structure.append(f"/{path.name}/")
                # 把每個頂層目錄視為一個組件
                node_id = self.extractor.make_id("comp", path.name)
                self.graph.add_node(
                    node_id   = node_id,
                    node_type = "Component",
                    title     = path.name,
                    content   = f"目錄：{path.name}，包含 {len(list(path.iterdir()))} 個子項目",
                    tags      = ["component", "directory"],
                    source_url= str(path.relative_to(self.workdir)),
                )
                count += 1

        # 記錄整體結構
        if structure:
            self.graph.add_node(
                node_id   = "project-structure",
                node_type = "Component",
                title     = "專案目錄結構",
                content   = "頂層目錄：\n" + "\n".join(structure),
                tags      = ["structure", "overview"],
            )

        self._log(f"  識別 {count} 個頂層組件")
        return count

    # ── Step 2：Git 歷史 ───────────────────────────────────────────

    def _scan_git_history(self) -> dict:
        """分析 git 歷史，提取決策和踩坑"""
        stats = {"decisions": 0, "pitfalls": 0}
        try:
            results = self.extractor.from_git_history(limit=limit)
            for result in results:
                meta = result.get("_meta", {})
                commit_hash   = meta.get("commit", "")
                commit_date   = meta.get("date", "")
                commit_node_id = (
                    self.extractor.make_id("commit", commit_hash)
                    if commit_hash else None
                )
                for chunk in result.get("knowledge_chunks", []):
                    node_id = self.extractor.make_id(
                        chunk["type"], chunk["title"] + chunk["content"]
                    )
                    self.graph.add_node(
                        node_id   = node_id,
                        node_type = chunk["type"],
                        title     = chunk["title"],
                        content   = chunk["content"],
                        tags      = chunk.get("tags", []),
                        source_url= commit_hash,
                        author    = meta.get("author", ""),
                        meta      = {"confidence": chunk.get("confidence", 0.8)},
                    )
                    if chunk["type"] == "Decision": stats["decisions"] += 1
                    if chunk["type"] == "Pitfall":  stats["pitfalls"]  += 1
                    # DEEP-05: create temporal edge from commit node to knowledge node
                    if self._brain_db is not None and commit_node_id:
                        try:
                            self._brain_db.add_temporal_edge(
                                source_id  = commit_node_id,
                                relation   = "INTRODUCES",
                                target_id  = node_id,
                                valid_from = commit_date or None,
                                content    = f"commit {commit_hash[:8]} introduced {chunk['type']}: {chunk['title'][:60]}",
                            )
                        except Exception:
                            pass

                # 記錄依賴關係
                for dep in result.get("dependencies_detected", []):
                    from_id = self.extractor.make_id("comp", dep["from"])
                    to_id   = self.extractor.make_id("comp", dep["to"])
                    # 確保節點存在
                    if not self.graph.get_node(from_id):
                        self.graph.add_node(from_id, "Component", dep["from"])
                    if not self.graph.get_node(to_id):
                        self.graph.add_node(to_id, "Component", dep["to"])
                    self.graph.add_edge(
                        from_id, "DEPENDS_ON", to_id,
                        note=dep.get("reason", "")
                    )
                    stats.setdefault("dependencies", 0)
                    stats["dependencies"] += 1

        except Exception as e:
            self._log(f"  Git 歷史分析失敗：{e}")

        self._log(f"  從 Git 提取 {stats['decisions']} 個決策，{stats['pitfalls']} 個踩坑")
        return stats

    # ── Step 3：程式碼掃描 ───────────────────────────────────────────

    def _scan_code_files(self) -> dict:
        """掃描程式碼文件，提取注釋知識和依賴關係"""
        stats = {"pitfalls": 0, "rules": 0, "dependencies": 0}

        # 找出最重要的檔案（被修改最多次的）
        hot_files = self._get_hot_files(limit=30)

        for file_path in hot_files:
            if not file_path.exists():
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                rel_path = str(file_path.relative_to(self.workdir))

                # 提取注釋知識
                comment_result = self.extractor.from_comments(rel_path, content)
                for chunk in comment_result.get("knowledge_chunks", []):
                    node_id = self.extractor.make_id(
                        chunk["type"], rel_path + chunk["title"]
                    )
                    self.graph.add_node(
                        node_id   = node_id,
                        node_type = chunk["type"],
                        title     = chunk["title"],
                        content   = chunk["content"],
                        tags      = chunk.get("tags", []) + ["from-comment"],
                        source_url= rel_path,
                    )
                    if chunk["type"] == "Pitfall": stats["pitfalls"] += 1
                    if chunk["type"] == "Rule":    stats["rules"] += 1

                # Python 依賴分析
                if file_path.suffix == ".py":
                    deps = self._extract_python_imports(content, rel_path)
                    stats["dependencies"] += len(deps)

                # TypeScript/JavaScript 依賴分析
                elif file_path.suffix in (".ts", ".tsx", ".js", ".jsx"):
                    deps = self._extract_ts_imports(content, rel_path)
                    stats["dependencies"] += len(deps)

            except Exception:
                continue

        self._log(f"  從程式碼提取 {stats['pitfalls']} 個踩坑，{stats['rules']} 個規則")
        return stats

    def _get_hot_files(self, limit: int = 30) -> list:
        """找出 git 歷史中被修改最多次的檔案"""
        try:
            output = subprocess.check_output(
                ["git", "log", "--pretty=format:", "--name-only",
                 "--diff-filter=M", "-n", "500"],
                cwd=str(self.workdir),
                stderr=subprocess.DEVNULL,
                text=True,
            )
            from collections import Counter
            counts = Counter(
                f for f in output.strip().split("\n") if f.strip()
            )
            hot = [
                self.workdir / path
                for path, _ in counts.most_common(limit)
                if Path(self.workdir / path).suffix in self.CODE_EXTENSIONS
            ]
            return hot
        except Exception:
            # fallback：直接列出所有程式碼檔案
            all_files = []
            for ext in self.CODE_EXTENSIONS:
                all_files.extend(self.workdir.rglob(f"*{ext}"))
            return [
                f for f in all_files
                if not any(d in f.parts for d in self.SKIP_DIRS)
            ][:limit]

    def _extract_python_imports(self, content: str, file_path: str) -> list:
        """提取 Python import 依賴"""
        deps = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        deps.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        deps.append(node.module)
        except SyntaxError:
            # Fallback to regex
            for m in re.finditer(r'^(?:from|import)\s+([\w.]+)', content, re.MULTILINE):
                deps.append(m.group(1))
        return deps

    def _extract_ts_imports(self, content: str, file_path: str) -> list:
        """提取 TypeScript/JavaScript import 依賴"""
        deps = []
        for m in re.finditer(
            r'(?:import|from)\s+["\']([^"\']+)["\']', content
        ):
            module = m.group(1)
            # 只記錄本地模組（不記錄 npm 套件）
            if module.startswith("."):
                deps.append(module)
        return deps

    # ── Step 4：現有文件 ───────────────────────────────────────────

    def _scan_existing_docs(self) -> dict:
        """整合現有的 README、docs/、ADR 文件"""
        stats = {"adrs": 0}

        # README
        for readme in ["README.md", "README.rst", "README.txt"]:
            p = self.workdir / readme
            if p.exists():
                content = p.read_text(encoding="utf-8", errors="ignore")
                self.graph.add_node(
                    node_id   = "readme",
                    node_type = "Component",
                    title     = "README（專案說明）",
                    content   = content[:3000],
                    tags      = ["readme", "overview", "documentation"],
                    source_url= readme,
                )
                break

        # ADR 文件
        for adr_dir_name in ["docs/adr", "docs/decisions", "adr", "decisions"]:
            adr_dir = self.workdir / adr_dir_name
            results = self.extractor.from_adr_files(adr_dir)
            for r in results:
                for chunk in r.get("knowledge_chunks", []):
                    node_id = self.extractor.make_id("adr", chunk["title"])
                    self.graph.add_node(
                        node_id   = node_id,
                        node_type = "ADR",
                        title     = chunk["title"],
                        content   = chunk["content"][:2000],
                        tags      = chunk.get("tags", []),
                        source_url= chunk.get("source_url", ""),
                    )
                    stats["adrs"] += 1

        self._log(f"  整合 {stats['adrs']} 個 ADR 文件")
        return stats

    # ── Step 5：報告 ───────────────────────────────────────────────

    def _generate_report(self, stats: dict) -> str:
        graph_stats = self.graph.stats()
        report = f"""
# Project Brain 考古報告

## 掃描結果

| 類型 | 數量 |
|------|------|
| 系統組件 | {stats.get('components', 0)} |
| 架構決策 | {stats.get('decisions', 0)} |
| 已知陷阱 | {stats.get('pitfalls', 0)} |
| 業務規則 | {stats.get('rules', 0)} |
| ADR 文件 | {stats.get('adrs', 0)} |
| 依賴關係 | {stats.get('dependencies', 0)} |

## 知識圖譜統計

- 總節點數：{graph_stats['nodes']}
- 總關係數：{graph_stats['edges']}

## 知識圖譜（Mermaid）

```mermaid
{self.graph.to_mermaid(limit=20)}
```

## 下一步

1. 執行 `brain context "你的任務"` 測試 Context 注入效果
2. 執行 `brain learn` 觸發手動知識積累
3. 在 Claude Code 中使用 `@腦` 或 `/brain` 存取知識庫
"""
        return report
