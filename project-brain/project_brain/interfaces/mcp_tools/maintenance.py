"""
Maintenance helpers: _adjust_signal_confidence, _run_maintenance_cycle.

These functions are used by BrainServer's background daemons, not MCP tools.
Extracted from mcp_server.py to reduce its line count.
"""

from __future__ import annotations

import logging

# Use parent module logger so existing tests that assertLogs("project_brain.interfaces.mcp_server") still pass
logger = logging.getLogger("project_brain.interfaces.mcp_server")


def adjust_signal_confidence(brain) -> dict:
    """C-05: If a signal kind has >30% negative feedback in 30 days, lower its auto-confidence.

    Reads from ``feedback_log`` (written by report_knowledge_outcome),
    grouped by ``signal_kind``. For each kind with negative_rate > 0.30,
    updates ``brain_meta`` with a lowered default confidence for that signal type.

    Returns dict of adjustments made: ``{signal_kind: new_confidence, ...}``.
    """
    THRESHOLD = 0.30
    FLOOR = 0.3
    STEP = 0.1
    adjustments: dict[str, float] = {}

    try:
        rows = brain.db.conn.execute(
            """SELECT signal_kind, COUNT(*) AS total,
                      SUM(CASE WHEN was_useful = 0 THEN 1 ELSE 0 END) AS negative
               FROM feedback_log
               WHERE signal_kind != ''
                 AND created_at >= datetime('now', '-30 days')
               GROUP BY signal_kind"""
        ).fetchall()
    except Exception:
        return adjustments

    for row in rows:
        kind = row[0]
        total = row[1]
        negative = row[2] or 0
        if total < 5:
            continue
        neg_rate = negative / total
        if neg_rate <= THRESHOLD:
            continue

        meta_key = f"signal_confidence:{kind}"
        current = 0.85
        try:
            r = brain.db.conn.execute(
                "SELECT value FROM brain_meta WHERE key=?", (meta_key,)
            ).fetchone()
            if r:
                current = float(r[0])
        except Exception:
            pass

        new_conf = max(FLOOR, current - STEP)
        if new_conf < current:
            try:
                brain.db.conn.execute(
                    "INSERT OR REPLACE INTO brain_meta(key,value) VALUES(?,?)",
                    (meta_key, str(round(new_conf, 2))),
                )
                brain.db.conn.commit()
                adjustments[kind] = new_conf
                logger.info(
                    "C-05: signal %s negative_rate=%.0f%% (%d/%d) → "
                    "auto_confidence lowered %.2f → %.2f",
                    kind, neg_rate * 100, negative, total, current, new_conf,
                )
            except Exception as _e:
                logger.debug("C-05: brain_meta update failed for %s: %s", kind, _e)

    return adjustments


def run_maintenance_cycle(brain) -> dict:
    """B-01: 單次維護週期 — decay pass + KRB staging 清理。

    從 _decay_daemon_fn 提取出來以便單元測試直接呼叫，不需要等待 sleep interval。
    """
    result: dict = {
        "decay_ok": False,
        "decay_error": None,
        "cleanup": None,
        "cleanup_error": None,
        "feedback_adj": None,
        "feedback_error": None,
    }

    try:
        from project_brain.decay_engine import DecayEngine as _DE
        _de = _DE(brain.graph, workdir=str(brain.workdir), db=brain.db)
        _de.run()
        result["decay_ok"] = True
        logger.info("FEAT-01: decay pass completed")
    except Exception as _e:
        result["decay_error"] = str(_e)
        logger.debug("FEAT-01: decay daemon error: %s", _e)

    try:
        _cleanup_result = brain.review_board.cleanup_expired_staging()
        result["cleanup"] = _cleanup_result
        logger.info(
            "B-01: KRB staging cleanup completed "
            "pending_skipped=%d rejected_archived=%d ttl_days=%d",
            _cleanup_result.get("pending_skipped", 0),
            _cleanup_result.get("rejected_archived", 0),
            _cleanup_result.get("ttl_days", 30),
        )
    except Exception as _ke:
        result["cleanup_error"] = str(_ke)
        logger.warning("B-01: KRB staging cleanup error: %s", _ke)

    try:
        result["feedback_adj"] = adjust_signal_confidence(brain)
    except Exception as _fe:
        result["feedback_error"] = str(_fe)
        logger.debug("C-05: feedback adjustment error: %s", _fe)

    return result
