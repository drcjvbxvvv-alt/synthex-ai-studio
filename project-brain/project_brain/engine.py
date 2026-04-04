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
import logging
import subprocess
import threading
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)
from .graph          import KnowledgeGraph
from .brain_db       import BrainDB               # A-10: unified DB
from .context_result import ContextResult         # P3-A: structured return
from .extractor      import KnowledgeExtractor
from .context        import ContextEngineer
from .constants      import DEFAULT_SEARCH_LIMIT  # REF-04

try:
    from core.config import cfg
except ImportError:
    cfg = None  # Brain 可獨立使用（無 synthex 整合時降級（brain.py 獨立運行））
from .archaeologist      import ProjectArchaeologist
from .review_board       import KnowledgeReviewBoard


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

    def __init__(self, workdir: str):
        self.workdir      = Path(workdir).resolve()
        self.brain_dir    = self.workdir / self.BRAIN_DIR

        # 延遲初始化（只有呼叫 init/scan 後才建立）
        self._db        = None   # A-10: BrainDB (unified)
        self._graph     = None
        self._extractor = None
        self._context   = None
        self._config    = {}
        # v3.0
        self._router:   "BrainRouter | None" = None
        # v4.0（KRB, distiller, validator）
        self._validator:  None = None
        self._distiller:  None = None
        self._krb:        None = None
        # BUG-A03: decay_engine / nudge_engine lazy instances
        self._decay:      None = None
        self._nudge:      None = None
        # BUG-A03: per-property locks — shared _init_lock was non-reentrant,
        # causing deadlock risk when chained lazy-init calls (e.g. context_engineer
        # calling self.graph which also tried to acquire _init_lock).
        self._db_lock        = threading.Lock()
        self._graph_lock     = threading.Lock()
        self._extractor_lock = threading.Lock()
        self._context_lock   = threading.Lock()
        self._krb_lock       = threading.Lock()
        self._router_lock    = threading.Lock()
        self._validator_lock = threading.Lock()
        self._distiller_lock = threading.Lock()
        self._decay_lock     = threading.Lock()
        self._nudge_lock     = threading.Lock()

    # ── 屬性懶初始化 ──────────────────────────────────────────────

    @property
    def db(self) -> 'BrainDB':
        """A-10: Unified BrainDB — single source of truth."""
        if self._db is None:
            with self._db_lock:                        # BUG-A03: per-property lock
                if self._db is None:
                    self.brain_dir.mkdir(parents=True, exist_ok=True)
                    self._db = BrainDB(self.brain_dir)
        return self._db

    @property
    def graph(self) -> KnowledgeGraph:
        if self._graph is None:
            with self._graph_lock:                     # BUG-A03
                if self._graph is None:
                    self.brain_dir.mkdir(parents=True, exist_ok=True)
                    self._graph = KnowledgeGraph(self.brain_dir)
        return self._graph

    @property
    def extractor(self) -> KnowledgeExtractor:
        if self._extractor is None:
            with self._extractor_lock:                 # BUG-A03
                if self._extractor is None:
                    self._extractor = KnowledgeExtractor(str(self.workdir))
        return self._extractor

    @property
    def context_engineer(self) -> ContextEngineer:
        if self._context is None:
            # Resolve dependencies outside lock — each dependency has its own lock now
            _graph = self.graph
            _db    = self.db
            with self._context_lock:                   # BUG-A03
                if self._context is None:
                    # A-11: pass BrainDB so ContextEngineer uses brain.db as primary read
                    self._context = ContextEngineer(
                        _graph, self.brain_dir, brain_db=_db
                    )
        return self._context

    @property
    def review_board(self) -> "KnowledgeReviewBoard":
        """
        Knowledge Review Board — 人工審查委員會（v7.0）。

        預設 strict_mode=False：手動 brain add 直接進 L3，
        scan/learn 的知識進 Staging 等待審查。
        """
        if self._krb is None:
            _graph = self.graph  # resolve before acquiring lock
            with self._krb_lock:                       # BUG-A03
                if self._krb is None:
                    self._krb = KnowledgeReviewBoard(
                        brain_dir   = self.brain_dir,
                        graph       = _graph,
                        strict_mode = False,
                    )
        return self._krb

    @property
    def router(self) -> "BrainRouter":
        """
        v3.0 三層認知路由器。
        懶初始化：第一次呼叫時建立 L1 + L2 + L3 連線。
        """
        if self._router is None:
            with self._router_lock:                    # BUG-A03
                if self._router is None:
                    from project_brain.router import BrainRouter
                    self._router = BrainRouter(
                        brain_dir    = self.brain_dir,
                        l3_brain     = self,
                        graphiti_url = os.environ.get("GRAPHITI_URL", ""),
                        agent_name   = self._config.get("project_name", "project-brain"),
                    )
        return self._router

    @property
    def validator(self) -> "KnowledgeValidator":
        """v4.0 自主知識驗證器（懶初始化）"""
        if self._validator is None:
            with self._validator_lock:                 # BUG-A03
                if self._validator is None:
                    from project_brain.knowledge_validator import KnowledgeValidator
                    self._validator = KnowledgeValidator(
                        graph     = self.graph,
                        workdir   = self.workdir,
                        brain_dir = self.brain_dir,
                    )
        return self._validator

    @property
    def distiller(self) -> "KnowledgeDistiller":
        """v4.0 知識蒸餾器（懶初始化）"""
        if self._distiller is None:
            with self._distiller_lock:                 # BUG-A03
                if self._distiller is None:
                    from project_brain.knowledge_distiller import KnowledgeDistiller
                    self._distiller = KnowledgeDistiller(
                        graph     = self.graph,
                        brain_dir = self.brain_dir,
                        workdir   = self.workdir,
                    )
        return self._distiller

    @property
    def decay_engine(self) -> "DecayEngine":
        """BUG-A03: DecayEngine 懶初始化（獨立鎖）"""
        if self._decay is None:
            with self._decay_lock:
                if self._decay is None:
                    from project_brain.decay_engine import DecayEngine
                    self._decay = DecayEngine(
                        graph   = self.graph,
                        workdir = str(self.workdir),
                    )
        return self._decay

    @property
    def nudge_engine(self) -> "NudgeEngine":
        """BUG-A03: NudgeEngine 懶初始化（獨立鎖）"""
        if self._nudge is None:
            with self._nudge_lock:
                if self._nudge is None:
                    from project_brain.nudge_engine import NudgeEngine
                    self._nudge = NudgeEngine(
                        graph    = self.graph,
                        brain_db = self._db,
                    )
        return self._nudge

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
            "model":           (cfg.model_sonnet if cfg else "claude-haiku-4-5-20251001"),  # standalone fallback
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
            except Exception as _e:
                logger.warning("git history extraction failed during init: %s", _e)

        # ── 組裝輸出 ─────────────────────────────────────────
        if has_git and commit_count > 0:
            if has_api_key:
                git_tip = f"  • Git 歷史掃描：已學習 {learned} 筆知識"
            else:
                _tip = ""
                _tip += "  偵測到 " + str(commit_count) + " 個 commit，但需要 API key 提取知識\n"
                _tip += "  請設定後執行：\n"
                _tip += "    export ANTHROPIC_API_KEY='sk-ant-...'\n"
                _tip += "    brain scan --workdir " + str(self.workdir)
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
  brain add "你的第一條規則"  --kind Rule
  brain add "踩坑記錄"        --kind Pitfall
  brain status

Agent 自動記錄：每次 git commit 後，brain sync 自動執行
"""

    def dedup(
        self,
        threshold: float = 0.85,
        dry_run:   bool  = True,
        verbose:   bool  = True,
    ) -> str:
        """
        語意去重：自動合並相似度 >= threshold 的重複知識節點（v6.0）。

        Args:
            threshold: 相似度閾值（0.0~1.0，預設 0.85）
            dry_run:   True=只回報不修改（預設），False=實際合並
            verbose:   是否印出進度

        Returns:
            str：去重報告文字

        範例：
            # 先 dry run 看結果
            report = brain.dedup(threshold=0.85, dry_run=True)
            print(report)

            # 確認後執行
            report = brain.dedup(threshold=0.85, dry_run=False)
        """
        from project_brain.semantic_dedup import SemanticDeduplicator

        if verbose:
            action = "（DRY RUN）" if dry_run else "（實際執行）"
            print(f"  [語意去重] threshold={threshold} {action}")

        dedup   = SemanticDeduplicator(self.graph, threshold=threshold)
        report  = dedup.run(dry_run=dry_run)
        summary = report.summary()

        if verbose:
            print(summary)

        return summary

    def distill(self) -> str:
        """知識蒸餾：生成可給任何 LLM 使用的 system prompt 片段"""
        return self.distiller.distill_all().summary if hasattr(self.distiller.distill_all(), "summary") else str(self.distiller.distillation_status())

    def scan(self, verbose: bool = True, limit: int = 100) -> str:
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

        result = archaeologist.scan(limit=limit)

        # 儲存報告
        report_path = self.brain_dir / "SCAN_REPORT.md"
        report_path.write_text(result["report"], encoding="utf-8")

        # v8.0 修正：scan 提取的知識先送入 KRB Staging，不直接進 L3
        # 解決「KRB 是孤島」問題——scan 不再繞過審查機制
        krb_staged = self._submit_scan_to_krb(verbose=verbose)
        if krb_staged > 0 and verbose:
            print(f"  [KRB] {krb_staged} 筆知識進入 Staging 待審查 "
                  f"（brain review list 查看）")

        # 入口品質把關（v5.1 保留，作為 KRB 的補充）
        quality_summary = self._post_scan_quality_gate(verbose=verbose)
        if quality_summary:
            result["report"] += f"\n\n## 入口品質檢查\n{quality_summary}"
            report_path.write_text(result["report"], encoding="utf-8")

        return result["report"]

    def _submit_scan_to_krb(self, verbose: bool = True) -> int:
        """
        使用 StagingGraph Wrapper，讓 archaeologist 寫入 KRB Staging 而非直接進 L3。

        正確做法（v7.0.x 修補）：
        1. 把 KnowledgeGraph 包裝成 StagingGraph
        2. StagingGraph 的 add_node() 攔截寫入，轉而呼叫 KRB.submit()
        3. 用這個 StagingGraph 執行 archaeologist.scan()
        4. 完成後恢復原本的 graph

        Returns:
            int：提交到 KRB 的知識數量
        """
        from project_brain.review_board import KnowledgeReviewBoard

        krb     = self.review_board
        staged  = 0
        real_graph = self.graph

        class StagingGraph:
            """
            攔截 add_node()，把知識送到 KRB Staging 而非 L3。
            其他方法（add_edge、get_node 等）委派給真正的 graph。
            """
            def __init__(self, inner, review_board):
                self._inner      = inner
                self._krb        = review_board
                self._count      = 0
                self._staged_ids: list = []  # KRB-01: track for auto-approve

            def __getattr__(self, name: str):
                """
                v7.0.x Fix 5: __getattr__ delegation — any attribute not
                explicitly defined on StagingGraph is forwarded to the real
                KnowledgeGraph. This makes the proxy robust against new
                methods added to KnowledgeGraph without requiring manual
                proxy list maintenance.

                Only add_node() is intercepted; everything else passes through.
                """
                if name.startswith('_'):
                    raise AttributeError(name)
                return getattr(self._inner, name)

            def add_node(self, node_id, node_type, title, content="",
                         tags=None, source_url="", author="", meta=None, **kw):
                # 只攔截知識類型節點（非 Component 結構節點）
                if node_type in ("Decision", "Pitfall", "Rule", "ADR"):
                    sid = self._krb.submit(
                        title     = title,
                        content   = content,
                        kind      = node_type,
                        source    = "scan",   # KRB-01: canonical source key
                        submitter = "auto-scan",
                    )
                    self._staged_ids.append(sid)
                    self._count += 1
                    return node_id
                else:
                    # Component、結構節點直接寫 L3（不需審查）
                    return self._inner.add_node(
                        node_id=node_id, node_type=node_type, title=title,
                        content=content, tags=tags, source_url=source_url,
                        author=author, meta=meta)

        staging_graph = StagingGraph(real_graph, krb)
        try:
            from project_brain.archaeologist import ProjectArchaeologist
            archaeologist = ProjectArchaeologist(
                workdir   = str(self.workdir),
                graph     = staging_graph,
                extractor = self.extractor,
                verbose   = verbose,
            )
            archaeologist.scan()
            staged = staging_graph._count
        except Exception as e:
            logger.warning("krb_staging_scan_failed: %s", str(e)[:100])

        # KRB-01: auto-approve all staged items by confidence
        auto_approved = 0
        for sid in staging_graph._staged_ids:
            try:
                l3_id = krb.auto_approve_by_confidence(sid)
                if l3_id:
                    auto_approved += 1
            except Exception as e:
                logger.debug("krb01_scan_auto_approve_failed: %s %s", sid[:8], e)
        if auto_approved:
            logger.info("krb01_scan: auto_approved=%d / staged=%d", auto_approved, staged)

        return staged

    def _post_scan_quality_gate(self, verbose: bool = True) -> str:
        """
        掃描後自動執行的入口品質把關（v5.1）。

        只做本地規則驗證（Rule 1 + Rule 2），零 API 費用：
        - Rule 1：必要欄位完整性（title 非空、content 非空）
        - Rule 2：Prompt Injection 偵測（title/content 含危險指令）

        對可疑節點在 meta 中加入 quality_flag，
        不刪除節點，只標記——由人類決定是否保留。

        Returns:
            str：品質摘要報告
        """
        try:
            from project_brain.knowledge_validator import KnowledgeValidator
            validator = KnowledgeValidator(
                self.graph,
                workdir   = str(self.workdir),
                brain_dir = self.brain_dir,
            )
            report = validator.run(
                max_api_calls = 0,   # 完全免費：不呼叫 AI
                dry_run       = True,  # 不修改 confidence，只標記
            )
            flagged = sum(1 for _ in report.results if getattr(_, "action", "") == "flag")
            if verbose and flagged:
                print(f"  [品質把關] 發現 {flagged} 個可疑節點，已標記（brain validate --dry-run 可查看）")
            return report.summary() if hasattr(report, "summary") else ""
        except Exception as e:
            logger.debug("post_scan_quality_gate_failed: %s", str(e)[:100])
            return ""

    def get_context(self, task: str, current_file: str = "") -> str:
        """
        [A-20 Deprecated] Use Brain.query() for structured result.
        This method remains for backward compatibility and returns str.

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

        # A-10 v2.0 fallback: use ContextEngineer with graph
        # BrainDB nodes are also searchable via KnowledgeGraph
        # (dual-write in add_knowledge keeps them in sync)
        raw = self.context_engineer.build(task, current_file)

        # Phase 4: remove episode lines already covered by L3 DERIVES_FROM
        try:
            if raw and self.brain_dir.exists():
                from .brain_db import BrainDB as _BDB
                _bdb = _BDB(self.brain_dir)
                _linked = {r[0] for r in _bdb.conn.execute(
                    "SELECT DISTINCT source_id FROM temporal_edges "
                    "WHERE relation='DERIVES_FROM'"
                ).fetchall()}
                if _linked:
                    lines   = raw.split('\n')
                    cleaned = [l for l in lines
                               if not any(eid in l for eid in _linked)]
                    raw = '\n'.join(cleaned)
        except Exception as _e:
            logger.warning("episode dedup filter failed in git_log_raw: %s", _e)

        return raw

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
            )[:8000]
            author = subprocess.check_output(
                ["git", "log", "-1", "--pretty=%ae", commit_hash],
                cwd=str(self.workdir), text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            return 0

        # FEAT-03: get actual commit date for valid_from (not "now")
        try:
            commit_date = subprocess.check_output(
                ["git", "log", "-1", "--pretty=%aI", commit_hash],
                cwd=str(self.workdir), text=True, stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            commit_date = datetime.now().isoformat()

        result = self.extractor.from_git_commit(commit_hash, msg, diff)
        meta   = {"commit": commit_hash, "author": author, "date": commit_date}
        learned = 0
        for chunk in result.get("knowledge_chunks", []):
            self._store_chunk(chunk, meta)
            learned += 1

        # Zero-API fallback: parse Conventional Commits → L3 node
        if learned == 0:
            chunk = self._heuristic_extract(msg, commit_hash)
            if chunk:
                self._store_chunk(chunk, meta)
                self.db.add_node(
                    self.extractor.make_id(chunk["type"], chunk["title"] + chunk["content"]),
                    chunk["type"], chunk["title"], content=chunk["content"],
                    confidence=chunk.get("confidence", 0.5),
                )
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
        title:      str   = "",
        content:    str   = "",
        kind:       str   = "Decision",
        tags:       list  = None,
        source:     str   = "",
        k_type:     str   = "",
        text:       str   = "",
        confidence: float = 0.8,
        scope:      str   = "global",
    ) -> str:
        """手動加入知識片段（供 CLI 和 Agent 呼叫）"""
        kind    = k_type    or kind
        content = text      or content
        title   = title     or content[:60]
        node_id = self.extractor.make_id(kind, title + content)
        self.graph.add_node(
            node_id   = node_id,
            node_type = kind,
            title     = title,
            content   = content,
            tags      = tags or [],
            source_url= source,
        )
                  # A-10: also write to unified BrainDB
        # A-10: also write to unified BrainDB
        try:
            self.db.add_node(node_id, kind, title, content=content,
                             tags=tags or [], source_url=source,
                             confidence=confidence, scope=scope)
        except Exception as _e:
            import logging; logging.getLogger(__name__).debug("db.add_node failed: %s", _e)
        # Phase 1: async embedding (non-blocking)
        try:
            from .embedder import get_embedder
            _emb = get_embedder()
            if _emb:
                _text = f"{title} {content}"[:2000]
                _vec  = _emb.embed(_text)
                if _vec:
                    self.db.add_vector(node_id, _vec, model=getattr(_emb, 'MODEL', 'unknown'))
        except Exception as _e:
            logger.warning("embedding failed for node %s", node_id, _e)  # embedding failure must never block add_knowledge

        # P3: near-duplicate check against FTS5 candidates (lightweight, non-blocking)
        try:
            from .semantic_dedup import SemanticDeduplicator
            _candidates = self.db.search_nodes(
                f"{title} {content}", node_type=kind, scope=scope, limit=DEFAULT_SEARCH_LIMIT  # REF-04
            )
            _dedup = SemanticDeduplicator(self.graph, threshold=0.85)
            _result = _dedup.check_near_duplicate(
                new_node_id=node_id,
                new_text=f"{title} {content}",
                node_type=kind,
                candidates=_candidates,
            )
            if _result:
                _dup_id, _sim = _result
                logger.warning(
                    "near_duplicate_detected: new=%s existing=%s similarity=%.3f "
                    "(use brain dedup --execute to merge)",
                    node_id[:12], _dup_id[:12], _sim
                )
                # Emit event so callers / CLI can surface this to the user
                self.db.emit("near_duplicate", {
                    "new_id": node_id, "existing_id": _dup_id,
                    "similarity": _sim, "kind": kind,
                })
        except Exception as _e:
            logger.warning("dedup check failed for node %s", node_id, _e)  # dedup check must never block add_knowledge

        return node_id
    def query(self, task: str, current_file: str = "",
              scope: str = "global") -> ContextResult:
        """
        P3-A: Structured context query — returns ContextResult not str.

        Agents should prefer this over get_context() because:
        - is_initialized=False  → Brain not set up
        - source_count=0        → No relevant knowledge
        - bool(result)==True    → Knowledge found, inject result.context
        """
        if not self.brain_dir.exists():
            return ContextResult.not_initialized()
        # P3-A: consider initialized if either brain.db OR knowledge_graph.db exists
        db_path  = self.brain_dir / "brain.db"
        alt_path = self.brain_dir / "knowledge_graph.db"
        if not db_path.exists() and not alt_path.exists():
            return ContextResult.not_initialized()
        try:
            # Phase 1: hybrid search (vector × 0.6 + FTS5 × 0.4)
            _vec = None
            try:
                from .embedder import get_embedder
                _emb = get_embedder()
                if _emb:
                    _vec = _emb.embed(task)
            except Exception as _e:
                logger.warning("query embedder failed: %s", _e)
            nodes = self.db.hybrid_search(task, query_vector=_vec, scope=scope, limit=10)
            if not nodes:
                return ContextResult.empty(scope=scope)
            # Feedback loop: surfacing a node counts as a weak positive signal
            for n in nodes[:5]:
                try:
                    self.db.record_access(n["id"])
                    self.db.record_feedback(n["id"], helpful=True)
                except Exception as _e:
                    logger.warning("record_access/feedback failed: %s", _e)
            # Build causal chain
            from .context import ContextEngineer
            cb    = ContextEngineer(self.graph, brain_dir=self.brain_dir,
                                   brain_db=self.db)
            chain = cb._build_causal_chain([n["id"] for n in nodes[:5]],
                                           db=self.db)
            # Build full context string (backward compat)
            ctx   = self.get_context(task, current_file) or ""
            # Gather nudges
            nudge_msgs: list = []
            try:
                from .nudge_engine import NudgeEngine
                nudges = NudgeEngine(self.graph, brain_db=self._db).check(task, top_k=3)
                nudge_msgs = [getattr(n,"message","") or str(n) for n in nudges]
            except Exception as _e:
                logger.warning("nudge engine failed in query: %s", _e)
            avg_conf = sum(n.get("confidence",0.8) for n in nodes) / len(nodes)
            # A-19: opt-in Memory Synthesizer (BRAIN_SYNTHESIZE=1)
            from .memory_synthesizer import MemorySynthesizer, is_enabled
            if is_enabled():
                try:
                    # Read L1: SessionStore working memory
                    l1_data = []
                    try:
                        from .session_store import SessionStore
                        ss = SessionStore(brain_dir=self.brain_dir)
                        l1_data = [{"content": e.value, "category": e.category}
                                   for e in ss.list(limit=5)]
                    except Exception as _e:
                        logger.warning("session store L1 read failed: %s", _e)
                    # Read L2: recent episodes
                    l2_data = []
                    try:
                        l2_data = self.db.recent_episodes(limit=5)
                    except Exception as _e:
                        logger.warning("recent_episodes L2 read failed: %s", _e)
                    synth = MemorySynthesizer(str(self.workdir))
                    ctx   = synth.fuse(l1_data, l2_data, ctx, task=task) or ctx
                except Exception as _e:
                    logger.warning("MemorySynthesizer fuse failed: %s", _e)
            return ContextResult(
                context       = ctx,
                source_count  = len(nodes),
                is_initialized= True,
                confidence    = round(avg_conf, 3),
                scope         = scope,
                causal_chains = chain.count("\n") if chain else 0,
                nudges        = nudge_msgs,
            )
        except Exception as _e:
            logger.warning("query() failed, returning empty context: %s", _e)
            return ContextResult.empty(scope=scope)

    def status(self) -> str:
        """查看知識庫狀態"""
        if not self.brain_dir.exists():
            return "❌ Project Brain 尚未初始化。\n   執行：brain init --workdir " + str(self.workdir)
        return self.context_engineer.summarize_brain()

    def export_mermaid(self, limit: int = 40) -> str:
        """匯出知識圖譜為 Mermaid 格式"""
        return self.graph.to_mermaid(limit=limit)

    # ── 內部方法 ──────────────────────────────────────────────────

    def _heuristic_extract(self, msg: str, commit_hash: str) -> dict | None:
        """
        Zero-API knowledge extraction from Conventional Commit messages.

        Maps commit type → knowledge type and builds a minimal knowledge chunk
        without calling any LLM. Works offline and for free.

        Conventional Commit format: type(scope): description
          feat      → Decision  (new capability added)
          fix       → Pitfall   (bug found and solved)
          refactor  → Decision  (design change)
          perf      → Rule      (performance guideline)
          security  → Rule      (security requirement)
          docs      → Rule      (documented constraint)
          test      → Rule      (testing pattern)

        Low-signal commits (wip, merge, bump, chore) are skipped.
        """
        import re
        msg = (msg or "").strip()
        if not msg or len(msg) < 8:
            return None

        # Parse: type(scope): description
        m = re.match(
            r'^(?P<type>feat|fix|refactor|perf|security|docs|test|style|ci|build)'
            r'(?:\((?P<scope>[^)]+)\))?[!]?:\s*(?P<desc>.+)$',
            msg, re.IGNORECASE
        )
        if not m:
            return None

        ctype = m.group("type").lower()
        scope = m.group("scope") or ""
        desc  = m.group("desc").strip()

        _type_map = {
            "feat":     ("Decision", 0.6),
            "fix":      ("Pitfall",  0.7),
            "refactor": ("Decision", 0.5),
            "perf":     ("Rule",     0.6),
            "security": ("Rule",     0.8),
            "docs":     ("Rule",     0.5),
            "test":     ("Rule",     0.5),
            "style":    ("Rule",     0.4),
            "ci":       ("Rule",     0.5),
            "build":    ("Rule",     0.5),
        }
        node_type, confidence = _type_map.get(ctype, ("Decision", 0.5))

        scope_prefix = f"[{scope}] " if scope else ""
        title   = f"{scope_prefix}{desc}"[:120]
        content = f"{ctype.upper()} commit {commit_hash[:8]}: {desc}"
        if scope:
            content += f" (scope: {scope})"

        return {
            "type":       node_type,
            "title":      title,
            "content":    content,
            "tags":       [ctype, scope] if scope else [ctype],
            "confidence": confidence,
            "source":     f"git-{commit_hash[:8]}",
        }

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
        # FEAT-03: sync valid_from to brain.db so temporal_query works on nodes
        if meta.get("date"):
            try:
                self.db.add_node(
                    node_id    = node_id,
                    node_type  = chunk["type"],
                    title      = chunk["title"],
                    content    = chunk["content"],
                    confidence = chunk.get("confidence", 0.8),
                    valid_from = meta["date"],
                )
            except Exception as _e:
                logger.warning("db.add_node sync in _store_chunk failed: %s", _e)




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
# 由 brain init 自動生成

COMMIT=$(git rev-parse HEAD)
WORKDIR="{self.workdir}"

# 背景執行，不阻塞 commit
(cd "$WORKDIR" && python -c "
import sys
sys.path.insert(0, '${{WORKDIR}}')
from brain_hook import learn_from_commit
learn_from_commit('${{COMMIT}}')
" 2>/dev/null &)
"""
        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)

        # 建立 hook 輔助腳本
        helper_path = self.workdir / "brain_hook.py"
        helper_content = f"""
\"\"\"Project Brain Git Hook 輔助腳本\"\"\"
import sys
sys.path.insert(0, '{self.workdir}')

def learn_from_commit(commit_hash: str):
    try:
        from project_brain import ProjectBrain
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
brain_hook.py
"""
        if gitignore.exists():
            existing = gitignore.read_text()
            if ".brain/knowledge_graph.db" not in existing:
                gitignore.write_text(existing + brain_rules)
        else:
            gitignore.write_text(brain_rules)
