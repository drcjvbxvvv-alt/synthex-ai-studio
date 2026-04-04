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
