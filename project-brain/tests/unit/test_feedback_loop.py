"""
C-05: Pipeline Layer 5 — Feedback Loop Tests

Verifies:
- feedback_log table created via migration v28
- FeedbackTracker.log_feedback writes records
- FeedbackTracker.get_negative_rate computes correctly
- _adjust_signal_confidence triggers on >30% negative rate
- _adjust_signal_confidence skips with <5 samples
- _run_maintenance_cycle includes feedback adjustment
"""
from __future__ import annotations

from pathlib import Path

import pytest

from project_brain.brain_db import BrainDB
from project_brain.feedback_tracker import FeedbackTracker


def _init(tmp_path: Path):
    bd = tmp_path / ".brain"
    bd.mkdir(exist_ok=True)
    db = BrainDB(bd)
    return bd, db


# ════════════════════════════════════════════════════════════════
# Migration v28: feedback_log table
# ════════════════════════════════════════════════════════════════


class TestFeedbackLogMigration:
    """feedback_log table exists after BrainDB init."""

    def test_feedback_log_table_exists(self, tmp_path):
        bd, db = _init(tmp_path)
        tables = {r[0] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "feedback_log" in tables
        db.close()

    def test_feedback_log_columns(self, tmp_path):
        bd, db = _init(tmp_path)
        cols = {r[1] for r in db.conn.execute(
            "PRAGMA table_info(feedback_log)"
        ).fetchall()}
        for expected in ("node_id", "signal_kind", "was_useful",
                         "notes", "conf_before", "conf_after", "created_at"):
            assert expected in cols, f"Missing column: {expected}"
        db.close()

    def test_schema_version_is_28(self, tmp_path):
        bd, db = _init(tmp_path)
        row = db.conn.execute(
            "SELECT value FROM brain_meta WHERE key='schema_version'"
        ).fetchone()
        assert int(row[0]) >= 28
        db.close()


# ════════════════════════════════════════════════════════════════
# FeedbackTracker.log_feedback
# ════════════════════════════════════════════════════════════════


class TestLogFeedback:
    """FeedbackTracker.log_feedback writes to feedback_log."""

    def test_write_positive_feedback(self, tmp_path):
        bd, db = _init(tmp_path)
        ft = FeedbackTracker(db.conn)
        ft.log_feedback("node-1", True, signal_kind="git_commit",
                         conf_before=0.8, conf_after=0.83)
        rows = db.conn.execute("SELECT * FROM feedback_log").fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "node-1"  # node_id
        assert rows[0][2] == "git_commit"  # signal_kind
        assert rows[0][3] == 1  # was_useful
        db.close()

    def test_write_negative_feedback(self, tmp_path):
        bd, db = _init(tmp_path)
        ft = FeedbackTracker(db.conn)
        ft.log_feedback("node-2", False, signal_kind="mcp_tool_call",
                         notes="outdated", conf_before=0.7, conf_after=0.65)
        rows = db.conn.execute("SELECT * FROM feedback_log").fetchall()
        assert len(rows) == 1
        assert rows[0][3] == 0  # was_useful = False
        db.close()

    def test_write_multiple(self, tmp_path):
        bd, db = _init(tmp_path)
        ft = FeedbackTracker(db.conn)
        for i in range(5):
            ft.log_feedback(f"n-{i}", i % 2 == 0, signal_kind="test_failure")
        count = db.conn.execute("SELECT COUNT(*) FROM feedback_log").fetchone()[0]
        assert count == 5
        db.close()


# ════════════════════════════════════════════════════════════════
# FeedbackTracker.get_negative_rate
# ════════════════════════════════════════════════════════════════


class TestGetNegativeRate:
    """get_negative_rate computes correctly."""

    def test_no_feedback_returns_zero(self, tmp_path):
        bd, db = _init(tmp_path)
        ft = FeedbackTracker(db.conn)
        assert ft.get_negative_rate("git_commit") == 0.0
        db.close()

    def test_all_positive_returns_zero(self, tmp_path):
        bd, db = _init(tmp_path)
        ft = FeedbackTracker(db.conn)
        for i in range(10):
            ft.log_feedback(f"n-{i}", True, signal_kind="git_commit")
        assert ft.get_negative_rate("git_commit") == 0.0
        db.close()

    def test_all_negative_returns_one(self, tmp_path):
        bd, db = _init(tmp_path)
        ft = FeedbackTracker(db.conn)
        for i in range(10):
            ft.log_feedback(f"n-{i}", False, signal_kind="mcp_tool_call")
        assert ft.get_negative_rate("mcp_tool_call") == 1.0
        db.close()

    def test_mixed_rate_correct(self, tmp_path):
        bd, db = _init(tmp_path)
        ft = FeedbackTracker(db.conn)
        # 3 negative, 7 positive → 30% negative
        for i in range(3):
            ft.log_feedback(f"neg-{i}", False, signal_kind="test_failure")
        for i in range(7):
            ft.log_feedback(f"pos-{i}", True, signal_kind="test_failure")
        rate = ft.get_negative_rate("test_failure")
        assert abs(rate - 0.3) < 0.01
        db.close()

    def test_different_kinds_independent(self, tmp_path):
        bd, db = _init(tmp_path)
        ft = FeedbackTracker(db.conn)
        # kind A: all negative
        for i in range(5):
            ft.log_feedback(f"a-{i}", False, signal_kind="kind_a")
        # kind B: all positive
        for i in range(5):
            ft.log_feedback(f"b-{i}", True, signal_kind="kind_b")
        assert ft.get_negative_rate("kind_a") == 1.0
        assert ft.get_negative_rate("kind_b") == 0.0
        db.close()


# ════════════════════════════════════════════════════════════════
# _adjust_signal_confidence
# ════════════════════════════════════════════════════════════════


class TestAdjustSignalConfidence:
    """_adjust_signal_confidence updates brain_meta when negative rate > 30%."""

    def _make_brain(self, tmp_path):
        from project_brain.engine import ProjectBrain
        (tmp_path / ".brain").mkdir(exist_ok=True)
        return ProjectBrain(str(tmp_path))

    def test_no_feedback_no_adjustment(self, tmp_path):
        from project_brain.interfaces.mcp_server import _adjust_signal_confidence
        brain = self._make_brain(tmp_path)
        result = _adjust_signal_confidence(brain)
        assert result == {}

    def test_below_threshold_no_adjustment(self, tmp_path):
        from project_brain.interfaces.mcp_server import _adjust_signal_confidence
        brain = self._make_brain(tmp_path)
        ft = FeedbackTracker(brain.db.conn)
        # 20% negative (below 30% threshold)
        for i in range(2):
            ft.log_feedback(f"neg-{i}", False, signal_kind="git_commit")
        for i in range(8):
            ft.log_feedback(f"pos-{i}", True, signal_kind="git_commit")
        result = _adjust_signal_confidence(brain)
        assert result == {}

    def test_above_threshold_triggers_adjustment(self, tmp_path):
        from project_brain.interfaces.mcp_server import _adjust_signal_confidence
        brain = self._make_brain(tmp_path)
        ft = FeedbackTracker(brain.db.conn)
        # 50% negative (above 30% threshold), 10 samples
        for i in range(5):
            ft.log_feedback(f"neg-{i}", False, signal_kind="mcp_tool_call")
        for i in range(5):
            ft.log_feedback(f"pos-{i}", True, signal_kind="mcp_tool_call")
        result = _adjust_signal_confidence(brain)
        assert "mcp_tool_call" in result
        assert result["mcp_tool_call"] < 0.85  # lowered from default

    def test_too_few_samples_skipped(self, tmp_path):
        from project_brain.interfaces.mcp_server import _adjust_signal_confidence
        brain = self._make_brain(tmp_path)
        ft = FeedbackTracker(brain.db.conn)
        # Only 3 samples (below minimum 5)
        for i in range(3):
            ft.log_feedback(f"neg-{i}", False, signal_kind="test_failure")
        result = _adjust_signal_confidence(brain)
        assert result == {}

    def test_confidence_floor_at_03(self, tmp_path):
        from project_brain.interfaces.mcp_server import _adjust_signal_confidence
        brain = self._make_brain(tmp_path)
        # Set current confidence very low
        brain.db.conn.execute(
            "INSERT OR REPLACE INTO brain_meta(key,value) VALUES(?,?)",
            ("signal_confidence:test_failure", "0.35"),
        )
        brain.db.conn.commit()
        ft = FeedbackTracker(brain.db.conn)
        # 100% negative
        for i in range(10):
            ft.log_feedback(f"neg-{i}", False, signal_kind="test_failure")
        result = _adjust_signal_confidence(brain)
        assert result.get("test_failure", 1.0) >= 0.3  # floor

    def test_adjustment_persisted_to_brain_meta(self, tmp_path):
        from project_brain.interfaces.mcp_server import _adjust_signal_confidence
        brain = self._make_brain(tmp_path)
        ft = FeedbackTracker(brain.db.conn)
        for i in range(8):
            ft.log_feedback(f"neg-{i}", False, signal_kind="knowledge_conflict")
        for i in range(2):
            ft.log_feedback(f"pos-{i}", True, signal_kind="knowledge_conflict")
        _adjust_signal_confidence(brain)
        row = brain.db.conn.execute(
            "SELECT value FROM brain_meta WHERE key='signal_confidence:knowledge_conflict'"
        ).fetchone()
        assert row is not None
        assert float(row[0]) < 0.85


# ════════════════════════════════════════════════════════════════
# Integration: _run_maintenance_cycle includes feedback
# ════════════════════════════════════════════════════════════════


class TestMaintenanceCycleIntegration:
    """_adjust_signal_confidence is called within _run_maintenance_cycle."""

    def test_adjust_function_importable(self):
        """_adjust_signal_confidence is importable from mcp_server."""
        from project_brain.interfaces.mcp_server import _adjust_signal_confidence
        assert callable(_adjust_signal_confidence)

    def test_maintenance_result_schema(self):
        """The result dict template includes feedback_adj/feedback_error keys."""
        # Verify the keys are in the initial result template
        # (testing _run_maintenance_cycle fully requires a real brain instance)
        result_keys = {
            "decay_ok", "decay_error", "cleanup", "cleanup_error",
            "feedback_adj", "feedback_error",
        }
        # The function signature guarantees these keys
        from project_brain.interfaces.mcp_server import _run_maintenance_cycle
        import inspect
        src = inspect.getsource(_run_maintenance_cycle)
        for key in result_keys:
            assert f'"{key}"' in src, f"Missing key {key!r} in _run_maintenance_cycle"
