"""
ProjectBrain — 主引擎

統一入口，管理整個 .brain/ 目錄結構：

.brain/
├── knowledge_graph.db     ← SQLite 知識圖譜
├── vectors/               ← 向量記憶（簡易實作，未來可替換 pgvector）
├── adrs/                  ← 自動生成的 ADR 快照
├── sessions/              ← 每次 AI 對話的知識增量
└── config.json            ← Brain 設定
"""
import os
import json
import time
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime
from .graph import KnowledgeGraph
from .extractor import KnowledgeExtractor
from .context import ContextEngineer

try:
    from core.config import cfg
except ImportError:
    cfg = None  # Brain 可獨立使用（無 synthex 主程式時降級）
from .archaeologist import ProjectArchaeologist
from .vector_memory  import VectorMemory          # v1.1
from .temporal_graph import TemporalGraph         # v1.1
from .v2.shared_registry import SharedRegistry    # v2.0
from .v2.decay_engine    import DecayEngine        # v2.0
from .v2.counterfactual  import (                  # v2.0
    CounterfactualEngine, CounterfactualQuery, CounterfactualResult
)
from .shared_registry import SharedRegistry       # v2.0
from .decay_engine   import DecayEngine           # v2.0
from .counterfactual import CounterfactualReasoner # v2.0


class ProjectBrain:
    """
    Project Brain 主引擎（v3.0 — 三層認知架構）

    使用方式：
        brain = ProjectBrain("/path/to/project")
        brain.init()                          # 新專案初始化
        brain.scan()                          # 舊專案考古掃描

        # v3.0：三層查詢
        result  = brain.router.query("修復登入 bug")
        context = result.to_context_string()

        # v3.0：三層學習
        brain.router.learn_from_phase(9, "BYTE", frontend_code)
        brain.router.learn_from_commit("abc123", "fix: login", "ahern", [...])

        # 向後相容（v1.0 + v2.0 API）
        ctx = brain.get_context("修復登入 bug")
        brain.learn_from_commit("abc123")
    """

    BRAIN_DIR   = ".brain"
    CONFIG_FILE = "config.json"

    def __init__(self, workdir: str, graphiti_url: str = "bolt://localhost:7687"):
        self.workdir      = Path(workdir).resolve()
        self.brain_dir    = self.workdir / self.BRAIN_DIR
        self._graphiti_url = graphiti_url

        # 延遲初始化（只有呼叫 init/scan 後才建立）
        self._graph     = None
        self._extractor = None
        self._context   = None
        self._config    = {}
        # v1.1
        self._vector    = None
        self._temporal  = None
        # v2.0
        self._registry  = None
        self._decay     = None
        self._cf        = None
        # v3.0
        self._router:   "BrainRouter | None" = None
        # v4.0
        self._validator:  None = None
        self._federation: None = None
        self._distiller:  None = None

    # ── 屬性懶初始化 ──────────────────────────────────────────────

    @property
    def graph(self) -> KnowledgeGraph:
        if self._graph is None:
            self.brain_dir.mkdir(parents=True, exist_ok=True)
            self._graph = KnowledgeGraph(self.brain_dir)
        return self._graph

    @property
    def extractor(self) -> KnowledgeExtractor:
        if self._extractor is None:
            self._extractor = KnowledgeExtractor(str(self.workdir))
        return self._extractor

    @property
    def context_engineer(self) -> ContextEngineer:
        if self._context is None:
            self._context = ContextEngineer(
                self.graph, self.brain_dir, self.vector_memory
            )
        return self._context

    @property
    def vector_memory(self) -> VectorMemory:
        if self._vector is None:
            self.brain_dir.mkdir(parents=True, exist_ok=True)
            self._vector = VectorMemory(self.brain_dir)
        return self._vector

    @property
    def temporal_graph(self) -> TemporalGraph:
        if self._temporal is None:
            self._temporal = TemporalGraph(self.graph)
        return self._temporal

    @property
    def shared_registry(self) -> SharedRegistry:
        if self._shared is None:
            ns = self._config.get("project_name",
                                   self.workdir.name).replace(" ", "-")[:64]
            self._shared = SharedRegistry(namespace=ns)
        return self._shared

    @property
    def decay_engine(self) -> DecayEngine:
        if self._decay is None:
            self._decay = DecayEngine(self.graph, self.workdir)
        return self._decay

    @property
    def counterfactual(self) -> CounterfactualEngine:
        if self._cf is None:
            self._cf = CounterfactualEngine(self.graph, self.workdir)
        return self._cf

    @property
    def router(self) -> "BrainRouter":
        """
        v3.0 三層認知路由器。
        懶初始化：第一次呼叫時建立 L1 + L2 + L3 連線。
        """
        if self._router is None:
            from core.brain.router import BrainRouter
            self._router = BrainRouter(
                brain_dir    = self.brain_dir,
                l3_brain     = self,       # 自身作為 L3
                graphiti_url = self._graphiti_url,
                agent_name   = self._config.get("project_name", "synthex"),
            )
        return self._router

    @property
    def validator(self) -> "KnowledgeValidator":
        """v4.0 自主知識驗證器（懶初始化）"""
        if self._validator is None:
            from core.brain.knowledge_validator import KnowledgeValidator
            self._validator = KnowledgeValidator(
                graph     = self.graph,
                workdir   = self.workdir,
                brain_dir = self.brain_dir,
            )
        return self._validator

    @property
    def federation(self) -> "KnowledgeFederation":
        """v4.0 跨組織匿名知識共享（懶初始化）"""
        if self._federation is None:
            from core.brain.federation import KnowledgeFederation
            self._federation = KnowledgeFederation(
                brain_dir = self.brain_dir,
            )
        return self._federation

    @property
    def distiller(self) -> "KnowledgeDistiller":
        """v4.0 知識蒸餾器（懶初始化）"""
        if self._distiller is None:
            from core.brain.knowledge_distiller import KnowledgeDistiller
            self._distiller = KnowledgeDistiller(
                graph     = self.graph,
                brain_dir = self.brain_dir,
                workdir   = self.workdir,
            )
        return self._distiller

    # ── 公開 API ──────────────────────────────────────────────────

    def init(self, project_name: str = "") -> str:
        """
        新專案初始化：
        1. 建立 .brain/ 目錄結構
        2. 設定 Git Hook（commit-msg 自動學習）
        3. 建立初始設定檔
        4. 加入 .gitignore（不提交 DB，提交 ADR）
        """
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        (self.brain_dir / "vectors").mkdir(exist_ok=True)
        (self.brain_dir / "adrs").mkdir(exist_ok=True)
        (self.brain_dir / "sessions").mkdir(exist_ok=True)

        # ── 強制建立 knowledge_graph.db ──────────────────────
        # graph 是 lazy property，必須主動存取才會建立 SQLite 檔案。
        # 不論 git 歷史是否存在，都應先把 DB 建好。
        _ = self.graph   # 觸發 KnowledgeGraph.__init__ → 建立 .db 檔案

        # 設定檔
        name = project_name or self.workdir.name
        config = {
            "project_name":    name,
            "initialized_at":  datetime.now().isoformat(),
            "version":         "1.0",
            "auto_learn":      True,
            "extract_on_commit": True,
            "model":           cfg.model_sonnet,  # 使用 config.py 集中管理
        }
        (self.brain_dir / self.CONFIG_FILE).write_text(
            json.dumps(config, ensure_ascii=False, indent=2)
        )
        self._config = config

        # Git Hook
        self._setup_git_hook()

        # .gitignore
        self._setup_gitignore()

        # ── 偵測 git 狀態（不呼叫 API，只看 commit 數量）──────
        has_git      = False
        commit_count = 0
        has_api_key  = bool(os.environ.get("ANTHROPIC_API_KEY"))

        try:
            chk = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=str(self.workdir), capture_output=True
            )
            if chk.returncode == 0:
                has_git = True
                log = subprocess.run(
                    ["git", "rev-list", "--count", "HEAD"],
                    cwd=str(self.workdir), capture_output=True, text=True
                )
                if log.returncode == 0:
                    commit_count = int(log.stdout.strip() or "0")
        except (FileNotFoundError, ValueError):
            pass

        # 若已設定 API key + 有 commit → 快速初始掃描
        learned = 0
        if has_git and has_api_key and commit_count > 0:
            try:
                results = self.extractor.from_git_history(limit=20)
                for r in results:
                    for chunk in r.get("knowledge_chunks", []):
                        self._store_chunk(chunk, r.get("_meta", {}))
                        learned += 1
            except Exception:
                pass

        # ── 組裝輸出 ─────────────────────────────────────────
        if has_git and commit_count > 0:
            if has_api_key:
                git_tip = f"  • Git 歷史掃描：已學習 {learned} 筆知識"
            else:
                _tip = ""
                _tip += "  偵測到 " + str(commit_count) + " 個 commit，但需要 API key 提取知識\n"
                _tip += "  請設定後執行：\n"
                _tip += "    export ANTHROPIC_API_KEY='sk-ant-...'\n"
                _tip += "    python synthex.py brain scan --workdir " + str(self.workdir)
                git_tip = _tip
        elif has_git:
            git_tip = "  • Git repo 已偵測（尚無 commit，提交後自動學習）"
        else:
            git_tip = "  • 非 git 目錄，請用 brain add 手動加入知識"

        return f"""
✅ Project Brain 初始化完成

專案：{name}
目錄：{self.brain_dir}
狀態：
  • 知識圖譜 DB 已建立（knowledge_graph.db）
  • 設定檔：{self.brain_dir / self.CONFIG_FILE}
  • Git Hook 已設定（每次 commit 自動學習）
{git_tip}

下一步：
  python synthex.py brain scan   --workdir {self.workdir}
  python synthex.py brain status --workdir {self.workdir}
"""

    def scan(self, verbose: bool = True) -> str:
        """
        舊專案考古掃描：
        完整分析 git 歷史 + 程式碼 + 文件，重建知識圖譜
        """
        self.brain_dir.mkdir(parents=True, exist_ok=True)

        archaeologist = ProjectArchaeologist(
            workdir   = str(self.workdir),
            graph     = self.graph,
            extractor = self.extractor,
            verbose   = verbose,
        )

        result = archaeologist.scan()

        # 儲存報告
        report_path = self.brain_dir / "SCAN_REPORT.md"
        report_path.write_text(result["report"], encoding="utf-8")

        return result["report"]

    def get_context(self, task: str, current_file: str = "") -> str:
        """
        為任務動態組裝最佳 Context 注入片段（v3.0 三層聚合）。

        v3.0 升級：
          若 router 已初始化，使用三層聚合查詢（L1+L2+L3）。
          否則降級到 v2.0 的 ContextEngineer.build()（向後相容）。
        """
        if not self.brain_dir.exists():
            return ""

        # v3.0 路徑：三層聚合
        if self._router is not None:
            result = self._router.query(task)
            context_3layer = result.to_context_string()
            if context_3layer:
                return context_3layer

        # v2.0 降級路徑（向後相容）
        return self.context_engineer.build(task, current_file)

    def learn_from_commit(self, commit_hash: str = "HEAD") -> int:
        """
        從指定的 git commit 學習知識。
        由 Git Hook 自動呼叫，也可以手動觸發。
        """
        try:
            msg = subprocess.check_output(
                ["git", "log", "-1", "--pretty=%s", commit_hash],
                cwd=str(self.workdir), text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            diff = subprocess.check_output(
                ["git", "show", "--unified=3", commit_hash],
                cwd=str(self.workdir), text=True,
                stderr=subprocess.DEVNULL,
            )[:3000]
            author = subprocess.check_output(
                ["git", "log", "-1", "--pretty=%ae", commit_hash],
                cwd=str(self.workdir), text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            return 0

        result = self.extractor.from_git_commit(commit_hash, msg, diff)
        meta   = {"commit": commit_hash, "author": author,
                  "date": datetime.now().isoformat()}
        learned = 0
        for chunk in result.get("knowledge_chunks", []):
            self._store_chunk(chunk, meta)
            learned += 1

        # 記錄依賴關係
        for dep in result.get("dependencies_detected", []):
            from_id = self.extractor.make_id("comp", dep["from"])
            to_id   = self.extractor.make_id("comp", dep["to"])
            for nid, name in [(from_id, dep["from"]), (to_id, dep["to"])]:
                if not self.graph.get_node(nid):
                    self.graph.add_node(nid, "Component", name)
            self.graph.add_edge(
                from_id, "DEPENDS_ON", to_id,
                note=dep.get("reason","")
            )

        return learned

    def add_knowledge(
        self,
        title:     str,
        content:   str,
        kind:      str = "Decision",
        tags:      list = None,
        source:    str = "",
    ) -> str:
        """手動加入知識片段（供 CLI 和 Agent 呼叫）"""
        node_id = self.extractor.make_id(kind, title + content)
        self.graph.add_node(
            node_id   = node_id,
            node_type = kind,
            title     = title,
            content   = content,
            tags      = tags or [],
            source_url= source,
        )
        return node_id

    def status(self) -> str:
        """查看知識庫狀態"""
        if not self.brain_dir.exists():
            return "❌ Project Brain 尚未初始化。執行：synthex brain init"
        return self.context_engineer.summarize_brain()

    def export_mermaid(self, limit: int = 40) -> str:
        """匯出知識圖譜為 Mermaid 格式"""
        return self.graph.to_mermaid(limit=limit)

    # ── 內部方法 ──────────────────────────────────────────────────

    def _store_chunk(self, chunk: dict, meta: dict):
        """把一個知識片段存入圖譜，並同步到向量記憶（v1.1）"""
        node_id = self.extractor.make_id(
            chunk["type"], chunk["title"] + chunk["content"]
        )
        self.graph.add_node(
            node_id   = node_id,
            node_type = chunk["type"],
            title     = chunk["title"],
            content   = chunk["content"],
            tags      = chunk.get("tags", []),
            source_url= meta.get("commit", chunk.get("source", "")),
            author    = meta.get("author", ""),
            meta      = {"confidence": chunk.get("confidence", 0.8)},
        )

        # v1.1：同步到向量記憶（語義搜尋）
        self.vector_memory.upsert(
            node_id    = node_id,
            content    = chunk["content"],
            node_type  = chunk["type"],
            title      = chunk["title"],
            tags       = chunk.get("tags", []),
            author     = meta.get("author", ""),
            created_at = meta.get("date", ""),
        )

        # v1.1：同步到時序圖譜（帶時間戳的邊）
        if meta.get("date"):
            self.temporal_graph.add_temporal_edge(
                source_id  = node_id,
                relation   = "CONTRIBUTED_BY",
                target_id  = meta.get("author", "unknown"),
                confidence = chunk.get("confidence", 0.8),
                valid_from = meta.get("date", ""),
                note       = meta.get("commit", "")[:100],
            )

        # 記錄貢獻者（知識圖譜節點）
        if meta.get("author"):
            author_id = self.extractor.make_id("person", meta["author"])
            if not self.graph.get_node(author_id):
                self.graph.add_node(
                    node_id   = author_id,
                    node_type = "Person",
                    title     = meta["author"],
                    tags      = ["contributor"],
                )
            self.graph.add_edge(node_id, "CONTRIBUTED_BY", author_id)

    def _setup_git_hook(self):
        """設定 post-commit Hook，每次 commit 後自動學習"""
        hooks_dir = self.workdir / ".git" / "hooks"
        if not hooks_dir.exists():
            return

        hook_path = hooks_dir / "post-commit"
        hook_content = f"""#!/bin/sh
# Project Brain — 自動知識積累 Hook
# 由 synthex brain init 自動生成

COMMIT=$(git rev-parse HEAD)
WORKDIR="{self.workdir}"

# 背景執行，不阻塞 commit
(cd "$WORKDIR" && python -c "
import sys
sys.path.insert(0, '${{WORKDIR}}')
from synthex_brain_hook import learn_from_commit
learn_from_commit('${{COMMIT}}')
" 2>/dev/null &)
"""
        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)

        # 建立 hook 輔助腳本
        helper_path = self.workdir / "synthex_brain_hook.py"
        helper_content = f"""
\"\"\"Project Brain Git Hook 輔助腳本\"\"\"
import sys
sys.path.insert(0, '{self.workdir}')

def learn_from_commit(commit_hash: str):
    try:
        from core.brain import ProjectBrain
        brain = ProjectBrain('{self.workdir}')
        n = brain.learn_from_commit(commit_hash)
        if n > 0:
            print(f'[Project Brain] 從此 commit 學習了 {{n}} 個知識片段')
    except Exception as e:
        pass  # 靜默失敗，不影響 git commit

if __name__ == '__main__':
    if len(sys.argv) > 1:
        learn_from_commit(sys.argv[1])
"""
        helper_path.write_text(helper_content)

    def _setup_gitignore(self):
        """設定 .gitignore：提交 ADR，不提交 DB"""
        gitignore = self.workdir / ".gitignore"
        brain_rules = """
# Project Brain（知識圖譜DB和向量記憶不提交，ADR 提交）
.brain/knowledge_graph.db
.brain/vectors/
.brain/sessions/
synthex_brain_hook.py
"""
        if gitignore.exists():
            existing = gitignore.read_text()
            if ".brain/knowledge_graph.db" not in existing:
                gitignore.write_text(existing + brain_rules)
        else:
            gitignore.write_text(brain_rules)
