"""
Feedback tools: mark_helpful, report_knowledge_outcome, complete_task.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def register(mcp: Any, srv: Any, helpers: dict) -> None:
    """Register feedback-related MCP tools."""

    _safe_str = helpers["_safe_str"]
    _check_permission = helpers["_check_permission"]
    _now_iso = helpers["_now_iso"]
    work_path = helpers["work_path"]

    MAX_QUERY_LEN = helpers["MAX_QUERY_LEN"]
    MAX_CONTENT_LEN = helpers["MAX_CONTENT_LEN"]

    # ── Tool: mark_helpful ─────────────────────────────────────────

    @mcp.tool()
    def mark_helpful(
        node_id: str,
        helpful: bool = True,
    ) -> str:
        """
        Confidence feedback — call this after a piece of knowledge was actually useful.

        When helpful=True:  confidence += 0.03 (capped at 1.0)
        When helpful=False: confidence -= 0.05 (floored at 0.05)

        Args:
            node_id: The node ID returned by get_context or add_knowledge.
            helpful: True if the knowledge was correct/useful, False otherwise.

        Returns:
            JSON with updated confidence value.
        """
        import json
        from pathlib import Path as _P

        srv.rate_check()
        node_id = _safe_str(node_id, 100, "node_id")
        wd = os.environ.get("BRAIN_WORKDIR", str(work_path))
        db_path = _P(wd) / ".brain" / "brain.db"
        if not db_path.exists():
            return json.dumps({"error": "Brain not initialized"})

        try:
            db = srv.resolve_brain(wd).db
            new_conf = db.record_feedback(node_id, helpful=bool(helpful))
            return json.dumps({
                "node_id": node_id,
                "helpful": helpful,
                "confidence": round(new_conf, 3),
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ── Tool: report_knowledge_outcome ─────────────────────────────

    @mcp.tool()
    def report_knowledge_outcome(
        node_id: str,
        was_useful: bool,
        notes: str = "",
        workdir: str = "",
    ) -> dict:
        """
        Close the knowledge feedback loop by reporting whether a retrieved
        knowledge node was actually useful.

        Call this after using knowledge returned by get_context:
        - was_useful=True  -> confidence increases (node surfaces more often)
        - was_useful=False -> confidence decreases (node surfaces less often)

        This drives the decay engine and keeps the knowledge base accurate
        over time. Without this feedback, stale or incorrect knowledge never
        gets deprioritised.

        Args:
            node_id:    The node ID from get_context or add_knowledge.
            was_useful: True if the knowledge helped; False if outdated/wrong.
            notes:      Optional explanation — especially important when
                        was_useful=False to document why the node is wrong.
            workdir:    Project working directory. Defaults to BRAIN_WORKDIR env var.

        Returns:
            {"ok": True, "node_id": "...", "confidence": 0.85, "delta": +0.03}
        """
        perm_err = _check_permission("report_knowledge_outcome")
        if perm_err:
            return perm_err
        srv.rate_check()

        node_id_clean = _safe_str(node_id, 100, "node_id")
        notes_clean = _safe_str(notes, MAX_CONTENT_LEN, "notes") if notes else ""
        wd_str = _safe_str(workdir or os.environ.get("BRAIN_WORKDIR", ""), 500, "workdir") or workdir

        b = srv.resolve_brain(wd_str)
        if not (b.brain_dir / "brain.db").exists():
            return {"ok": False, "error": "Brain not initialized — run brain init first"}

        try:
            db = b.db
            delta = 0.03 if was_useful else -0.05
            _conf_before = 0.0
            try:
                _r = db.conn.execute(
                    "SELECT confidence FROM nodes WHERE id=?", (node_id_clean,)
                ).fetchone()
                _conf_before = float(_r[0]) if _r else 0.0
            except Exception:
                pass
            new_conf = db.record_feedback(node_id_clean, helpful=bool(was_useful))
            # C-05: write to feedback_log for pipeline feedback loop
            try:
                _sig_kind = ""
                try:
                    _pm = db.conn.execute(
                        "SELECT signal_id FROM pipeline_metrics WHERE node_id=? LIMIT 1",
                        (node_id_clean,),
                    ).fetchone()
                    if _pm:
                        _sq = db.conn.execute(
                            "SELECT kind FROM signal_queue WHERE id=? LIMIT 1",
                            (_pm[0],),
                        ).fetchone()
                        if _sq:
                            _sig_kind = _sq[0]
                except Exception:
                    pass
                db._feedback_tracker.log_feedback(
                    node_id_clean, was_useful,
                    signal_kind=_sig_kind,
                    notes=notes_clean,
                    conf_before=_conf_before,
                    conf_after=new_conf,
                )
            except Exception as _fl:
                logger.debug("C-05: feedback_log write failed: %s", _fl)
            # BUG-C fix: emit event so analytics_engine.useful_knowledge_rate() works
            try:
                db.emit("knowledge_outcome", {
                    "node_id": node_id_clean,
                    "was_useful": was_useful,
                    "notes": notes_clean,
                    "confidence": round(new_conf, 3),
                })
            except Exception as _e:
                logger.debug("knowledge_outcome event emit failed", exc_info=True)
            # DEEP-05: update adoption_count
            if was_useful:
                try:
                    b.graph.increment_adoption(node_id_clean)
                except Exception as _e:
                    logger.debug("increment_adoption failed", exc_info=True)

            # If notes provided and node is now low-confidence, append note
            if notes_clean and not was_useful:
                try:
                    db.conn.execute(
                        "UPDATE nodes SET content = content || ? WHERE id = ?",
                        (f"\n\n[Feedback {_now_iso()}: {notes_clean}]", node_id_clean),
                    )
                    db.conn.commit()
                except Exception as _e:
                    logger.debug("feedback note append failed", exc_info=True)

            return {
                "ok": True,
                "node_id": node_id_clean,
                "was_useful": was_useful,
                "confidence": round(new_conf, 3),
                "delta": delta,
            }
        except Exception as e:
            logger.error("report_knowledge_outcome error: %s", e)
            return {"ok": False, "error": str(e)}

    # ── Tool: complete_task ────────────────────────────────────────

    @mcp.tool()
    def complete_task(
        task_description: str,
        decisions: list[str] | None = None,
        lessons: list[str] | None = None,
        pitfalls: list[str] | None = None,
        workdir: str = "",
    ) -> dict:
        """
        Batch-write session learnings to L3 after completing a task.

        Call this at the end of EVERY non-trivial task. It creates permanent
        knowledge nodes from the work just done, closing the knowledge
        production loop so future agents benefit from this session.

        Args:
            task_description: One-sentence summary of what was accomplished.
            decisions: Architectural or design choices made during the task
                       (each item becomes a Decision node).
            lessons:   Things learned that would help future work — best
                       practices, non-obvious constraints, shortcuts found
                       (each item becomes a Rule node).
            pitfalls:  Mistakes encountered, near-misses, or traps to avoid
                       (each item becomes a Pitfall node).
            workdir:   Project working directory. Defaults to BRAIN_WORKDIR env var.

        Returns:
            {"ok": True, "created": N, "node_ids": [...]}
        """
        perm_err = _check_permission("complete_task")
        if perm_err:
            return perm_err
        srv.rate_check()

        wd_str = _safe_str(workdir or os.environ.get("BRAIN_WORKDIR", ""), 500, "workdir") or workdir
        b = srv.resolve_brain(wd_str)

        task_desc = _safe_str(task_description, MAX_CONTENT_LEN, "task_description")
        _decisions = [_safe_str(d, MAX_CONTENT_LEN, "decisions[i]") for d in (decisions or [])]
        _lessons = [_safe_str(l, MAX_CONTENT_LEN, "lessons[i]") for l in (lessons or [])]
        _pitfalls = [_safe_str(p, MAX_CONTENT_LEN, "pitfalls[i]") for p in (pitfalls or [])]

        created_ids: list[str] = []

        from project_brain.extractor import KnowledgeExtractor as _KE
        _extractor = _KE(workdir=str(b.workdir))
        _source = f"session:{datetime.now(timezone.utc).date()}"
        extracted = _extractor.from_session_log(
            task_description=task_desc,
            decisions=_decisions,
            lessons=_lessons,
            pitfalls=_pitfalls,
            source=_source,
        )
        chunks = extracted.get("knowledge_chunks", [])

        if not chunks:
            chunks = [{
                "type": "Decision",
                "title": task_desc[:60].strip(),
                "content": task_desc,
                "tags": ["session"],
                "confidence": 0.75,
                "source": _source,
            }]

        for chunk in chunks:
            _title = chunk.get("title", task_desc[:60]).strip()
            try:
                node_id = b.add_knowledge(
                    title=_title,
                    content=chunk.get("content", task_desc),
                    kind=chunk.get("type", "Decision"),
                    tags=chunk.get("tags", []) + ["auto:complete_task"],
                    confidence=chunk.get("confidence", 0.8),
                )
                created_ids.append(node_id)
            except Exception as e:
                logger.warning("complete_task: failed to write node %r: %s", _title, e)

        # VISION-01: auto-feedback on session nodes
        _wk = str(b.workdir)
        _auto_nodes: list[str] = []
        with srv._snodes_lock:
            _auto_nodes = list(srv._session_nodes.pop(_wk, []))
        if _auto_nodes:
            _had_pitfalls = bool(_pitfalls)
            try:
                for _nid in _auto_nodes[:5]:
                    b.db.record_feedback(_nid, helpful=not _had_pitfalls)
                logger.debug(
                    "VISION-01 auto-feedback: %d nodes helpful=%s",
                    min(5, len(_auto_nodes)), not _had_pitfalls,
                )
            except Exception as _fe:
                logger.debug("VISION-01 auto-feedback failed: %s", _fe)

        # C-04: emit TEST_FAILURE signal when pitfalls exist
        _error_lessons = [
            l for l in _pitfalls
            if any(kw in l.lower() for kw in ("test", "error", "fail", "bug", "crash"))
        ]
        if _error_lessons:
            srv.emit_signal(
                "test_failure", str(b.workdir),
                f"complete_task pitfall: {_error_lessons[0][:100]}",
                raw_content="\n".join(_error_lessons[:3]),
                metadata={"task": task_desc[:200], "pitfall_count": len(_pitfalls)},
                priority=3,
            )

        return {"ok": True, "created": len(created_ids), "node_ids": created_ids}
