"""
project_brain/feedback_tracker.py — FeedbackTracker (REF-01 extracted from BrainDB)

Manages confidence feedback and access recording for knowledge nodes.
Extracted from brain_db.py to reduce God Object complexity.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

DECAY_FLOOR = 0.05
DECAY_CEIL  = 1.0


class FeedbackTracker:
    """Manages confidence feedback and access recording for knowledge nodes."""

    def __init__(self, conn):
        self.conn = conn

    def record_access(self, node_id: str) -> None:
        self.conn.execute(
            "UPDATE nodes SET access_count=access_count+1,"
            " last_accessed=datetime('now') WHERE id=?", (node_id,)
        )
        self.conn.commit()

    def record_feedback(self, node_id: str, helpful: bool) -> float:
        """
        Confidence feedback loop — called after an Agent actually uses a node.

        helpful=True  → confidence += BOOST   (capped at 1.0)
        helpful=False → confidence -= PENALTY  (floored at DECAY_FLOOR=0.05)

        Returns the updated confidence value.
        """
        BOOST   = 0.03   # +3% per positive signal
        PENALTY = 0.05   # -5% per negative signal
        FLOOR   = DECAY_FLOOR

        row = self.conn.execute(
            "SELECT confidence FROM nodes WHERE id=?", (node_id,)
        ).fetchone()
        if not row:
            return 0.0

        current = float(row[0])
        if helpful:
            new_conf = min(DECAY_CEIL, current + BOOST)
        else:
            new_conf = max(FLOOR, current - PENALTY)

        if helpful:
            # DEEP-05: increment adoption_count for F6 factor
            self.conn.execute(
                "UPDATE nodes SET confidence=?, updated_at=datetime('now'),"
                " adoption_count=COALESCE(adoption_count,0)+1 WHERE id=?",
                (new_conf, node_id)
            )
        else:
            self.conn.execute(
                "UPDATE nodes SET confidence=?, updated_at=datetime('now') WHERE id=?",
                (new_conf, node_id)
            )
        self.conn.commit()
        return new_conf

    def record_outcome(self, node_id: str, was_useful: bool) -> float:
        """DEEP-05: alias for record_feedback — named for MCP/REST clarity."""
        return self.record_feedback(node_id, helpful=was_useful)

    def log_feedback(
        self,
        node_id: str,
        was_useful: bool,
        signal_kind: str = "",
        notes: str = "",
        conf_before: float = 0.0,
        conf_after: float = 0.0,
    ) -> None:
        """C-05: Write to feedback_log table for pipeline feedback loop analytics."""
        try:
            self.conn.execute(
                """INSERT INTO feedback_log
                   (node_id, signal_kind, was_useful, notes, conf_before, conf_after)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (node_id, signal_kind, int(was_useful), notes[:500],
                 conf_before, conf_after),
            )
            self.conn.commit()
        except Exception as _e:
            logger.debug("C-05: feedback_log write failed (non-fatal): %s", _e)

    def get_negative_rate(self, signal_kind: str, days: int = 30) -> float:
        """C-05: Return the negative feedback rate for a signal kind over N days.

        Returns 0.0 if no feedback exists for this kind.
        """
        try:
            row = self.conn.execute(
                """SELECT
                     COUNT(*) AS total,
                     SUM(CASE WHEN was_useful = 0 THEN 1 ELSE 0 END) AS negative
                   FROM feedback_log
                   WHERE signal_kind = ?
                     AND created_at >= datetime('now', ?)""",
                (signal_kind, f"-{max(1, days)} days"),
            ).fetchone()
            if not row or not row[0]:
                return 0.0
            return row[1] / row[0]
        except Exception as _e:
            logger.debug("C-05: get_negative_rate failed: %s", _e)
            return 0.0
