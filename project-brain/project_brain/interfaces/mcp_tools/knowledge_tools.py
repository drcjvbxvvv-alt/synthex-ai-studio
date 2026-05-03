"""
Knowledge CRUD tools: get_context, search_knowledge, add_knowledge,
batch_add_knowledge, answer_question.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def register(mcp: Any, srv: Any, helpers: dict) -> None:
    """Register knowledge-related MCP tools."""

    _safe_str = helpers["_safe_str"]
    _check_permission = helpers["_check_permission"]
    _get_central_client = helpers["_get_central_client"]
    work_path = helpers["work_path"]
    brain = helpers["brain"]

    MAX_QUERY_LEN = helpers["MAX_QUERY_LEN"]
    MAX_CONTENT_LEN = helpers["MAX_CONTENT_LEN"]
    MAX_TITLE_LEN = helpers["MAX_TITLE_LEN"]
    MAX_TAGS_COUNT = helpers["MAX_TAGS_COUNT"]

    # ── Tool: get_context ──────────────────────────────────────────

    @mcp.tool()
    def get_context(
        task: str,
        current_file: str = "",
        scope: str = "global",
        workdir: str = "",
        force: bool = False,
        detail_level: str = "full",
        current_context_tags: "list[str] | None" = None,
        ai_select: bool = False,
    ) -> str:
        """
        根據當前任務動態組裝最相關的專案知識,注入 AI 的 Context。

        Args:
            task:                 當前任務描述(自然語言)
            current_file:         當前操作的檔案路徑(選填,提升相關性)
            workdir:              Claude Code 當前工作目錄(選填,讓 Brain 自動找對應 .brain/)
            force:                MEM-03:True 時跳過 session 去重,重新顯示所有相關知識
            detail_level:         MEM-06:'summary' 只回 title+description;'full' 為完整內容(預設)
            current_context_tags: MEM-05:當前操作標籤,Rule/Decision 與標籤重疊時降權
            ai_select:            MEM-01:True 時啟用 AI 輔助相關性選取(需 Ollama 或 ANTHROPIC_API_KEY)

        Returns:
            格式化的知識注入字串,可直接加在 prompt 前面。
            若知識庫為空,回傳空字串。
        """
        try:
            srv.rate_check()
        except RuntimeError as _rl_err:
            return f"[rate_limited] {_rl_err} — 請稍後再試"
        task_clean = _safe_str(task, MAX_QUERY_LEN, "task")
        file_clean = _safe_str(current_file, 500, "current_file") if current_file else ""

        if ".." in file_clean:
            file_clean = ""

        b = srv.resolve_brain(workdir or file_clean)
        _wk = str(b.workdir)

        # MEM-03: session dedup
        srv.cleanup_expired_sessions()
        if force:
            _exclude: set[str] = set()
        else:
            with srv._sserved_lock:
                _exclude = set(srv._session_served.get(_wk, set()))

        try:
            ctx = b.get_context(
                task_clean, file_clean,
                exclude_ids=_exclude if not force else None,
                current_context_tags=current_context_tags,
                detail_level=detail_level,
            ) or ""

            # MEM-03: update served set with IDs shown this call
            try:
                _new_ids = set(getattr(b.context_engineer, '_last_shown_ids', []))
                if _new_ids:
                    with srv._sserved_lock:
                        srv._session_served.setdefault(_wk, set()).update(_new_ids)
                        srv._session_served_ts[_wk] = time.monotonic()
            except Exception as _e:
                logger.warning("session dedup update failed: %s", _e, exc_info=True)

            # A-19: apply Memory Synthesizer if BRAIN_SYNTHESIZE=1
            try:
                from project_brain.memory_synthesizer import MemorySynthesizer, is_enabled
                if is_enabled():
                    l1_data = []
                    try:
                        from project_brain.session_store import SessionStore
                        ss = SessionStore(brain_dir=b.brain_dir)
                        l1_data = [{"content": e.value, "category": e.category}
                                   for e in ss.list(limit=5)]
                    except Exception as _e:
                        logger.debug("session_store L1 read failed in get_context", exc_info=True)
                    l2_data = []
                    try:
                        l2_data = b.db.recent_episodes(limit=5)
                    except Exception as _e:
                        logger.debug("recent_episodes L2 read failed in get_context", exc_info=True)
                    synth = MemorySynthesizer(str(b.workdir))
                    ctx = synth.fuse(l1_data, l2_data, ctx, task=task_clean) or ctx
            except Exception as _e:
                logger.debug("synthesis failed, skipping", exc_info=True)

            # P2-A: attach nudges to every MCP response
            try:
                from project_brain.nudge_engine import NudgeEngine
                nudge_eng = NudgeEngine(b.graph, brain_db=b.db)
                nudges = nudge_eng.check(task_clean, top_k=3)
                if nudges:
                    nudge_block = "\n## 🧠 Brain Nudges（主動警告）\n"
                    for n in nudges:
                        _urgency = getattr(n, 'urgency', '')
                        _msg = getattr(n, 'content', '') or getattr(n, 'message', '') or str(n)
                        _conf = getattr(n, 'confidence', None)
                        _icon = '⚠' if _urgency == 'high' else 'ℹ'
                        _conf_str = f" [conf={_conf:.2f}]" if _conf is not None else ""
                        nudge_block += f"  {_icon}{_conf_str} {_msg}\n"
                    ctx = nudge_block + ctx if ctx else nudge_block
            except Exception as _e:
                logger.debug("nudge block failed, skipping", exc_info=True)

            # DEEP-04: background AI auto-resolve low-confidence nodes
            try:
                from project_brain.nudge_engine import NudgeEngine as _NE

                def _bg_resolve():
                    try:
                        _ne = _NE(b.graph, brain_db=b.db)
                        _ne.auto_resolve_batch(task_clean, threshold=0.5, use_llm=False)
                    except Exception as _e:
                        logger.debug("bg_resolve auto_resolve_batch failed", exc_info=True)
                threading.Thread(target=_bg_resolve, daemon=True).start()
            except Exception as _e:
                logger.debug("auto-resolve thread start failed, skipping", exc_info=True)

            # VISION-01: record recently updated node IDs for auto-feedback
            try:
                _recent_rows = b.db.conn.execute(
                    "SELECT id FROM nodes ORDER BY updated_at DESC LIMIT 10"
                ).fetchall()
                _wk2 = str(b.workdir)
                with srv._snodes_lock:
                    srv._session_nodes[_wk2] = [r[0] for r in _recent_rows if r[0]]
            except Exception as _e:
                logger.debug("session_nodes update failed", exc_info=True)

            # E-03: overlay — append central brain context if configured
            try:
                _central, _team_cfg = _get_central_client()
                if _central and _team_cfg:
                    _is_central_only = (_team_cfg.mode == "central-only")
                    _is_overlay = (_team_cfg.mode == "overlay")
                    _local_thin = not ctx or len(ctx) < 100
                    if _is_central_only:
                        ctx = _central.get_context(task_clean, current_file=file_clean)
                    elif _is_overlay and _local_thin:
                        _central_ctx = _central.get_context(task_clean, current_file=file_clean)
                        if _central_ctx:
                            ctx = (ctx or "") + "\n\n---\n## 🌐 Central Brain\n" + _central_ctx
            except Exception as _e:
                logger.debug("E-03 overlay failed (non-fatal): %s", _e)

            return ctx
        except Exception as e:
            logger.error("get_context 內部錯誤：%s", e)
            return ""

    # ── Tool: search_knowledge ─────────────────────────────────────

    @mcp.tool()
    def search_knowledge(
        query: str,
        kind: str = "",
        top_k: int = 5,
        author: str = "",
    ) -> list[dict]:
        """
        語義搜尋專案知識庫。

        Args:
            query:  搜尋詞(自然語言)
            kind:   節點類型過濾(Decision / Pitfall / Rule / ADR,空字串=全部)
            top_k:  回傳筆數(1-10)
            author: E-02: 按來源過濾(例:"telegram:@alice",空字串=不過濾)

        Returns:
            知識片段列表,每筆包含 title / content / type / similarity / source。
        """
        srv.rate_check()
        q_clean = _safe_str(query, MAX_QUERY_LEN, "query")

        valid_kinds = {"", "Decision", "Pitfall", "Rule", "ADR",
                       "Component", "Commit", "Person"}
        if kind not in valid_kinds:
            raise ValueError(f"kind 必須是 {valid_kinds} 之一")

        top_k = max(1, min(10, int(top_k)))
        author_filter = _safe_str(author, 200, "author") if author else ""

        def _format_result(r: dict) -> dict:
            return {
                "title": r.get("title", ""),
                "content": (r.get("content", "") or "")[:500],
                "type": r.get("type", ""),
                "similarity": r.get("similarity"),
                "tags": r.get("tags", []),
                "source": r.get("source_url", ""),
            }

        def _author_match(r: dict) -> bool:
            if not author_filter:
                return True
            src = r.get("source_url", "") or ""
            return author_filter.lower() in src.lower()

        try:
            from project_brain.vector_memory import VectorMemory
            vm = VectorMemory(Path(str(work_path)) / ".brain")
            if vm.available:
                results = vm.search(q_clean, top_k=top_k * 3 if author_filter else top_k,
                                    node_type=kind or None)
                if results:
                    filtered = [r for r in results if _author_match(r)]
                    return [_format_result(r) for r in filtered[:top_k]]

            # Fallback: SQLite FTS5
            raw = brain.graph.search_nodes(
                q_clean, node_type=kind or None,
                limit=top_k * 3 if author_filter else top_k,
            )
            filtered = [r for r in raw if _author_match(r)]
            local_results = [_format_result(r) for r in filtered[:top_k]]

            # E-03: overlay — supplement with central brain results
            try:
                _central, _team_cfg = _get_central_client()
                if _central and _team_cfg:
                    if _team_cfg.mode == "central-only":
                        return _central.search_knowledge(q_clean, top_k=top_k, kind=kind)
                    if _team_cfg.mode == "overlay" and len(local_results) < top_k:
                        _need = top_k - len(local_results)
                        _central_results = _central.search_knowledge(q_clean, top_k=_need, kind=kind)
                        _local_titles = {r["title"].lower() for r in local_results}
                        for cr in _central_results:
                            if cr.get("title", "").lower() not in _local_titles:
                                cr["source"] = cr.get("source", "") + " [central]"
                                local_results.append(cr)
                            if len(local_results) >= top_k:
                                break
            except Exception as _e:
                logger.debug("E-03 search overlay failed (non-fatal): %s", _e)

            return local_results
        except Exception as e:
            logger.error("search_knowledge 內部錯誤：%s", e)
            return []

    # ── Tool: add_knowledge ────────────────────────────────────────

    @mcp.tool()
    def add_knowledge(
        title: str,
        content: str,
        kind: str = "Note",
        scope: str = "global",
        tags: "list[str] | None" = None,
        confidence: float = 0.8,
        source: str = "",
        workdir: str = "",
        description: str = "",
    ) -> dict:
        """
        手動加入一筆知識片段到知識庫。

        Args:
            title:       標題(簡短,< 200 字)
            content:     詳細說明(< 2000 字)
            kind:        類型(Note / Decision / Pitfall / Rule / ADR)
            scope:       模組作用域("global" / "auth" / "payment_service" 等)
            confidence:  確信度 0.0~1.0(agent 發現 = 0.6, human verified = 0.9)
            tags:        標籤列表(最多 10 個)
            source:      E-02: 知識來源(例:"telegram:@alice" / "cli:bob" / "agent:crawler")
            workdir:     Claude Code 當前工作目錄(選填,讓 Brain 自動找對應 .brain/)
            description: MEM-02:一行摘要,供 AI 相關性選取使用(空白時自動截取 content 前 100 字)

        Returns:
            {"node_id": "...", "success": true}
        """
        perm_err = _check_permission("add_knowledge")
        if perm_err:
            return perm_err
        srv.rate_check()

        title_c = _safe_str(title, MAX_TITLE_LEN, "title")
        content_c = _safe_str(content, MAX_CONTENT_LEN, "content")
        desc_c = _safe_str(description, 300, "description") if description else ""

        valid_kinds = {"Note", "Decision", "Pitfall", "Rule", "ADR", "Component"}
        kind = kind if kind in valid_kinds else "Note"

        safe_tags = []
        for tag in (tags or [])[:MAX_TAGS_COUNT]:
            t = _safe_str(str(tag), 50, "tag")
            if t:
                safe_tags.append(t)

        source_c = _safe_str(source, 200, "source") if source else ""

        b = srv.resolve_brain(workdir)
        try:
            node_id = b.add_knowledge(
                title=title_c,
                content=content_c,
                kind=kind,
                tags=safe_tags,
                confidence=max(0.0, min(1.0, confidence)),
                source=source_c,
                description=desc_c,
            )
            # A-21: write scope to BrainDB
            if scope and scope != "global" and node_id:
                try:
                    b.db.conn.execute(
                        "UPDATE nodes SET scope=? WHERE id=?",
                        (scope, node_id)
                    )
                    b.db.conn.commit()
                except Exception as e:
                    logger.warning("scope update failed for node %s: %s", node_id, e)
            # C-04: emit MCP_TOOL_CALL signal
            srv.emit_signal(
                "mcp_tool_call", str(b.workdir),
                f"add_knowledge kind={kind} title={title_c[:80]}",
                raw_content=f"title: {title_c}\ncontent: {content_c[:500]}",
                metadata={"tool": "add_knowledge", "kind": kind, "node_id": node_id},
                priority=7,
            )
            # C-04: background conflict detection
            def _bg_conflict_check():
                try:
                    conflicts = b.db.find_conflicts_for_node(
                        node_id, similarity_threshold=0.6, candidates_per_anchor=10,
                    )
                    if conflicts:
                        srv.emit_signal(
                            "knowledge_conflict", str(b.workdir),
                            f"conflict: {title_c[:80]} vs {len(conflicts)} existing",
                            raw_content="\n".join(
                                f"[{c.get('type', '')}] {c.get('title_b', '')}: {c.get('reason', '')}"
                                for c in conflicts[:3]
                            ),
                            metadata={"node_id": node_id, "conflict_count": len(conflicts)},
                            priority=4,
                        )
                except Exception:
                    pass
            threading.Thread(target=_bg_conflict_check, daemon=True).start()
            return {"node_id": node_id, "success": True, "scope": scope,
                    "confidence": confidence, "source": source_c}
        except Exception as e:
            logger.error("add_knowledge 內部錯誤：%s", e)
            return {"node_id": "", "success": False, "error": "加入失敗"}

    # ── Tool: batch_add_knowledge ──────────────────────────────────

    @mcp.tool()
    def batch_add_knowledge(
        items: "list[dict]",
        workdir: str = "",
    ) -> dict:
        """
        批量加入多筆知識到知識庫(單次呼叫,降低 MCP round-trip 開銷)。

        Args:
            items:   知識清單,每筆格式與 add_knowledge 相同:
                     {"title": str, "content": str, "kind": str,
                      "scope": str, "tags": list, "confidence": float,
                      "description": str}
                     最多 50 筆。
            workdir: Claude Code 當前工作目錄

        Returns:
            {"ok": true, "created": N, "node_ids": [...], "errors": [...]}
        """
        srv.rate_check()
        MAX_BATCH = 50
        raw_items = items[:MAX_BATCH] if isinstance(items, list) else []
        b = srv.resolve_brain(workdir)
        valid_kinds = {"Note", "Decision", "Pitfall", "Rule", "ADR", "Component"}
        node_ids: list[str] = []
        errors: list[str] = []

        for idx, item in enumerate(raw_items):
            if not isinstance(item, dict):
                errors.append(f"item[{idx}] is not a dict")
                continue
            try:
                title_c = _safe_str(str(item.get("title", "")), MAX_TITLE_LEN, "title")
                content_c = _safe_str(str(item.get("content", "")), MAX_CONTENT_LEN, "content")
                desc_c = _safe_str(str(item.get("description", "")), 300, "description")
                kind = item.get("kind", "Note")
                kind = kind if kind in valid_kinds else "Note"
                scope = str(item.get("scope", "global"))
                conf = float(max(0.0, min(1.0, item.get("confidence", 0.8))))
                safe_tags = [
                    _safe_str(str(t), 50, "tag")
                    for t in (item.get("tags") or [])[:MAX_TAGS_COUNT]
                    if t
                ]
                node_id = b.add_knowledge(
                    title=title_c, content=content_c, kind=kind,
                    tags=safe_tags, confidence=conf, description=desc_c,
                )
                if scope and scope != "global" and node_id:
                    try:
                        b.db.conn.execute(
                            "UPDATE nodes SET scope=? WHERE id=?", (scope, node_id)
                        )
                        b.db.conn.commit()
                    except Exception as _se:
                        logger.warning("batch scope update failed for %s: %s", node_id, _se)
                node_ids.append(node_id)
            except Exception as _e:
                errors.append(f"item[{idx}]: {_e}")
                logger.warning("FEAT-02: batch_add item[%d] failed: %s", idx, _e)

        return {"ok": True, "created": len(node_ids), "node_ids": node_ids, "errors": errors}

    # ── Tool: answer_question ──────────────────────────────────────

    @mcp.tool()
    def answer_question(
        node_id: str,
        answer: str,
        new_confidence: float = 0.9,
        workdir: str = "",
    ) -> dict:
        """DEEP-04: AI 回饋對特定節點的判斷,更新信心值並記錄學習事件。

        配合 generate_questions() 使用,也可以獨立呼叫。
        AI 自行判斷後直接呼叫此工具更新知識庫,形成完全自動的學習閉環。

        Args:
            node_id:        目標節點 ID
            answer:         AI 的判斷 / 補充說明
            new_confidence: 更新後信心值(預設 0.9)
            workdir:        工作目錄(選填)

        Returns:
            {"ok": True, "node_id": ..., "new_confidence": ...} or {"ok": False, "error": ...}
        """
        srv.rate_check()
        b = srv.resolve_brain(workdir)
        try:
            node_id_clean = _safe_str(node_id, 128, "node_id")
            answer_clean = _safe_str(answer, MAX_QUERY_LEN, "answer")
            conf = float(max(0.0, min(1.0, new_confidence)))
            node = b.db.get_node(node_id_clean)
            if not node:
                return {"ok": False, "error": f"node {node_id_clean!r} not found"}
            new_content = (node.get("content") or "") + f"\n[AI確認] {answer_clean}"
            b.db.update_node(
                node_id_clean,
                content=new_content,
                confidence=conf,
                changed_by="answer_question",
                change_note=f"AI confirmation: {answer_clean[:80]}",
            )
            b.db.add_episode(
                content=f"[AI主動確認] {node.get('title', '')}: {answer_clean}",
                source=f"answer_question:{node_id_clean}",
                confidence=conf,
            )
            return {"ok": True, "node_id": node_id_clean, "new_confidence": conf}
        except Exception as e:
            logger.error("answer_question error: %s", e)
            return {"ok": False, "error": str(e)}
